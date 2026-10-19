"""Tier 1 – the 50+ concurrent market watchers.

All markets live in one struct-of-arrays ``MarketBook`` so the hunter can scan every market in a
single numba pass. Per market we keep: latest bid/ask/sizes, exact tick-arrival time, EW
inter-arrival time (-> staleness ratio and tick rate), fast/slow spread EW (-> spread regime), and
a ring of (t, bid, ask) for as-of price lookups and markout resolution.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

import numpy as np
from numba import njit

from . import mathkit as mk
from .config import WatcherConfig

# state columns
BID, ASK, BQ, AQ, LAST_T, FIRST_T, MEAN_DT, SPR_FAST, SPR_SLOW, NTICK, MID, LMID, NK = range(13)
K_COLS = NK + 1

REGIME_TIGHT, REGIME_NORMAL, REGIME_WIDE = 0, 1, 2


@njit(cache=True)
def _book_push(state, rt, rb, ra, n, cap, i, t, b, a, bq, aq, sfa, ssa, rate_n):
    mid = 0.5 * (b + a)
    sbps = (a - b) / mid * 1e4
    if state[i, NTICK] == 0.0:
        state[i, FIRST_T] = t
        state[i, MEAN_DT] = 1.0
        state[i, SPR_FAST] = sbps
        state[i, SPR_SLOW] = sbps
    else:
        dt = t - state[i, LAST_T]
        if dt < 0.0:
            dt = 0.0
        al = 1.0 / min(state[i, NTICK], rate_n)
        state[i, MEAN_DT] += al * (dt - state[i, MEAN_DT])
        state[i, SPR_FAST] += sfa * (sbps - state[i, SPR_FAST])
        state[i, SPR_SLOW] += ssa * (sbps - state[i, SPR_SLOW])
    state[i, BID] = b
    state[i, ASK] = a
    state[i, BQ] = bq
    state[i, AQ] = aq
    state[i, LAST_T] = t
    state[i, NTICK] += 1.0
    state[i, MID] = mid
    state[i, LMID] = math.log(mid)
    k = n[i] % cap
    rt[i, k] = t
    rb[i, k] = b
    ra[i, k] = a
    n[i] += 1


@njit(cache=True)
def log_mid_asof(rt, rb, ra, n, cap, i, tq):
    """log mid of market i as of time tq, NaN if unavailable."""
    j = mk.ring_asof(rt[i], n[i], cap, tq)
    if j < 0:
        return np.nan
    k = j % cap
    return math.log(0.5 * (rb[i, k] + ra[i, k]))


@dataclass
class MarketMeta:
    id: str
    venue: str            # binance | gate | coinbase
    symbol: str           # venue-native symbol
    base: str
    tick: float = 0.0
    step: float = 0.0
    min_notional: float = 5.0
    quote_vol_usd: float = 0.0
    beta_prior: float = 1.0
    tradable: bool = True


class MarketBook:
    """SoA book of N markets. Index 0 is always the BTC reference (Binance BTCUSDT)."""

    def __init__(self, metas: Sequence[MarketMeta], cfg: Optional[WatcherConfig] = None):
        self.cfg = cfg or WatcherConfig()
        self.metas: List[MarketMeta] = list(metas)
        self.M = len(self.metas)
        self.ids = [m.id for m in self.metas]
        self.index: Dict[str, int] = {m.id: i for i, m in enumerate(self.metas)}
        cap = self.cfg.ring_cap
        self.cap = cap
        self.state = np.zeros((self.M, K_COLS))
        self.rt = np.zeros((self.M, cap))
        self.rb = np.zeros((self.M, cap))
        self.ra = np.zeros((self.M, cap))
        self.n = np.zeros(self.M, dtype=np.int64)
        self.rejected = 0

    # ---------------------------------------------------------------- ingestion
    def on_quote(self, i: int, t: float, bid: float, ask: float, bq: float, aq: float) -> bool:
        if not (bid > 0.0 and ask >= bid):
            self.rejected += 1
            return False
        _book_push(self.state, self.rt, self.rb, self.ra, self.n, self.cap, i, t, bid, ask, bq, aq,
                   self.cfg.spread_fast_alpha, self.cfg.spread_slow_alpha, self.cfg.rate_tau_ticks)
        return True

    # ---------------------------------------------------------------- derived views
    def spread_bps(self) -> np.ndarray:
        s = self.state
        with np.errstate(divide="ignore", invalid="ignore"):
            return np.where(s[:, MID] > 0, (s[:, ASK] - s[:, BID]) / s[:, MID] * 1e4, np.nan)

    def staleness(self, t: float) -> np.ndarray:
        """Seconds since the last tick (inf if never seen)."""
        lt = self.state[:, LAST_T]
        return np.where(self.state[:, NTICK] > 0, t - lt, np.inf)

    def stale_ratio(self, t: float) -> np.ndarray:
        """Silence expressed in units of the market's own mean inter-arrival time."""
        with np.errstate(divide="ignore", invalid="ignore"):
            return self.staleness(t) / self.state[:, MEAN_DT]

    def tick_rate(self) -> np.ndarray:
        with np.errstate(divide="ignore", invalid="ignore"):
            return np.where(self.state[:, NTICK] > 5, 1.0 / self.state[:, MEAN_DT], 0.0)

    def regime(self) -> np.ndarray:
        f, s = self.state[:, SPR_FAST], self.state[:, SPR_SLOW]
        out = np.full(self.M, REGIME_NORMAL, dtype=np.int8)
        out[f > 2.0 * s] = REGIME_WIDE
        out[f < 0.7 * s] = REGIME_TIGHT
        return out

    def quote_asof(self, i: int, tq: float):
        """(bid, ask) as of time tq or None."""
        j = mk.ring_asof(self.rt[i], self.n[i], self.cap, tq)
        if j < 0:
            return None
        k = j % self.cap
        return float(self.rb[i, k]), float(self.ra[i, k])

    def mid_asof(self, i: int, tq: float) -> float:
        q = self.quote_asof(i, tq)
        return float("nan") if q is None else 0.5 * (q[0] + q[1])

    def telemetry(self, t: float) -> List[dict]:
        sp = self.spread_bps()
        st = self.staleness(t)
        rate = self.tick_rate()
        reg = self.regime()
        names = ("tight", "normal", "wide")
        rows = []
        for i, m in enumerate(self.metas):
            rows.append({"market": m.id, "venue": m.venue, "ticks": int(self.state[i, NTICK]),
                         "rate_hz": float(rate[i]), "stale_s": float(st[i]), "spread_bps": float(sp[i]),
                         "regime": names[int(reg[i])]})
        return rows


