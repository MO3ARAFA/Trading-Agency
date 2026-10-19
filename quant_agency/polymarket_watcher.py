"""Battleground 2 — slow-reaction prediction markets (Polymarket CLOB) driven by the Binance BTC oracle.

Markets watched (all resolve on BTC price): daily "Bitcoin above $K on <date>" thresholds, daily price brackets,
hourly "Up or Down" (resolves on the Binance BTC/USDT 1H candle open->close = our oracle's own venue), and 5m / 15m / 4h
"Up or Down" (Chainlink BTC/USD 60 s TWAP vs the price at window start).

Each market has an analytic fair probability P(S, tau) under a driftless lognormal with the oracle's realised vol. Following the
same lead-lag definition as the Hunter, a signal compares the *change* in fair probability caused by the BTC impulse over horizon h
with the *change* the CLOB mid actually made over that horizon:

    Gap_p = [P(S_now, tau) - P(S_{t-h}, tau + h)]  -  [mid_now - mid_{t-h}]            (probability points)

so a persistent implied-vol mismatch cannot masquerade as a gap. Signals feed the unchanged CFO -> execution -> CEO path; the CFO
prices Polymarket's *price-dependent taker fee*  fee/share = rate * p * (1-p)  (e.g. 7 % * 0.25 = 1.75 c at p = 0.5, ~350 bps of
notional) while makers pay nothing — which is exactly the CEO's taker->maker-only lever.
"""
from __future__ import annotations

import asyncio
import json
import math
import re
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import numpy as np
import orjson

from .btc_oracle import BtcOracle, OracleState
from .config import PolyConfig
from .inefficiency_hunter import Signal
from .market_watchers import ASK, AQ, BID, BQ, LAST_T, MID, NTICK, MarketBook, MarketMeta

BPS = 1e4
GAMMA = "https://gamma-api.polymarket.com"
WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
SQRT2 = math.sqrt(2.0)
SEC_PER_YEAR = 365.0 * 86400.0


def ncdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / SQRT2))


# --------------------------------------------------------------------------------- fair-probability models
@dataclass
class PmSpec:
    kind: str                       # above | below | range | updown_terminal | updown_twap
    t_end: float                    # wall epoch seconds
    K: float = 0.0                  # strike (above/below) or lower bound (range)
    B: float = 0.0                  # upper bound (range)
    t_start: float = 0.0            # updown window start
    S0: float = 0.0                 # reference price at window start (0 until known)
    acc_sum: float = 0.0            # integral of S dt since t_start (TWAP types)
    acc_t: float = 0.0              # seconds accumulated
    last_wall: float = 0.0


def _up_prob_terminal(S: float, ref: float, s: float) -> float:
    """P(S_T >= ref) with ln-sd s."""
    if s <= 1e-12:
        return 1.0 if S >= ref else 0.0
    return ncdf(math.log(S / ref) / s)


def fair_prob(spec: PmSpec, S: float, now: float, sigma_s: float, horizon_back: float = 0.0, A_bar: Optional[float] = None) -> Optional[float]:
    """Fair probability of the YES/Up token at wall time ``now`` with spot ``S``.

    ``horizon_back`` > 0 evaluates the model as it stood ``horizon_back`` seconds earlier (tau larger by that much).
    Returns None when the market is not in a state the model covers (window not started / too close to expiry).
    """
    tau = spec.t_end - now + horizon_back
    if tau <= 0.0:
        return None
    s = sigma_s * math.sqrt(tau)
    k = spec.kind
    if k == "above":
        return _up_prob_terminal(S, spec.K, s)
    if k == "below":
        return 1.0 - _up_prob_terminal(S, spec.K, s)
    if k == "range":
        return _up_prob_terminal(S, spec.K, s) - _up_prob_terminal(S, spec.B, s)
    if k == "updown_terminal":
        if spec.S0 <= 0.0:
            return None
        return _up_prob_terminal(S, spec.S0, s)
    if k == "updown_twap":
        if spec.S0 <= 0.0 or A_bar is None:
            return None
        T = spec.t_end - spec.t_start
        e = T - tau
        if e < -1e-9:
            return None
        e = max(e, 0.0)
        Kp = (T * spec.S0 - e * A_bar) / max(tau, 1e-9)        # future-average must reach this level
        if Kp <= 0.0:
            return 1.0
        return _up_prob_terminal(S, Kp, sigma_s * math.sqrt(tau / 3.0))
    return None


