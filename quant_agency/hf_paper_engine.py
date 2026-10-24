"""Omega engine, layer 3: event-driven high-frequency paper execution for a 100 USD account.

The engine is synchronous and clock-injected (``on_print`` / ``on_create`` / ``on_quote`` / ``on_tweet`` / ``poll``), so the live daemon,
a recorded tape and a synthetic tape all drive the same code. It never builds, signs or sends an order.

Execution realism
-----------------
* **pump.fun bonding curve (AMM).** A decision at ``t`` lands at ``t + pump_latency_s``. The fill is priced on the curve state *as of
  landing* (the reserves after the last real print before landing), our own size moves the curve (constant product), the fee is the
  rate the venue reported in its own trade events (floored at ``pump_fee_floor_bps``), and every transaction pays the Solana base +
  priority fee. If the landing price is worse than the decision price by more than ``pump_slippage_bps`` the transaction fails and only
  the network fee is lost. A second model, ``adverse``, prices the same order at the *worst* curve state seen between decision and
  landing (a lower bound). Order-book "depletion" / "queue" models do not exist on an AMM and are not pretended.
* **Gate CLOB (meme pairs).** Taker orders fill at the as-of-arrival touch, beyond the displayed size at a 10 bps worse price.
  Passive entries (``breakout_scalp``) run the three queue models of ``queue_model.py`` side by side — ``strict`` (only a crossed touch
  fills), ``trades`` (real prints consume the queue ahead; primary), ``depletion`` (any displayed-size drop counts; optimistic bound).
  Sizes are rounded down to the pair's lot (``amount_precision``) and must clear its ``min_quote_amount``.
* **Valuation.** Open positions are marked at what selling them now would fetch, after fees and network costs (liquidation value).

Throughput and memory
---------------------
At most ``max_fills_per_hour`` (1,000) fills per rolling hour, enforced by the CEO. Every growing structure is bounded: token rings
(numpy, fixed size), universe LRU, pending orders, recent round trips (deque); the audit trail is buffered and appended to JSONL every
``flush_every_s`` (300 s) or at ``audit_cap`` rows, then dropped from memory.
"""
from __future__ import annotations

import json
import math
import os
import time
from collections import Counter, deque
from dataclasses import asdict, dataclass, field
from typing import Deque, Dict, List, Optional, Tuple

from . import queue_model as qm
from .meme_discovery import Quote, SafetyGate, TokenCreated, TokenState, TradePrint, Universe, curve_buy, curve_sell
from .omega_governance import GovConfig, OmegaCEO, OState
from .x_sentiment_crawler import SocialBook, Tweet

MODELS_CLOB = ("strict", "trades", "depletion")


# ================================================================================ configuration
@dataclass
class MomentumCfg:                       # meme_momentum: order-flow burst on a pump.fun curve
    w_fast: float = 30.0
    w_slow: float = 120.0
    min_prints: int = 8
    min_unique: int = 6
    min_buy_ratio: float = 2.0           # buy SOL / sell SOL over w_fast
    min_net_sol: float = 1.0
    min_ret: float = 0.03
    max_ret: float = 0.25                # skip parabolic candles: we would be the exit liquidity
    min_accel: float = 2.0               # (flow per second over w_fast) / (flow per second over w_slow)
    min_real_sol: float = 5.0
    stop: float = 0.08
    tp: float = 0.15
    trail_arm: float = 0.06
    trail: float = 0.05
    time_stop_s: float = 90.0
    exit_sell_ratio: float = 2.0         # exit when sells outweigh buys 2:1 over 15 s (>= 5 prints)


@dataclass
class SocialCfg:
    min_score: float = 60.0
    stop: float = 0.10
    tp: float = 0.20
    trail_arm: float = 0.08
    trail: float = 0.06
    time_stop_s: float = 300.0


@dataclass
class BreakoutCfg:                       # breakout_scalp: Gate CLOB meme pairs, passive entry after a range break
    lookback_s: float = 120.0
    min_break: float = 0.003
    flow_w: float = 30.0
    min_buy_share: float = 0.6
    max_spread_bps: float = 25.0
    entry_ttl_s: float = 20.0
    stop: float = 0.006
    tp: float = 0.010
    trail_arm: float = 0.006
    trail: float = 0.004
    time_stop_s: float = 180.0