# ------------------------------------------------------------------------------ discovery
async def discover_binance_universe(n_markets: int, exclude_bases: Sequence[str], session=None, exclude_regex: str = "",
                                    rest_base: str = "https://data-api.binance.vision") -> List[MarketMeta]:
    """Top-N USDT spot markets by 24h quote volume, with tick/step/min-notional filters."""
    import aiohttp
    import orjson

    own = session is None
    session = session or aiohttp.ClientSession(trust_env=True, timeout=aiohttp.ClientTimeout(total=30))
    try:
        async with session.get(f"{rest_base}/api/v3/ticker/24hr") as r:
            tick24 = orjson.loads(await r.read())
        bad_suffix = ("UP", "DOWN", "BULL", "BEAR")
        rows = []
        for x in tick24:
            s = x["symbol"]
            if not s.endswith("USDT"):
                continue
            base = s[:-4]
            if base in exclude_bases or base.endswith(bad_suffix) or float(x["quoteVolume"]) <= 0:
                continue
            if exclude_regex and re.match(exclude_regex, base):
                continue
            rows.append((float(x["quoteVolume"]), s, base))
        rows.sort(reverse=True)
        chosen = [r for r in rows if r[1] != "BTCUSDT"][: n_markets]
        syms = ["BTCUSDT"] + [r[1] for r in chosen]
        import json
        async with session.get(f"{rest_base}/api/v3/exchangeInfo",
                               params={"symbols": json.dumps(syms, separators=(",", ":"))}) as r:
            info = orjson.loads(await r.read())
        meta: Dict[str, MarketMeta] = {}
        vols = {r[1]: r[0] for r in rows}
        for s in info["symbols"]:
            f = {x["filterType"]: x for x in s["filters"]}
            tick = float(f.get("PRICE_FILTER", {}).get("tickSize", 0) or 0)
            step = float(f.get("LOT_SIZE", {}).get("stepSize", 0) or 0)
            mn = float((f.get("NOTIONAL") or f.get("MIN_NOTIONAL") or {}).get("minNotional", 5) or 5)
            meta[s["symbol"]] = MarketMeta(id=s["symbol"], venue="binance", symbol=s["symbol"],
                                           base=s["baseAsset"], tick=tick, step=step, min_notional=mn,
                                           quote_vol_usd=vols.get(s["symbol"], 0.0),
                                           beta_prior=1.0)
        return [meta[s] for s in syms if s in meta]
    finally:
        if own:
            await session.close()


def cross_venue_metas() -> List[MarketMeta]:
    """Cross-venue BTC-family markets (Gate + Kraken BBO) for venue lead-lag."""
    out = []
    for base in ("BTC", "ETH", "SOL"):
        out.append(MarketMeta(id=f"gate:{base}_USDT", venue="gate", symbol=f"{base}_USDT", base=base, tick=0.0))
        out.append(MarketMeta(id=f"kraken:{base}/USD", venue="kraken", symbol=f"{base}/USD", base=base, tick=0.0))
    return out


@njit(cache=True)
def ring_window_lmid(rt, rb, ra, n, cap, t0, t1):
    """Contiguous (t, log-mid) window for one market row, anchored at t0 (see mathkit.ring_window)."""
    j1 = mk.ring_asof(rt, n, cap, t1)
    if j1 < 0:
        return np.empty(0), np.empty(0)
    j0 = mk.ring_asof(rt, n, cap, t0)
    start = j0 + 1 if j0 >= 0 else max(0, n - cap)
    cnt = j1 - start + 1
    if cnt < 0:
        cnt = 0
    extra = 1 if j0 >= 0 else 0
    tt = np.empty(cnt + extra)
    vv = np.empty(cnt + extra)
    if extra == 1:
        tt[0] = t0
        vv[0] = math.log(0.5 * (rb[j0 % cap] + ra[j0 % cap]))
    for k in range(cnt):
        q = (start + k) % cap
        tt[extra + k] = rt[q]
        vv[extra + k] = math.log(0.5 * (rb[q] + ra[q]))
    return tt, vv
