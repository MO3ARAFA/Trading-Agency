"""Tier 1 – Lead-lag & micro-gap quant engine.

Per market i, relative to the BTC reference:
  * **lead-lag**: Hayashi-Yoshida cross-correlation over a lag grid (no grid synchronisation, so no
    Epps bias) -> peak lag l*, peak corr rho, contemporaneous corr, response decay.
  * **dynamic beta**: window-OLS init at calibration, then a scalar Kalman filter on
    y = Δmid_i(t)  vs  x = ΔBTC(t - l*) over h_cal windows.
  * **idiosyncratic noise**: EW variance of the lag-aligned residual at every impulse horizon.

Instantaneous fair-price gap (log, signed, + means market should rise):

    Gap_{i,t} = beta_i * Δ(BTC micro-price over h) - Δ(market-i mid over h)

where the BTC micro-price already embeds the order-book imbalance (Stoikov). A signal fires when
BTC makes a high-Z impulse, the gap is significant vs the market's own noise, the market has not yet
repriced (<= max_repriced of the expected move) and the impulse is still inside the market's
historical lag window.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
from numba import njit

from . import mathkit as mk
from .btc_oracle import BtcOracle, OracleState
from .config import HunterConfig
from .market_watchers import (ASK, BID, BQ, AQ, LAST_T, LMID, MEAN_DT, MID, NTICK, MarketBook,
                              log_mid_asof, ring_window_lmid)

BPS = mk.BPS


@dataclass
class Signal:
    sid: int
    t: float
    t_recv: float
    market: str
    idx: int
    side: int                  # +1 buy / -1 sell
    horizon_s: float
    btc_delta_bps: float
    btc_z: float
    btc_obi: float
    btc_flow_1s: float
    vol_ratio: float
    beta: float
    rho: float
    lag_s: float
    window_s: float
    age_s: float
    fair_bps: float
    actual_bps: float
    gap_bps: float             # signed: + => market should go up
    gap_z: float
    sigma_res_bps: float
    spread_bps: float
    bid: float
    ask: float
    bq: float
    aq: float
    mid: float
    impulse_id: int
    t_decide: float = 0.0
    # filled by downstream agents
    decision: Optional[object] = None

    def as_dict(self):
        d = {k: getattr(self, k) for k in self.__dataclass_fields__ if k != "decision"}
        return d


# --------------------------------------------------------------------------------- kernels
@njit(cache=True, nogil=True)
def _ols_windows(tx, x, ty, y, t0, t1, step, lag, h):
    """Through-origin OLS sums of  y(s)-y(s-h)  on  x(s-lag)-x(s-lag-h)  for s on a grid in [t0+h+lag, t1]."""
    sxx = sxy = syy = 0.0
    cnt = 0
    s = t0 + h + lag + 1e-9
    while s <= t1:
        qx1 = s - lag
        qx0 = qx1 - h
        a1 = np.searchsorted(tx, qx1, side="right") - 1
        a0 = np.searchsorted(tx, qx0, side="right") - 1
        b1 = np.searchsorted(ty, s, side="right") - 1
        b0 = np.searchsorted(ty, s - h, side="right") - 1
        if a0 >= 0 and b0 >= 0 and a1 >= 0 and b1 >= 0:
            dx = x[a1] - x[a0]
            dy = y[b1] - y[b0]
            sxx += dx * dx
            sxy += dx * dy
            syy += dy * dy
            cnt += 1
        s += step
    return sxx, sxy, syy, cnt


@njit(cache=True, nogil=True)
def _calibrate_one(tx, x, ty, y, lags, t0, t1, h_cal, beta_prior, ridge):
    cov, corr, rvx, rvy = mk.hy_leadlag(tx, x, ty, y, lags)
    lag, rho, rho0, decay = mk.leadlag_summary(corr, lags)
    lag_use = lag if lag > 0.0 else 0.0
    sxx, sxy, syy, cnt = _ols_windows(tx, x, ty, y, t0, t1, 1.0, lag_use, h_cal)
    beta = beta_prior
    rvar = 0.0
    rho_ols = 0.0
    tstat = 0.0
    if cnt > 10 and sxx > 0.0:
        beta = (sxy + ridge * beta_prior * sxx) / (sxx * (1.0 + ridge))
        rvar = max((syy - 2.0 * beta * sxy + beta * beta * sxx) / cnt, 0.0)
        if syy > 0.0:
            rho_ols = sxy / np.sqrt(sxx * syy)
        if rvar > 0.0:
            tstat = (sxy / sxx) / np.sqrt(rvar / sxx)
    # rho_hy is not bounded by 1 (HY covariance / tick-level RV); clip for display, gate on the OLS correlation
    return lag, min(max(rho, -1.0), 1.0), min(max(rho0, -1.0), 1.0), decay, beta, rvar, cnt, rho_ols, tstat


@njit(cache=True)
def _kalman_obs(rt, rb, ra, n, cap, state, btc_t, btc_lmid, btc_n, btc_cap, t, lag, h, calibrated, beta, xs, ys):
    M = beta.shape[0]
    for i in range(1, M):
        xs[i] = 0.0
        ys[i] = np.nan
        if not calibrated[i]:
            continue
        lm1 = state[i, LMID]
        lm0 = log_mid_asof(rt, rb, ra, n, cap, i, t - h)
        j1 = mk.ring_asof(btc_t, btc_n, btc_cap, t - lag[i])
        j0 = mk.ring_asof(btc_t, btc_n, btc_cap, t - lag[i] - h)
        if j1 < 0 or j0 < 0 or not np.isfinite(lm0):
            continue
        xs[i] = btc_lmid[j1 % btc_cap] - btc_lmid[j0 % btc_cap]
        ys[i] = lm1 - lm0


@njit(cache=True)
def _resid_update(rt, rb, ra, n, cap, state, btc_t, btc_lmid, btc_n, btc_cap, t, lag, horizons, beta, alpha, res_m2, res_n):
    M = beta.shape[0]
    for i in range(1, M):
        if state[i, NTICK] < 10:
            continue
        lm1 = state[i, LMID]
        for k in range(horizons.shape[0]):
            h = horizons[k]
            lm0 = log_mid_asof(rt, rb, ra, n, cap, i, t - h)
            j1 = mk.ring_asof(btc_t, btc_n, btc_cap, t - lag[i])
            j0 = mk.ring_asof(btc_t, btc_n, btc_cap, t - lag[i] - h)
            if j1 < 0 or j0 < 0 or not np.isfinite(lm0):
                continue
            x = btc_lmid[j1 % btc_cap] - btc_lmid[j0 % btc_cap]
            r = (lm1 - lm0) - beta[i] * x
            res_n[i, k] += 1
            a = max(alpha, 1.0 / res_n[i, k])
            res_m2[i, k] += a * (r * r - res_m2[i, k])


@njit(cache=True)
def _scan(rt, rb, ra, n, cap, state, t, h, hk, dbtc, dirn, beta, rho, tstat, tmin, lag, decay, calibrated, tradable,
          cooldown_until, res_m2, res_n, min_gap_bps, gap_z_thr, rho_min, max_repriced, window_mult,
          window_base, window_min, window_max, max_spread_bps, min_rate, age, out_idx):
    M = beta.shape[0]
    cnt = 0
    for i in range(1, M):
        if not (calibrated[i] and tradable[i]):
            continue
        if cooldown_until[i] > t or state[i, NTICK] < 30.0 or rho[i] < rho_min or beta[i] <= 0.0 or tstat[i] < tmin:
            continue
        if 1.0 / state[i, MEAN_DT] < min_rate:
            continue
        mid = state[i, MID]
        if (state[i, ASK] - state[i, BID]) / mid * 1e4 > max_spread_bps:
            continue
        win = window_mult * max(lag[i], 0.0) + decay[i] + window_base
        win = min(max(win, window_min), window_max)
        if age > win:
            continue
        lm0 = log_mid_asof(rt, rb, ra, n, cap, i, t - h)
        if not np.isfinite(lm0):
            continue
        actual = state[i, LMID] - lm0
        fair = beta[i] * dbtc
        gap = fair - actual
        if gap * dirn <= 0.0 or abs(gap) * 1e4 < min_gap_bps:
            continue
        if res_n[i, hk] < 30:
            continue
        sig = math.sqrt(max(res_m2[i, hk], 1e-10))
        if abs(gap) / sig < gap_z_thr:
            continue
        if actual * dirn > 0.0 and actual / fair > max_repriced:
            continue
        out_idx[cnt] = i
        cnt += 1
    return cnt


# --------------------------------------------------------------------------------- model
class LeadLagModel:
    def __init__(self, book: MarketBook, oracle: BtcOracle, cfg: HunterConfig):
        self.book, self.oracle, self.cfg = book, oracle, cfg
        M = book.M
        H = len(oracle.horizons)
        a, b, s = cfg.lag_grid_s
        self.lags = np.arange(round(a / s), round(b / s) + 1) * s
        self.beta = np.array([m.beta_prior for m in book.metas], dtype=np.float64)
        self.P = np.full(M, 0.25)
        self.R = np.full(M, 1e-8)
        self.lag = np.zeros(M)
        self.rho = np.zeros(M)
        self.rho0 = np.zeros(M)
        self.rho_hy = np.zeros(M)
        self.tstat = np.zeros(M)
        self.decay = np.zeros(M)
        self.calibrated = np.zeros(M, dtype=np.bool_)
        self.n_calib = np.zeros(M, dtype=np.int64)
        self.tradable = np.array([m.tradable for m in book.metas], dtype=np.bool_)
        self.tradable[0] = False
        self.res_m2 = np.full((M, H), 1e-8)
        self.res_n = np.zeros((M, H), dtype=np.int64)
        self._xs = np.zeros(M)
        self._ys = np.full(M, np.nan)
        self.alpha_res = 1.0 - 0.5 ** (cfg.resid_period_s / cfg.resid_halflife_s)
        self.last_calib = -1e18
        self.last_kalman = -1e18
        self.last_resid = -1e18
        self.calib_ms = 0.0

    # --- calibration split in three so the heavy part can run in a worker thread (nogil kernels)
    def calibrate_inputs(self, t: float):
        c = self.cfg
        t0 = t - c.calib_window_s
        o = self.oracle
        tx, x = mk.ring_window(o.tick_t, o.tick_lmid, o.n, o.cfg.tick_cap, t0, t)
        items = []
        if tx.shape[0] < 100:
            return t0, t, tx, x, items
        bk = self.book
        for i in range(1, bk.M):
            if bk.n[i] < c.min_calib_ticks:
                continue
            ty, y = ring_window_lmid(bk.rt[i], bk.rb[i], bk.ra[i], int(bk.n[i]), bk.cap, t0, t)
            if ty.shape[0] >= c.min_calib_ticks:
                items.append((i, ty, y))
        return t0, t, tx, x, items

    def calibrate_compute(self, packed):
        t0, t1, tx, x, items = packed
        out = []
        for i, ty, y in items:
            out.append((i,) + _calibrate_one(tx, x, ty, y, self.lags, t0, t1, self.cfg.h_cal_s,
                                             float(self.book.metas[i].beta_prior), 0.1))
        return out

    def calibrate_apply(self, t: float, results) -> int:
        c = self.cfg
        k = 0
        for i, lag, rho_hy, rho0, decay, beta, rvar, cnt, rho_ols, tstat in results:
            if cnt < 20:
                continue
            first = not self.calibrated[i]
            self.lag[i], self.rho[i], self.rho0[i], self.decay[i] = lag, rho_ols, rho0, decay
            self.rho_hy[i] = rho_hy
            self.tstat[i] = tstat
            beta = min(max(beta, 0.0), c.beta_max)
            if first:
                self.beta[i] = beta
                self.P[i] = 0.05
            else:
                self.beta[i] = 0.7 * self.beta[i] + 0.3 * beta
            self.R[i] = max(rvar, 1e-10) * (c.h_cal_s / c.kalman_period_s)
            self.calibrated[i] = True
            self.n_calib[i] += 1
            k += 1
        self.last_calib = t
        return k

    def calibrate(self, t: float) -> int:
        return self.calibrate_apply(t, self.calibrate_compute(self.calibrate_inputs(t)))

    # --- online updates
    def update_online(self, t: float) -> None:
        c, bk, o = self.cfg, self.book, self.oracle
        if t - self.last_resid >= c.resid_period_s:
            _resid_update(bk.rt, bk.rb, bk.ra, bk.n, bk.cap, bk.state, o.tick_t, o.tick_lmid, o.n,
                          o.cfg.tick_cap, t, self.lag, o.horizons, self.beta, self.alpha_res,
                          self.res_m2, self.res_n)
            self.last_resid = t
        if t - self.last_kalman >= c.kalman_period_s and self.calibrated.any():
            _kalman_obs(bk.rt, bk.rb, bk.ra, bk.n, bk.cap, bk.state, o.tick_t, o.tick_lmid, o.n,
                        o.cfg.tick_cap, t, self.lag, c.h_cal_s, self.calibrated, self.beta, self._xs, self._ys)
            ok = np.isfinite(self._ys) & (self._xs != 0.0)
            if ok.any():
                # EW residual variance of the observation noise, then Kalman step
                r = self._ys - self.beta * self._xs
                idx = np.where(ok)[0]
                self.R[idx] = 0.98 * self.R[idx] + 0.02 * (r[idx] ** 2) * (c.h_cal_s / c.kalman_period_s)
                ys = np.where(ok, self._ys, 0.0)
                mk.kalman_beta_step(self.beta, self.P, self._xs, ys, self.R, c.kalman_q * 1e-2)
                np.clip(self.beta, 0.0, c.beta_max, out=self.beta)
            self.last_kalman = t

    def table(self) -> List[dict]:
        rows = []
        for i, m in enumerate(self.book.metas):
            if i == 0:
                continue
            rows.append({"market": m.id, "beta": float(self.beta[i]), "rho": float(self.rho[i]), "rho_hy": float(self.rho_hy[i]), "tstat": float(self.tstat[i]),
                         "rho0": float(self.rho0[i]), "lag_s": float(self.lag[i]),
                         "decay_s": float(self.decay[i]), "calibrated": bool(self.calibrated[i]),
                         "sigma_res_3s_bps": float(math.sqrt(self.res_m2[i, 1]) * BPS)})
        return rows


# --------------------------------------------------------------------------------- hunter
class InefficiencyHunter:
    DIRECTIVE_KEYS = {"z_thr", "z_release", "min_impulse_bps", "min_gap_bps", "gap_z_thr", "rho_min",
                      "max_repriced", "window_mult", "cooldown_s", "beta_tmin"}

    def __init__(self, book: MarketBook, oracle: BtcOracle, cfg: Optional[HunterConfig] = None):
        self.cfg = cfg or HunterConfig()
        self.book, self.oracle = book, oracle
        self.model = LeadLagModel(book, oracle, self.cfg)
        self.cooldown_until = np.zeros(book.M)
        self._out = np.zeros(book.M, dtype=np.int64)
        self.active = False
        self.dir = 0
        self.onset_t = 0.0
        self.impulse_id = 0
        self.hk = 0
        self._sid = 0
        self.last_scan = -1e18
        self.n_scans = 0
        self.n_signals = 0
        self.n_impulses = 0
        self.per_market_signals: Dict[str, int] = {}
        self.dirty = False
        self.applied_directives: List[dict] = []
        self.executor = None                    # set to a ThreadPoolExecutor for off-loop calibration
        self._calib_future = None
        self._calib_t = 0.0
        self.calib_errors: List[str] = []

    # ------------------------------------------------------------------ directives from the CEO
    def apply_directive(self, d: dict) -> dict:
        before = {}
        for k, v in d.items():
            if k in self.DIRECTIVE_KEYS:
                before[k] = getattr(self.cfg, k)
                setattr(self.cfg, k, v)
        if before:
            self.applied_directives.append({"before": before, "after": {k: d[k] for k in before}})
        return before

    # ------------------------------------------------------------------ main loop hooks
    def maintain(self, t: float) -> None:
        """Calibration cadence + online filters; cheap, call once per scan."""
        o = self.oracle
        o.advance(t)
        m = self.model
        if self._calib_future is not None and self._calib_future.done():
            fut, self._calib_future = self._calib_future, None
            try:
                m.calibrate_apply(self._calib_t, fut.result())
            except Exception as e:                       # never let calibration kill the hunter
                self.calib_errors.append(repr(e))
        if o.first_t >= 0.0 and (t - o.first_t) >= self.cfg.first_calib_after_s \
                and t - m.last_calib >= self.cfg.calib_interval_s and self._calib_future is None:
            if self.executor is None:
                m.calibrate(t)
            else:
                m.last_calib = t
                self._calib_t = t
                self._calib_future = self.executor.submit(m.calibrate_compute, m.calibrate_inputs(t))
        m.update_online(t)

    def scan(self, t: float, t_recv: Optional[float] = None) -> List[Signal]:
        c = self.cfg
        if t - self.last_scan < c.scan_min_interval_s:
            return []
        self.last_scan = t
        self.n_scans += 1
        self.dirty = False
        o = self.oracle
        self.maintain(t)
        st = o.state(t)
        if not st.warm or t - o.last_t > 2.0:
            self.active = False
            return []
        bi = st.best_horizon(c.min_impulse_bps)
        # impulse state machine with hysteresis
        if self.active:
            zref = st.z[self.hk]
            if np.sign(zref) != self.dir or abs(zref) < c.z_release:
                self.active = False
        if not self.active:
            if bi >= 0 and abs(st.z[bi]) >= c.z_thr:
                self.active, self.dir = True, int(np.sign(st.z[bi]))
                self.onset_t, self.hk = t, bi
                self.impulse_id += 1
                self.n_impulses += 1
            else:
                return []
        elif bi >= 0 and abs(st.z[bi]) > abs(st.z[self.hk]) and np.sign(st.z[bi]) == self.dir:
            self.hk = bi
        hk = self.hk
        h = float(o.horizons[hk])
        if not st.ok[hk]:
            return []
        m = self.model
        age = t - self.onset_t
        n = _scan(self.book.rt, self.book.rb, self.book.ra, self.book.n, self.book.cap, self.book.state, t, h, hk,
                  float(st.delta[hk]), float(self.dir), m.beta, m.rho, m.tstat, c.beta_tmin, m.lag, m.decay, m.calibrated, m.tradable,
                  self.cooldown_until, m.res_m2, m.res_n, c.min_gap_bps, c.gap_z_thr, c.rho_min, c.max_repriced,
                  c.window_mult, c.window_base_s, c.window_min_s, c.window_max_s, c.max_spread_bps,
                  c.min_tick_rate, age, self._out)
        sigs: List[Signal] = []
        bk = self.book
        for k in range(n):
            i = int(self._out[k])
            s = bk.state[i]
            lm0 = bk.mid_asof(i, t - h)
            actual = float(s[LMID] - math.log(lm0))
            fair = float(m.beta[i] * st.delta[hk])
            gap = fair - actual
            win = min(max(c.window_mult * max(m.lag[i], 0.0) + m.decay[i] + c.window_base_s, c.window_min_s), c.window_max_s)
            self._sid += 1
            sig = Signal(
                sid=self._sid, t=t, t_recv=t_recv if t_recv is not None else t, market=bk.ids[i], idx=i,
                side=self.dir, horizon_s=h, btc_delta_bps=float(st.delta[hk] * BPS), btc_z=float(st.z[hk]),
                btc_obi=float(st.obi), btc_flow_1s=float(st.flow_imb_1s), vol_ratio=float(st.vol_ratio),
                beta=float(m.beta[i]), rho=float(m.rho[i]), lag_s=float(m.lag[i]), window_s=float(win),
                age_s=float(age), fair_bps=fair * BPS, actual_bps=actual * BPS, gap_bps=gap * BPS,
                gap_z=abs(gap) / math.sqrt(max(m.res_m2[i, hk], 1e-10)),
                sigma_res_bps=math.sqrt(max(m.res_m2[i, hk], 1e-10)) * BPS,
                spread_bps=float((s[ASK] - s[BID]) / s[MID] * BPS), bid=float(s[BID]), ask=float(s[ASK]),
                bq=float(s[BQ]), aq=float(s[AQ]), mid=float(s[MID]), impulse_id=self.impulse_id)
            self.cooldown_until[i] = t + c.cooldown_s
            self.n_signals += 1
            self.per_market_signals[sig.market] = self.per_market_signals.get(sig.market, 0) + 1
            sigs.append(sig)
        return sigs
