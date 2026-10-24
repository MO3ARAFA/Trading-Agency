"""Track 1 (Phase 12): Polymarket slow-horizon event markets - structural dislocations and queue-aware passive quoting.

Phases 5-6 quoted passively on Polymarket's 5 m / 15 m BTC markets and lost to adverse selection: those prices are derivatives of a 1-second Binance
ticker, so a resting order is picked off by whoever sees the ticker first. This module asks the same questions on markets with no such ticker:

1. **Universe.** Active, slow (> 24 h to expiry), non-1-second-ticker event markets with real 24 h volume and a naturally wide spread (3-8 cents).
2. **Structural scan.** Over mutually exclusive (NegRisk) groups and binary pairs: is there a locked margin after fees?
     * *exclusive sell-set*  sum(best bid YES) > 1  ==  buy NO on every leg (the NO ask mirrors the YES bid): at most one leg can win, so payout >= N-1 for a cost of
       N - sum(bid). Valid for any mutually exclusive set, exhaustive or not.
     * *exhaustive buy-set*  sum(best ask YES) < 1: buy YES on every leg; exactly one wins. Only valid when the set is exhaustive (sum of mids ~ 1).
     * *binary complement*   ask(YES) + ask(NO) < 1 or bid(YES) + bid(NO) > 1 (the two books are mirrors, so this is a consistency check).
   Every margin is net of the taker fee schedule, sized by the thinnest leg, and tracked for how long it lasts.
3. **Maker evaluation.** Virtual post-only bids and asks (the real minimum order, 5 shares) through ``queue_model.RestOrder`` under three fill models
   (strict = lower bound, trades = real prints consume the queue, depletion = upper bound), with markouts at +60 s / +300 s against the same quotes placed on
   BTC-ticker control markets in the same session.

Measurement only: nothing here builds or sends an order and no credential is read.
"""
from __future__ import annotations

import asyncio
import gzip
import json
import math
import os
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from .polymarket_watcher import GAMMA, WS_URL, PmBooks, _fee_schedule, handle_clob_message
from .queue_model import QuoteHist, RestOrder, advance, on_quote as q_on_quote, on_trade as q_on_trade, request_cancel

MODELS = ("strict", "trades", "depletion")
POLICIES = ("join", "penny")


@dataclass
class PsConfig:
    # universe
    min_hours: float = 24.0
    v24_min: float = 500.0
    spread_lo: float = 0.03
    spread_hi: float = 0.08
    mid_lo: float = 0.05
    mid_hi: float = 0.95
    n_slow: int = 80
    per_event: int = 3
    n_groups: int = 40
    max_group_legs: int = 20
    max_tokens: int = 640
    n_control: int = 8
    # maker simulation
    qty: float = 5.0                         # shares: the Polymarket minimum order
    order_latency_s: float = 0.4
    cancel_latency_s: float = 0.4
    ttl_s: float = 300.0
    repost_s: float = 15.0
    markout_s: Tuple[float, ...] = (60.0, 300.0)
    hist_len: int = 40000
    # structural scan
    min_set_shares: float = 5.0
    exhaustive_band: float = 0.05
    scan_min_interval_s: float = 0.2
    sample_every_s: float = 10.0
    set_ttl_s: float = 300.0
    set_groups: int = 12
    set_max_legs: int = 6


@dataclass
class PmMarket:
    token: str                               # YES token
    no_token: str
    question: str
    slug: str                                # event slug (group id for NegRisk events)
    neg: bool
    tick: float
    min_size: float
    t_end: float
    v24: float
    liq: float
    fee: Optional[tuple]
    kind: str = "slow"                       # slow | control | leg
    n_legs: int = 1


def fee_per_share(fee: Optional[tuple], p: float) -> float:
    """Taker fee in USD per share at price p (Polymarket: rate * (p(1-p))^exponent); makers pay nothing on taker-only schedules."""
    if not fee:
        return 0.0
    rate, exp, _ = fee
    p = min(max(p, 1e-6), 1.0 - 1e-6)
    return rate * (p * (1.0 - p)) ** exp


# ================================================================================ universe
def _tokens(m: dict) -> Optional[Tuple[str, str]]:
    toks = m.get("clobTokenIds")
    try:
        toks = json.loads(toks) if isinstance(toks, str) else toks
        return str(toks[0]), str(toks[1])
    except Exception:
        return None


def _t_end(x: dict) -> Optional[float]:
    s = x.get("endDate")
    if not s:
        return None
    import datetime as dt
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def _parse_ts(s) -> Optional[float]:
    """Gamma timestamps come as ISO ('...Z') or as '2026-10-20 10:50:00+00'."""
    if not s:
        return None
    import datetime as dt
    try:
        x = str(s).strip().replace("Z", "+00:00").replace(" ", "T", 1)
        if len(x) >= 3 and x[-3] in "+-" and x[-2:].isdigit() and ":" not in x[-5:]:
            x += ":00"
        return dt.datetime.fromisoformat(x).timestamp()
    except Exception:
        return None


def event_time(e: dict, m: dict) -> Optional[float]:
    """When the *event* happens: the game start for sports markets (their ``endDate`` is a generic settlement deadline), else the market end date."""
    gs = _parse_ts(m.get("gameStartTime"))
    return gs if gs is not None else (_t_end(m) or _t_end(e))