@dataclass
class EngineConfig:
    bankroll: float = 100.0
    min_trade_usd: float = 2.0
    max_trade_usd: float = 5.0
    risk_frac: float = 0.015              # at most 1.5 USD lost at the stop per position
    min_notional_usd: float = 1.0
    max_open_per_sleeve: int = 6
    pump_latency_s: float = 0.8
    gate_latency_s: float = 0.15
    cancel_latency_s: float = 0.15
    pump_fee_floor_bps: float = 125.0
    sol_tx_fee_sol: float = 0.000005
    sol_priority_fee_sol: float = 0.0001
    pump_slippage_bps: float = 500.0
    pump_lot: float = 1e-6
    gate_extra_bps: float = 10.0          # price beyond the displayed touch size
    eval_every_s: float = 1.0
    flush_every_s: float = 300.0
    audit_cap: int = 5000
    snapshot_every_s: float = 60.0
    stats_every_s: float = 60.0
    expire_every_s: float = 60.0
    max_pending: int = 200
    momentum: MomentumCfg = field(default_factory=MomentumCfg)
    social: SocialCfg = field(default_factory=SocialCfg)
    breakout: BreakoutCfg = field(default_factory=BreakoutCfg)
    gov: GovConfig = field(default_factory=GovConfig)


# ================================================================================ orders and positions
@dataclass
class Position:
    pid: int
    sleeve: str
    key: str
    venue: str
    qty: float
    entry_px: float                       # quote per token actually paid on the curve / book (excl. fees)
    cost_usd: float                       # all-in USD paid
    fees_usd: float
    t_open: float
    stop: float
    tp: float
    trail_arm: float
    trail: float
    time_stop_s: float
    reason: str
    peak_px: float = 0.0
    closing: bool = False
    shadow: Dict[str, dict] = field(default_factory=dict)    # other fill models: model -> {"cost_usd", "qty"} or {"filled": False}


@dataclass
class Pending:
    oid: int
    sleeve: str
    key: str
    venue: str
    side: int                             # +1 open (buy) / -1 close (sell)
    t_dec: float
    t_arr: float
    dec_px: float
    usd: float = 0.0                      # buys: all-in budget
    pid: int = 0                          # closes: position id
    reason: str = ""
    params: dict = field(default_factory=dict)
    worst: Optional[Tuple[float, float, float]] = None      # pump: (price, v_quote, v_base) of the worst state seen while in flight
    rest: Dict[str, qm.RestOrder] = field(default_factory=dict)   # gate passive: model -> order
    ttl: float = 0.0
    hist: Optional[qm.QuoteHist] = None