# --------------------------------------------------------------------------------- discovery
def _http_json(session_get):
    return session_get


async def _gamma_event(session, slug: str):
    import aiohttp
    try:
        async with session.get(f"{GAMMA}/events", params={"slug": slug}) as r:
            if r.status != 200:
                return None
            d = orjson.loads(await r.read())
            return d[0] if d else None
    except Exception:
        return None


def _month(dt) -> str:
    return dt.strftime("%B").lower()


def candidate_slugs(now_wall: float, horizon_s: float, cfg: PolyConfig) -> List[Tuple[str, str]]:
    """(slug, family) for every event that overlaps [now, now + horizon]."""
    ET = ZoneInfo("America/New_York")
    out: List[Tuple[str, str]] = []
    t_hi = now_wall + horizon_s
    for per, lab in ((300, "5m"), (900, "15m"), (14400, "4h")):
        ts = int(now_wall // per) * per
        while ts <= t_hi + per:
            out.append((f"btc-updown-{lab}-{ts}", f"updown_{lab}"))
            ts += per
    import datetime as dt
    h0 = int(now_wall // 3600) * 3600
    h = h0
    while h <= t_hi + 3600:
        d = dt.datetime.fromtimestamp(h, ET)
        hh = d.hour % 12 or 12
        ap = "am" if d.hour < 12 else "pm"
        out.append((f"bitcoin-up-or-down-{_month(d)}-{d.day}-{d.year}-{hh}{ap}-et", "updown_1h"))
        h += 3600
    for k in range(0, 4):
        d = dt.datetime.fromtimestamp(now_wall + k * 86400, ET)
        tail = f"{_month(d)}-{d.day}-{d.year}"
        out.append((f"bitcoin-above-on-{tail}", "above"))
        out.append((f"bitcoin-price-on-{tail}", "bracket"))
    return out


_NUM = r"\$([\d,]+(?:\.\d+)?)"


def _num(x: str) -> float:
    return float(x.replace(",", ""))


def parse_threshold(question: str) -> Optional[Tuple[str, float, float]]:
    q = question.lower()
    m = re.search(r"between " + _NUM + r" and " + _NUM, q)
    if m:
        return "range", _num(m.group(1)), _num(m.group(2))
    m = re.search(r"(?:less than|below|under) " + _NUM, q)
    if m:
        return "below", _num(m.group(1)), 0.0
    m = re.search(r"(?:above|greater than|over|more than) " + _NUM, q)
    if m:
        return "above", _num(m.group(1)), 0.0
    return None


def _fee_schedule(m: dict) -> Optional[tuple]:
    fs = m.get("feeSchedule")
    if m.get("feesEnabled") and isinstance(fs, dict) and fs.get("rate"):
        return (float(fs["rate"]), float(fs.get("exponent", 1)), bool(fs.get("takerOnly", True)))
    return None


async def discover(now_wall: float, horizon_s: float, cfg: PolyConfig, session) -> Tuple[List[MarketMeta], Dict[str, PmSpec], Dict[str, str]]:
    """Returns (metas, specs by market id, yes-token by market id)."""
    slugs = candidate_slugs(now_wall, horizon_s, cfg)
    events = await asyncio.gather(*[_gamma_event(session, s) for s, _ in slugs])
    metas: List[MarketMeta] = []
    specs: Dict[str, PmSpec] = {}
    tokens: Dict[str, str] = {}
    for (slug, fam), ev in zip(slugs, events):
        if not ev or ev.get("closed"):
            continue
        for m in ev.get("markets", []):
            if m.get("closed") or not m.get("acceptingOrders") or not m.get("clobTokenIds"):
                continue
            toks = json.loads(m["clobTokenIds"]) if isinstance(m["clobTokenIds"], str) else m["clobTokenIds"]
            end = m.get("endDate") or ev.get("endDate")
            if not end:
                continue
            import datetime as dt
            t_end = dt.datetime.fromisoformat(end.replace("Z", "+00:00")).timestamp()
            if t_end < now_wall + 30:
                continue
            if fam in ("above", "bracket"):
                p = parse_threshold(m.get("question", ""))
                if p is None:
                    continue
                kind, K, B = p
                spec = PmSpec(kind=kind, t_end=t_end, K=K, B=B)
                label = f"{kind}-{K:g}" + (f"-{B:g}" if kind == "range" else "")
            else:
                per = {"updown_5m": 300, "updown_15m": 900, "updown_4h": 14400, "updown_1h": 3600}[fam]
                t_start = t_end - per
                kind = "updown_terminal" if fam == "updown_1h" else "updown_twap"
                spec = PmSpec(kind=kind, t_end=t_end, t_start=t_start)
                label = fam
            mid = f"pm:{slug}:{label}"
            tick = float(m.get("orderPriceMinTickSize") or 0.01)
            metas.append(MarketMeta(id=mid, venue="polymarket", symbol=toks[0], base="BTC", tick=tick, step=0.01,
                                    min_notional=1.0, asset="BTC-PM", kind="prediction", quote="USD",
                                    fee_schedule=_fee_schedule(m), spread_gate_bps=5000.0, hunt=False, tradable=True,
                                    extra={"slug": slug, "family": fam, "t_end": t_end, "question": m.get("question", ""),
                                           "min_size": float(m.get("orderMinSize") or 5)}))
            specs[mid] = spec
            tokens[mid] = toks[0]
    # prefer the soonest-expiring markets if over budget
    order = sorted(range(len(metas)), key=lambda i: specs[metas[i].id].t_end)
    metas = [metas[i] for i in order][: cfg.max_markets]
    keep = {m.id for m in metas}
    return metas, {k: v for k, v in specs.items() if k in keep}, {k: v for k, v in tokens.items() if k in keep}


async def binance_ref_prices(session, specs: Dict[str, PmSpec], now_wall: float,
                             rest: str = "https://data-api.binance.vision") -> None:
    """Fill S0 (and TWAP running average) for windows already in progress, from Binance klines."""
    for spec in specs.values():
        if spec.kind not in ("updown_terminal", "updown_twap") or spec.t_start > now_wall or spec.S0 > 0.0:
            continue
        try:
            if spec.kind == "updown_terminal":                               # exact resolution source: 1H candle open
                async with session.get(f"{rest}/api/v3/klines", params={"symbol": "BTCUSDT", "interval": "1h",
                                                                        "startTime": int(spec.t_start * 1000), "limit": 1}) as r:
                    k = orjson.loads(await r.read())
                if k:
                    spec.S0 = float(k[0][1])
                continue
            async with session.get(f"{rest}/api/v3/klines", params={"symbol": "BTCUSDT", "interval": "1s",
                                                                    "startTime": int(spec.t_start * 1000), "limit": 1}) as r:
                k = orjson.loads(await r.read())
            if k:
                spec.S0 = float(k[0][1])
            n_min = int((now_wall - spec.t_start) // 60)
            tot, cnt = 0.0, 0
            t0 = int(spec.t_start * 1000)
            while cnt < n_min:
                async with session.get(f"{rest}/api/v3/klines", params={"symbol": "BTCUSDT", "interval": "1m", "startTime": t0,
                                                                        "limit": min(1000, n_min - cnt)}) as r:
                    ks = orjson.loads(await r.read())
                if not ks:
                    break
                for row in ks:
                    tot += 0.5 * (float(row[1]) + float(row[4])) * 60.0
                    cnt += 1
                t0 = int(ks[-1][0]) + 60_000
            spec.acc_sum, spec.acc_t = tot, cnt * 60.0
            spec.last_wall = spec.t_start + cnt * 60.0
        except Exception:
            pass


# --------------------------------------------------------------------------------- CLOB book handling
class PmBooks:
    """Per-token L2 state -> O(1) top of book (best prices cached; the CLOB sends best_bid/best_ask with every change)."""

    def __init__(self):
        self.b: Dict[str, Dict[float, float]] = {}
        self.a: Dict[str, Dict[float, float]] = {}
        self.bb: Dict[str, float] = {}
        self.ba: Dict[str, float] = {}

    def snapshot(self, aid: str, bids, asks) -> None:
        self.b[aid] = {float(x["price"]): float(x["size"]) for x in bids if float(x["size"]) > 0}
        self.a[aid] = {float(x["price"]): float(x["size"]) for x in asks if float(x["size"]) > 0}
        self.bb[aid] = max(self.b[aid]) if self.b[aid] else 0.0
        self.ba[aid] = min(self.a[aid]) if self.a[aid] else 1.0

    def change(self, aid: str, side: str, price: float, size: float, best_bid: Optional[float] = None,
               best_ask: Optional[float] = None) -> None:
        is_bid = side.upper() == "BUY"
        d = (self.b if is_bid else self.a).setdefault(aid, {})
        if size <= 0.0:
            d.pop(price, None)
        else:
            d[price] = size
        if best_bid is not None and best_ask is not None:                 # authoritative, no scan needed
            self.bb[aid], self.ba[aid] = best_bid, best_ask
            return
        if is_bid:
            cur = self.bb.get(aid, 0.0)
            if size > 0 and price >= cur:
                self.bb[aid] = price
            elif size <= 0 and price == cur:
                self.bb[aid] = max(d) if d else 0.0
        else:
            cur = self.ba.get(aid, 1.0)
            if size > 0 and price <= cur:
                self.ba[aid] = price
            elif size <= 0 and price == cur:
                self.ba[aid] = min(d) if d else 1.0

    def top(self, aid: str) -> Optional[Tuple[float, float, float, float]]:
        bb, aa = self.bb.get(aid, 0.0), self.ba.get(aid, 1.0)
        if bb <= 0.0 or aa >= 1.0 or bb >= aa:
            return None
        b, a = self.b.get(aid), self.a.get(aid)
        return bb, aa, (b.get(bb, 0.0) if b else 0.0), (a.get(aa, 0.0) if a else 0.0)


def handle_clob_message(m, books: PmBooks, on_top, on_trade=None) -> None:
    items = m if isinstance(m, list) else [m]
    for it in items:
        et = it.get("event_type")
        if et == "book":
            aid = it["asset_id"]
            books.snapshot(aid, it.get("bids", []), it.get("asks", []))
            on_top(aid)
        elif et == "price_change":
            seen = set()
            for pc in it.get("price_changes", []):
                aid = pc["asset_id"]
                bb, ba = pc.get("best_bid"), pc.get("best_ask")
                books.change(aid, pc["side"], float(pc["price"]), float(pc["size"]),
                             float(bb) if bb not in (None, "") else None, float(ba) if ba not in (None, "") else None)
                seen.add(aid)
            for aid in seen:
                on_top(aid)
        elif et == "last_trade_price" and on_trade is not None:
            on_trade(it["asset_id"], float(it["price"]), float(it["size"]), it.get("side", ""))


# --------------------------------------------------------------------------------- the watcher / hunter
class PolymarketWatcher:
    """Owns discovery results, the CLOB feed, and the prediction-market scanner (a Hunter extension)."""

    def __init__(self, agency, metas: List[MarketMeta], specs: Dict[str, PmSpec], tokens: Dict[str, str],
                 cfg: Optional[PolyConfig] = None, wall0: float = 0.0, t0: float = 0.0):
        self.a = agency
        self.cfg = cfg or PolyConfig()
        self.book: MarketBook = agency.book
        self.specs = specs
        self.tokens = tokens
        self.idx_of_token = {tok: self.book.index[mid] for mid, tok in tokens.items()}
        self.pm_idx = [self.book.index[m.id] for m in metas]
        self.wall0, self.t0 = wall0, t0
        self.books = PmBooks()
        self.n_signals = 0
        self.per_market: Dict[str, int] = {}
        self.cooldown: Dict[int, float] = {}
        self.active = False
        self.dir = 0
        self.onset_t = 0.0
        self.hk = 0
        self.impulse_id = 0
        self._sid = 10_000_000
        self.n_scans = 0
        self.n_quotes = 0
        self.last_scan = -1e18
        self.coverage_rejects: Dict[str, int] = {}
        self.ctrl_pending: List[tuple] = []
        self.ctrl_rows: List[dict] = []
        self.ctrl_horizons = (5.0, 30.0)
        self._ctrl_done: set = set()

    def wall(self, t: float) -> float:
        return self.wall0 + (t - self.t0)

    # ---- feed
    async def feed(self, fm) -> None:
        perf = fm.perf
        loads = orjson.loads
        toks = list(self.tokens.values())

        last: Dict[str, tuple] = {}

        def on_top(aid):
            i = self.idx_of_token.get(aid)
            if i is None:
                return
            tp = self.books.top(aid)
            if tp is not None and last.get(aid) != tp:                  # only genuine top-of-book changes enter the book/rings
                last[aid] = tp
                self.n_quotes += 1
                self.a.on_quote(i, perf(), tp[0], tp[1], tp[2], tp[3])

        def on_trade(aid, price, size, side_str):
            i = self.idx_of_token.get(aid)
            if i is None:
                return
            row = self.book.state[i]
            mid = float(row[MID]) if row[NTICK] > 0 else 0.0
            agg = (1 if price >= mid else -1) if mid > 0 else (1 if side_str.upper() == "BUY" else -1)   # aggressor inferred from price vs mid
            self.a.on_market_trade(i, perf(), price, size, agg)

        async def on_open(ws):
            self.books = PmBooks()
            last.clear()
            await ws.send(orjson.dumps({"assets_ids": toks, "type": "market"}).decode())

        async def handler(ws, st):
            async for raw in ws:
                st.msgs += 1
                st.last_msg = perf()
                if raw in ("PONG", b"PONG"):
                    continue
                try:
                    m = loads(raw)
                except Exception:
                    continue
                handle_clob_message(m, self.books, on_top, on_trade if fm.trade_prints else None)
                st.quotes = self.n_quotes

        async def pinger(ws):
            while True:
                await asyncio.sleep(9)
                try:
                    await ws.send("PING")
                except Exception:
                    return

        async def handler_with_ping(ws, st):
            task = asyncio.create_task(pinger(ws))
            try:
                await handler(ws, st)
            finally:
                task.cancel()

        await fm._run("polymarket", WS_URL, on_open, handler_with_ping, list(self.pm_idx), max_size=2 ** 24)

    # ---- sigma
    def sigma_s(self, st: OracleState) -> float:
        floor = self.cfg.vol_floor_ann / math.sqrt(SEC_PER_YEAR)
        return max(max(st.vol_slow_bps, st.vol_fast_bps) * 1e-4, floor)

    # ---- scan: called after the hunter's scan on the same BTC tick
    def scan(self, t: float, st: OracleState) -> List[Signal]:
        c = self.cfg
        if not c.enabled or not st.warm:
            return []
        if t - self.last_scan < 0.005:
            return []
        self.last_scan = t
        self.n_scans += 1
        wall = self.wall(t)
        S = float(st.micro)
        # accumulate TWAP integrals / initialise references for windows that have started
        for spec in self.specs.values():
            if spec.kind in ("updown_terminal", "updown_twap") and spec.t_start <= wall < spec.t_end:
                if spec.S0 <= 0.0:                      # window started during the run: oracle price at start (first scan after)
                    spec.S0, spec.acc_sum, spec.acc_t, spec.last_wall = S, 0.0, 0.0, wall
                if spec.kind == "updown_twap":
                    dt = wall - spec.last_wall
                    if 0.0 < dt < 5.0:
                        spec.acc_sum += S * dt
                        spec.acc_t += dt
                    spec.last_wall = wall
        self._resolve_ctrl(t, wall, S, self.sigma_s(st))
        # BTC impulse trigger (own, more sensitive than the lead-lag hunter's)
        best, bk = 0.0, -1
        for k in range(len(st.z)):
            if st.ok[k] and abs(st.delta[k]) * BPS >= c.min_impulse_bps and abs(st.z[k]) > best:
                best, bk = abs(st.z[k]), k
        if self.active:
            if np.sign(st.z[self.hk]) != self.dir or abs(st.z[self.hk]) < 0.5 * c.z_thr:
                self.active = False
        if not self.active:
            if bk >= 0 and best >= c.z_thr:
                self.active, self.dir, self.onset_t, self.hk = True, int(np.sign(st.z[bk])), t, bk
                self.impulse_id += 1
            else:
                return []
        elif bk >= 0 and abs(st.z[bk]) > abs(st.z[self.hk]) and np.sign(st.z[bk]) == self.dir:
            self.hk = bk
        h = float(st.horizons[self.hk])
        age = t - self.onset_t
        sig_s = self.sigma_s(st)
        if age > c.window_s:
            return []
        S_then = S * math.exp(-float(st.delta[self.hk]))
        bk_state = self.book.state
        out: List[Signal] = []
        for i in self.pm_idx:
            row = bk_state[i]
            if row[NTICK] < 2 or self.cooldown.get(i, 0.0) > t:
                continue
            mid_now = float(row[MID])
            spread = float(row[ASK] - row[BID])
            if spread > c.max_spread_prob or not (c.mid_lo < mid_now < c.mid_hi):
                continue
            mid_id = self.book.ids[i]
            spec = self.specs[mid_id]
            if spec.t_end - wall < c.min_ttl_s:                                  # resolution gap risk: no entries near expiry
                self.coverage_rejects["near_expiry"] = self.coverage_rejects.get("near_expiry", 0) + 1
                continue
            A_now = (spec.acc_sum / spec.acc_t) if spec.acc_t > 0 else None
            p_now = fair_prob(spec, S, wall, sig_s, 0.0, A_now)
            p_then = fair_prob(spec, S_then, wall, sig_s, h, A_now)
            if p_now is None or p_then is None:
                self.coverage_rejects["no_model"] = self.coverage_rejects.get("no_model", 0) + 1
                continue
            m_then = self.book.mid_asof(i, t - h)
            if not np.isfinite(m_then):
                continue
            fair_d = p_now - p_then
            mkt_d = mid_now - m_then
            gap = fair_d - mkt_d
            if abs(gap) < c.min_gap_prob or gap * fair_d <= 0.0:
                continue
            if mkt_d * fair_d > 0.0 and mkt_d / fair_d > c.max_repriced:
                continue
            side = 1 if gap > 0 else -1
            self._sid += 1
            self.cooldown[i] = t + c.cooldown_s
            self.n_signals += 1
            self.ctrl_pending.append((t, self._sid, i, side, p_now, mid_now, gap, 1_000_000 + self.impulse_id, mid_id))
            self.per_market[mid_id] = self.per_market.get(mid_id, 0) + 1
            spread_bps = spread / mid_now * BPS
            out.append(Signal(
                sid=self._sid, t=t, t_recv=t, market=mid_id, idx=i, side=side, horizon_s=h,
                btc_delta_bps=float(st.delta[self.hk] * BPS), btc_z=float(st.z[self.hk]), btc_obi=float(st.obi),
                btc_flow_1s=float(st.flow_imb_1s), vol_ratio=float(st.vol_ratio), beta=1.0, rho=1.0, lag_s=0.0,
                window_s=c.window_s, age_s=age, fair_bps=fair_d / mid_now * BPS, actual_bps=mkt_d / mid_now * BPS,
                gap_bps=gap / mid_now * BPS, gap_z=abs(gap) / max(spread, 0.005), sigma_res_bps=max(spread_bps, 100.0),
                spread_bps=spread_bps, bid=float(row[BID]), ask=float(row[ASK]), bq=float(row[BQ]), aq=float(row[AQ]),
                mid=mid_now, impulse_id=1_000_000 + self.impulse_id))
        return out

    def _resolve_ctrl(self, t: float, wall: float, S: float, sig_s: float) -> None:
        """Momentum control: after h seconds compare (a) how far the CLOB mid actually moved, with (b) how far the *model fair value*
        moved because BTC kept drifting. If the CLOB merely tracked fair value, (a) ~ (b) and the 'gap' was not an edge."""
        pend = self.ctrl_pending
        if not pend:
            return
        keep = []
        for rec in pend:
            t0, sid, i, side, p0, m0, gap, imp, mid_id = rec
            done = True
            for h in self.ctrl_horizons:
                key = (sid, h)
                if t - t0 >= h and key not in self._ctrl_done:
                    spec = self.specs[mid_id]
                    A = (spec.acc_sum / spec.acc_t) if spec.acc_t > 0 else None
                    p1 = fair_prob(spec, S, wall, sig_s, 0.0, A)
                    m1 = float(self.book.state[i, MID])
                    if p1 is not None:
                        self.ctrl_rows.append({"sid": sid, "imp": imp, "market": mid_id, "kind": spec.kind, "h": h, "side": side,
                                               "gap_p": side * gap, "fair_move": side * (p1 - p0), "mkt_move": side * (m1 - m0)})
                    self._ctrl_done.add(key)
                if key not in self._ctrl_done:
                    done = False
            if not done and t - t0 < max(self.ctrl_horizons) + 5.0:
                keep.append(rec)
        self.ctrl_pending = keep

    def table(self, t: float) -> List[dict]:
        wall = self.wall(t)
        rows = []
        for mid_id, spec in self.specs.items():
            i = self.book.index[mid_id]
            r = self.book.state[i]
            rows.append({"market": mid_id, "kind": spec.kind, "ttl_min": (spec.t_end - wall) / 60.0, "ticks": int(r[NTICK]),
                         "mid": float(r[MID]), "spread_c": float((r[ASK] - r[BID]) * 100), "signals": self.per_market.get(mid_id, 0)})
        return rows