def _f(x, d=0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


@dataclass
class PolyUniverse:
    slow: List[PmMarket]
    groups: Dict[str, List[PmMarket]]
    group_info: Dict[str, dict]
    counts: Dict[str, int]

    def tokens(self, cfg: PsConfig, control: Sequence[PmMarket] = ()) -> List[str]:
        """YES tokens to subscribe: quoted markets, control markets, group legs and (for the mirror check) the NO token of the quoted markets."""
        seen: Dict[str, None] = {}
        for m in list(self.slow) + list(control):
            seen.setdefault(m.token)
            seen.setdefault(m.no_token)
        for legs in self.groups.values():
            for m in legs:
                seen.setdefault(m.token)
        return list(seen)[: cfg.max_tokens + 2 * cfg.n_control]


def build_poly_universe(events: Sequence[dict], now: float, cfg: Optional[PsConfig] = None) -> PolyUniverse:
    """Pure builder from Gamma /events payloads. Gamma's bestBid / bestAsk are cached snapshots: they *screen* here, the live CLOB books decide."""
    cfg = cfg or PsConfig()
    slow_c: List[Tuple[float, PmMarket]] = []
    groups: Dict[str, List[PmMarket]] = {}
    info: Dict[str, dict] = {}
    n_mk = n_live = 0
    n_inplay = 0
    for e in events:
        legs: List[PmMarket] = []
        n_total = len(e.get("markets", []))
        if e.get("live") or e.get("ended"):
            n_inplay += n_total
            continue                                          # in play, or finished and awaiting resolution: informed flow, not a slow market
        for m in e.get("markets", []):
            n_mk += 1
            if not (m.get("enableOrderBook") and m.get("acceptingOrders") and not m.get("closed")):
                continue
            tk = _tokens(m)
            te = _t_end(m) or _t_end(e)
            if tk is None or te is None:
                continue
            n_live += 1
            bb, ba = _f(m.get("bestBid")), _f(m.get("bestAsk"))
            pm = PmMarket(token=tk[0], no_token=tk[1], question=m.get("question", "")[:120], slug=e.get("slug", ""), neg=bool(e.get("negRisk")),
                          tick=_f(m.get("orderPriceMinTickSize"), 0.01) or 0.01, min_size=_f(m.get("orderMinSize"), cfg.qty) or cfg.qty, t_end=te,
                          v24=_f(m.get("volume24hr")), liq=_f(m.get("liquidity")), fee=_fee_schedule(m), kind="slow")
            legs.append(pm)
            hrs = ((event_time(e, m) or te) - now) / 3600.0
            if bb > 0 and ba > bb and hrs > cfg.min_hours and pm.v24 >= cfg.v24_min and cfg.spread_lo <= ba - bb <= cfg.spread_hi and cfg.mid_lo < 0.5 * (ba + bb) < cfg.mid_hi:
                slow_c.append((pm.v24, pm))
        if e.get("negRisk") and 3 <= len(legs) <= cfg.max_group_legs:
            sb = sum(_f(m.get("bestBid")) for m in e["markets"] if m.get("acceptingOrders") and not m.get("closed"))
            sa = sum(_f(m.get("bestAsk"), 1.0) for m in e["markets"] if m.get("acceptingOrders") and not m.get("closed"))
            gid = e.get("slug", "")
            for pm in legs:
                pm.kind, pm.n_legs = "leg", len(legs)
            groups[gid] = legs
            info[gid] = {"title": e.get("title", "")[:100], "n_live": len(legs), "n_total": n_total, "gamma_sum_bid": sb, "gamma_sum_ask": sa,
                         "v24": sum(x.v24 for x in legs), "complete": len(legs) == n_total}
    # slow: most active first, at most `per_event` per event
    slow, per = [], defaultdict(int)
    for v, pm in sorted(slow_c, key=lambda x: -x[0]):
        if per[pm.slug] < cfg.per_event and len(slow) < cfg.n_slow:
            slow.append(pm)
            per[pm.slug] += 1
    # groups: the ones whose cached sums are closest to a locked margin, then the busiest
    def score(g):
        i = info[g]
        sell = i["gamma_sum_bid"] - 1.0
        buy = (1.0 - i["gamma_sum_ask"]) if abs(0.5 * (i["gamma_sum_bid"] + i["gamma_sum_ask"]) - 1.0) <= 0.1 else -9.0
        return max(sell, buy)
    ranked = sorted(groups, key=lambda g: (-score(g), -info[g]["v24"]))
    keep = ranked[: cfg.n_groups]
    return PolyUniverse(slow, {g: groups[g] for g in keep}, {g: info[g] for g in keep},
                        {"events": len(events), "markets": n_mk, "live": n_live, "in_play_or_ended_excluded": n_inplay, "slow": len(slow), "slow_candidates": len(slow_c), "groups": len(groups), "groups_kept": len(keep)})


async def fetch_events(session, max_events: int = 2100) -> List[dict]:
    import orjson
    out: List[dict] = []
    for off in range(0, max_events, 100):
        async with session.get(f"{GAMMA}/events", params={"active": "true", "closed": "false", "limit": 100, "offset": off, "order": "volume24hr", "ascending": "false"}) as r:
            if r.status != 200:
                break
            part = orjson.loads(await r.read())
        if not part:
            break
        out += part
    return out


async def discover_control(session, now: float, horizon_s: float, cfg: PsConfig) -> List[PmMarket]:
    """BTC-ticker-driven markets (the Phase 5-6 population), for the side-by-side comparison."""
    from .config import PolyConfig
    from .polymarket_watcher import discover
    metas, specs, tokens = await discover(now, horizon_s, PolyConfig(), session)
    out = []
    for m in metas:
        ex = m.extra
        out.append(PmMarket(token=m.symbol, no_token="", question=ex.get("question", m.id)[:120], slug=ex.get("slug", ""), neg=False, tick=m.tick or 0.01,
                            min_size=ex.get("min_size", cfg.qty), t_end=ex.get("t_end", now + 3600), v24=0.0, liq=0.0, fee=m.fee_schedule, kind="control"))
    return out[: cfg.n_control * 3]


# ================================================================================ structural scanner
@dataclass
class SetOpp:
    gid: str
    kind: str                                # sell_set | buy_set
    t0: float
    t_last: float
    n_legs: int
    max_net: float                           # USD per set, after fees
    max_gross: float
    min_shares: float                        # thinnest leg at the best margin
    exhaustive_like: bool
    open: bool = True
    samples: int = 0
    days_to_end: float = float("nan")      # earliest expiry among the legs: the time the capital is locked

    @property
    def duration(self) -> float:
        return self.t_last - self.t0


class GroupScanner:
    def __init__(self, groups: Dict[str, List[PmMarket]], info: Dict[str, dict], books: PmBooks, cfg: PsConfig):
        self.groups, self.info, self.books, self.cfg = groups, info, books, cfg
        self.of_token: Dict[str, List[str]] = defaultdict(list)
        for g, legs in groups.items():
            for m in legs:
                self.of_token[m.token].append(g)
        self.last_eval: Dict[str, float] = {}
        self.open: Dict[Tuple[str, str], SetOpp] = {}
        self.closed: List[SetOpp] = []
        self.samples: List[dict] = []
        self.next_sample = 0.0
        self.n_eval = self.n_incomplete = 0
        self.worst: Dict[str, dict] = {}
        self.wall_of = None                       # engine clock -> wall clock (set by the runner), so expiry times can be turned into days left

    def _leg(self, tok: str) -> Optional[Tuple[float, float, float, float]]:
        b = self.books
        bb, ba = b.bb.get(tok), b.ba.get(tok)
        if bb is None or ba is None or tok not in b.b and tok not in b.a:
            return None
        bq = b.b.get(tok, {}).get(bb, 0.0) if bb > 0 else 0.0
        aq = b.a.get(tok, {}).get(ba, 0.0) if ba < 1.0 else 0.0
        return bb, ba, bq, aq

    def evaluate(self, g: str, t: float) -> Optional[dict]:
        legs = self.groups[g]
        tops = [self._leg(m.token) for m in legs]
        if any(x is None for x in tops):
            self.n_incomplete += 1
            return None
        self.n_eval += 1
        n = len(legs)
        sum_bid = sum(x[0] for x in tops)
        sum_ask = sum(x[1] for x in tops)
        sum_mid = sum(0.5 * (x[0] + x[1]) for x in tops)
        # sell-set == buy NO on every leg at 1 - bid; payout >= n - 1
        gross_sell = sum_bid - 1.0
        fee_sell = sum(fee_per_share(m.fee, 1.0 - x[0]) for m, x in zip(legs, tops))
        legs_ok_sell = all(x[0] > 0 for x in tops)
        sh_sell = min(x[2] for x in tops)
        # buy-set: buy YES on every leg; needs an exhaustive set
        gross_buy = 1.0 - sum_ask
        fee_buy = sum(fee_per_share(m.fee, x[1]) for m, x in zip(legs, tops))
        legs_ok_buy = all(x[1] < 1.0 for x in tops)
        sh_buy = min(x[3] for x in tops)
        exh = abs(sum_mid - 1.0) <= self.cfg.exhaustive_band and self.info[g].get("complete", False)
        return {"gid": g, "n": n, "sum_bid": sum_bid, "sum_ask": sum_ask, "sum_mid": sum_mid, "exhaustive_like": exh,
                "sell": {"gross": gross_sell, "net": gross_sell - fee_sell, "shares": sh_sell, "ok": legs_ok_sell},
                "buy": {"gross": gross_buy, "net": gross_buy - fee_buy, "shares": sh_buy, "ok": legs_ok_buy and exh}}

    def on_top(self, tok: str, t: float) -> None:
        for g in self.of_token.get(tok, ()):
            if t - self.last_eval.get(g, -1e9) < self.cfg.scan_min_interval_s:
                continue
            r = self.evaluate(g, t)
            if r is None:
                continue                                     # an incomplete group does not start the throttle clock
            self.last_eval[g] = t
            for kind in ("sell", "buy"):
                x = r[kind]
                key = (g, kind)
                hit = x["ok"] and x["net"] > 0 and x["shares"] >= self.cfg.min_set_shares
                o = self.open.get(key)
                if hit:
                    if o is None:
                        o = self.open[key] = SetOpp(g, kind + "_set", t, t, r["n"], x["net"], x["gross"], x["shares"], r["exhaustive_like"],
                                                    days_to_end=(min(m.t_end for m in self.groups[g]) - self.wall_of(t)) / 86400.0 if self.wall_of else float("nan"))
                    o.t_last, o.samples = t, o.samples + 1
                    if x["net"] > o.max_net:
                        o.max_net, o.max_gross, o.min_shares = x["net"], x["gross"], x["shares"]
                elif o is not None:
                    o.open = False
                    self.closed.append(self.open.pop(key))
                w = self.worst.setdefault(f"{g}|{kind}", {"gid": g, "kind": kind, "best_net": -9.0, "best_gross": -9.0, "shares": 0.0, "n": r["n"], "exh": r["exhaustive_like"]})
                if x["ok"] and x["net"] > w["best_net"]:
                    w.update(best_net=x["net"], best_gross=x["gross"], shares=x["shares"])
            if t >= self.next_sample:
                self.samples.append({"t": t, "gid": g, "n": r["n"], "sum_bid": r["sum_bid"], "sum_ask": r["sum_ask"], "sum_mid": r["sum_mid"], "exh": r["exhaustive_like"]})
        if t >= self.next_sample:
            self.next_sample = t + self.cfg.sample_every_s

    def finish(self, t: float) -> List[SetOpp]:
        for k in list(self.open):
            o = self.open.pop(k)
            o.open = False
            self.closed.append(o)
        return self.closed


class MirrorCheck:
    """YES and NO books of one binary market must be mirrors; any ask(YES) + ask(NO) < 1 or bid(YES) + bid(NO) > 1 would be a free lunch."""

    def __init__(self, pairs: Dict[str, str], books: PmBooks):
        self.pairs, self.books = pairs, books
        self.rev = {no: yes for yes, no in pairs.items()}
        self.min_ask_sum = 9.0
        self.max_bid_sum = -9.0
        self.n = 0
        self.n_cross = 0

    def on_top(self, tok: str) -> None:
        yes = tok if tok in self.pairs else self.rev.get(tok)
        if yes is None:
            return
        no = self.pairs[yes]
        b = self.books
        by, ay, bn, an = b.bb.get(yes), b.ba.get(yes), b.bb.get(no), b.ba.get(no)
        if None in (by, ay, bn, an) or by <= 0 or bn <= 0 or ay >= 1.0 or an >= 1.0:
            return
        self.n += 1
        self.min_ask_sum = min(self.min_ask_sum, ay + an)
        self.max_bid_sum = max(self.max_bid_sum, by + bn)
        if ay + an < 1.0 - 1e-9 or by + bn > 1.0 + 1e-9:
            self.n_cross += 1


# ================================================================================ maker simulator
@dataclass
class Attempt:
    aid: int
    token: str
    kind: str                                # slow | control
    policy: str
    model: str
    side: int
    price: float
    qty: float
    t_send: float
    spread0: float
    mid0: float
    tick: float
    order: RestOrder
    t_end: float
    fill_t: Optional[float] = None
    fill_px: float = 0.0
    fill_qty: float = 0.0
    cancel_req: bool = False
    marks: Dict[float, float] = field(default_factory=dict)
    done: bool = False

    def row(self) -> dict:
        o = self.order
        return {"aid": self.aid, "token": self.token[-8:], "kind": self.kind, "policy": self.policy, "model": self.model, "side": self.side, "price": self.price, "qty": self.qty,
                "t_send": self.t_send, "spread0": self.spread0, "mid0": self.mid0, "tick": self.tick, "state": o.state, "reject": o.reject, "ahead": o.ahead,
                "fill_t": self.fill_t, "fill_px": self.fill_px, "fill_qty": self.fill_qty, "marks": {str(k): v for k, v in self.marks.items()}}


class MakerSim:
    def __init__(self, markets: Sequence[PmMarket], cfg: PsConfig):
        self.cfg = cfg
        self.meta: Dict[str, PmMarket] = {m.token: m for m in markets}
        self.hist: Dict[str, QuoteHist] = {m.token: QuoteHist(cfg.hist_len) for m in markets}
        self.live: Dict[Tuple[str, str, str, int], Attempt] = {}
        self.next_ok: Dict[Tuple[str, str, str, int], float] = {}
        self.finished: List[Attempt] = []
        self.pending_marks: List[Attempt] = []
        self._aid = 0
        self.trade_ts: Dict[str, List[float]] = defaultdict(list)
        self.trade_sz: Dict[str, float] = defaultdict(float)
        self.t_first: Dict[str, float] = {}
        self.t_last: float = 0.0
        self.feed_t: float = 0.0                 # last message of any kind: the feed is event-driven, so a book that has not changed for minutes is still valid

    # ---- feed
    def on_top(self, t: float, tok: str, bid: float, ask: float, bq: float, aq: float) -> None:
        h = self.hist.get(tok)
        if h is None:
            return
        self.t_first.setdefault(tok, t)
        h.add(t, bid, ask, bq, aq)
        self.t_last = t
        q = (t, bid, ask, bq, aq)
        for key, a in list(self.live.items()):
            if key[0] != tok:
                continue
            out: list = []
            advance(a.order, t, h, out)
            q_on_quote(a.order, t, q, a.model, out)
            self._collect(a, out)

    def on_trade(self, t: float, tok: str, px: float, sz: float, aggressor: int) -> None:
        if tok not in self.hist:
            return
        self.trade_ts[tok].append(t)
        self.trade_sz[tok] += sz
        h = self.hist[tok]
        for key, a in list(self.live.items()):
            if key[0] != tok:
                continue
            out: list = []
            advance(a.order, t, h, out)
            q_on_trade(a.order, t, px, sz, aggressor, a.model, out)
            self._collect(a, out)

    def _collect(self, a: Attempt, out: list) -> None:
        for (t, px, qty, _) in out:
            if a.fill_t is None:
                a.fill_t = t
            a.fill_px = (a.fill_px * a.fill_qty + px * qty) / (a.fill_qty + qty)
            a.fill_qty += qty

    # ---- clock
    def poll(self, t: float) -> None:
        c = self.cfg
        for key, a in list(self.live.items()):
            h = self.hist[key[0]]
            out: list = []
            advance(a.order, t, h, out)
            self._collect(a, out)
            if a.order.state in ("resting", "inflight") and not a.cancel_req and t >= a.t_send + c.ttl_s:
                a.cancel_req = request_cancel(a.order, t, c.cancel_latency_s, "ttl")
            if a.order.state in ("filled", "cancelled", "rejected"):
                self._finish(key, a, t)
        for tok, h in self.hist.items():
            last = h.last()
            if last is None or t - self.feed_t > 30.0:
                continue
            m = self.meta[tok]
            if (m.t_end - t) < 120.0:
                continue
            _, bid, ask, bq, aq = last
            if not (0.0 < bid < ask < 1.0):
                continue
            for pol in POLICIES:
                for side in (+1, -1):
                    if pol == "penny" and ask - bid < 3 * m.tick - 1e-9:
                        continue
                    price = (bid if side > 0 else ask) if pol == "join" else ((bid + m.tick) if side > 0 else (ask - m.tick))
                    price = round(price / m.tick) * m.tick
                    for model in MODELS:
                        key = (tok, pol, model, side)
                        if key in self.live or t < self.next_ok.get(key, 0.0):
                            continue
                        self._aid += 1
                        o = RestOrder(side, price, c.qty, t, t + c.order_latency_s)
                        self.live[key] = Attempt(self._aid, tok, m.kind, pol, model, side, price, c.qty, t, ask - bid, 0.5 * (ask + bid), m.tick, o, m.t_end)
        self._resolve_marks(t)

    def _finish(self, key, a: Attempt, t: float) -> None:
        a.done = True
        del self.live[key]
        self.next_ok[key] = t + self.cfg.repost_s
        if a.fill_qty > 0:
            self.pending_marks.append(a)
        else:
            self.finished.append(a)

    def _resolve_marks(self, t: float) -> None:
        keep = []
        for a in self.pending_marks:
            h = self.hist[a.token]
            ready = True
            for hz in self.cfg.markout_s:
                if hz in a.marks:
                    continue
                if t >= a.fill_t + hz:
                    q = h.asof(a.fill_t + hz)
                    if q is not None:
                        a.marks[hz] = 0.5 * (q[1] + q[2])
                else:
                    ready = False
            if ready and len(a.marks) == len(self.cfg.markout_s):
                self.finished.append(a)
            else:
                keep.append(a)
        self.pending_marks = keep

    def finalize(self, t: float) -> None:
        for key, a in list(self.live.items()):
            if a.fill_qty > 0:
                a.done = True
                self.pending_marks.append(a)
            else:
                a.done = True
                self.finished.append(a)
        self.live.clear()
        self._resolve_marks(t + max(self.cfg.markout_s) + 1.0)
        for a in self.pending_marks:                    # fills too recent to have a full markout: kept with whatever marks exist
            self.finished.append(a)
        self.pending_marks = []


def maker_stats(attempts: Sequence[Attempt], hours: float, n_markets: int, qty: float) -> dict:
    """Per (kind, policy, model): fill rate, fills per market-hour, spread capture, markouts and dollars (5 shares)."""
    out = {}
    groups = defaultdict(list)
    for a in attempts:
        if a.order.state == "rejected":
            continue
        groups[(a.kind, a.policy, a.model)].append(a)
    for key, rs in groups.items():
        fills = [a for a in rs if a.fill_qty > 0]
        d = {"attempts": len(rs), "fills": len(fills), "fill_rate": len(fills) / len(rs) if rs else float("nan"),
             "fills_per_market_hour": len(fills) / hours / max(n_markets, 1) if hours else float("nan")}
        if fills:
            sgn = np.array([a.side for a in fills])
            px = np.array([a.fill_px for a in fills])
            mid0 = np.array([a.mid0 for a in fills])
            half = np.array([0.5 * a.spread0 for a in fills])
            d["spread_capture_c"] = float(np.mean(sgn * (mid0 - px) * 100.0))               # vs the mid when the order was placed: >0 = bought below / sold above the mid
            d["mean_price"] = float(px.mean())
            for hz in (60.0, 300.0):
                v = [a.side * (a.marks[hz] - a.fill_px) * 100.0 for a in fills if hz in a.marks]
                if v:
                    d[f"markout_{int(hz)}s_c"] = float(np.mean(v))
                    d[f"markout_{int(hz)}s_se"] = float(np.std(v, ddof=1) / math.sqrt(len(v))) if len(v) > 1 else float("nan")
                    d[f"markout_{int(hz)}s_n"] = len(v)
                    d[f"usd_per_fill_{int(hz)}s"] = float(np.mean(v)) / 100.0 * qty
            d["median_half_spread_c"] = float(np.median(half) * 100.0)
            # attempts in one market are not independent (one print can fill several, and a market that is moving fills them all): the market is the unit
            per: Dict[str, List[float]] = defaultdict(list)
            for a in fills:
                if 300.0 in a.marks:
                    per[a.token].append(a.side * (a.marks[300.0] - a.fill_px) * 100.0)
            mm = [float(np.mean(v)) for v in per.values()]
            d["markets_with_fills"] = len({a.token for a in fills})
            d["top_market_fill_share"] = max((sum(1 for a in fills if a.token == t) for t in {a.token for a in fills}), default=0) / len(fills)
            if mm:
                d["markout_300s_market_mean_c"] = float(np.mean(mm))
                d["markout_300s_market_se_c"] = float(np.std(mm, ddof=1) / math.sqrt(len(mm))) if len(mm) > 1 else float("nan")
                d["markout_300s_markets"] = len(mm)
        out["|".join(key)] = d
    return out


def trade_burstiness(ts: Dict[str, List[float]], t0: float, t1: float, bin_s: float = 60.0) -> dict:
    """Trades per market-minute and the Fano factor (variance / mean of per-minute counts; 1 = Poisson, >> 1 = bursty / informed sweeps)."""
    nb = max(int((t1 - t0) / bin_s), 1)
    rates, fanos = [], []
    for tok, v in ts.items():
        if len(v) < 5:
            continue
        c, _ = np.histogram(np.asarray(v) - t0, bins=nb, range=(0, nb * bin_s))
        m = c.mean()
        rates.append(m)
        if m > 0:
            fanos.append(c.var() / m)
    return {"markets_with_trades": len(rates), "trades_per_min_median": float(np.median(rates)) if rates else 0.0, "fano_median": float(np.median(fanos)) if fanos else float("nan"),
            "fano_p90": float(np.percentile(fanos, 90)) if fanos else float("nan")}


# ================================================================================ maker-lock simulation over exhaustive groups
class SetMakerSim:
    """Post a join-bid on every YES leg of a small exhaustive group; a *complete set* locks 1 - sum(fill prices) with zero fees. Legging risk is the point: partial sets are marked at mid after the TTL."""

    def __init__(self, groups: Dict[str, List[PmMarket]], info: Dict[str, dict], books: PmBooks, cfg: PsConfig):
        self.cfg, self.books = cfg, books
        self.groups = {g: legs for g, legs in groups.items() if len(legs) <= cfg.set_max_legs and info[g].get("complete")}
        self.hist: Dict[str, QuoteHist] = {m.token: QuoteHist(cfg.hist_len) for legs in self.groups.values() for m in legs}
        self.live: Dict[str, dict] = {}
        self.done: List[dict] = []
        self.next_ok: Dict[str, float] = {}
        self.feed_t: float = 0.0

    def on_top(self, t: float, tok: str, bid: float, ask: float, bq: float, aq: float) -> None:
        h = self.hist.get(tok)
        if h is None:
            return
        h.add(t, bid, ask, bq, aq)
        for g, s in self.live.items():
            o = s["orders"].get(tok)
            if o is not None:
                out: list = []
                advance(o, t, h, out)
                q_on_quote(o, t, (t, bid, ask, bq, aq), "trades", out)

    def on_trade(self, t: float, tok: str, px: float, sz: float, agg: int) -> None:
        h = self.hist.get(tok)
        if h is None:
            return
        for g, s in self.live.items():
            o = s["orders"].get(tok)
            if o is not None:
                out: list = []
                advance(o, t, h, out)
                q_on_trade(o, t, px, sz, agg, "trades", out)

    def poll(self, t: float) -> None:
        c = self.cfg
        for g, s in list(self.live.items()):
            for tok, o in s["orders"].items():
                out: list = []
                advance(o, t, self.hist[tok], out)
            if all(o.state == "filled" for o in s["orders"].values()) or t >= s["t0"] + c.set_ttl_s:
                self._close(g, s, t)
        if len(self.live) >= c.set_groups:
            return
        for g, legs in self.groups.items():
            if g in self.live or t < self.next_ok.get(g, 0.0):
                continue
            tops = [self.hist[m.token].last() for m in legs]
            if any(x is None or not (0 < x[1] < x[2] < 1) for x in tops) or t - self.feed_t > 30.0:
                continue
            sum_bid = sum(x[1] for x in tops)
            sum_mid = sum(0.5 * (x[1] + x[2]) for x in tops)
            if abs(sum_mid - 1.0) > c.exhaustive_band or sum_bid >= 1.0 - 1e-9:
                continue
            orders = {m.token: RestOrder(+1, x[1], c.qty, t, t + c.order_latency_s) for m, x in zip(legs, tops)}
            self.live[g] = {"t0": t, "orders": orders, "sum_bid": sum_bid, "mid0": {m.token: 0.5 * (x[1] + x[2]) for m, x in zip(legs, tops)}, "n": len(legs)}

    def _close(self, g: str, s: dict, t: float) -> None:
        orders = s["orders"]
        for tok, o in orders.items():
            if o.state in ("resting", "inflight"):
                request_cancel(o, t, 0.0, "ttl")
                advance(o, t + 1.0, self.hist[tok], [])
        filled = {tok: o for tok, o in orders.items() if o.filled > 0}
        complete = len(filled) == len(orders) and all(o.remaining <= 1e-9 for o in orders.values())
        cost = sum(o.price * o.filled for o in filled.values())
        # inventory not matched by a full set is marked at the last mid (what it would sell for, no spread, no resolution)
        mark = 0.0
        for tok, o in filled.items():
            q = self.hist[tok].last()
            mark += (0.5 * (q[1] + q[2]) if q else o.price) * o.filled
        full_sets = min((o.filled for o in orders.values()), default=0.0)
        self.done.append({"gid": g, "t0": s["t0"], "n": s["n"], "sum_bid_at_post": s["sum_bid"], "legs_filled": len(filled), "complete": complete, "cost_usd": cost, "mark_usd": mark,
                          "locked_usd": full_sets * 1.0 - sum(o.price * full_sets for o in orders.values()) if complete else 0.0, "pnl_mark_usd": mark - cost + 0.0, "dur": t - s["t0"]})
        del self.live[g]
        self.next_ok[g] = t + self.cfg.repost_s * 4


# ================================================================================ engine
class PolyStructural:
    """Clock-injected: feed raw CLOB messages with ``on_message(t, msg)`` and call ``poll(t)`` ~ once a second (live or replayed)."""

    def __init__(self, uni: PolyUniverse, control: Sequence[PmMarket], cfg: Optional[PsConfig] = None):
        self.cfg = cfg or PsConfig()
        self.uni, self.control = uni, list(control)
        self.books = PmBooks()
        quoted = list(uni.slow) + self.control
        self.sim = MakerSim(quoted, self.cfg)
        self.scan = GroupScanner(uni.groups, uni.group_info, self.books, self.cfg)
        self.setsim = SetMakerSim(uni.groups, uni.group_info, self.books, self.cfg)
        self.mirror = MirrorCheck({m.token: m.no_token for m in quoted if m.no_token}, self.books)
        self.t_start: Optional[float] = None
        self.t_now = 0.0
        self.n_msgs = 0
        self._last_top: Dict[str, tuple] = {}
        self._t = 0.0

    def on_message(self, t: float, m) -> None:
        self.n_msgs += 1
        self.t_now = self._t = t
        self.sim.feed_t = self.setsim.feed_t = t
        if self.t_start is None:
            self.t_start = t
        handle_clob_message(m, self.books, self._on_top, self._on_trade)

    def _on_top(self, aid: str) -> None:
        t = self._t
        tp = self.books.top(aid)
        self.scan.on_top(aid, t)
        self.mirror.on_top(aid)
        if tp is not None and self._last_top.get(aid) != tp:
            self._last_top[aid] = tp
            self.sim.on_top(t, aid, tp[0], tp[1], tp[2], tp[3])
            self.setsim.on_top(t, aid, tp[0], tp[1], tp[2], tp[3])

    def _on_trade(self, aid: str, px: float, sz: float, side: str) -> None:
        tp = self.books.top(aid)
        mid = 0.5 * (tp[0] + tp[1]) if tp else None
        agg = (1 if px >= mid else -1) if mid is not None else (1 if side.upper() == "BUY" else -1)     # aggressor inferred from price vs mid, as in Phase 5-6
        self.sim.on_trade(self._t, aid, px, sz, agg)
        self.setsim.on_trade(self._t, aid, px, sz, agg)

    def poll(self, t: float) -> None:
        self.t_now = t
        self.sim.poll(t)
        self.setsim.poll(t)

    def finish(self, t: float) -> dict:
        self.sim.finalize(t)
        for g, s in list(self.setsim.live.items()):
            self.setsim._close(g, s, t)
        opps = self.scan.finish(t)
        hours = max((t - (self.t_start or t)) / 3600.0, 1e-9)
        n_slow = len(self.uni.slow)
        stats = {}
        for kind, n in (("slow", n_slow), ("control", len(self.control))):
            sub = [a for a in self.sim.finished if a.kind == kind]
            stats.update({k: v for k, v in maker_stats(sub, hours, n, self.cfg.qty).items()})
        res = {"hours": hours, "msgs": self.n_msgs, "maker": stats,
               "burst": {kind: trade_burstiness({tok: v for tok, v in self.sim.trade_ts.items() if self.sim.meta[tok].kind == kind}, self.t_start or 0.0, t) for kind in ("slow", "control")},
               "opps": [asdict(o) | {"duration": o.duration} for o in opps], "worst": self.scan.worst, "scan": {"evals": self.scan.n_eval, "incomplete": self.scan.n_incomplete, "groups": len(self.uni.groups)},
               "mirror": {"checks": self.mirror.n, "min_ask_sum": self.mirror.min_ask_sum, "max_bid_sum": self.mirror.max_bid_sum, "crossed": self.mirror.n_cross},
               "sets": self.setsim.done, "n_slow": n_slow, "n_control": len(self.control)}
        return res


# ================================================================================ live runner
async def run_live(duration_s: float, out_dir: str, cfg: Optional[PsConfig] = None, record: bool = True) -> dict:
    import aiohttp
    import orjson
    from websockets.asyncio.client import connect

    cfg = cfg or PsConfig()
    os.makedirs(out_dir, exist_ok=True)
    sess = aiohttp.ClientSession(trust_env=True, timeout=aiohttp.ClientTimeout(total=40), headers={"User-Agent": "Mozilla/5.0"})
    try:
        now = time.time()
        events = await fetch_events(sess)
        uni = build_poly_universe(events, now, cfg)
        control = await discover_control(sess, now, duration_s + 600.0, cfg)
    finally:
        await sess.close()
    # the control markets that are actually mid-priced (1-sided books carry no information)
    control = control[: cfg.n_control]
    eng = PolyStructural(uni, control, cfg)
    wall_anchor, perf_anchor = time.time(), time.perf_counter()
    eng.scan.wall_of = lambda t: wall_anchor + (t - perf_anchor)
    toks = uni.tokens(cfg, control)
    with open(os.path.join(out_dir, "pm_universe.json"), "w") as f:
        json.dump({"counts": uni.counts, "slow": [asdict(m) for m in uni.slow], "control": [asdict(m) for m in control], "groups": {g: [m.question for m in legs] for g, legs in uni.groups.items()},
                   "group_info": uni.group_info, "tokens": len(toks)}, f, indent=1, default=float)
    print(f"slow markets {len(uni.slow)} (of {uni.counts['slow_candidates']} candidates) | control {len(control)} | groups {len(uni.groups)} | subscribing {len(toks)} tokens", flush=True)
    rec = gzip.open(os.path.join(out_dir, "pm_events.jsonl.gz"), "wt", compresslevel=1) if record else None
    t0 = time.perf_counter()
    stop = asyncio.Event()
    stats = {"reconnects": 0, "errors": 0}

    async def feed():
        backoff = 0.5
        while not stop.is_set():
            try:
                async with connect(WS_URL, open_timeout=15, max_size=2 ** 25, compression=None, ping_interval=None) as ws:
                    eng.books.__init__()
                    eng._last_top.clear()
                    await ws.send(orjson.dumps({"assets_ids": toks, "type": "market"}).decode())

                    async def pinger():
                        while True:
                            await asyncio.sleep(9)
                            await ws.send("PING")

                    pt = asyncio.create_task(pinger())
                    try:
                        async for raw in ws:
                            if raw in ("PONG", b"PONG"):
                                continue
                            t = time.perf_counter()
                            try:
                                m = orjson.loads(raw)
                            except Exception:
                                continue
                            if rec is not None:
                                rec.write(f"{t:.4f}\t{raw if isinstance(raw, str) else raw.decode()}\n")
                            eng.on_message(t, m)
                            backoff = 0.5
                    finally:
                        pt.cancel()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                stats["errors"] += 1
                stats["last_error"] = f"{type(e).__name__}: {str(e)[:100]}"
            if stop.is_set():
                break
            stats["reconnects"] += 1
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 10.0)

    task = asyncio.create_task(feed())
    try:
        nxt = t0 + 60.0
        while time.perf_counter() - t0 < duration_s:
            await asyncio.sleep(0.5)
            t = time.perf_counter()
            eng.poll(t)
            if t >= nxt:
                nxt += 60.0
                print(f"[{t - t0:5.0f}s] msgs={eng.n_msgs} attempts={len(eng.sim.finished) + len(eng.sim.live)} fills={sum(1 for a in eng.sim.finished if a.fill_qty > 0)} "
                      f"opps_open={len(eng.scan.open)} closed={len(eng.scan.closed)} sets={len(eng.setsim.done)} reconnects={stats['reconnects']}", flush=True)
    finally:
        stop.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        if rec is not None:
            rec.close()
    res = eng.finish(time.perf_counter())
    res["feed"] = stats
    res["universe_counts"] = uni.counts
    with open(os.path.join(out_dir, "pm_result.json"), "w") as f:
        json.dump(res, f, indent=1, default=float)
    with open(os.path.join(out_dir, "pm_attempts.jsonl"), "w") as f:
        for a in eng.sim.finished:
            f.write(json.dumps(a.row(), default=float) + "\n")
    with open(os.path.join(out_dir, "pm_group_samples.jsonl"), "w") as f:
        for s in eng.scan.samples:
            f.write(json.dumps(s, default=float) + "\n")
    return res


