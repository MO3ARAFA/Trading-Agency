"""Shared resting-order queue model (used by the Phase 6 engines; mirrors the Phase 5 rules, tested separately).

A post-only order is *sent* at t_send, *arrives* at t_arr (order latency) and is judged against the as-of quote at arrival:
rejected if it would cross; joins behind the visible size at the touch; starts at the front inside the spread.
Fills follow the model chosen per run:

  strict     fill only when the opposite touch crosses our price (certain, lower bound)
  depletion  displayed-size depletion at our level counts as trades (optimistic upper bound)
  trades     real trade prints consume the queue ahead of us and sweep through when printed beyond our price

Cancels are *requested* at t_req and take effect at t_req + cancel latency; fills inside that window are real and flagged.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Deque, List, Optional, Tuple

EPS = 1e-12


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


@dataclass
class RestOrder:
    side: int                         # +1 bid / -1 ask
    price: float
    qty: float
    t_send: float
    t_arr: float
    state: str = "inflight"           # inflight | resting | cancel_pending | filled | cancelled | rejected
    ahead: Optional[float] = None
    last_lvl: Optional[float] = None
    filled: float = 0.0
    fill_value: float = 0.0
    cancel_t: Optional[float] = None
    cancel_eff: Optional[float] = None
    cancel_reason: str = ""
    fills: List[Tuple[float, float, float, bool]] = field(default_factory=list)   # (t, px, qty, during_cancel)
    reject: str = ""

    @property
    def remaining(self) -> float:
        return max(self.qty - self.filled, 0.0)

    @property
    def live(self) -> bool:
        return self.state in ("inflight", "resting", "cancel_pending")


def request_cancel(o: RestOrder, t: float, latency: float, reason: str) -> bool:
    if o.state == "inflight":                      # the cancel is sent behind the order: it takes effect cancel-latency after *now*, not before arrival
        if o.cancel_t is not None:
            return False
        o.cancel_t, o.cancel_eff, o.cancel_reason = t, max(t + latency, o.t_arr), reason
        return True
    if o.state != "resting":
        return False
    o.state, o.cancel_t, o.cancel_eff, o.cancel_reason = "cancel_pending", t, t + latency, reason
    return True


def _fill(o: RestOrder, t: float, qty: float, out: list) -> None:
    qty = min(qty, o.remaining)
    if qty <= EPS:
        return
    during = o.cancel_t is not None and t >= o.cancel_t
    o.fills.append((t, o.price, qty, during))
    o.filled += qty
    o.fill_value += o.price * qty
    out.append((t, o.price, qty, during))
    if o.remaining <= EPS:
        o.state = "filled"
        o.cancel_eff = None


def advance(o: RestOrder, t: float, hist: QuoteHist, out: list) -> None:
    """Process time-driven transitions (arrival, cancel taking effect) up to t."""
    if o.state == "inflight" and o.t_arr <= t:
        q = hist.asof(o.t_arr)
        if q is None:
            o.state, o.reject = "rejected", "no_quote"
            return
        _, bid, ask, bq, aq = q
        if (o.side > 0 and o.price >= ask - EPS) or (o.side < 0 and o.price <= bid + EPS):
            o.state, o.reject = "rejected", "post_only_cross"
            return
        if o.side > 0:
            if o.price > bid:
                o.ahead, o.last_lvl = 0.0, None
            elif abs(o.price - bid) < EPS:
                o.ahead, o.last_lvl = bq, bq
            else:
                o.ahead, o.last_lvl = None, None
        else:
            if o.price < ask:
                o.ahead, o.last_lvl = 0.0, None
            elif abs(o.price - ask) < EPS:
                o.ahead, o.last_lvl = aq, aq
            else:
                o.ahead, o.last_lvl = None, None
        o.state = "cancel_pending" if o.cancel_t is not None else "resting"
    if o.state == "cancel_pending" and o.cancel_eff is not None and o.cancel_eff <= t:
        o.state = "cancelled"
        o.cancel_eff = None


def on_quote(o: RestOrder, t: float, q: tuple, model: str, out: list) -> None:
    if o.state not in ("resting", "cancel_pending"):
        return
    _, bid, ask, bq, aq = q
    P = o.price
    if o.side > 0:
        if ask <= P + EPS:                                         # touch crossed our bid: certain fill
            _fill(o, t, o.remaining, out)
            return
        if model == "depletion":
            if abs(bid - P) < EPS:
                if o.ahead is None:
                    o.ahead = bq
                elif o.last_lvl is not None:
                    o.ahead -= max(0.0, o.last_lvl - bq)
                    if o.ahead < 0:
                        _fill(o, t, -o.ahead, out)
                        o.ahead = 0.0
                o.last_lvl = bq
            elif bid < P - EPS and o.ahead is not None:            # our level vanished downwards: consumed
                _fill(o, t, o.remaining, out)
            else:
                o.last_lvl = None
        elif model == "trades" and abs(bid - P) < EPS and o.ahead is None:
            o.ahead = bq
    else:
        if bid >= P - EPS:
            _fill(o, t, o.remaining, out)
            return
        if model == "depletion":
            if abs(ask - P) < EPS:
                if o.ahead is None:
                    o.ahead = aq
                elif o.last_lvl is not None:
                    o.ahead -= max(0.0, o.last_lvl - aq)
                    if o.ahead < 0:
                        _fill(o, t, -o.ahead, out)
                        o.ahead = 0.0
                o.last_lvl = aq
            elif ask > P + EPS and o.ahead is not None:
                _fill(o, t, o.remaining, out)
            else:
                o.last_lvl = None
        elif model == "trades" and abs(ask - P) < EPS and o.ahead is None:
            o.ahead = aq


def on_trade(o: RestOrder, t: float, px: float, sz: float, aggressor: int, model: str, out: list) -> None:
    if model != "trades" or o.state not in ("resting", "cancel_pending"):
        return
    P = o.price
    hit = (o.side > 0 and aggressor < 0) or (o.side < 0 and aggressor > 0)
    if not hit:
        return
    through = (px < P - EPS) if o.side > 0 else (px > P + EPS)
    if through:
        _fill(o, t, o.remaining, out)
    elif abs(px - P) < EPS:
        ahead = o.ahead if o.ahead is not None else 0.0
        if sz <= ahead:
            o.ahead = ahead - sz
        else:
            o.ahead = 0.0
            _fill(o, t, sz - ahead, out)
