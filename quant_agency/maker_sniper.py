"""Phase 5 — queue-aware passive maker sniper with an oracle cancel shield (Hyperliquid perps + Polymarket CLOB).

Idea: a validated Binance BTC impulse says a lagging venue's price is about to move. Instead of *crossing* the book (paying
spread + taker fee) we rest a post-only order at the touch (``join``) or one tick inside a wide spread (``penny``), ride the
lag wave, and work a passive exit at the converged price. The danger is adverse selection (filled only when the impulse fails),
so a **cancel shield** watches the Binance oracle on every BTC tick and pulls the order if the impulse decays or reverses — with
a 150 ms cancel latency during which fills still happen and are charged.

Fill realism (no fake optimism):
  * an order sent at t0 *arrives* at t0 + order latency and is judged against the **as-of quote at arrival** (post-only that
    would cross is rejected; joining queues behind the visible size; penny-jumping starts at the front);
  * ``strict``   fills only when the opposite touch crosses our price (a certain, lower-bound fill);
  * ``depletion``  treats displayed-size depletion at our level as trades (upper bound; used when no trade tape exists);
  * ``trades``   consumes the queue ahead with real trade prints (live) and sweeps through on prints beyond our price;
  * cancels take effect ``cancel latency`` after the request; fills inside that window are real and flagged
    ``fill_during_cancel`` (the shield's blind spot is measured, not assumed away).
All variants run on the *same* signals so taker / join / penny / no-shield / taker-exit are compared on identical ticks.
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional, Tuple

import numpy as np

from .config import SnipeConfig
from .execution_engine import TradeResult
from .inefficiency_hunter import Signal
from .market_watchers import MarketBook, MarketMeta, maker_fee_bps, taker_fee_bps

BPS = 1e4
EPS = 1e-12


@dataclass(frozen=True)
class Variant:
    name: str
    entry: str            # taker | join | penny
    exit: str             # passive | taker
    shield: bool
    model: str            # strict | depletion | trades


@dataclass
class Order:
    kind: str                         # entry | exit
    side: int                         # +1 buy / -1 sell
    price: float
    qty: float
    tif: str                          # ALO | IOC
    t_send: float
    t_arr: float
    state: str = "inflight"           # inflight | resting | cancel_pending | filled | cancelled | rejected | done
    ahead: Optional[float] = None     # queue ahead (None = not at the touch yet)
    last_lvl: Optional[float] = None
    filled: float = 0.0
    fill_value: float = 0.0
    cancel_t: Optional[float] = None
    cancel_eff: Optional[float] = None
    cancel_reason: str = ""
    fills: List[Tuple[float, float, float, bool]] = field(default_factory=list)   # (t, px, qty, during_cancel)

    @property
    def remaining(self) -> float:
        return max(self.qty - self.filled, 0.0)


class QuoteHist:
    """Short per-market quote history with sizes (as-of lookups for order arrival)."""

    def __init__(self, maxlen: int = 3000):
        self.q: Deque[tuple] = deque(maxlen=maxlen)

    def add(self, t, bid, ask, bq, aq):
        self.q.append((t, bid, ask, bq, aq))

    def asof(self, t: float) -> Optional[tuple]:
        for rec in reversed(self.q):
            if rec[0] <= t:
                return rec
        return self.q[0] if self.q else None

    def last(self):
        return self.q[-1] if self.q else None


class Attempt:
    """One signal x one variant: entry order -> (cancel) -> exit -> result."""

    def __init__(self, sn: "MakerSniper", var: Variant, sig: Signal, notional: float, account: bool, S0: float, stop_bps: float,
                 tp_bps: float, entry_mode: Optional[str] = None, pred_net_bps: float = 0.0):
        self.sn, self.var, self.sig, self.account = sn, var, sig, account
        self.i = sig.idx
        self.meta: MarketMeta = sn.book.metas[self.i]
        self.cfg = sn.cfg
        self.side = sig.side
        self.t0 = sig.t
        self.notional = notional
        self.stop_bps = stop_bps
        self.tp_bps = tp_bps
        self.dir = 1 if sig.btc_delta_bps >= 0 else -1
        self.impulse_bps = max(abs(sig.btc_delta_bps), 1e-9)
        self.S0 = S0
        self.S_ref = S0 / math.exp(sig.btc_delta_bps / BPS)
        self.mid0 = sig.mid
        self.hs_bps = sig.spread_bps / 2.0
        self.pred_net = pred_net_bps
        self.mode = entry_mode or var.entry
        self.state = "entry"
        self.entry: Optional[Order] = None
        self.exit: Optional[Order] = None
        self.taker_exit: Optional[Order] = None
        self.exit_reason = ""
        self.entry_fill_t: Optional[float] = None
        self.fill_mid: float = 0.0
        self.qty_pos = 0.0
        self.entry_px = 0.0
        self.shield_cancelled = False
        self.fill_during_cancel = False
        self.exit_start: Optional[float] = None
        self.work_deadline: Optional[float] = None
        self.hold_deadline: Optional[float] = None
        self.stop_t: Optional[float] = None
        self.result: Optional[dict] = None
        self.reject: str = ""
        self._place_entry()

    # ------------------------------------------------------------------ helpers
    @property
    def venue(self) -> str:
        return self.meta.venue

    def tick(self) -> float:
        return self.meta.tick if self.meta.tick > 0 else self.sn.tick_est.get(self.i, 0.0)

    def _round(self, px: float, up: bool) -> float:
        tk = self.tick()
        if tk <= 0:
            return px
        return math.ceil(px / tk - 1e-9) * tk if up else math.floor(px / tk + 1e-9) * tk

    def _fee(self, maker: bool, px: float) -> float:
        c = self.sn.cfo.cfg
        return maker_fee_bps(self.meta, c.fee_maker_bps) if maker else taker_fee_bps(self.meta, px, c.fee_taker_bps)

    # ------------------------------------------------------------------ entry
    def _place_entry(self) -> None:
        sg, c = self.sig, self.cfg
        olat = c.order_latency_s
        if self.var.entry == "taker" or self.mode == "taker":
            px = sg.ask * (1 + c.taker_slack_bps / BPS) if self.side > 0 else sg.bid * (1 - c.taker_slack_bps / BPS)
            tif = "IOC"
        else:
            tk = self.tick()
            if self.mode == "penny" and tk > 0 and (sg.ask - sg.bid) >= 2 * tk - 1e-12:
                px = sg.bid + tk if self.side > 0 else sg.ask - tk
            else:
                px = sg.bid if self.side > 0 else sg.ask
            tif = "ALO"
        qty = self.notional / max(px, EPS)
        if self.venue == "polymarket":
            qty = math.floor(qty * 100) / 100
            if qty < self.meta.extra.get("min_size", 5.0):
                self.reject = "below_min_size"
        elif self.notional < 10.0:
            self.reject = "below_min_notional"
        self.entry = Order("entry", self.side, px, qty, tif, self.t0, self.t0 + olat)
        if self.reject:
            self.entry.state = "rejected"
            self._finish(self.t0, "no_fill")

    # ------------------------------------------------------------------ event clock
    def _next_event(self) -> Optional[Tuple[float, str]]:
        ev: List[Tuple[float, str]] = []
        e, x = self.entry, self.exit
        if self.state == "entry" and e is not None:
            if e.state == "inflight":
                ev.append((e.t_arr, "entry_arrive"))
            if e.state == "resting" and e.cancel_t is None:
                ev.append((e.t_send + self.cfg.ttl_s.get(self.venue, 6.0), "entry_ttl"))
            if e.state in ("resting", "cancel_pending") and e.cancel_eff is not None:
                ev.append((e.cancel_eff, "entry_cancel_eff"))
        if self.state == "exit":
            if x is not None:
                if x.state == "inflight":
                    ev.append((x.t_arr, "exit_arrive"))
                if x.state in ("resting", "cancel_pending") and x.cancel_eff is not None:
                    ev.append((x.cancel_eff, "exit_cancel_eff"))
            if self.work_deadline is not None and self.taker_exit is None and self.stop_t is None:
                ev.append((self.work_deadline, "work_deadline"))
            if self.hold_deadline is not None and self.taker_exit is None:
                ev.append((self.hold_deadline, "hold_deadline"))
            if self.taker_exit is not None and self.taker_exit.state == "inflight":
                ev.append((self.taker_exit.t_arr, "taker_arrive"))
        if not ev:
            return None
        return min(ev)

    def advance(self, t: float) -> None:
        guard = 0
        while self.state != "done" and guard < 50:
            guard += 1
            nxt = self._next_event()
            if nxt is None or nxt[0] > t:
                return
            self._handle(nxt[0], nxt[1])

    def _handle(self, t: float, kind: str) -> None:
        c = self.cfg
        if kind == "entry_arrive":
            self._entry_arrive(t)
        elif kind == "entry_ttl":
            self.request_cancel(t, "ttl")
        elif kind == "entry_cancel_eff":
            e = self.entry
            e.state = "cancelled" if e.filled <= 0 else "filled"
            e.cancel_eff = None
            if e.filled <= 0:
                self._finish(t, "no_fill", e.cancel_reason or "cancelled")
            else:
                self._start_exit(t)
        elif kind == "exit_arrive":
            self._exit_arrive(t)
        elif kind == "exit_cancel_eff":
            self.exit.state = "cancelled" if self.exit.filled < self.exit.qty - 1e-12 else "filled"
            self.exit.cancel_eff = None
        elif kind in ("work_deadline", "hold_deadline"):
            self._send_taker_exit(t, "work_expired" if kind == "work_deadline" else "time_stop")
        elif kind == "taker_arrive":
            self._taker_arrive(t)

    # ------------------------------------------------------------------ entry arrival / resting
    def _entry_arrive(self, t: float) -> None:
        e = self.entry
        q = self.sn.hist[self.i].asof(t)
        if q is None:
            e.state = "rejected"
            self._finish(t, "no_fill", "no_quote")
            return
        _, bid, ask, bq, aq = q
        if e.tif == "IOC":
            px = ask if e.side > 0 else bid
            lim_ok = (px <= e.price) if e.side > 0 else (px >= e.price)
            top = aq if e.side > 0 else bq
            if not lim_ok:
                e.state = "rejected"
                self._finish(t, "no_fill", "ioc_price_moved")
                return
            qty = min(e.qty, top)
            if qty < 0.5 * e.qty or qty <= 0:
                e.state = "rejected"
                self._finish(t, "no_fill", "ioc_no_liquidity")
                return
            self._fill(e, t, px, qty, maker=False)
            e.state = "filled"
            self._start_exit(t)
            return
        # post-only
        if (e.side > 0 and e.price >= ask - 1e-12) or (e.side < 0 and e.price <= bid + 1e-12):
            e.state = "rejected"
            self._finish(t, "no_fill", "post_only_cross")
            return
        self._rest(e, q)
        e.state = "resting"

    def _rest(self, o: Order, q: tuple) -> None:
        _, bid, ask, bq, aq = q
        if o.side > 0:
            if o.price > bid:
                o.ahead, o.last_lvl = 0.0, None             # inside the spread: front of queue
            elif abs(o.price - bid) < 1e-12:
                o.ahead, o.last_lvl = bq, bq                # joins behind the visible size
            else:
                o.ahead, o.last_lvl = None, None            # behind the touch
        else:
            if o.price < ask:
                o.ahead, o.last_lvl = 0.0, None
            elif abs(o.price - ask) < 1e-12:
                o.ahead, o.last_lvl = aq, aq
            else:
                o.ahead, o.last_lvl = None, None

    def request_cancel(self, t: float, reason: str) -> None:
        o = self.entry if self.state == "entry" else self.exit
        if o is None or o.state != "resting":
            return
        o.state = "cancel_pending"
        o.cancel_t = t
        o.cancel_eff = t + self.cfg.cancel_latency_s
        o.cancel_reason = reason
        if o.kind == "entry" and reason in ("shield", "converged"):
            self.shield_cancelled = True

    # ------------------------------------------------------------------ fills
    def _fill(self, o: Order, t: float, px: float, qty: float, maker: bool) -> None:
        qty = min(qty, o.remaining)
        if qty <= 1e-12:
            return
        during = o.cancel_t is not None and t >= o.cancel_t
        o.fills.append((t, px, qty, during))
        o.filled += qty
        o.fill_value += px * qty
        if during and o.kind == "entry":
            self.fill_during_cancel = True
        if o.kind == "entry" and self.entry_fill_t is None:
            self.entry_fill_t = t
            self.fill_mid = self.sn.mid_at(self.i, t)
            if o.state == "resting":                       # first fill: cancel the remainder (latency charged)
                if o.remaining > 1e-12:
                    o.state = "cancel_pending"
                    o.cancel_t = t
                    o.cancel_eff = t + self.cfg.cancel_latency_s
                    o.cancel_reason = "post_fill"
                else:
                    o.state = "filled"
                    self._start_exit(t)

    def _book_fill_rules(self, o: Order, t: float, q_new: tuple) -> None:
        """Apply quote-driven fill rules to a resting/cancel-pending order."""
        _, bid, ask, bq, aq = q_new
        model = self.var.model
        P = o.price
        if o.side > 0:
            if ask <= P + 1e-12:                                               # strict: touch crossed our bid
                self._fill(o, t, P, o.remaining, True)
                return
            if model == "depletion":
                if abs(bid - P) < 1e-12:
                    if o.ahead is None:
                        o.ahead = bq
                    elif o.last_lvl is not None:
                        dep = max(0.0, o.last_lvl - bq)
                        o.ahead -= dep
                        if o.ahead < 0:
                            self._fill(o, t, P, -o.ahead, True)
                            o.ahead = 0.0
                    o.last_lvl = bq
                elif bid < P - 1e-12 and o.ahead is not None:                  # our level vanished downwards: consumed
                    self._fill(o, t, P, o.remaining, True)
                else:
                    o.last_lvl = None
            elif model == "trades":
                if abs(bid - P) < 1e-12 and o.ahead is None:
                    o.ahead = bq
        else:
            if bid >= P - 1e-12:
                self._fill(o, t, P, o.remaining, True)
                return
            if model == "depletion":
                if abs(ask - P) < 1e-12:
                    if o.ahead is None:
                        o.ahead = aq
                    elif o.last_lvl is not None:
                        dep = max(0.0, o.last_lvl - aq)
                        o.ahead -= dep
                        if o.ahead < 0:
                            self._fill(o, t, P, -o.ahead, True)
                            o.ahead = 0.0
                    o.last_lvl = aq
                elif ask > P + 1e-12 and o.ahead is not None:
                    self._fill(o, t, P, o.remaining, True)
                else:
                    o.last_lvl = None
            elif model == "trades":
                if abs(ask - P) < 1e-12 and o.ahead is None:
                    o.ahead = aq

    def _trade_fill_rules(self, o: Order, t: float, px: float, sz: float, aggressor: int) -> None:
        if self.var.model != "trades":
            return
        P = o.price
        if o.side > 0 and aggressor < 0:                                       # seller-initiated print hits bids
            if px < P - 1e-12:
                self._fill(o, t, P, o.remaining, True)                         # swept through our price
            elif abs(px - P) < 1e-12:
                self._consume(o, t, sz)
        elif o.side < 0 and aggressor > 0:
            if px > P + 1e-12:
                self._fill(o, t, P, o.remaining, True)
            elif abs(px - P) < 1e-12:
                self._consume(o, t, sz)

    def _consume(self, o: Order, t: float, sz: float) -> None:
        ahead = o.ahead if o.ahead is not None else 0.0
        if sz <= ahead:
            o.ahead = ahead - sz
        else:
            o.ahead = 0.0
            self._fill(o, t, o.price, sz - ahead, True)

    # ------------------------------------------------------------------ event inputs
    def on_quote(self, t: float, q: tuple) -> None:
        if self.state == "done":
            return
        self.advance(t)
        if self.state == "done":
            return
        o = self.entry if self.state == "entry" else self.exit
        if o is not None and o.state in ("resting", "cancel_pending") and o.tif == "ALO":
            before = o.filled
            self._book_fill_rules(o, t, q)
            self._after_fill(o, before, t)
        if self.state == "exit":
            self._check_stop_tp(t, q)

    def on_trade(self, t: float, px: float, sz: float, aggressor: int) -> None:
        if self.state == "done":
            return
        self.advance(t)
        if self.state == "done":
            return
        o = self.entry if self.state == "entry" else self.exit
        if o is not None and o.state in ("resting", "cancel_pending") and o.tif == "ALO":
            before = o.filled
            self._trade_fill_rules(o, t, px, sz, aggressor)
            self._after_fill(o, before, t)

    def _after_fill(self, o: Order, before: float, t: float) -> None:
        if o.filled <= before:
            return
        if o.kind == "entry":
            if o.remaining <= 1e-12 and o.state in ("resting", "cancel_pending"):
                o.state = "filled"
                o.cancel_eff = None
                self._start_exit(t)
        else:
            if o.remaining <= 1e-12:
                o.state = "filled"
                o.cancel_eff = None
                self._maybe_close(t)

    # ------------------------------------------------------------------ exit
    def _start_exit(self, t: float) -> None:
        e = self.entry
        self.qty_pos = e.filled
        self.entry_px = e.fill_value / e.filled
        self.state = "exit"
        self.exit_start = max(t, self.entry_fill_t or t)
        self.hold_deadline = (self.entry_fill_t or t) + self.cfg.max_hold_s
        olat = self.cfg.order_latency_s
        if self.var.exit == "passive":
            tgt = self.mid0 * (1 + self.side * self.tp_bps / BPS)
            tgt_ask = tgt * (1 + self.side * self.hs_bps / BPS)                 # converged touch on the exit side
            px = self._round(tgt_ask, up=(self.side > 0))
            self.exit = Order("exit", -self.side, px, self.qty_pos, "ALO", self.exit_start, self.exit_start + olat)
            self.work_deadline = self.exit_start + self.cfg.work_s.get(self.venue, 8.0)
        else:
            self.exit = None

    def _exit_arrive(self, t: float) -> None:
        x = self.exit
        q = self.sn.hist[self.i].asof(t)
        if q is None:
            self._send_taker_exit(t, "no_quote")
            return
        _, bid, ask, bq, aq = q
        crosses = (x.side < 0 and x.price <= bid + 1e-12) or (x.side > 0 and x.price >= ask - 1e-12)
        if crosses:                                                             # market already through our target: take it
            x.state = "rejected"
            self._send_taker_exit(t, "target_passed", immediate=True)
            return
        self._rest(x, q)
        x.state = "resting"

    def _send_taker_exit(self, t: float, reason: str, immediate: bool = False) -> None:
        if self.taker_exit is not None or self.state == "done":
            return
        self.exit_reason = self.exit_reason or reason
        x = self.exit
        if x is not None and x.state == "resting":
            x.state = "cancel_pending"
            x.cancel_t = t
            x.cancel_eff = t + self.cfg.cancel_latency_s
            x.cancel_reason = reason
        rem = self.qty_pos - (x.filled if x is not None else 0.0)
        if rem <= 1e-12:
            return
        self.taker_exit = Order("exit", -self.side, 0.0, rem, "IOC", t, t if immediate else t + self.cfg.order_latency_s)
        self.stop_t = self.stop_t or (t if reason == "adverse_stop" else None)
        if immediate:
            self._taker_arrive(t)

    def _taker_arrive(self, t: float) -> None:
        tx = self.taker_exit
        q = self.sn.hist[self.i].asof(t)
        if q is None:
            return
        _, bid, ask, bq, aq = q
        x = self.exit
        rem = self.qty_pos - (x.filled if x is not None else 0.0)         # passive fills before arrival reduce the taker size
        if rem <= 1e-12:
            tx.state = "done"
            self._maybe_close(t)
            return
        px = bid if self.side > 0 else ask
        tx.qty = rem
        tx.fills.append((t, px, rem, False))
        tx.filled = rem
        tx.fill_value = px * rem
        tx.state = "filled"
        self._maybe_close(t)

    def _check_stop_tp(self, t: float, q: tuple) -> None:
        if self.taker_exit is not None:
            return
        _, bid, ask, bq, aq = q
        mid = 0.5 * (bid + ask)
        adverse = -self.side * (mid - self.fill_mid) / max(self.fill_mid, EPS) * BPS
        if adverse >= self.stop_bps:
            self._send_taker_exit(t, "adverse_stop")
            return
        if self.var.exit == "taker":
            tgt = self.mid0 * (1 + self.side * self.tp_bps / BPS)
            if (self.side > 0 and mid >= tgt) or (self.side < 0 and mid <= tgt):
                self._send_taker_exit(t, "take_profit")

    def _maybe_close(self, t: float) -> None:
        x, tx = self.exit, self.taker_exit
        done_qty = (x.filled if x is not None else 0.0) + (tx.filled if tx is not None else 0.0)
        if done_qty >= self.qty_pos - 1e-9:
            self._finish(t, "filled")

    # ------------------------------------------------------------------ result
    def _finish(self, t: float, outcome: str, why: str = "") -> None:
        if self.state == "done":
            return
        self.state = "done"
        r = {"variant": self.var.name, "model": self.var.model, "account": self.account, "entry_mode": self.mode, "market": self.meta.id,
             "venue": self.venue, "kind": self.meta.kind, "side": self.side, "sid": self.sig.sid, "imp": self.sig.impulse_id, "t0": self.t0,
             "t_end": t, "outcome": outcome, "reason": why or self.reject, "gap_bps": self.sig.gap_bps, "spread_bps": self.sig.spread_bps,
             "mid0": self.mid0, "shield_cancel": self.shield_cancelled, "fill_during_cancel": self.fill_during_cancel,
             "notional": self.notional, "pred_net_bps": self.pred_net}
        if outcome == "filled" and self.qty_pos > 0:
            e, x, tx = self.entry, self.exit, self.taker_exit
            qty = self.qty_pos
            ent = e.fill_value / e.filled
            ex_val = (x.fill_value if x is not None else 0.0) + (tx.fill_value if tx is not None else 0.0)
            ex_qty = (x.filled if x is not None else 0.0) + (tx.filled if tx is not None else 0.0)
            exp = ex_val / ex_qty if ex_qty > 0 else ent
            entry_maker = e.tif == "ALO"
            f_in = self._fee(entry_maker, ent) * ent * qty / BPS
            f_out = 0.0
            if x is not None and x.filled > 0:
                f_out += self._fee(True, x.fill_value / x.filled) * x.fill_value / BPS
            if tx is not None and tx.filled > 0:
                f_out += self._fee(False, tx.fill_value / tx.filled) * tx.fill_value / BPS
            gross = self.side * (exp - ent) * qty
            net = gross - f_in - f_out
            fill_t = self.entry_fill_t or t
            mk5 = self.sn.mid_at(self.i, fill_t + 5.0)
            exit_kind = ("passive" if (x is not None and x.filled > 0 and (tx is None or tx.filled == 0)) else
                         ("mixed" if (x is not None and x.filled > 0) else "taker"))
            r.update({"entry_px": ent, "exit_px": exp, "qty": qty, "fill_t": fill_t, "wait_s": fill_t - self.t0, "fees_usd": f_in + f_out,
                      "gross_usd": gross, "net_usd": net, "gross_bps": gross / (ent * qty) * BPS, "net_bps": net / (ent * qty) * BPS,
                      "exit_kind": exit_kind, "exit_reason": self.exit_reason or ("passive_fill" if exit_kind == "passive" else "exit"),
                      "hold_s": t - fill_t, "entry_maker": entry_maker,
                      "markout5_bps": (self.side * (mk5 - ent) / ent * BPS) if np.isfinite(mk5) else float("nan"),
                      "net_cents": net / qty * 100.0, "gross_cents": gross / qty * 100.0})
        self.result = r
        self.sn._on_result(self, r)


class MakerSniper:
    def __init__(self, agency, cfg: Optional[SnipeConfig] = None, variants: Optional[List[Variant]] = None):
        self.a = agency
        self.book: MarketBook = agency.book
        self.cfo = agency.cfo
        self.cfg = cfg or SnipeConfig()
        self.variants = variants if variants is not None else default_variants(self.cfg)
        self.hist: Dict[int, QuoteHist] = {}
        self.tick_est: Dict[int, float] = {}
        self._prev_px: Dict[int, tuple] = {}
        self.venues = set(self.cfg.venues)
        self.elig = [i for i, m in enumerate(self.book.metas) if m.venue in self.venues]
        for i in self.elig:
            self.hist[i] = QuoteHist()
        self.active: Dict[int, List[Attempt]] = {}
        self.results: List[dict] = []
        self.n_signals = 0
        self.account_open: Dict[int, Attempt] = {}
        self.account_results: List[dict] = []
        self.enabled = True

    # -------------------------------------------------------------- infra
    def eligible(self, idx: int) -> bool:
        return idx in self.hist

    def mid_at(self, i: int, t: float) -> float:
        return self.book.mid_asof(i, t)

    def has_position(self, idx: int) -> bool:
        return idx in self.account_open

    # -------------------------------------------------------------- inputs
    def on_quote(self, i: int, t: float, bid: float, ask: float, bq: float, aq: float) -> None:
        h = self.hist.get(i)
        if h is None:
            return
        prev = self._prev_px.get(i)
        if prev is not None:                                    # infer HL tick from the smallest observed price step
            for a, b in ((prev[0], bid), (prev[1], ask)):
                d = abs(a - b)
                if d > 1e-9 and (self.tick_est.get(i, 1e18) > d):
                    self.tick_est[i] = d
        self._prev_px[i] = (bid, ask)
        h.add(t, bid, ask, bq, aq)
        atts = self.active.get(i)
        if atts:
            q = (t, bid, ask, bq, aq)
            for at in list(atts):
                at.on_quote(t, q)
            self._sweep(i)

    def on_trade(self, i: int, t: float, px: float, sz: float, aggressor: int) -> None:
        atts = self.active.get(i)
        if atts:
            for at in list(atts):
                at.on_trade(t, px, sz, aggressor)
            self._sweep(i)

    def _sweep(self, i: int) -> None:
        atts = self.active.get(i)
        if atts is not None:
            self.active[i] = [a for a in atts if a.state != "done"]

    def poll(self, t: float, S: float) -> None:
        """Time events + the oracle cancel shield (called on every BTC scan and by housekeeping)."""
        if not self.active:
            return
        c = self.cfg
        for i, atts in list(self.active.items()):
            for at in list(atts):
                at.advance(t)
                if at.state == "entry" and at.entry is not None and at.entry.state == "resting" and at.var.shield and S > 0:
                    ret = at.dir * math.log(S / at.S_ref) * BPS / at.impulse_bps
                    rev = at.dir * math.log(S / at.S0) * BPS
                    why = None
                    if ret < c.hold_frac or rev <= -c.rev_bps:
                        why = "shield"
                    else:
                        q = self.hist[i].last()
                        if q is not None:
                            mid = 0.5 * (q[1] + q[2])
                            gap_px = abs(at.sig.gap_bps) / BPS * at.mid0
                            moved = at.side * (mid - at.mid0)
                            if gap_px > 0 and moved >= c.converge_frac * gap_px:
                                why = "converged"
                    if why:
                        at.request_cancel(t, why)
            self._sweep(i)

    # -------------------------------------------------------------- signals
    def on_signal(self, sig: Signal, S: float, dec=None) -> None:
        """Spawn every shadow variant (fixed notional) and, if the CFO approved, the account attempt."""
        if not self.enabled or sig.idx not in self.hist:
            return
        self.n_signals += 1
        meta = self.book.metas[sig.idx]
        c = self.cfg
        notional = c.hl_notional if meta.venue == "hyperliquid" else c.pm_notional
        tp_bps = self.cfo.cfg.tp_capture * abs(sig.gap_bps)
        stop_bps = max(self.cfo.cfg.stop_mult * sig.sigma_res_bps, self.cfo.cfg.min_stop_bps)
        for v in self.variants:
            at = Attempt(self, v, sig, notional, False, S, stop_bps, tp_bps)
            self.active.setdefault(sig.idx, []).append(at)
        if dec is not None and dec.approved and dec.mode == "snipe" and sig.idx not in self.account_open:
            v = Variant("ACCOUNT", "penny" if dec.entry_mode == "penny" else "join", "passive", True, c.account_model)
            at = Attempt(self, v, sig, dec.notional, True, S, dec.stop_bps, dec.tp_bps, entry_mode=dec.entry_mode, pred_net_bps=dec.net_edge_bps)
            self.active.setdefault(sig.idx, []).append(at)
            if at.state != "done":
                self.account_open[sig.idx] = at

    # -------------------------------------------------------------- results
    def _on_result(self, at: Attempt, r: dict) -> None:
        self.results.append(r)
        if len(self.results) > 200_000:
            del self.results[:50_000]
        if at.account:
            self.account_open.pop(at.i, None)
            self.account_results.append(r)
            if r["outcome"] == "filled":
                tr = TradeResult(oid=at.sig.sid, sid=at.sig.sid, market=r["market"], side=at.side, mode="snipe", t_entry=r["fill_t"], t_exit=r["t_end"],
                                 entry_px=r["entry_px"], exit_px=r["exit_px"], qty=r["qty"], notional=r["entry_px"] * r["qty"], gross_bps=r["gross_bps"],
                                 fees_usd=r["fees_usd"], net_pnl_usd=r["net_usd"], net_bps=r["net_bps"],
                                 R=r["net_usd"] / max(r["entry_px"] * r["qty"] * at.stop_bps / BPS, 1e-9), exit_reason=r["exit_reason"], hold_s=r["hold_s"],
                                 entry_slip_bps=0.0, exit_slip_bps=0.0, spread_bps_entry=at.sig.spread_bps, predicted_net_bps=at.pred_net,
                                 gap_bps=at.sig.gap_bps, predicted_slip_bps=0.0)
                self.cfo.on_open(r["market"], at.side, tr.notional, 1.0)
                self.cfo.on_close(r["market"], at.side, tr.notional, 1.0)
                self.cfo.on_trade_closed(tr, r["t_end"])
                self.a.engine.closed.append(tr)
                self.a._write("trades", tr.as_dict())
            self.cfo.on_snipe_result(r)
            self.a._write("snipe_account", r)

    def finalize(self, t: float) -> None:
        """End of run: pull unfilled orders, flatten open positions at the last quote (charged as taker exits)."""
        for i, atts in list(self.active.items()):
            for at in list(atts):
                at.advance(t)
                if at.state == "entry":
                    at._finish(t, "no_fill", "end_of_run")
                elif at.state == "exit":
                    at._send_taker_exit(t, "end_of_run", immediate=True)
            self._sweep(i)

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

    @staticmethod
    def summarize(rows: List[dict]) -> dict:
        n = len(rows)
        if n == 0:
            return {"n": 0}
        f = [r for r in rows if r["outcome"] == "filled"]
        nb = np.array([r["net_bps"] for r in f]) if f else np.zeros(0)
        mk = np.array([r["markout5_bps"] for r in f if np.isfinite(r["markout5_bps"])]) if f else np.zeros(0)
        out = {"n": n, "filled": len(f), "fill_rate": len(f) / n, "shield": sum(1 for r in rows if r["shield_cancel"]),
               "fill_during_cancel": sum(1 for r in rows if r["fill_during_cancel"]),
               "net_bps_per_fill": float(nb.mean()) if nb.size else 0.0, "net_usd": float(sum(r["net_usd"] for r in f)),
               "gross_bps_per_fill": float(np.mean([r["gross_bps"] for r in f])) if f else 0.0,
               "net_bps_per_attempt": float(sum(r["net_bps"] for r in f) / n) if f else 0.0,
               "markout5_per_fill": float(mk.mean()) if mk.size else 0.0,
               "wait_s": float(np.mean([r["wait_s"] for r in f])) if f else 0.0,
               "hit": float((nb > 0).mean()) if nb.size else 0.0,
               "net_cents_per_fill": float(np.mean([r["net_cents"] for r in f])) if f else 0.0,
               "reasons": {}}
        for r in rows:
            if r["outcome"] != "filled":
                out["reasons"][r["reason"] or "?"] = out["reasons"].get(r["reason"] or "?", 0) + 1
        return out


def default_variants(cfg: SnipeConfig) -> List[Variant]:
    out: List[Variant] = []
    for m in cfg.shadow_models:
        out += [Variant(f"taker/taker", "taker", "taker", False, m),
                Variant(f"taker/passive", "taker", "passive", False, m),
                Variant(f"join/passive+shield", "join", "passive", True, m),
                Variant(f"join/passive noshield", "join", "passive", False, m),
                Variant(f"join/taker-exit+shield", "join", "taker", True, m),
                Variant(f"penny/passive+shield", "penny", "passive", True, m)]
    return out
