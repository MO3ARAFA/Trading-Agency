"""Phase 6 / Architecture A — pre-positioned quote maker with a Binance oracle cancel-shield.

Phase 5 showed that *reacting* to an impulse with a passive order is too late: by the time the signal fires the lagging venue's
makers are already repricing and the order is only filled when it is wrong. Architecture A moves the order *before* the impulse:

  * while Binance BTC is calm (every fast-horizon |Z| < ``calm_z``) we rest post-only quotes at the touch on both sides of each
    eligible market (Polymarket: 0 fee; Hyperliquid: assumed 1.5 bp maker — a two-leg round trip of 3 bp is more than HL's whole
    spread, so HL is gated out unless the fee assumption changes);
  * one clip of inventory per market: after a fill the opposite quote is the exit (spread capture) and the same-side quote is pulled;
  * when Binance fires a directional impulse (``impulse_z``, measured on 0.25 s / 1 s / 3 s horizons — faster than the 1 s+
    horizons of the signal path) the *vulnerable* quote (ask on a bullish jump, bid on a bearish one — sign flipped for
    contracts that fall when BTC rises) is cancelled. The cancel takes ``cancel_latency_s`` to land and **fills inside that
    window are real and flagged** — the shield's blind spot is measured, not assumed away;
  * the favourable quote stays; inventory on the vulnerable side is flattened (taker) and favourable inventory exits into the
    converged price (the exit order is the vulnerable ask on a bullish jump, so it is re-posted at the converged level);
  * quotes are never posted inside the shield hold or while BTC is not calm; no quotes inside ``expiry_pull_s`` of expiry,
    inventory is flat before ``expiry_flat_s`` (the CFO's own 60 s entry guard sits behind both).

Every variant (shield / no-shield x strict / depletion / trades fill model) runs the *same* quote policy on the same ticks; one
``ACCOUNT`` quoter is CFO-governed (binary worst-case sizing, breakers) and feeds the CFO/CEO books with a TradeResult per
inventory round trip. Fill realism lives in ``queue_model`` (queue position, post-only rejection, strict/depletion/trades).
"""
from __future__ import annotations

import math
from bisect import bisect_right
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np

from . import queue_model as qm
from .config import MMConfig
from .execution_engine import TradeResult
from .market_watchers import MarketBook, MarketMeta, maker_fee_bps, taker_fee_bps

BPS = 1e4
EPS = 1e-12


@dataclass(frozen=True)
class MMVariant:
    name: str
    shield: bool
    model: str            # strict | depletion | trades


class FastImpulse:
    """Sub-second BTC impulse detector: delta and Z over short horizons (own EW variance on a 50 ms grid)."""

    def __init__(self, horizons=(0.25, 1.0, 3.0), halflife_s: float = 120.0, grid_s: float = 0.05, floor_bps_sqrt_s: float = 0.2, warm_n: int = 400):
        self.h = tuple(horizons)
        self.grid = grid_s
        self.ts: List[float] = []
        self.ls: List[float] = []
        self.i0 = 0
        self.alpha = 1.0 - 0.5 ** (grid_s / halflife_s)
        self.m2 = [0.0] * len(self.h)
        self.n = [0] * len(self.h)
        self.floor = [floor_bps_sqrt_s * math.sqrt(h) * 1e-4 for h in self.h]
        self.next_grid = -1.0
        self.warm_n = warm_n
        self.last_lp = 0.0
        self.t = -1.0

    def _asof(self, x: float) -> float:
        j = bisect_right(self.ts, x, self.i0) - 1
        if j < self.i0:
            return float("nan")
        return self.ls[j]

    def update(self, t: float, S: float) -> None:
        if S <= 0:
            return
        lp = math.log(S)
        if self.ts and t < self.ts[-1]:
            return
        self.ts.append(t)
        self.ls.append(lp)
        self.last_lp = lp
        self.t = t
        if self.next_grid < 0:
            self.next_grid = (math.floor(t / self.grid) + 1) * self.grid
        if t - self.next_grid > 200 * self.grid:               # long gap: skip ahead rather than replaying it
            self.next_grid = math.floor(t / self.grid) * self.grid
        while self.next_grid <= t:
            g = self.next_grid
            lg = self._asof(g)
            if lg == lg:
                for k, h in enumerate(self.h):
                    lo = self._asof(g - h)
                    if lo != lo:
                        continue
                    d = lg - lo
                    self.n[k] += 1
                    a = max(self.alpha, 1.0 / self.n[k])
                    self.m2[k] += a * (d * d - self.m2[k])
            self.next_grid += self.grid
        horizon = self.h[-1] + 1.0
        if self.ts[-1] - self.ts[self.i0] > 3 * horizon + 2.0:        # trim: keep ~3 horizons of ticks
            j = bisect_right(self.ts, self.ts[-1] - 2 * horizon, self.i0)
            self.i0 = j
            if self.i0 > 20000:
                del self.ts[:self.i0], self.ls[:self.i0]
                self.i0 = 0

    def warm(self) -> bool:
        return self.n[-1] >= self.warm_n

    def read(self, t: float) -> List[Tuple[float, float]]:
        """[(delta_bps, z)] per horizon at time t (delta from the as-of log price t-h to the latest)."""
        out = []
        for k, h in enumerate(self.h):
            lo = self._asof(t - h)
            if lo != lo or not self.warm():
                out.append((0.0, 0.0))
                continue
            d = self.last_lp - lo
            sig = max(math.sqrt(max(self.m2[k], 0.0)), self.floor[k])
            out.append((d * BPS, d / sig))
        return out


