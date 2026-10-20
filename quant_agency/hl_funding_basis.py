"""Track 2 (Phase 12): Hyperliquid hourly funding and persistent spot-perp basis, slow horizons (minutes to hours).

Two questions, both measured before anything is sized:

1. **Basis mean reversion.** For a matched Binance-spot / Hyperliquid-perp pair, ``basis = ln(HL / Binance)``. When the (smoothed) basis sits
   >= thr bps away from its own trailing equilibrium, does it come back within 5 / 15 / 30 minutes, which leg does the moving, and does what is
   left survive costs? (Phase 11 showed that ~2/3 of a sub-second gap never closes in 30 s; it did not show *why*.)
2. **Funding carry.** Hyperliquid funding settles hourly. How often is it far from its 0.125 bps/hour floor among liquid coins, how long does an
   extreme last, and how many hours of carry does it take to pay for the two legs (perp + spot hedge)?

This module is measurement only: no order is built and no credential is read. Everything that depends on the account size (minimum order,
fees, leverage cap, loss limit) lives in :class:`Bankroll` so the same numbers drive the study and the later paper simulation.
"""
from __future__ import annotations

import json
import math
import os
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

BPS = 1e4
HL_INFO = "https://api.hyperliquid.xyz/info"
BN_REST = "https://data-api.binance.vision"
MIN_MS = 60_000

# Public base-tier fees, per side (bps). Assumptions, not verified for any account.
HL_MAKER_BPS, HL_TAKER_BPS = 1.5, 4.5
BN_SPOT_BPS = 7.5          # Binance spot with BNB discount, maker == taker at the base tier


@dataclass
class Bankroll:
    """A real 100 USD account, expressed as constraints the simulation must respect."""
    capital_usd: float = 100.0
    min_notional_usd: float = 10.0          # Hyperliquid minimum order value
    notional_usd: float = 20.0              # per position (the brief: 10-25)
    max_leverage: float = 2.0
    max_open: int = 4                       # concurrent positions: 4 x 20 = 80 USD notional <= capital x leverage
    max_loss_frac: float = 0.10             # stop the whole run at -10 % of capital
    pm_min_shares: float = 5.0              # Polymarket minimum order size (shares)

    def can_open(self, open_notional: float, equity: float, n_open: int = 0) -> bool:
        return (n_open < self.max_open and open_notional + self.notional_usd <= equity * self.max_leverage and self.notional_usd >= self.min_notional_usd
                and equity > self.capital_usd * (1.0 - self.max_loss_frac))


# ================================================================================ REST (history)
def _post(url: str, data: dict, retries: int = 3):
    for k in range(retries):
        try:
            req = urllib.request.Request(url, data=json.dumps(data).encode(), headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"})
            return json.loads(urllib.request.urlopen(req, timeout=40).read())
        except Exception:
            if k == retries - 1:
                raise
            time.sleep(1.5 * (k + 1))


def _get(url: str, retries: int = 3):
    for k in range(retries):
        try:
            return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=40).read())
        except Exception:
            if k == retries - 1:
                raise
            time.sleep(1.5 * (k + 1))


@dataclass
class PairHistory:
    asset: str
    t0_ms: int                                  # minute-aligned start
    hl_close: np.ndarray
    hl_n: np.ndarray                            # trades in the minute
    bn_close: np.ndarray
    bn_n: np.ndarray
    funding: np.ndarray = field(default_factory=lambda: np.zeros((0, 2)))      # (time_ms, hourly rate) from fundingHistory


BAR_MS = {"1m": MIN_MS, "1h": 60 * MIN_MS}