class HFPaperEngine:
    def __init__(self, cfg: Optional[EngineConfig] = None, out_dir: Optional[str] = None, social_enabled: bool = False):
        self.cfg = cfg or EngineConfig()
        self.ceo = OmegaCEO(self.cfg.gov)
        self.uni = Universe()
        self.gate_safety = SafetyGate()
        self.social = SocialBook()
        self.social_enabled = social_enabled
        self.sol_usd = float("nan")
        self.positions: Dict[int, Position] = {}
        self.pending: Dict[int, Pending] = {}
        self.by_key: Dict[str, int] = {}                     # key -> pid (one position per token across the account)
        self.pending_keys: set = set()
        self.quotes: Dict[str, qm.QuoteHist] = {}
        self.pair_rules: Dict[str, dict] = {}
        self.need_safety: Deque[str] = deque(maxlen=500)
        self.safety_asked: set = set()
        self.last_eval: Dict[str, float] = {}
        self.recent: Deque[dict] = deque(maxlen=500)
        self.stats: Counter = Counter()
        self.model_pnl: Dict[str, List[float]] = {}        # model -> [sum net usd, n]
        self.audit: List[dict] = []
        self.out_dir = out_dir
        self.next_id = 1
        self.t = 0.0
        self.t_start: Optional[float] = None
        self.last_flush = self.last_snapshot = self.last_stats = self.last_expire = -1e18
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)

    # ------------------------------------------------------------------ plumbing
    def _id(self) -> int:
        self.next_id += 1
        return self.next_id

    def log(self, kind: str, **kw) -> None:
        self.audit.append({"kind": kind, "t": round(self.t, 3), **kw})
        if len(self.audit) >= self.cfg.audit_cap:
            self.flush()

    def flush(self) -> None:
        if self.out_dir and self.audit:
            with open(os.path.join(self.out_dir, "omega_audit.jsonl"), "a") as f:
                for r in self.audit:
                    f.write(json.dumps(r, default=float) + "\n")
        self.stats["audit_rows_flushed"] += len(self.audit)
        self.audit = []
        self.last_flush = self.t

    def set_sol_usd(self, px: float) -> None:
        if px > 0:
            self.sol_usd = px

    def set_pair_rules(self, rows: List[dict]) -> None:
        for r in rows:
            self.pair_rules[r["pair"]] = r
            st = self.uni.get(r["pair"], "gate", self.t)
            st.lot, st.min_notional, st.taker_fee_bps = r["lot"], max(r["min_quote"], self.cfg.min_notional_usd), r["fee_bps"]
            self.uni.pinned.add(r["pair"])

    def set_safety(self, key: str, facts: dict) -> None:
        st = self.uni.tokens.get(key)
        if st is not None:
            st.safety = self.gate_safety.evaluate(st, dict(facts), self.t).as_dict()

    def set_twitter(self, key: str, handle: str) -> None:
        st = self.uni.tokens.get(key)
        if st is not None and handle:
            st.twitter = handle

    def _usd(self, venue: str) -> float:
        return self.sol_usd if venue == "pump" else 1.0

    def _tx_fee_quote(self, venue: str) -> float:
        return self.cfg.sol_tx_fee_sol + self.cfg.sol_priority_fee_sol if venue == "pump" else 0.0

    def _fee_bps(self, st: TokenState) -> float:
        if st.venue == "pump":
            return max(st.fee_bps if st.fee_bps == st.fee_bps else 0.0, self.cfg.pump_fee_floor_bps)
        return st.taker_fee_bps if st.taker_fee_bps == st.taker_fee_bps else 20.0

    # ------------------------------------------------------------------ valuation
    def liquidation_value(self, pos: Position, st: TokenState, worst: Optional[Tuple[float, float, float]] = None) -> Tuple[float, float, float]:
        """(USD received, USD fees, quote price per token) if ``pos`` were sold now."""
        fee_bps = self._fee_bps(st)
        if pos.venue == "pump":
            vq, vb = (worst[1], worst[2]) if worst else (st.v_quote, st.v_base)
            if not (vq > 0 and vb > 0) or not (self.sol_usd > 0):
                return 0.0, 0.0, 0.0
            sol_out, fee_sol, _ = curve_sell(vq, vb, pos.qty, fee_bps)
            if st.real_quote == st.real_quote:
                sol_out = min(sol_out, max(0.0, st.real_quote) * 0.99)
            tx = self._tx_fee_quote("pump")
            return max(0.0, (sol_out - tx) * self.sol_usd), (fee_sol + tx) * self.sol_usd, (sol_out + fee_sol) / pos.qty
        bid = st.bid
        if not bid > 0:
            return 0.0, 0.0, 0.0
        q_top = min(pos.qty, st.bq) if st.bq > 0 else 0.0
        gross = q_top * bid + (pos.qty - q_top) * bid * (1 - self.cfg.gate_extra_bps / 1e4)
        fee = gross * fee_bps / 1e4
        return gross - fee, fee, gross / pos.qty

    # ------------------------------------------------------------------ event entry points
    def on_create(self, c: TokenCreated) -> None:
        self.t = max(self.t, c.t)
        self.uni.on_create(c)
        self.stats["creates"] += 1

    def on_complete(self, mint: str, t: float) -> None:
        st = self.uni.tokens.get(mint)
        if st is not None:
            st.complete = True

    def on_tweet(self, tw: Tweet) -> None:
        self.social.on_tweet(tw)
        self.stats["tweets"] += 1

    def on_print(self, p: TradePrint) -> None:
        self._tick(p.t)
        self.stats["prints"] += 1
        st = self.uni.tokens.get(p.key)
        if st is not None:
            self._resolve(p.key, p.t, st)                       # orders that landed before this print see the state before it
        st = self.uni.on_print(p)
        for pd in list(self.pending.values()):                  # orders still in flight: remember the worst state they could land on
            if pd.key == p.key and pd.venue == "pump" and pd.t_arr > p.t:
                px = st.v_quote / st.v_base
                if pd.worst is None or (pd.side > 0 and px > pd.worst[0]) or (pd.side < 0 and px < pd.worst[0]):
                    pd.worst = (px, st.v_quote, st.v_base)
            if pd.key == p.key and pd.rest:
                for m, o in pd.rest.items():
                    fills: list = []
                    qm.on_trade(o, p.t, p.price, p.qty, p.side, m, fills)
                self._resolve_passive(pd, p.t, st)              # a fill by this very print is booked now, not at the next event
        self._after_market(p.key, st)

    def on_quote(self, q: Quote) -> None:
        self._tick(q.t)
        self.stats["quotes"] += 1
        st = self.uni.tokens.get(q.key)
        if st is not None:
            self._resolve(q.key, q.t, st)
        h = self.quotes.get(q.key)
        if h is None:
            h = self.quotes[q.key] = qm.QuoteHist(maxlen=600)
        h.add(q.t, q.bid, q.ask, q.bq, q.aq)
        st = self.uni.on_quote(q)
        for pd in list(self.pending.values()):
            if pd.key == q.key and pd.rest:
                for m, o in pd.rest.items():
                    fills: list = []
                    qm.advance(o, q.t, h, fills)
                    qm.on_quote(o, q.t, (q.t, q.bid, q.ask, q.bq, q.aq), m, fills)
                self._resolve_passive(pd, q.t, st)
        self._after_market(q.key, st)

    def poll(self, now: float) -> None:
        self._tick(now)
        for pd in list(self.pending.values()):
            st = self.uni.tokens.get(pd.key)
            if st is not None and pd.t_arr <= now:
                self._resolve(pd.key, now, st)
        for pos in list(self.positions.values()):
            if not pos.closing and now - pos.t_open >= pos.time_stop_s:
                self._close(pos, now, "time_stop")
        for ev in self.ceo.review(now):
            d = ev.as_dict()
            d["gov_kind"] = d.pop("kind")
            self.log("gov", **d)
        while self.ceo.to_flatten:
            name = self.ceo.to_flatten.pop()
            for pos in list(self.positions.values()):
                if pos.sleeve == name and not pos.closing:
                    self._close(pos, now, "governance_flatten")
            for pd in list(self.pending.values()):
                if pd.sleeve == name and pd.side > 0:
                    self._drop_pending(pd, "governance_cancel")
        if now - self.last_expire >= self.cfg.expire_every_s:
            self.last_expire = now
            self.uni.pinned = set(self.by_key) | self.pending_keys | set(self.pair_rules)
            self.uni.expire(now)
            self.social.expire(now, idle_s=900.0)          # a token nobody tweeted about for 15 min has no social signal left
            for k in [k for k in self.last_eval if k not in self.uni.tokens]:
                del self.last_eval[k]
            for k in [k for k in self.quotes if k not in self.uni.tokens]:
                del self.quotes[k]
            self.safety_asked &= set(self.uni.tokens)
        if now - self.last_stats >= self.cfg.stats_every_s:
            self.last_stats = now
            self.log("stats", **self.status())
        if now - self.last_flush >= self.cfg.flush_every_s:
            self.flush()
        if self.out_dir and now - self.last_snapshot >= self.cfg.snapshot_every_s:
            self.last_snapshot = now
            self.save_snapshot()

    def _tick(self, t: float) -> None:
        if self.t_start is None:
            self.t_start = t
            self.last_flush = self.last_snapshot = self.last_stats = self.last_expire = t
        if t > self.t:
            self.t = t

    # ------------------------------------------------------------------ after every market update on ``key``
    def _after_market(self, key: str, st: TokenState) -> None:
        pid = self.by_key.get(key)
        if pid is not None:
            pos = self.positions[pid]
            val, _, px = self.liquidation_value(pos, st)
            self.ceo.books[pos.sleeve].mark(pid, val)
            if not pos.closing and px > 0:
                self._check_exit(pos, st, px)
        if self.t - self.last_eval.get(key, -1e18) >= self.cfg.eval_every_s:
            self.last_eval[key] = self.t
            self._entries(st)

    def _check_exit(self, pos: Position, st: TokenState, px: float) -> None:
        pos.peak_px = max(pos.peak_px, px)
        r = px / pos.entry_px - 1.0
        why = ""
        if r <= -pos.stop:
            why = "stop"
        elif r >= pos.tp:
            why = "take_profit"
        elif pos.peak_px / pos.entry_px - 1.0 >= pos.trail_arm and px <= pos.peak_px * (1 - pos.trail):
            why = "trail"
        elif pos.venue == "pump":
            if st.creator and st.creator_sold > 0 and st.creator_sold > 0.5 * max(st.creator_bought, 1e-9):
                why = "creator_dump"
            else:
                w = st.window(self.t, 15.0)
                if w["n"] >= 5 and w["sell_quote"] > self.cfg.momentum.exit_sell_ratio * max(w["buy_quote"], 1e-9):
                    why = "sell_pressure"
        if why:
            self._close(pos, self.t, why)

    # ------------------------------------------------------------------ strategies
    def _entries(self, st: TokenState) -> None:
        if st.key in self.by_key or st.key in self.pending_keys or self.ceo.halted:
            return
        if st.venue == "pump":
            self._momentum(st)
            if self.social_enabled:
                self._social(st)
        else:
            self._breakout(st)

    def _volume_accel(self, st: TokenState) -> float:
        f, s = st.window(self.t, 60.0), st.window(self.t, 300.0)
        rate_f = (f["buy_quote"] + f["sell_quote"]) / 60.0
        rate_s = (s["buy_quote"] + s["sell_quote"]) / 300.0
        return rate_f / rate_s if rate_s > 0 else (10.0 if rate_f > 0 else 1.0)

    def _safe(self, st: TokenState) -> bool:
        if st.safety is None:
            if st.key not in self.safety_asked:
                self.safety_asked.add(st.key)
                self.need_safety.append(st.key)
                self.stats["safety_requested"] += 1
            return False
        if not st.safety["ok"]:
            self.stats["safety_rejected_eval"] += 1
        return bool(st.safety["ok"])

    def _momentum(self, st: TokenState) -> None:
        c = self.cfg.momentum
        if st.complete or not (st.real_quote == st.real_quote and st.real_quote >= c.min_real_sol):
            return
        f = st.window(self.t, c.w_fast)
        if f["n"] < c.min_prints or f["unique"] < c.min_unique:
            return
        if f["buy_quote"] < c.min_buy_ratio * max(f["sell_quote"], 1e-9) or f["net_quote"] < c.min_net_sol:
            return
        if not (c.min_ret <= f["ret"] <= c.max_ret):
            return
        s = st.window(self.t, c.w_slow)
        acc = ((f["buy_quote"] + f["sell_quote"]) / c.w_fast) / max((s["buy_quote"] + s["sell_quote"]) / c.w_slow, 1e-12)
        if acc < c.min_accel:
            return
        self.stats["signal_momentum"] += 1
        if not self._safe(st):
            return
        self._open("meme_momentum", st, c.stop, c.tp, c.trail_arm, c.trail, c.time_stop_s,
                   f"burst {f['n']:.0f} prints / {f['unique']} traders, net {f['net_quote']:.2f} SOL, ret {f['ret']:+.1%}, accel {acc:.1f}x")

    def _social(self, st: TokenState) -> None:
        c = self.cfg.social
        keys = [st.key] + ([f"${st.symbol.upper()}"] if st.symbol else [])
        acc = self._volume_accel(st)
        best = None
        for k in keys:
            sc = self.social.score(k, self.t, acc)
            if sc is not None and (best is None or sc["score"] > best["score"]):
                best = sc
        if best is None or best["bot_capped"] or best["score"] < c.min_score:
            return
        if st.window(self.t, 60.0)["net_quote"] <= 0:
            return
        self.stats["signal_social"] += 1
        if not self._safe(st):
            return
        self._open("social_sentiment", st, c.stop, c.tp, c.trail_arm, c.trail, c.time_stop_s,
                   f"social alpha {best['score']:.0f} (bot {best['bot_score']:.2f}), volume accel {acc:.1f}x")

    def _breakout(self, st: TokenState) -> None:
        c = self.cfg.breakout
        h = self.quotes.get(st.key)
        if h is None or len(h.q) < 20 or not (st.bid > 0 and st.ask > 0):
            return
        mid = 0.5 * (st.bid + st.ask)
        if (st.ask - st.bid) / mid * 1e4 > c.max_spread_bps:
            return
        prior = [0.5 * (b + a) for (t, b, a, _, _) in h.q if self.t - c.lookback_s <= t < self.t - 2.0]
        if len(prior) < 10 or mid < max(prior) * (1 + c.min_break):
            return
        w = st.window(self.t, c.flow_w)
        if w["n"] < 5 or w["buy_quote"] < c.min_buy_share * (w["buy_quote"] + w["sell_quote"]):
            return
        self.stats["signal_breakout"] += 1
        self._open("breakout_scalp", st, c.stop, c.tp, c.trail_arm, c.trail, c.time_stop_s,
                   f"break {mid / max(prior) - 1:+.2%} over {c.lookback_s:.0f}s high, buy share {w['buy_quote'] / (w['buy_quote'] + w['sell_quote']):.0%}",
                   passive=True)

    # ------------------------------------------------------------------ sizing
    def size_usd(self, sleeve: str, st: TokenState, stop: float) -> float:
        """Dollar budget for one entry, or 0 when the account cannot place an exchange-valid order."""
        c = self.cfg
        mult = self.ceo.size_mult(sleeve)
        if mult <= 0:
            return 0.0
        book = self.ceo.books[sleeve]
        usd = min(c.max_trade_usd * mult, c.bankroll * c.risk_frac * mult / max(stop, 1e-9), book.cash)
        floor = max(c.min_trade_usd, st.min_notional, c.min_notional_usd)
        return usd if usd >= floor - 1e-9 else 0.0

    def _open(self, sleeve: str, st: TokenState, stop, tp, trail_arm, trail, time_stop, reason, passive: bool = False) -> None:
        book = self.ceo.books.get(sleeve)
        if book is None or not book.can_open(0.0):
            self.stats[f"skip_{sleeve}_state"] += 1
            return
        if sum(1 for p in self.positions.values() if p.sleeve == sleeve) + sum(1 for p in self.pending.values() if p.sleeve == sleeve and p.side > 0) >= self.cfg.max_open_per_sleeve:
            self.stats[f"skip_{sleeve}_max_open"] += 1
            return
        if not self.ceo.fill_budget_ok(self.t) or len(self.ceo.fill_times) > self.cfg.gov.max_fills_per_hour - 2:
            self.stats["skip_rate_cap"] += 1
            return
        if len(self.pending) >= self.cfg.max_pending:
            self.stats["skip_pending_cap"] += 1
            return
        usd = self.size_usd(sleeve, st, stop)
        if usd <= 0:
            self.stats[f"skip_{sleeve}_size"] += 1
            return
        if st.venue == "pump" and not (self.sol_usd > 0):
            self.stats["skip_no_sol_price"] += 1
            return
        lat = self.cfg.pump_latency_s if st.venue == "pump" else self.cfg.gate_latency_s
        pd = Pending(self._id(), sleeve, st.key, st.venue, +1, self.t, self.t + lat, st.mid(), usd=usd, reason=reason,
                     params={"stop": stop, "tp": tp, "trail_arm": trail_arm, "trail": trail, "time_stop_s": time_stop})
        if passive:
            h = self.quotes[st.key]
            qty = math.floor(usd / (1 + self._fee_bps(st) / 1e4) / st.bid / st.lot) * st.lot
            if qty * st.bid < st.min_notional:
                self.stats[f"skip_{sleeve}_lot"] += 1
                return
            pd.rest = {m: qm.RestOrder(+1, st.bid, qty, self.t, self.t + lat) for m in MODELS_CLOB}
            pd.ttl, pd.hist = self.t + self.cfg.breakout.entry_ttl_s, h
        self.pending[pd.oid] = pd
        self.pending_keys.add(st.key)
        self.stats["orders"] += 1
        self.log("order", oid=pd.oid, sleeve=sleeve, key=st.key, venue=st.venue, side="buy", usd=round(usd, 4), dec_px=pd.dec_px, passive=passive, reason=reason)

    def _close(self, pos: Position, now: float, why: str) -> None:
        pos.closing = True
        st = self.uni.tokens.get(pos.key)
        lat = self.cfg.pump_latency_s if pos.venue == "pump" else self.cfg.gate_latency_s
        pd = Pending(self._id(), pos.sleeve, pos.key, pos.venue, -1, now, now + lat, st.mid() if st else float("nan"), pid=pos.pid, reason=why)
        self.pending[pd.oid] = pd
        self.pending_keys.add(pos.key)

    def _drop_pending(self, pd: Pending, why: str) -> None:
        self.pending.pop(pd.oid, None)
        if not any(p.key == pd.key for p in self.pending.values()):
            self.pending_keys.discard(pd.key)
        self.log("cancel", oid=pd.oid, key=pd.key, sleeve=pd.sleeve, reason=why)

    # ------------------------------------------------------------------ fills
    def _resolve(self, key: str, now: float, st: TokenState) -> None:
        for pd in [p for p in self.pending.values() if p.key == key]:
            if pd.rest:
                self._resolve_passive(pd, now, st)
            elif pd.t_arr <= now:
                (self._fill_open if pd.side > 0 else self._fill_close)(pd, st)

    def _pump_buy(self, usd: float, vq: float, vb: float, fee_bps: float) -> Tuple[float, float, float]:
        """(tokens, quote price per token on the curve, fee USD incl. network)."""
        tx = self._tx_fee_quote("pump")
        sol_in = usd / self.sol_usd - tx
        if sol_in <= 0:
            return 0.0, 0.0, 0.0
        tok, fee_sol, _ = curve_buy(vq, vb, sol_in, fee_bps)
        tok = math.floor(tok / self.cfg.pump_lot) * self.cfg.pump_lot
        net = sol_in - fee_sol
        return tok, (net / tok if tok > 0 else 0.0), (fee_sol + tx) * self.sol_usd

    def _fill_open(self, pd: Pending, st: TokenState) -> None:
        self.pending.pop(pd.oid, None)
        self.pending_keys.discard(pd.key)
        book = self.ceo.books[pd.sleeve]
        if not book.can_open(pd.usd) or not self.ceo.fill_budget_ok(self.t):
            self.log("cancel", oid=pd.oid, key=pd.key, sleeve=pd.sleeve, reason="state_or_budget_at_landing")
            return
        fee_bps = self._fee_bps(st)
        shadow: Dict[str, dict] = {}
        if pd.venue == "pump":
            if not (st.v_quote > 0 and st.v_base > 0) or st.complete:
                self.log("cancel", oid=pd.oid, key=pd.key, sleeve=pd.sleeve, reason="no_curve")
                return
            land_px = st.v_quote / st.v_base
            if land_px > pd.dec_px * (1 + self.cfg.pump_slippage_bps / 1e4):
                fee = self._tx_fee_quote("pump") * self.sol_usd
                book.failed_tx(fee)
                self.stats["failed_tx"] += 1
                self.log("failed_tx", oid=pd.oid, key=pd.key, sleeve=pd.sleeve, dec_px=pd.dec_px, land_px=land_px, fee_usd=round(fee, 5))
                return
            qty, px, fees = self._pump_buy(pd.usd, st.v_quote, st.v_base, fee_bps)
            if pd.worst is not None:
                q2, p2, f2 = self._pump_buy(pd.usd, pd.worst[1], pd.worst[2], fee_bps)
                shadow["adverse"] = {"qty": q2, "px": p2, "cost_usd": pd.usd}
            else:
                shadow["adverse"] = {"qty": qty, "px": px, "cost_usd": pd.usd}
            cost = pd.usd
        else:
            h = self.quotes.get(pd.key)
            q = h.asof(pd.t_arr) if h else None
            if q is None or not q[2] > 0:
                self.log("cancel", oid=pd.oid, key=pd.key, sleeve=pd.sleeve, reason="no_quote")
                return
            ask, aq = q[2], q[4]
            qty = math.floor(pd.usd / (1 + fee_bps / 1e4) / ask / st.lot) * st.lot
            top = min(qty, aq)
            notional = top * ask + (qty - top) * ask * (1 + self.cfg.gate_extra_bps / 1e4)
            if notional < st.min_notional:
                self.log("cancel", oid=pd.oid, key=pd.key, sleeve=pd.sleeve, reason="below_min_notional")
                return
            fees = notional * fee_bps / 1e4
            px, cost = notional / qty, notional + fees
        if qty <= 0:
            self.log("cancel", oid=pd.oid, key=pd.key, sleeve=pd.sleeve, reason="zero_qty")
            return
        self._book_open(pd, qty, px, cost, fees, shadow)

    def _book_open(self, pd: Pending, qty: float, px: float, cost: float, fees: float, shadow: Dict[str, dict]) -> None:
        p = pd.params
        pos = Position(self._id(), pd.sleeve, pd.key, pd.venue, qty, px, cost, fees, self.t, p["stop"], p["tp"], p["trail_arm"], p["trail"],
                       p["time_stop_s"], pd.reason, peak_px=px, shadow=shadow)
        self.positions[pos.pid] = pos
        self.by_key[pd.key] = pos.pid
        self.ceo.books[pd.sleeve].open(pos.pid, cost, fees)
        self.ceo.note_fill(self.t)
        self.stats["fills"] += 1
        self.stats["opens"] += 1
        self.log("open", pid=pos.pid, sleeve=pd.sleeve, key=pd.key, venue=pd.venue, qty=qty, px=px, cost_usd=round(cost, 5), fees_usd=round(fees, 5),
                 latency=round(self.t - pd.t_dec, 3), slip=(px / pd.dec_px - 1) if pd.dec_px > 0 else None, reason=pd.reason,
                 shadow={k: v for k, v in shadow.items()})

    def _resolve_passive(self, pd: Pending, now: float, st: TokenState) -> None:
        if pd.hist is not None:
            for m, o in pd.rest.items():
                qm.advance(o, now, pd.hist, [])
        prim = pd.rest["trades"]
        if prim.state == "filled":
            self.pending.pop(pd.oid, None)
            self.pending_keys.discard(pd.key)
            fee_bps = self._fee_bps(st)
            notional = prim.fill_value
            fees = notional * fee_bps / 1e4
            shadow = {m: ({"filled": True, "px": o.fill_value / o.filled} if o.filled > 0 else {"filled": False}) for m, o in pd.rest.items() if m != "trades"}
            self._book_open(pd, prim.filled, notional / prim.filled, notional + fees, fees, shadow)
            return
        if now >= pd.ttl or prim.state in ("rejected", "cancelled"):
            for m, o in pd.rest.items():
                if o.filled > 0:
                    self.stats[f"shadow_fill_only_{m}"] += 1
            self.stats["passive_expired"] += 1
            self._drop_pending(pd, "ttl" if now >= pd.ttl else prim.reject or prim.state)

    def _fill_close(self, pd: Pending, st: TokenState) -> None:
        self.pending.pop(pd.oid, None)
        self.pending_keys.discard(pd.key)
        pos = self.positions.get(pd.pid)
        if pos is None:
            return
        got, fees, px = self.liquidation_value(pos, st)
        if pos.venue == "gate":
            h = self.quotes.get(pos.key)
            q = h.asof(pd.t_arr) if h else None
            if q is not None and q[1] > 0:
                top = min(pos.qty, q[3])
                gross = top * q[1] + (pos.qty - top) * q[1] * (1 - self.cfg.gate_extra_bps / 1e4)
                fees = gross * self._fee_bps(st) / 1e4
                got, px = gross - fees, gross / pos.qty
        book = self.ceo.books[pos.sleeve]
        pnl = book.close(pos.pid, got, fees)
        self.ceo.note_fill(self.t)
        self.stats["fills"] += 1
        self.stats["closes"] += 1
        del self.positions[pos.pid]
        if self.by_key.get(pos.key) == pos.pid:
            del self.by_key[pos.key]
        models = {"primary": pnl}
        for m, sh in pos.shadow.items():                      # same exit, other entry models
            if sh.get("qty"):
                val_m = got * sh["qty"] / pos.qty
                models[m] = val_m - sh["cost_usd"]
            elif sh.get("filled") is False:
                models[m] = None
            elif sh.get("filled"):
                models[m] = pnl - (sh["px"] - pos.entry_px) * pos.qty
        if pos.venue == "pump" and pd.worst is not None:
            got_w, _, _ = self.liquidation_value(pos, st, pd.worst)
            models["adverse_exit"] = got_w - pos.cost_usd
        for m, v in models.items():
            if v is not None:
                agg = self.model_pnl.setdefault(f"{pos.sleeve}|{m}", [0.0, 0])
                agg[0] += v
                agg[1] += 1
        row = {"pid": pos.pid, "sleeve": pos.sleeve, "key": pos.key, "venue": pos.venue, "reason_in": pos.reason, "reason_out": pd.reason,
               "hold_s": round(self.t - pos.t_open, 2), "cost_usd": round(pos.cost_usd, 5), "got_usd": round(got, 5), "pnl_usd": round(pnl, 5),
               "ret": round(pnl / pos.cost_usd, 5) if pos.cost_usd else None, "fees_usd": round(pos.fees_usd + fees, 5),
               "models": {k: (None if v is None else round(v, 5)) for k, v in models.items()}}
        self.recent.append(row)
        self.log("close", **row)

    # ------------------------------------------------------------------ reporting / warm state
    def status(self) -> dict:
        s = self.ceo.summary()
        el = max(self.t - (self.t_start or self.t), 1e-9)
        return {"elapsed_s": round(el, 1), "equity": s["equity"], "halted": s["halted"], "fills": self.stats["fills"],
                "fills_per_hour": round(self.stats["fills"] / el * 3600, 1), "open": len(self.positions), "pending": len(self.pending),
                "tokens": len(self.uni.tokens), "prints": self.stats["prints"], "sleeves": {b["sleeve"]: [b["state"], b["equity"], b["round_trips"]] for b in s["sleeves"]}}

    def summary(self) -> dict:
        rt = list(self.recent)
        return {"status": self.status(), "ceo": self.ceo.summary(), "stats": dict(self.stats),
                "model_pnl": {k: {"sum_usd": round(v[0], 5), "n": v[1], "mean_usd": round(v[0] / v[1], 5) if v[1] else None} for k, v in self.model_pnl.items()},
                "recent_round_trips": rt[-50:], "gov_events": [e.as_dict() for e in self.ceo.events]}

    def save_snapshot(self) -> None:
        snap = {"t": self.t, "ceo": self.ceo.snapshot(), "next_id": self.next_id, "stats": dict(self.stats),
                "positions": [asdict(p) for p in self.positions.values()], "model_pnl": self.model_pnl}
        tmp = os.path.join(self.out_dir, "omega_state.json.tmp")
        with open(tmp, "w") as f:
            json.dump(snap, f, default=float)
        os.replace(tmp, os.path.join(self.out_dir, "omega_state.json"))

    def load_snapshot(self, path: str) -> None:
        snap = json.load(open(path))
        self.ceo.restore(snap["ceo"])
        self.next_id = snap.get("next_id", self.next_id)
        self.stats.update(snap.get("stats", {}))
        self.model_pnl = {k: list(v) for k, v in snap.get("model_pnl", {}).items()}
        for d in snap.get("positions", []):
            pos = Position(**d)
            self.positions[pos.pid] = pos
            self.by_key[pos.key] = pos.pid