class Quoter:
    """One market x one variant: two-sided post-only quotes, one clip of inventory, oracle cancel-shield."""

    def __init__(self, eng: "PrePositionedMM", i: int, var: MMVariant, account: bool):
        self.eng, self.i, self.var, self.account = eng, i, var, account
        self.meta: MarketMeta = eng.book.metas[i]
        self.cfg = eng.cfg
        self.venue = self.meta.venue
        self.bid: Optional[qm.RestOrder] = None
        self.ask: Optional[qm.RestOrder] = None
        self.old: List[qm.RestOrder] = []          # cancel-pending / retired orders that can still fill until their cancel lands
        self.inv = 0.0
        self.avg = 0.0
        self.ep: Optional[dict] = None
        self.qty = 0.0
        self.sign = 1
        self.vuln_side = 0                          # order side that is vulnerable while the shield is up (+1 bid / -1 ask)
        self.shield_until = -1.0
        self.last_imp_id = 0
        self.last_imp_t = -1e18
        self.taker: Optional[dict] = None
        self.conv_px: Optional[float] = None
        self.cool_until = -1.0
        self.gate_retry_t = -1.0
        self.n = {"posted": 0, "rejected_cross": 0, "shield_cancels": 0, "repegs": 0, "fills_bid": 0, "fills_ask": 0, "fills_in_cancel": 0,
                  "shield_flatten": 0, "gated_out": 0}

    # ------------------------------------------------------------------ helpers
    def models(self) -> str:
        return self.var.model

    def _old_live(self, side: int) -> bool:
        return any(o.side == side and o.live for o in self.old)

    def _orders(self) -> List[qm.RestOrder]:
        out = [o for o in (self.bid, self.ask) if o is not None]
        return out + self.old

    @property
    def idle(self) -> bool:
        return self.inv == 0.0 and self.taker is None and self.bid is None and self.ask is None and not self.old

    def _fee(self, maker: bool, px: float) -> float:
        c = self.eng.cfo.cfg
        return maker_fee_bps(self.meta, c.fee_maker_bps) if maker else taker_fee_bps(self.meta, px, c.fee_taker_bps)

    def _tick(self) -> float:
        return self.eng.tick(self.i)

    # ------------------------------------------------------------------ order primitives
    def _post(self, side: int, price: float, t: float) -> None:
        o = qm.RestOrder(side, price, self.qty_for(side), t, t + self.cfg.order_latency_s)
        if o.qty <= EPS:
            return
        self.n["posted"] += 1
        if side > 0:
            self.bid = o
        else:
            self.ask = o

    def qty_for(self, side: int) -> float:
        if self.inv != 0.0 and side == -int(math.copysign(1, self.inv)):
            return abs(self.inv)
        return self.qty

    def _cancel(self, o: Optional[qm.RestOrder], t: float, reason: str) -> None:
        if o is None or not o.live or o.cancel_t is not None:
            return
        qm.request_cancel(o, t, self.cfg.cancel_latency_s, reason)

    def _retire(self, side: int, t: float, reason: str) -> None:
        """Cancel the current order on ``side`` (it keeps filling until the cancel lands) and move it to ``old``."""
        o = self.bid if side > 0 else self.ask
        if o is None:
            return
        if o.live:
            self._cancel(o, t, reason)
            self.old.append(o)
        if side > 0:
            self.bid = None
        else:
            self.ask = None

    # ------------------------------------------------------------------ time
    def advance(self, t: float) -> None:
        hist = self.eng.hist[self.i]
        for o in self._orders():
            was = o.state
            qm.advance(o, t, hist, [])
            if was != o.state and o.state == "rejected":
                self.n["rejected_cross"] += 1
                self.cool_until = max(self.cool_until, t + 0.25)
        for o in (self.bid, self.ask):
            if o is not None and o.state in ("cancelled", "rejected", "filled"):
                if o is self.bid:
                    self.bid = None
                else:
                    self.ask = None
        self.old = [o for o in self.old if o.state in ("inflight", "resting", "cancel_pending")]
        tk = self.taker
        if tk is not None and t >= tk["t_arr"]:
            self._taker_arrive(t)

    # ------------------------------------------------------------------ inputs
    def on_quote(self, t: float, q: tuple) -> None:
        self.advance(t)
        m = self.var.model
        for o in self._orders():
            if o.state in ("resting", "cancel_pending"):
                out: list = []
                qm.on_quote(o, t, q, m, out)
                for (tt, px, qty, during) in out:
                    self._on_fill(o.side, px, qty, tt, during, True, o.cancel_reason)
        self._after_fills(t)
        self.manage(t, q)

    def on_trade(self, t: float, px: float, sz: float, agg: int) -> None:
        if self.var.model != "trades":
            return
        self.advance(t)
        for o in self._orders():
            if o.state in ("resting", "cancel_pending"):
                out: list = []
                qm.on_trade(o, t, px, sz, agg, "trades", out)
                for (tt, p, qty, during) in out:
                    self._on_fill(o.side, p, qty, tt, during, True, o.cancel_reason)
        self._after_fills(t)

    def _after_fills(self, t: float) -> None:
        for o in (self.bid, self.ask):
            if o is not None and o.state == "filled":
                if o is self.bid:
                    self.bid = None
                else:
                    self.ask = None
        self.old = [o for o in self.old if o.state in ("inflight", "resting", "cancel_pending")]

    # ------------------------------------------------------------------ inventory accounting
    def _on_fill(self, side: int, px: float, qty: float, t: float, during: bool, maker: bool = True, reason: str = "") -> None:
        if qty <= EPS:
            return
        self.n["fills_bid" if side > 0 else "fills_ask"] += 1
        if during:
            self.n["fills_in_cancel"] += 1
        fee = self._fee(maker, px) * px * qty / BPS
        pos = self.inv
        if pos == 0.0 or (pos > 0) == (side > 0):                  # opening / adding
            self._open(side, px, qty, t, during, maker, fee, reason)
            return
        close = min(qty, abs(pos))
        f_close = fee * close / qty
        ep = self.ep
        if ep is not None:
            ep["exit_qty"] += close
            ep["exit_val"] += close * px
            ep["fees"] += f_close
            ep["exit_maker_qty" if maker else "exit_taker_qty"] += close
            if during:
                ep["exit_in_cancel"] = True
                if reason == "shield":
                    ep["exit_in_shield"] = True
        self.inv = pos + side * close
        if abs(self.inv) < 1e-9:
            self.inv = 0.0
            self._close_episode(t)
        rest = qty - close
        if rest > 1e-9:                                            # flipped through flat: the remainder opens a fresh clip
            self._open(side, px, rest, t, during, maker, fee - f_close, reason)

    def _open(self, side: int, px: float, qty: float, t: float, during: bool, maker: bool, fee: float, reason: str = "") -> None:
        new = self.inv + side * qty
        self.avg = (abs(self.inv) * self.avg + qty * px) / max(abs(new), EPS)
        self.inv = new
        if self.ep is None:
            eng = self.eng
            recent = (t - self.last_imp_t) <= 10.0
            self.ep = {"side": side, "t0": t, "entry_qty": 0.0, "entry_val": 0.0, "exit_qty": 0.0, "exit_val": 0.0, "fees": 0.0,
                       "exit_maker_qty": 0.0, "exit_taker_qty": 0.0, "entry_in_cancel": False, "exit_in_cancel": False,
                       "entry_maker": maker, "entry_in_shield": False, "exit_in_shield": False, "after_impulse_s": (t - self.last_imp_t) if recent else None,
                       "imp": self.last_imp_id if recent else -eng.next_uid(), "shielded": t < self.shield_until,
                       "mid_entry": eng.mid_at(self.i, t), "reason": ""}
        ep = self.ep
        ep["entry_qty"] += qty
        ep["entry_val"] += qty * px
        ep["fees"] += fee
        if self.account:
            self.eng.cfo.on_open(self.meta.id, side, qty * px, 1.0)
            self.eng.account_open[self.i] = self
            ep["expo"] = ep.get("expo", 0.0) + qty * px
        if during:
            ep["entry_in_cancel"] = True
            if reason == "shield":
                ep["entry_in_shield"] = True
        # a fill on a side makes that side's quote obsolete (one clip); the opposite quote becomes the exit
        same = self.bid if side > 0 else self.ask
        if same is not None and same.live and same.state != "filled":
            self._retire(side, t, "post_fill")

    def _close_episode(self, t: float) -> None:
        ep, self.ep = self.ep, None
        if ep is None or ep["entry_qty"] <= EPS:
            return
        qty = ep["entry_qty"]
        ent = ep["entry_val"] / qty
        ex = ep["exit_val"] / max(ep["exit_qty"], EPS)
        side = ep["side"]
        gross = side * (ex - ent) * min(qty, ep["exit_qty"])
        net = gross - ep["fees"]
        eng = self.eng
        mk5 = eng.mid_at(self.i, ep["t0"] + 5.0)
        mk1 = eng.mid_at(self.i, ep["t0"] + 1.0)
        mq, tq = ep["exit_maker_qty"], ep["exit_taker_qty"]
        kind = "passive" if tq <= EPS else ("taker" if mq <= EPS else "mixed")
        notional = ent * qty
        r = {"variant": self.var.name, "model": self.var.model, "shield": self.var.shield, "account": self.account, "market": self.meta.id,
             "venue": self.venue, "kind": self.meta.kind, "side": side, "t0": ep["t0"], "t_end": t, "outcome": "filled", "entry_px": ent,
             "exit_px": ex, "qty": qty, "notional": notional, "gross_usd": gross, "fees_usd": ep["fees"], "net_usd": net,
             "gross_bps": gross / max(notional, EPS) * BPS, "net_bps": net / max(notional, EPS) * BPS, "net_cents": net / qty * 100.0,
             "gross_cents": gross / qty * 100.0, "hold_s": t - ep["t0"], "exit_kind": kind, "exit_reason": ep["reason"] or ("passive_fill" if kind == "passive" else "exit"),
             "entry_in_cancel": ep["entry_in_cancel"], "exit_in_cancel": ep["exit_in_cancel"], "in_shield_cancel": ep["entry_in_shield"] or ep["exit_in_shield"], "shielded_at_entry": ep["shielded"],
             "after_impulse_s": ep["after_impulse_s"], "imp": ep["imp"], "pred_net_bps": getattr(self, "pred_net", 0.0), "entry_maker": ep["entry_maker"],
             "markout1_bps": (side * (mk1 - ent) / ent * BPS) if np.isfinite(mk1) else float("nan"),
             "markout5_bps": (side * (mk5 - ent) / ent * BPS) if np.isfinite(mk5) else float("nan"),
             "stop_bps": self.cfg.stop_bps.get(self.venue, 6.0)}
        self.conv_px = None
        if self.account:
            eng.cfo.on_close(self.meta.id, side, ep.get("expo", notional), 1.0)
            eng.account_open.pop(self.i, None)
        eng._on_result(self, r)

    # ------------------------------------------------------------------ taker exit (IOC after order latency)
    def _send_taker(self, t: float, reason: str) -> None:
        if self.taker is not None or self.inv == 0.0:
            return
        if self.ep is not None and not self.ep["reason"]:
            self.ep["reason"] = reason
        self._retire(-1 if self.inv > 0 else 1, t, reason)               # pull the working exit (its fills during the cancel window still count)
        self.taker = {"t_arr": t + self.cfg.order_latency_s, "reason": reason}

    def _taker_arrive(self, t: float) -> None:
        tk, self.taker = self.taker, None
        if tk is None or self.inv == 0.0:
            return
        q = self.eng.hist[self.i].asof(tk["t_arr"])
        if q is None:
            return
        _, bid, ask, _, _ = q
        side = -1 if self.inv > 0 else 1
        px = bid if self.inv > 0 else ask
        qty = abs(self.inv)
        self._on_fill(side, px, qty, tk["t_arr"], False, maker=False)

    # ------------------------------------------------------------------ the shield
    def on_impulse(self, t: float, d: int, imp_id: int) -> None:
        """Binance just fired a directional impulse of sign ``d`` (BTC up = +1). Cancel what the lagging venue's informed flow can pick off."""
        eng = self.eng
        self.last_imp_id, self.last_imp_t = imp_id, t
        if not self.var.shield:
            return
        s = d * self.sign if self.meta.kind == "prediction" else d
        self.vuln_side = -s                                         # bullish contract move -> the ask is stale-cheap
        self.shield_until = max(self.shield_until, t + self.eng.hold_s(self.venue, self.account))
        v = self.bid if self.vuln_side > 0 else self.ask
        if v is not None and v.live and v.cancel_t is None:
            self.n["shield_cancels"] += 1
            self._retire(self.vuln_side, t, "shield")
        if self.inv != 0.0 and self.taker is None and (self.inv > 0) == (self.vuln_side > 0):   # holding the side about to be repriced against us
            self.n["shield_flatten"] += 1
            self._send_taker(t, "shield_flatten")

    # ------------------------------------------------------------------ quote management
    def manage(self, t: float, q: tuple) -> None:
        eng, c = self.eng, self.cfg
        _, bid, ask, bq, aq = q
        if bid <= 0 or ask <= bid:
            return
        mid = 0.5 * (bid + ask)
        ttl = eng.ttl(self.i, t)
        if self.inv != 0.0:
            self._manage_inventory(t, q, mid, ttl)
            return
        if ttl < c.expiry_pull_s or not eng.enabled_for(self.venue, self.account):
            for s in (1, -1):
                self._retire(s, t, "expiry" if ttl < c.expiry_pull_s else "disabled")
            return
        if self.taker is not None:
            return
        shielded = t < self.shield_until
        calm = eng.calm
        wait = False
        for side in (1, -1):
            o = self.bid if side > 0 else self.ask
            px = bid if side > 0 else ask
            if o is not None:
                if o.state == "rejected":
                    continue
                if (not shielded) and calm and o.live and o.cancel_t is None and abs(o.price - px) > 1e-12 and t - o.t_send >= c.min_rest_s:
                    self.n["repegs"] += 1                               # touch moved away: queue position is lost anyway
                    self._retire(side, t, "repeg")
                else:
                    continue
            if self._old_live(side):
                continue
            if shielded or not calm or t < self.cool_until:
                wait = True
                continue
            if t < self.gate_retry_t:
                continue
            if not eng.gate(self, t, bid, ask, mid):
                self.n["gated_out"] += 1
                self.gate_retry_t = t + 1.0                              # economics change slowly: don't re-run the gate on every tick
                continue
            self._post(side, px, t)
        if wait:
            eng.wait[(self.i, self.var.name)] = self
        else:
            eng.wait.pop((self.i, self.var.name), None)

    def _manage_inventory(self, t: float, q: tuple, mid: float, ttl: float) -> None:
        eng, c = self.eng, self.cfg
        _, bid, ask, bq, aq = q
        side_in = 1 if self.inv > 0 else -1
        exit_side = -side_in
        if self.taker is not None:
            return
        # same-side quote must not stay up (one clip of inventory)
        same = self.bid if side_in > 0 else self.ask
        if same is not None and same.live and same.cancel_t is None:
            self._retire(side_in, t, "inventory")
        adverse = -side_in * (mid - self.avg) / max(self.avg, EPS) * BPS
        held = t - (self.ep["t0"] if self.ep else t)
        if ttl < c.expiry_flat_s:
            self._send_taker(t, "expiry")
            return
        if self.meta.kind == "prediction":
            tkp = self._tick() or 0.01
            if -side_in * (mid - self.avg) >= c.stop_ticks * tkp - 1e-12:
                self._send_taker(t, "adverse_stop")
                return
        elif adverse >= c.stop_bps.get(self.venue, 6.0):
            self._send_taker(t, "adverse_stop")
            return
        if held >= c.hold_s.get(self.venue, 20.0):
            self._send_taker(t, "time_stop")
            return
        shielded = t < self.shield_until
        x = self.ask if exit_side < 0 else self.bid
        vulnerable_exit = shielded and self.vuln_side == exit_side
        if vulnerable_exit:
            if x is not None and x.live and x.cancel_t is None and not getattr(x, "conv", False):
                self._retire(exit_side, t, "shield")
                self.n["shield_cancels"] += 1
            if self.conv_px is None:
                return
        if x is not None and x.live:
            if x.qty + 1e-9 < abs(self.inv) and x.cancel_t is None:        # more filled during a cancel window: resize the exit
                self._retire(exit_side, t, "resize")
            return
        if t < self.cool_until or self._old_live(exit_side):
            return
        tk = self._tick()
        if vulnerable_exit and self.conv_px is not None:
            px = self.conv_px                                            # exit into the *converged* price, not the stale touch
        else:
            px = ask if exit_side < 0 else bid
        if tk > 0:
            px = math.ceil(px / tk - 1e-9) * tk if exit_side < 0 else math.floor(px / tk + 1e-9) * tk
        self._post_exit(exit_side, px, t, conv=(vulnerable_exit and self.conv_px is not None))

    def _post_exit(self, side: int, px: float, t: float, conv: bool = False) -> None:
        o = qm.RestOrder(side, px, abs(self.inv), t, t + self.cfg.order_latency_s)
        o.conv = conv                                                    # a converged-price exit is not the stale quote: the shield leaves it alone
        if side > 0:
            self.bid = o
        else:
            self.ask = o