def fetch_pair_history(asset: str, hl_coin: str, bn_symbol: str, minutes: int = 4900, now_ms: Optional[int] = None, interval: str = "1m") -> PairHistory:
    """Aligned closes + trade counts for both venues over the last ``minutes`` bars of ``interval`` (Hyperliquid keeps ~5 000 candles per interval:
    ~3.4 days of 1-minute bars, ~200 days of hourly bars). Despite the argument name, ``minutes`` counts bars."""
    bar = BAR_MS[interval]
    now_ms = now_ms or int(time.time() * 1000)
    end = now_ms - now_ms % bar
    start = end - minutes * bar
    n = minutes
    hl_c, hl_n = np.full(n, np.nan), np.zeros(n)
    bn_c, bn_n = np.full(n, np.nan), np.zeros(n)
    for c in _post(HL_INFO, {"type": "candleSnapshot", "req": {"coin": hl_coin, "interval": interval, "startTime": start, "endTime": end}}):
        k = (c["t"] - start) // bar
        if 0 <= k < n:
            hl_c[k], hl_n[k] = float(c["c"]), float(c["n"])
    cur = start
    while cur < end:
        rows = _get(f"{BN_REST}/api/v3/klines?symbol={bn_symbol}&interval={interval}&limit=1000&startTime={cur}&endTime={end}")
        if not rows:
            break
        for r in rows:
            k = (r[0] - start) // bar
            if 0 <= k < n:
                bn_c[k], bn_n[k] = float(r[4]), float(r[8])
        nxt = rows[-1][0] + bar
        if nxt <= cur:
            break
        cur = nxt
    return PairHistory(asset, start, hl_c, hl_n, bn_c, bn_n)


def fetch_funding_history(hl_coin: str, days: int = 90, now_ms: Optional[int] = None) -> np.ndarray:
    """(time_ms, hourly funding rate) rows, paginated forward (500 per request)."""
    now_ms = now_ms or int(time.time() * 1000)
    cur = now_ms - days * 86_400_000
    out: List[Tuple[int, float]] = []
    while cur < now_ms:
        rows = _post(HL_INFO, {"type": "fundingHistory", "coin": hl_coin, "startTime": cur})
        if not rows:
            break
        out += [(r["time"], float(r["fundingRate"])) for r in rows]
        nxt = rows[-1]["time"] + 1
        if nxt <= cur or len(rows) < 500:
            break
        cur = nxt
    return np.array(out, dtype=float) if out else np.zeros((0, 2))


def fetch_all(pairs: Sequence[dict], minutes: int = 4900, funding_days: int = 90, workers: int = 4, cache: Optional[str] = None, interval: str = "1m") -> List[PairHistory]:
    """``pairs``: dicts with asset / binance (symbol) / hl (``hyperliquid:<coin>``). Cached as one npz per run so a study is reproducible offline."""
    if cache and os.path.exists(cache):
        return load_cache(cache)

    def one(p):
        coin = p["hl"].split(":", 1)[1]
        h = fetch_pair_history(p["asset"], coin, p["binance"], minutes, interval=interval)
        h.funding = fetch_funding_history(coin, funding_days)
        return h

    with ThreadPoolExecutor(max_workers=workers) as ex:
        res = list(ex.map(one, pairs))
    if cache:
        save_cache(cache, res)
    return res


