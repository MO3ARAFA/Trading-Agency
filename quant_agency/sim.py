"""Synthetic lead-lag market for deterministic tests and offline dry-runs.

BTC = diffusion + Poisson jump impulses. Alt i's *fair* log price is ``beta_i * BTC(t - lag_i)`` plus a
slow idiosyncratic OU term; it only *quotes* at its own Poisson tick times, so between ticks it is
genuinely stale. Ground-truth (beta, lag) is returned so the estimators can be validated.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

import numpy as np

from .market_watchers import MarketMeta


@dataclass
class SimTruth:
    ids: List[str]
    beta: np.ndarray
    lag: np.ndarray
    rate: np.ndarray
    spread_bps: np.ndarray


def make_sim(n_alts: int = 20, duration_s: float = 600.0, seed: int = 7, btc_rate_hz: float = 80.0,
             jump_rate_hz: float = 1 / 12.0, jump_bps: float = 6.0, diff_bps_per_sqrt_s: float = 0.7,
             lag_range: Tuple[float, float] = (0.3, 1.5), noise_alts: int = 3, t0: float = 1000.0):
    """Returns (metas, events, truth). events: list of (t, idx, bid, ask, bq, aq) sorted by t."""
    rng = np.random.default_rng(seed)
    dt = 0.01
    grid = np.arange(0.0, duration_s + 5.0, dt)
    inc = rng.normal(0.0, diff_bps_per_sqrt_s * 1e-4 * np.sqrt(dt), grid.size)
    njump = rng.poisson(jump_rate_hz * dt, grid.size)
    inc += njump * rng.normal(0.0, jump_bps * 1e-4, grid.size)
    btc_log = np.log(80_000.0) + np.cumsum(inc)

    ids = ["BTCUSDT"]
    metas = [MarketMeta("BTCUSDT", "binance", "BTCUSDT", "BTC", tick=0.01, step=1e-5, min_notional=5.0)]
    beta = np.zeros(n_alts + 1)
    lag = np.zeros(n_alts + 1)
    rate = np.zeros(n_alts + 1)
    spr = np.zeros(n_alts + 1)
    events = []

    # BTC quotes
    tb = np.sort(rng.uniform(0.0, duration_s, int(btc_rate_hz * duration_s)))
    pb = np.exp(np.interp(tb, grid, btc_log))
    bq = rng.uniform(1, 6, tb.size)
    aq = rng.uniform(1, 6, tb.size)
    for k in range(tb.size):
        events.append((t0 + tb[k], 0, pb[k] - 0.005, pb[k] + 0.005, bq[k], aq[k]))

    for a in range(1, n_alts + 1):
        sym = f"ALT{a:02d}USDT"
        ids.append(sym)
        metas.append(MarketMeta(sym, "binance", sym, f"ALT{a:02d}", tick=1e-4, step=0.1, min_notional=5.0))
        noise = a > n_alts - noise_alts            # decoupled markets: no lead-lag
        beta[a] = 0.0 if noise else rng.uniform(0.8, 1.6)
        lag[a] = 0.0 if noise else rng.uniform(*lag_range)
        rate[a] = rng.uniform(1.5, 8.0)
        spr[a] = rng.uniform(1.0, 6.0)
        n_t = rng.poisson(rate[a] * duration_s)
        ta = np.sort(rng.uniform(1.0, duration_s, n_t))
        shift = np.interp(ta - lag[a], grid, btc_log) - btc_log[0]
        # slow idiosyncratic walk (kept small so beta*BTC dominates)
        idio = np.cumsum(rng.normal(0.0, 0.4e-4, n_t))
        if noise:
            idio = np.cumsum(rng.normal(0.0, 1.5e-4, n_t))
        p0 = 10.0 * (1 + a / 10)
        mid = p0 * np.exp(beta[a] * shift + idio)
        half = mid * spr[a] * 0.5e-4
        bqs = rng.uniform(500, 5000, n_t)
        aqs = rng.uniform(500, 5000, n_t)
        for k in range(n_t):
            events.append((t0 + ta[k], a, mid[k] - half[k], mid[k] + half[k], bqs[k], aqs[k]))
    events.sort(key=lambda e: e[0])
    return metas, events, SimTruth(ids, beta, lag, rate, spr)