def replay(path: str, uni: PolyUniverse, control: Sequence[PmMarket], cfg: Optional[PsConfig] = None, poll_every: float = 1.0) -> dict:
    """Re-run a recorded session (``pm_events.jsonl.gz``) through the same engine."""
    eng = PolyStructural(uni, control, cfg)
    last = None
    t = 0.0
    with gzip.open(path, "rt") as f:
        try:
            for line in f:
                try:                                   # a session killed mid-write leaves a truncated last line
                    ts, raw = line.split("\t", 1)
                    msg = json.loads(raw)
                except ValueError:
                    continue
                t = float(ts)
                eng.on_message(t, msg)
                if last is None or t - last >= poll_every:
                    eng.poll(t)
                    last = t
        except EOFError:                               # ... and an unterminated gzip stream
            pass
    return eng.finish(t)


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--duration", type=float, default=2700.0)
    p.add_argument("--out", default="runs/pm_structural")
    p.add_argument("--no-record", action="store_true")
    a = p.parse_args(argv)
    out = os.path.join(a.out, time.strftime("%Y%m%d_%H%M%S"))
    res = asyncio.run(run_live(a.duration, out, record=not a.no_record))
    print(json.dumps({k: res[k] for k in ("hours", "msgs", "scan", "mirror")}, default=float))
    print("artifacts:", out)


if __name__ == "__main__":
    main()