class PrePositionedMM:
    def __init__(self, agency, cfg: Optional[MMConfig] = None, variants: Optional[List[MMVariant]] = None):
        self.a = agency
        self.book: MarketBook = agency.book
        self.cfo = agency.cfo
        self.cfg = cfg or MMConfig()
        self.variants = variants if variants is not None else default_mm_variants(self.cfg)
        self.venues = set(self.cfg.venues)
        self.prior_buf = dict(agency.cfg.cfo.mm_adverse_bps)
        self.prior_hold = dict(self.cfg.requote_hold_s)
        self.elig = [i for i, m in enumerate(self.book.metas) if m.venue in self.venues]
        self.hist: Dict[int, qm.QuoteHist] = {i: qm.QuoteHist() for i in self.elig}
        self.tick_est: Dict[int, float] = {}
        self._prev_px: Dict[int, tuple] = {}
        self.quoters: Dict[Tuple[int, str], Quoter] = {}
        self.by_market: Dict[int, List[Quoter]] = {}
        self.active: Dict[Tuple[int, str], Quoter] = {}
        self.wait: Dict[Tuple[int, str], Quoter] = {}
        self.fast = FastImpulse(self.cfg.fast_horizons_s, self.cfg.fast_halflife_s)
        self.calm = False
        self.impulse_id = 0
        self.imp_active_until = -1.0
        self.imp_dir = 0
        self.n_impulses = 0
        self._uid = 0
        self.results: List[dict] = []
        self.account_results: List[dict] = []
        self.account_open: Dict[int, Quoter] = {}
        self.enabled = True
        self._last_adv = -1.0
        self.n_gate_calls = 0
        self.max_abs_z = 0.0
        self.calm_frac = [0.0, 0.0]               # [calm seconds, total seconds]
        self._last_t = -1.0
        self.impulse_log: List[dict] = []

    # -------------------------------------------------------------- infra
    def eligible(self, idx: int) -> bool:
        return idx in self.hist

    def next_uid(self) -> int:
        self._uid += 1
        return 1000 + self._uid

    def tick(self, i: int) -> float:
        m = self.book.metas[i]
        return m.tick if m.tick > 0 else self.tick_est.get(i, 0.0)

    def mid_at(self, i: int, t: float) -> float:
        return self.book.mid_asof(i, t)

    def ttl(self, i: int, t: float) -> float:
        m = self.book.metas[i]
        te = m.extra.get("t_end") if m.extra else None
        pm = self.a.pm
        if te is None or pm is None:
            return 1e18
        return float(te) - pm.wall(t)

    def enabled_for(self, venue: str, account: bool = False) -> bool:
        """Shadow variants are a measurement instrument: only the ACCOUNT quoter obeys the CEO's venue switch-off."""
        if not self.enabled:
            return False
        return (venue not in self.cfo.cfg.mm_blocked and self.cfo.cfg.mm_enabled) if account else True

    def hold_s(self, venue: str, account: bool) -> float:
        return (self.cfg.requote_hold_s if account else self.prior_hold).get(venue, 3.0)

    def has_position(self, idx: int) -> bool:
        q = self.account_open.get(idx)
        return q is not None

    def pm_sign(self, i: int, S: float) -> int:
        pm = self.a.pm
        if pm is None:
            return 1
        spec = pm.specs.get(self.book.metas[i].id)
        if spec is None:
            return 1
        if spec.kind == "below":
            return -1
        if spec.kind == "range":
            return 1 if S < 0.5 * (spec.K + spec.B) else -1
        return 1

    def _quoter(self, i: int, var: MMVariant) -> Quoter:
        k = (i, var.name)
        q = self.quoters.get(k)
        if q is None:
            q = self.quoters[k] = Quoter(self, i, var, account=(var.name == "ACCOUNT"))
            self.by_market.setdefault(i, []).append(q)
        return q

    # -------------------------------------------------------------- gating
    def static_econ(self, i: int, spread_bps: float) -> Tuple[float, float, float]:
        """Shadow-variant economics with the *prior* adverse buffer (the ACCOUNT quoter uses the CFO's learned one), so the
        side-by-side variants test the raw policy and are not re-gated by what the account happened to learn."""
        c = self.cfo.cfg
        meta = self.book.metas[i]
        fee = maker_fee_bps(meta, c.fee_maker_bps)
        buf = max(self.prior_buf.get(meta.venue, 0.0), c.snipe_adverse_hs_frac * spread_bps / 2.0)
        return spread_bps - 2.0 * fee - buf - c.safety_hurdle_bps, fee, buf

    def gate(self, qt: Quoter, t: float, bid: float, ask: float, mid: float) -> bool:
        """May this quoter (re)post? Shadows: economics only. ACCOUNT: the full CFO decision (sizing, breakers, caps)."""
        i, meta = qt.i, qt.meta
        spread_bps = (ask - bid) / mid * BPS
        if meta.kind == "prediction":
            if not (self.cfg.pm_mid_lo <= mid <= self.cfg.pm_mid_hi):
                return False
        net, fee, buf = self.cfo.quote_econ(i, spread_bps) if qt.account else self.static_econ(i, spread_bps)
        if net < self.cfo.cfg.mm_min_ev_bps:
            return False
        self.n_gate_calls += 1
        ttl = self.ttl(i, t)
        if qt.account:
            dec = self.cfo.evaluate_quote(i, t, mid, spread_bps, n_open=len(self.account_open), ttl_s=ttl)
            if not dec.approved:
                return False
            notional, qt.pred_net = dec.notional, dec.net_edge_bps
        else:
            c = self.cfg
            notional = c.quote_notional.get("polymarket" if meta.kind == "prediction" else meta.venue, 100.0)
            qt.pred_net = net
        if meta.kind == "prediction":
            qty = math.floor(notional / max(mid, 1e-9) * 100) / 100
            if qty < meta.extra.get("min_size", 5.0):
                return False
        else:
            qty = notional / max(mid, 1e-9)
            if notional < 10.0:
                return False
        qt.qty = qty
        qt.sign = self.pm_sign(i, mid) if meta.kind == "prediction" else 1
        return True

    # -------------------------------------------------------------- inputs
    def on_quote(self, i: int, t: float, bid: float, ask: float, bq: float, aq: float) -> None:
        h = self.hist.get(i)
        if h is None:
            return
        prev = self._prev_px.get(i)
        if prev is not None:
            for a, b in ((prev[0], bid), (prev[1], ask)):
                d = abs(a - b)
                if d > 1e-9 and self.tick_est.get(i, 1e18) > d:
                    self.tick_est[i] = d
        self._prev_px[i] = (bid, ask)
        h.add(t, bid, ask, bq, aq)
        if not self.enabled or not self.fast.warm():
            return
        q = (t, bid, ask, bq, aq)
        for var in self.variants:
            qt = self._quoter(i, var)
            qt.on_quote(t, q)
            self._track(qt)

    def on_trade(self, i: int, t: float, px: float, sz: float, aggressor: int) -> None:
        for qt in self.by_market.get(i, ()):
            if qt.var.model == "trades" and not qt.idle:
                qt.on_trade(t, px, sz, aggressor)
                self._track(qt)

    def _track(self, qt: Quoter) -> None:
        k = (qt.i, qt.var.name)
        if qt.idle:
            self.active.pop(k, None)
        else:
            self.active[k] = qt

    # -------------------------------------------------------------- the oracle path
    def poll(self, t: float, S: float) -> None:
        if S <= 0 or not self.enabled:
            return
        c = self.cfg
        self.fast.update(t, S)
        if not self.fast.warm():
            return
        reads = self.fast.read(t)
        zmax, zd, dmax = 0.0, 0.0, 0.0
        for (d_bps, z) in reads:
            if abs(z) > zmax:
                zmax, zd, dmax = abs(z), (1 if z > 0 else -1), abs(d_bps)
        if self._last_t >= 0:
            dt = min(t - self._last_t, 1.0)
            self.calm_frac[1] += dt
            if zmax < c.calm_z:
                self.calm_frac[0] += dt
        self._last_t = t
        self.calm = zmax < c.calm_z
        self.max_abs_z = max(self.max_abs_z, zmax)
        if zmax >= c.impulse_z and dmax >= c.min_abs_bps:
            if t > self.imp_active_until or zd != self.imp_dir:      # a new directional impulse (not the tail of the last one)
                self.impulse_id += 1
                self.n_impulses += 1
                self.impulse_log.append({"id": self.impulse_id, "t": t, "dir": zd, "z": zmax, "bps": dmax})
                if len(self.impulse_log) > 20000:
                    del self.impulse_log[:5000]
            self.imp_active_until = t + 1.0
            self.imp_dir = zd
            for qt in list(self.active.values()):
                qt.on_impulse(t, zd, self.impulse_id)
            if self.var_shield_markets():
                for i, lst in self.by_market.items():                # quoters that are idle but could post next tick still need the impulse stamp
                    for qt in lst:
                        if qt.idle:
                            qt.on_impulse(t, zd, self.impulse_id)
        if t - self._last_adv >= 0.02:
            self._last_adv = t
            if self.calm or self.wait:
                for k, qt in list(self.wait.items()):
                    q = self.hist[qt.i].last()
                    if q is not None:
                        qt.advance(t)
                        qt.manage(t, q)
                        self._track(qt)
            for qt in list(self.active.values()):
                qt.advance(t)
                if qt.inv != 0.0 or qt.bid is not None or qt.ask is not None:
                    q = self.hist[qt.i].last()
                    if q is not None and (qt.inv != 0.0):
                        qt.manage(t, q)
                self._track(qt)

    def var_shield_markets(self) -> bool:
        return any(v.shield for v in self.variants)

    # -------------------------------------------------------------- signals: converged-price hint for inventory exits
    def on_signal(self, sig, S: float, dec=None) -> None:
        if not self.enabled:
            return
        for qt in self.by_market.get(sig.idx, ()):
            if qt.inv == 0.0 or qt.ep is None or qt.taker is not None:
                continue
            if (qt.inv > 0) != (sig.side > 0):
                continue                                          # signal points against our inventory: the shield/stop handles it
            tp = self.cfo.cfg.tp_capture * abs(sig.gap_bps)
            hs = sig.spread_bps / 2.0
            tgt = sig.mid * (1 + sig.side * tp / BPS) * (1 + sig.side * hs / BPS)
            tk = qt._tick()
            if tk > 0:
                tgt = math.ceil(tgt / tk - 1e-9) * tk if qt.inv > 0 else math.floor(tgt / tk + 1e-9) * tk
            qt.conv_px = tgt

    # -------------------------------------------------------------- results
    def _on_result(self, qt: Quoter, r: dict) -> None:
        self.results.append(r)
        if len(self.results) > 200_000:
            del self.results[:50_000]
        if qt.account:
            self.account_results.append(r)
            side = r["side"]
            tr = TradeResult(oid=int(r["imp"]), sid=int(r["imp"]), market=r["market"], side=side, mode="quote", t_entry=r["t0"], t_exit=r["t_end"],
                             entry_px=r["entry_px"], exit_px=r["exit_px"], qty=r["qty"], notional=r["notional"], gross_bps=r["gross_bps"],
                             fees_usd=r["fees_usd"], net_pnl_usd=r["net_usd"], net_bps=r["net_bps"],
                             R=r["net_usd"] / max(r["notional"] * r["stop_bps"] / BPS, 1e-9), exit_reason=r["exit_reason"], hold_s=r["hold_s"],
                             entry_slip_bps=0.0, exit_slip_bps=0.0, spread_bps_entry=0.0, predicted_net_bps=r["pred_net_bps"], gap_bps=0.0,
                             predicted_slip_bps=0.0)
            self.cfo.on_trade_closed(tr, r["t_end"])
            self.cfo.on_mm_result(r)
            self.a.engine.closed.append(tr)
            self.a._write("trades", tr.as_dict())
            self.a._write("mm_account", r)

    def finalize(self, t: float) -> None:
        """End of run: pull every quote, flatten remaining inventory at the last quote as a (charged) taker exit."""
        for qt in list(self.quoters.values()):
            qt.advance(t)
            for s in (1, -1):
                o = qt.bid if s > 0 else qt.ask
                if o is not None:
                    o.state = "cancelled"
            qt.bid = qt.ask = None
            qt.old = []
            if qt.inv != 0.0:
                q = self.hist[qt.i].last()
                if q is not None:
                    qt.ep["reason"] = qt.ep["reason"] or "end_of_run"
                    qt._on_fill(-1 if qt.inv > 0 else 1, q[1] if qt.inv > 0 else q[2], abs(qt.inv), t, False, maker=False)
            self._track(qt)

    # -------------------------------------------------------------- stats
    def rows(self, variant: Optional[str] = None, model: Optional[str] = None, venue: Optional[str] = None, account: Optional[bool] = None) -> List[dict]:
        out = []
        for r in self.results:
            if variant is not None and r["variant"] != variant:
                continue
            if model is not None and r["model"] != model:
                continue
            if venue is not None and r["venue"] != venue:
                continue
            if account is not None and r["account"] != account:
                continue
            out.append(r)
        return out

    def counters(self, variant: Optional[str] = None, model: Optional[str] = None, venue: Optional[str] = None) -> dict:
        tot: Dict[str, int] = {}
        for (i, vn), qt in self.quoters.items():
            if variant is not None and vn != variant:
                continue
            if model is not None and qt.var.model != model:
                continue
            if venue is not None and qt.venue != venue:
                continue
            for k, v in qt.n.items():
                tot[k] = tot.get(k, 0) + v
        return tot

    @staticmethod
    def summarize(rows: List[dict]) -> dict:
        n = len(rows)
        if n == 0:
            return {"n": 0}
        nb = np.array([r["net_bps"] for r in rows])
        mk = np.array([r["markout5_bps"] for r in rows if np.isfinite(r["markout5_bps"])])
        mu = float(nb.mean())
        by_imp: Dict[int, float] = {}
        for r in rows:
            by_imp[r["imp"]] = by_imp.get(r["imp"], 0.0) + (r["net_bps"] - mu)
        cl = np.array(list(by_imp.values()))
        se = float(np.sqrt((cl ** 2).sum()) / n) if len(cl) > 1 else 0.0           # cluster-robust by BTC impulse
        reasons: Dict[str, int] = {}
        for r in rows:
            reasons[r["exit_reason"]] = reasons.get(r["exit_reason"], 0) + 1
        return {"n": n, "net_usd": float(sum(r["net_usd"] for r in rows)), "net_bps": float(nb.mean()), "se_bps": se,
                "gross_bps": float(np.mean([r["gross_bps"] for r in rows])), "net_cents": float(np.mean([r["net_cents"] for r in rows])),
                "hit": float((nb > 0).mean()), "passive_exit": float(np.mean([r["exit_kind"] == "passive" for r in rows])),
                "in_cancel": sum(1 for r in rows if r["entry_in_cancel"] or r["exit_in_cancel"]), "in_shield_cancel": sum(1 for r in rows if r.get("in_shield_cancel")),
                "markout5": float(mk.mean()) if mk.size else 0.0, "reasons": reasons,
                "hold_s": float(np.mean([r["hold_s"] for r in rows])),
                "after_impulse": sum(1 for r in rows if r["after_impulse_s"] is not None)}


def default_mm_variants(cfg: MMConfig) -> List[MMVariant]:
    out: List[MMVariant] = []
    for m in cfg.shadow_models:
        out += [MMVariant(f"shield/{m}", True, m), MMVariant(f"noshield/{m}", False, m)]
    out.append(MMVariant("ACCOUNT", True, cfg.account_model))
    return out
