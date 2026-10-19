"""Tier 1 – BTC master reference oracle.

Consumes BTCUSDT top-of-book (and optionally aggTrades) and maintains:
  * a tick ring (every top-of-book update; ~ms resolution),
  * a 100 ms grid ring (sub-second) and a 1 s ring,
  * Stoikov micro-price, order-book imbalance, multi-horizon impulse returns
    (1/3/5/10 s), EW impulse variance -> Z-scores, a fast/slow vol regime ratio,
  * signed trade-flow imbalance from aggTrades in 100 ms buckets.

The oracle is clock-injected (callers pass ``t`` in seconds) so it is replayable and unit-testable.
"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np
from numba import njit

from . import mathkit as mk
from .config import OracleConfig


@njit(cache=True)
def _deltas(t, v, n, cap, tnow, horizons, vnow, out, ok):
    for k in range(horizons.shape[0]):
        j = mk.ring_asof(t, n, cap, tnow - horizons[k])
        if j < 0:
            out[k] = 0.0
            ok[k] = 0
        else:
            out[k] = vnow - v[j % cap]
            ok[k] = 1


class OracleState:
    """Mutable snapshot reused across scans (no per-scan allocation)."""
    __slots__ = ("t", "bid", "ask", "bq", "aq", "mid", "micro", "lmu", "lmid", "spread_bps", "obi",
                 "delta", "ok", "sigma", "z", "vol_fast_bps", "vol_slow_bps", "vol_ratio",
                 "tick_vol_bps", "flow_imb_1s", "flow_imb_3s", "warm", "last_trade_px", "horizons")

    def __init__(self, horizons):
        H = len(horizons)
        self.horizons = np.asarray(horizons, dtype=np.float64)
        self.delta = np.zeros(H)
        self.ok = np.zeros(H, dtype=np.int8)
        self.sigma = np.ones(H)
        self.z = np.zeros(H)
        self.t = self.bid = self.ask = self.bq = self.aq = self.mid = self.micro = 0.0
        self.lmu = self.lmid = self.spread_bps = self.obi = 0.0
        self.vol_fast_bps = self.vol_slow_bps = self.vol_ratio = self.tick_vol_bps = 0.0
        self.flow_imb_1s = self.flow_imb_3s = 0.0
        self.warm = False
        self.last_trade_px = 0.0

    def best_horizon(self, min_impulse_bps: float):
        """Index of the horizon with the largest |Z| among those with |delta| >= min_impulse_bps."""
        best, bi = 0.0, -1
        for k in range(len(self.z)):
            if self.ok[k] and abs(self.delta[k]) * mk.BPS >= min_impulse_bps and abs(self.z[k]) > best:
                best, bi = abs(self.z[k]), k
        return bi

    def as_dict(self):
        return {
            "t": self.t, "bid": self.bid, "ask": self.ask, "micro": self.micro, "mid": self.mid,
            "spread_bps": self.spread_bps, "obi": self.obi,
            "delta_bps": {f"{h:g}s": float(d * mk.BPS) for h, d in zip(self.horizons, self.delta)},
            "z": {f"{h:g}s": float(z) for h, z in zip(self.horizons, self.z)},
            "vol_fast_bps_s": self.vol_fast_bps, "vol_slow_bps_s": self.vol_slow_bps,
            "vol_ratio": self.vol_ratio, "tick_vol_bps_s": self.tick_vol_bps,
            "flow_imb_1s": self.flow_imb_1s, "flow_imb_3s": self.flow_imb_3s,
        }


class BtcOracle:
    def __init__(self, cfg: Optional[OracleConfig] = None):
        self.cfg = cfg or OracleConfig()
        c = self.cfg
        self.horizons = np.asarray(c.horizons_s, dtype=np.float64)
        H = len(self.horizons)
        # tick ring
        self.tick_t = np.zeros(c.tick_cap)
        self.tick_lmu = np.zeros(c.tick_cap)
        self.tick_lmid = np.zeros(c.tick_cap)
        self.n = 0
        # grid rings
        self.grid_t = np.zeros(c.grid_cap)
        self.grid_lmu = np.zeros(c.grid_cap)
        self.ng = 0
        self.sec_t = np.zeros(c.sec_cap)
        self.sec_px = np.zeros((c.sec_cap, 4))     # micro, mid, spread_bps, obi
        self.nsec = 0
        # latest top of book
        self.bid = self.ask = self.bq = self.aq = 0.0
        self.micro = self.mid = self.lmu = self.lmid = 0.0
        self.last_t = -1.0
        self.first_t = -1.0
        self.blackout_until = -1.0
        self.n_quotes = 0
        # EW second moments of horizon deltas (fast & slow)
        self.m2 = np.zeros(H)
        self.m2_slow = np.zeros(H)
        self.n_samp = np.zeros(H, dtype=np.int64)
        self._next_grid = -1.0
        self.alpha_fast = 1.0 - 0.5 ** (c.grid_s / c.vol_halflife_s)
        self.alpha_slow = 1.0 - 0.5 ** (c.grid_s / c.slow_vol_halflife_s)
        # trade flow buckets
        self._fcap = 1024
        self._f_stamp = np.full(self._fcap, -1, dtype=np.int64)
        self._f_signed = np.zeros(self._fcap)
        self._f_vol = np.zeros(self._fcap)
        self.last_trade_px = 0.0
        self.n_trades = 0
        self.st = OracleState(self.horizons)
        self._floor = np.array([c.sigma_floor_bps_per_sqrt_s * math.sqrt(h) / mk.BPS for h in self.horizons])

    # ------------------------------------------------------------------ ingestion
    def on_book(self, t: float, bid: float, ask: float, bq: float, aq: float) -> bool:
        if not (bid > 0.0 and ask >= bid):
            return False
        if self.last_t > 0.0 and t - self.last_t > self.cfg.gap_s:   # feed gap: horizons spanning it are invalid
            self.blackout_until = t + float(self.horizons[-1])
        micro = mk.micro_price(bid, ask, bq, aq)
        mid = 0.5 * (bid + ask)
        self.bid, self.ask, self.bq, self.aq = bid, ask, bq, aq
        self.micro, self.mid = micro, mid
        self.lmu, self.lmid = math.log(micro), math.log(mid)
        k = self.n % self.cfg.tick_cap
        self.tick_t[k] = t
        self.tick_lmu[k] = self.lmu
        self.tick_lmid[k] = self.lmid
        self.n += 1
        self.n_quotes += 1
        self.last_t = t
        if self.first_t < 0.0:
            self.first_t = t
            self._next_grid = (math.floor(t / self.cfg.grid_s) + 1) * self.cfg.grid_s
        return True

    def on_trade(self, t: float, price: float, qty: float, buyer_is_maker: bool) -> None:
        """aggTrade: buyer_is_maker=True means the aggressor sold (negative flow)."""
        idx = int(t / self.cfg.flow_bucket_s)
        k = idx % self._fcap
        if self._f_stamp[k] != idx:
            self._f_stamp[k] = idx
            self._f_signed[k] = 0.0
            self._f_vol[k] = 0.0
        self._f_signed[k] += -qty if buyer_is_maker else qty
        self._f_vol[k] += qty
        self.last_trade_px = price
        self.n_trades += 1

    # ------------------------------------------------------------------ time advance
    def reset_feed(self, t: float) -> None:
        """Called on reconnect: invalidate every horizon that could straddle the gap."""
        self.blackout_until = t + float(self.horizons[-1])

    def advance(self, t: float) -> None:
        """Roll the 100 ms / 1 s grids forward to ``t`` and update EW impulse variances."""
        if self.n == 0 or self._next_grid < 0.0:
            return
        c = self.cfg
        if t - self._next_grid > 100 * c.grid_s:           # long gap: skip ahead, don't replay
            self._next_grid = (math.floor(t / c.grid_s)) * c.grid_s
        H = len(self.horizons)
        while self._next_grid <= t:
            g = self._next_grid
            j = mk.ring_asof(self.tick_t, self.n, c.tick_cap, g)
            if j >= 0:
                lm = self.tick_lmu[j % c.tick_cap]
                kg = self.ng % c.grid_cap
                self.grid_t[kg] = g
                self.grid_lmu[kg] = lm
                self.ng += 1
                for h in range(H):
                    jr = mk.ring_asof(self.tick_t, self.n, c.tick_cap, g - self.horizons[h])
                    if jr < 0:
                        continue
                    d = lm - self.tick_lmu[jr % c.tick_cap]
                    d2 = d * d
                    self.n_samp[h] += 1
                    k = self.n_samp[h]
                    a_f = max(self.alpha_fast, 1.0 / k)        # fast warm-up via cumulative mean
                    a_s = max(self.alpha_slow, 1.0 / k)
                    self.m2[h] += a_f * (d2 - self.m2[h])
                    self.m2_slow[h] += a_s * (d2 - self.m2_slow[h])
                if self.ng % 10 == 0:
                    ks = self.nsec % c.sec_cap
                    self.sec_t[ks] = g
                    self.sec_px[ks, 0] = self.micro
                    self.sec_px[ks, 1] = self.mid
                    self.sec_px[ks, 2] = (self.ask - self.bid) / self.mid * mk.BPS if self.mid else 0.0
                    self.sec_px[ks, 3] = mk.obi(self.bq, self.aq)
                    self.nsec += 1
            self._next_grid += c.grid_s

    # ------------------------------------------------------------------ queries
    def flow_imbalance(self, t: float, window_s: float) -> float:
        i1 = int(t / self.cfg.flow_bucket_s)
        i0 = i1 - int(round(window_s / self.cfg.flow_bucket_s))
        s = v = 0.0
        for idx in range(i0 + 1, i1 + 1):
            k = idx % self._fcap
            if self._f_stamp[k] == idx:
                s += self._f_signed[k]
                v += self._f_vol[k]
        return s / v if v > 0.0 else 0.0

    def state(self, t: float) -> OracleState:
        st = self.st
        st.t = t
        st.bid, st.ask, st.bq, st.aq = self.bid, self.ask, self.bq, self.aq
        st.mid, st.micro, st.lmu, st.lmid = self.mid, self.micro, self.lmu, self.lmid
        st.spread_bps = (self.ask - self.bid) / self.mid * mk.BPS if self.mid else 0.0
        st.obi = mk.obi(self.bq, self.aq)
        _deltas(self.tick_t, self.tick_lmu, self.n, self.cfg.tick_cap, t, self.horizons, self.lmu, st.delta, st.ok)
        sig = np.sqrt(np.maximum(self.m2, self._floor ** 2))
        st.sigma[:] = sig
        for k in range(len(self.horizons)):
            st.z[k] = st.delta[k] / sig[k] if st.ok[k] and self.n_samp[k] > 20 else 0.0
        st.vol_fast_bps = math.sqrt(max(self.m2[0], self._floor[0] ** 2)) * mk.BPS / math.sqrt(self.horizons[0])
        st.vol_slow_bps = math.sqrt(max(self.m2_slow[0], self._floor[0] ** 2)) * mk.BPS / math.sqrt(self.horizons[0])
        st.vol_ratio = st.vol_fast_bps / st.vol_slow_bps if st.vol_slow_bps > 0 else 1.0
        st.tick_vol_bps = mk.tick_realized_vol(self.tick_t, self.tick_lmid, self.n, self.cfg.tick_cap, t, 10.0) * mk.BPS
        st.flow_imb_1s = self.flow_imbalance(t, 1.0)
        st.flow_imb_3s = self.flow_imbalance(t, 3.0)
        st.last_trade_px = self.last_trade_px
        st.warm = (self.first_t >= 0.0 and (t - self.first_t) >= self.cfg.warmup_s and self.n_samp[-1] > 50
                   and t >= self.blackout_until)
        return st