def save_cache(path: str, hs: Sequence[PairHistory]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    d = {}
    for h in hs:
        d[f"{h.asset}__meta"] = np.array([h.t0_ms], dtype=np.int64)
        for k in ("hl_close", "hl_n", "bn_close", "bn_n", "funding"):
            d[f"{h.asset}__{k}"] = getattr(h, k)
    np.savez_compressed(path, **d)


def load_cache(path: str) -> List[PairHistory]:
    z = np.load(path)
    assets = sorted({k.split("__")[0] for k in z.files})
    return [PairHistory(a, int(z[f"{a}__meta"][0]), z[f"{a}__hl_close"], z[f"{a}__hl_n"], z[f"{a}__bn_close"], z[f"{a}__bn_n"], z[f"{a}__funding"]) for a in assets]


# ================================================================================ basis study (pure numpy)
@dataclass
class BasisConfig:
    min_trades: float = 2.0                 # a minute with fewer trades on either venue is a stale print, not a quote
    smooth_min: int = 3                     # smoothing window (minutes) of the basis, ~ the brief's 60 s smoothing on 1-minute closes
    eq_window_min: int = 360                # trailing equilibrium = median of the basis over the previous 6 h ...
    eq_gap_min: int = 10                    # ... excluding the most recent 10 minutes (so a fresh dislocation cannot define its own normal)
    eq_min_valid: int = 240
    entry_delay_min: int = 1                # the trigger is known at the close of minute t; the earliest fill is the close of t+1
    cooldown_min: int = 30                  # one event per coin per 30 minutes
    horizons_min: Tuple[int, ...] = (5, 15, 30)
    thresholds_bps: Tuple[float, ...] = (8.0, 15.0, 30.0)
    block_min: int = 30                     # cluster = 30-minute block (market-wide moves hit many coins at once)


def _rolling_mean_valid(x: np.ndarray, w: int) -> np.ndarray:
    out = np.full(len(x), np.nan)
    ok = np.isfinite(x)
    c = np.cumsum(np.where(ok, x, 0.0))
    k = np.cumsum(ok.astype(float))
    for i in range(w - 1, len(x)):
        cnt = k[i] - (k[i - w] if i >= w else 0.0)
        if cnt >= max(1, w - 1):
            out[i] = (c[i] - (c[i - w] if i >= w else 0.0)) / cnt
    return out


def basis_series(h: PairHistory, cfg: BasisConfig) -> np.ndarray:
    """Raw 1-minute basis in bps, NaN where either venue's minute is a stale print."""
    ok = (h.hl_n >= cfg.min_trades) & (h.bn_n >= cfg.min_trades) & np.isfinite(h.hl_close) & np.isfinite(h.bn_close)
    b = np.full(len(h.hl_close), np.nan)
    b[ok] = np.log(h.hl_close[ok] / h.bn_close[ok]) * BPS
    return b


def deviation_series(basis: np.ndarray, cfg: BasisConfig) -> Tuple[np.ndarray, np.ndarray]:
    """(smoothed basis, deviation from the trailing median equilibrium)."""
    sm = _rolling_mean_valid(basis, cfg.smooth_min)
    dev = np.full(len(sm), np.nan)
    W, G = cfg.eq_window_min, cfg.eq_gap_min
    for i in range(W + G, len(sm)):
        win = sm[i - W - G: i - G]
        v = win[np.isfinite(win)]
        if len(v) >= cfg.eq_min_valid and np.isfinite(sm[i]):
            dev[i] = sm[i] - np.median(v)
    return sm, dev


def find_events(h: PairHistory, cfg: BasisConfig, thr: float, lo: int = 0, hi: Optional[int] = None) -> List[dict]:
    """Basis-dislocation events with their leg-by-leg outcomes at every horizon (positions: short the rich leg, long the cheap one)."""
    basis = basis_series(h, cfg)
    sm, dev = deviation_series(basis, cfg)
    hi = len(dev) if hi is None else hi
    ev: List[dict] = []
    last = -10 ** 9
    hl, bn = h.hl_close, h.bn_close
    for t in range(max(lo, 1), hi):
        d = dev[t]
        if not np.isfinite(d) or abs(d) < thr or t - last < cfg.cooldown_min:
            continue
        e = t + cfg.entry_delay_min
        s = 1.0 if d > 0 else -1.0                         # + : perp rich -> short perp / long spot
        if e >= len(hl) or not (np.isfinite(hl[e]) and np.isfinite(bn[e])):
            continue
        row = {"asset": h.asset, "t": t, "dev": float(d), "side": s, "block": t // cfg.block_min, "hl_n": float(h.hl_n[t]), "bn_n": float(h.bn_n[t]), "out": {}}
        for H in cfg.horizons_min:
            x = e + H
            if x >= len(hl) or not (np.isfinite(hl[x]) and np.isfinite(bn[x])):
                continue
            perp = -s * math.log(hl[x] / hl[e]) * BPS             # short rich perp earns when the perp falls
            spot = s * math.log(bn[x] / bn[e]) * BPS              # long cheap spot earns when spot rises
            row["out"][H] = {"perp": perp, "spot": spot, "hedged": perp + spot, "dev_exit": float(dev[x]) if np.isfinite(dev[x]) else float("nan")}
        if row["out"]:
            ev.append(row)
            last = t
    return ev


def cluster_mean(x: Sequence[float], clusters: Sequence) -> Tuple[float, float, int]:
    """(mean, cluster-robust s.e., n clusters)."""
    x = np.asarray(x, dtype=float)
    n = len(x)
    if n == 0:
        return float("nan"), float("nan"), 0
    mu = x.mean()
    by: Dict[object, float] = {}
    for v, c in zip(x, clusters):
        by[c] = by.get(c, 0.0) + (v - mu)
    cl = np.array(list(by.values()))
    if len(cl) < 2:
        return float(mu), float("nan"), len(cl)
    return float(mu), float(np.sqrt((cl ** 2).sum()) / n), len(cl)


COSTS = {"perp_only_maker": 2 * HL_MAKER_BPS, "perp_only_taker": 2 * HL_TAKER_BPS, "hedged_perp_maker+spot": 2 * HL_MAKER_BPS + 2 * BN_SPOT_BPS}


def summarise(events: Sequence[dict], horizons: Sequence[int]) -> Dict[int, dict]:
    out = {}
    for H in horizons:
        rs = [(e, e["out"][H]) for e in events if H in e["out"]]
        if not rs:
            continue
        cl = [e["block"] for e, _ in rs]
        dev = np.array([abs(e["dev"]) for e, _ in rs])
        d = {"n": len(rs), "clusters": len({c for c in cl}), "mean_abs_dev": float(dev.mean())}
        for leg in ("perp", "spot", "hedged"):
            m, se, k = cluster_mean([o[leg] for _, o in rs], cl)
            d[leg] = {"mean": m, "se": se}
        # fraction of the deviation that came back (ratio of means; the deviation itself is signed by the position side)
        d["reverted_frac"] = float(np.mean([e["dev"] * e["side"] - o["dev_exit"] * e["side"] for e, o in rs if np.isfinite(o["dev_exit"])]) / dev.mean()) if dev.mean() > 0 else float("nan")
        d["net"] = {k: {"mean": (d["hedged"]["mean"] if k.startswith("hedged") else d["perp"]["mean"]) - c, "se": (d["hedged"]["se"] if k.startswith("hedged") else d["perp"]["se"])}
                    for k, c in COSTS.items()}
        out[H] = d
    return out


def basis_study(hists: Sequence[PairHistory], cfg: Optional[BasisConfig] = None, split_frac: float = 0.55, exclude: Sequence[str] = (), min_events: int = 30) -> dict:
    """Train on the first ``split_frac`` of the window (pick threshold x horizon), evaluate the chosen cell **once** on the rest."""
    cfg = cfg or BasisConfig()
    hs = [h for h in hists if h.asset not in exclude]
    n = min(len(h.hl_close) for h in hs)
    cut = int(n * split_frac)
    res: dict = {"cut_min": cut, "n_min": n, "coins": [h.asset for h in hs], "train": {}, "test": {}}
    for part, (lo, hi) in (("train", (0, cut)), ("test", (cut, n))):
        for thr in cfg.thresholds_bps:
            ev = [e for h in hs for e in find_events(h, cfg, thr, lo, hi)]
            res[part][str(thr)] = {"events": len(ev), "by_h": summarise(ev, cfg.horizons_min)}
            res.setdefault("events_" + part, {})[str(thr)] = ev
    # selection on TRAIN only: best perp-only maker net with >= min_events events
    best = None
    for thr, r in res["train"].items():
        for H, d in r["by_h"].items():
            if d["n"] >= min_events:
                v = d["net"]["perp_only_maker"]["mean"]
                if best is None or v > best[0]:
                    best = (v, thr, H)
    res["selected"] = {"thr": best[1], "h": best[2], "train_net_perp_maker": best[0]} if best else None
    return res


# ================================================================================ funding study
@dataclass
class FundingConfig:
    levels_bps: Tuple[float, ...] = (0.5, 1.0, 3.0, 5.0)         # |hourly funding| levels to count (floor is 0.125)
    hold_hours: Tuple[int, ...] = (1, 4, 8, 24)
    min_run_h: Tuple[int, ...] = (3, 6, 12)


def funding_study(hists: Sequence[PairHistory], cfg: Optional[FundingConfig] = None, exclude: Sequence[str] = ()) -> dict:
    cfg = cfg or FundingConfig()
    rows = {}
    pooled: List[np.ndarray] = []
    for h in hists:
        if h.asset in exclude or len(h.funding) < 24:
            continue
        f = h.funding[:, 1] * BPS                                   # bps per hour
        pooled.append(f)
        rows[h.asset] = f
    allf = np.concatenate(pooled) if pooled else np.zeros(0)
    out: dict = {"coins": len(rows), "coin_hours": int(len(allf)), "median_bps_h": float(np.median(allf)) if len(allf) else float("nan"),
                 "pct": {p: float(np.percentile(allf, p)) for p in (1, 5, 50, 95, 99)} if len(allf) else {}}
    out["share_ge"] = {str(L): {"pos": float((allf >= L).mean()), "neg": float((allf <= -L).mean())} for L in cfg.levels_bps} if len(allf) else {}
    # persistence: given an hour at >= L, the mean funding over the following k hours (positive side: the one a spot hedge can carry)
    pers = {}
    for L in cfg.levels_bps:
        if L < 1.0:
            continue
        per_k = {k: [] for k in cfg.hold_hours}
        starts = 0
        for a, f in rows.items():
            for i in range(len(f) - max(cfg.hold_hours) - 1):
                if f[i] >= L:
                    starts += 1
                    for k in cfg.hold_hours:
                        per_k[k].append(f[i + 1: i + 1 + k].sum())
        pers[str(L)] = {"starts": starts, **{f"carry_{k}h_bps": (float(np.mean(v)) if v else float("nan")) for k, v in per_k.items()}}
    out["persistence_pos"] = pers
    # run lengths of positive extremes
    runs = {}
    for L in cfg.levels_bps:
        if L < 1.0:
            continue
        lens = []
        for f in rows.values():
            r = 0
            for v in f:
                if v >= L:
                    r += 1
                elif r:
                    lens.append(r)
                    r = 0
            if r:
                lens.append(r)
        runs[str(L)] = {"episodes": len(lens), "median_h": float(np.median(lens)) if lens else float("nan"), **{f"share_ge_{m}h": float(np.mean(np.array(lens) >= m)) if lens else float("nan") for m in cfg.min_run_h}}
    out["runs_pos"] = runs
    # break-even: hours of carry at a given hourly funding to pay the round-trip cost of each structure
    out["breakeven_hours"] = {name: {str(L): (c / L if L > 0 else float("inf")) for L in (0.125, 1.0, 3.0, 5.0)} for name, c in COSTS.items()}
    return out


def dollars(bps: float, notional: float) -> float:
    return bps / BPS * notional


# ================================================================================ hourly premium test (pre-declared in docs/PHASE12_PLAN.md)
HOURLY = BasisConfig(min_trades=2.0, smooth_min=1, eq_window_min=24, eq_gap_min=1, eq_min_valid=16, entry_delay_min=0, cooldown_min=4,
                     horizons_min=(1, 2, 4, 24), thresholds_bps=(15.0, 30.0), block_min=4)          # all "min" fields count 1-hour bars here
PREMIUM_PRIMARY = {"thr_bps": 30.0, "h_bars": 4, "cost_bps": 6.0, "min_clusters": 30, "alpha": 0.05, "exclude_last_bars": 84}


def market_return_bps(hists: Sequence[PairHistory], e: int, x: int) -> float:
    """Equal-weight spot return over bars e..x across the pairs (the benchmark the perp leg is compared with)."""
    r = [math.log(h.bn_close[x] / h.bn_close[e]) for h in hists if np.isfinite(h.bn_close[e]) and np.isfinite(h.bn_close[x])]
    return float(np.mean(r)) * BPS if r else float("nan")


def premium_events(hists: Sequence[PairHistory], cfg: BasisConfig, thr: float, last_bar: int) -> List[dict]:
    """Dislocation events (both signs) with the perp leg's raw and market-neutral outcome; only bars before ``last_bar`` are used (the discovery window is excluded)."""
    out = []
    for h in hists:
        for e in find_events(h, cfg, thr, 0, last_bar):
            ent = e["t"] + cfg.entry_delay_min
            row = dict(e)
            row["neutral"] = {}
            for H, o in e["out"].items():
                x = ent + H
                if x >= last_bar:
                    continue
                m = market_return_bps(hists, ent, x)
                if np.isfinite(m):
                    row["neutral"][H] = o["perp"] + e["side"] * m                 # short rich perp earns when the market falls, so add back side * market
            out.append(row)
    return out


def premium_test(hists: Sequence[PairHistory], cfg: BasisConfig = HOURLY, spec: Optional[dict] = None, exclude: Sequence[str] = ("BTC", "ETH")) -> dict:
    """The single pre-declared test plus its secondary cells. ``hists`` are hourly; the last ``exclude_last_bars`` bars (the 3.4-day window in which the
    hypothesis was found) are never used."""
    from scipy import stats
    spec = spec or PREMIUM_PRIMARY
    hs = [h for h in hists if h.asset not in exclude]
    n = min(len(h.hl_close) for h in hs)
    last = n - spec["exclude_last_bars"]
    res: dict = {"bars_used": last, "coins": len(hs), "spec": spec, "cells": {}}
    for thr in cfg.thresholds_bps:
        ev = premium_events(hs, cfg, thr, last)
        for H in cfg.horizons_min:
            rows = [e for e in ev if H in e["neutral"]]
            if not rows:
                continue
            cl = [e["block"] for e in rows]
            cell = {"n": len(rows), "clusters": len(set(cl))}
            for name, vals in (("neutral", [e["neutral"][H] for e in rows]), ("raw_perp", [e["out"][H]["perp"] for e in rows]), ("hedged", [e["out"][H]["hedged"] for e in rows])):
                m, se, k = cluster_mean(vals, cl)
                cell[name] = {"mean": m, "se": se}
            m, se, k = cluster_mean([e["neutral"][H] - spec["cost_bps"] for e in rows], cl)
            t = m / se if se and se == se and se > 0 else float("nan")
            cell["net_neutral"] = {"mean": m, "se": se, "t": t, "p1": float(1 - stats.t.cdf(t, max(k - 1, 1))) if t == t else float("nan"), "df": max(k - 1, 1)}
            cell["share_short_perp"] = float(np.mean([e["side"] > 0 for e in rows]))
            res["cells"][f"{thr:g}|{H}"] = cell
    key = f"{spec['thr_bps']:g}|{spec['h_bars']}"
    p = res["cells"].get(key)
    if p is None:
        res["decision"] = "no events in the primary cell"
    elif p["clusters"] < spec["min_clusters"]:
        res["decision"] = f"underpowered: {p['clusters']} clusters < {spec['min_clusters']} - no decision"
    else:
        res["decision"] = "REJECT H0 (net > 0)" if p["net_neutral"]["p1"] < spec["alpha"] else "do not reject H0"
    res["primary"] = p
    return res
