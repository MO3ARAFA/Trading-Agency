"""Numerical kernels: micro-price, ring-buffer as-of search, Hayashi-Yoshida lead-lag, Kalman beta.

Everything on the hot path is numba nopython. Time is float64 seconds (any monotonic origin),
prices are natural logs unless the name says otherwise. Ring buffers are logical-index rings:
``n`` is the total number of writes, element ``k`` lives at ``k % cap`` and only the last
``cap`` elements are valid.
"""
from __future__ import annotations

import numpy as np
from numba import njit

BPS = 1e4


# ----------------------------------------------------------------------------- micro-price
@njit(cache=True)
def micro_price(bid, ask, bq, aq):
    """Stoikov volume-weighted micro-price: I*Pa + (1-I)*Pb with I = Qb/(Qb+Qa).

    A heavy bid (large I) pulls the fair price toward the ask, because the ask is the side
    likely to be consumed next.
    """
    tot = bq + aq
    if tot <= 0.0:
        return 0.5 * (bid + ask)
    return (ask * bq + bid * aq) / tot


@njit(cache=True)
def obi(bq, aq):
    """Order-book imbalance in [-1, 1]; >0 means bid-heavy."""
    tot = bq + aq
    if tot <= 0.0:
        return 0.0
    return (bq - aq) / tot


# ----------------------------------------------------------------------------- ring buffers
@njit(cache=True)
def ring_asof(t, n, cap, tq):
    """Logical index of the last element with t <= tq, or -1 if none is available."""
    lo = n - cap
    if lo < 0:
        lo = 0
    hi = n - 1
    if hi < lo:
        return -1
    if t[lo % cap] > tq:
        return -1
    while lo < hi:
        mid = (lo + hi + 1) >> 1
        if t[mid % cap] <= tq:
            lo = mid
        else:
            hi = mid - 1
    return lo


@njit(cache=True)
def ring_window(t, v, n, cap, t0, t1):
    """Contiguous copies of (t, v) for t0 < t <= t1, plus the as-of value at t0 prepended.

    The prepended point (time t0, last value known at t0) anchors the first increment so
    the window covers its whole span. Returns (tt, vv) – possibly empty.
    """
    j1 = ring_asof(t, n, cap, t1)
    if j1 < 0:
        return np.empty(0), np.empty(0)
    j0 = ring_asof(t, n, cap, t0)
    start = j0 + 1 if j0 >= 0 else max(0, n - cap)
    cnt = j1 - start + 1
    if cnt < 0:
        cnt = 0
    extra = 1 if j0 >= 0 else 0
    tt = np.empty(cnt + extra)
    vv = np.empty(cnt + extra)
    if extra == 1:
        tt[0] = t0
        vv[0] = v[j0 % cap]
    for k in range(cnt):
        tt[extra + k] = t[(start + k) % cap]
        vv[extra + k] = v[(start + k) % cap]
    return tt, vv


# ----------------------------------------------------------------------------- Hayashi-Yoshida
@njit(cache=True, nogil=True)
def hy_cov(tx, x, ty, y, shift):
    """Hayashi-Yoshida covariance of increments of x and y, with y's clock moved by -shift.

    shift > 0 pairs x increments at time s with y increments at time s+shift, i.e. y LAGS x
    by ``shift`` seconds. No synchronisation grid is needed, so there is no Epps bias from
    previous-tick interpolation. O(n+m).
    """
    nx = tx.shape[0]
    ny = ty.shape[0]
    if nx < 2 or ny < 2:
        return 0.0
    i = 0
    j = 0
    acc = 0.0
    while i < nx - 1 and j < ny - 1:
        a0 = tx[i]
        a1 = tx[i + 1]
        b0 = ty[j] - shift
        b1 = ty[j + 1] - shift
        lo = a0 if a0 > b0 else b0
        hi = a1 if a1 < b1 else b1
        if lo < hi:
            acc += (x[i + 1] - x[i]) * (y[j + 1] - y[j])
        if a1 <= b1:
            i += 1
        else:
            j += 1
    return acc


@njit(cache=True, nogil=True)
def realized_var(x):
    acc = 0.0
    for i in range(x.shape[0] - 1):
        d = x[i + 1] - x[i]
        acc += d * d
    return acc


@njit(cache=True, nogil=True)
def hy_leadlag(tx, x, ty, y, lags):
    """HY covariance and correlation across a grid of lags.

    Returns (cov[L], corr[L], rv_x, rv_y). corr = cov / sqrt(rv_x rv_y).
    """
    L = lags.shape[0]
    cov = np.zeros(L)
    corr = np.zeros(L)
    rvx = realized_var(x)
    rvy = realized_var(y)
    den = np.sqrt(rvx * rvy)
    for k in range(L):
        c = hy_cov(tx, x, ty, y, lags[k])
        cov[k] = c
        corr[k] = c / den if den > 0.0 else 0.0
    return cov, corr, rvx, rvy


@njit(cache=True, nogil=True)
def leadlag_summary(corr, lags):
    """Peak lag, peak corr, contemporaneous corr, and response half-decay span.

    ``decay`` is how many seconds past the peak the correlation stays above half its peak –
    a proxy for how long the market takes to finish repricing.
    """
    L = corr.shape[0]
    kmax = 0
    best = -1e18
    k0 = 0
    zmin = 1e18
    for k in range(L):
        if corr[k] > best:
            best = corr[k]
            kmax = k
        if abs(lags[k]) < zmin:
            zmin = abs(lags[k])
            k0 = k
    decay = 0.0
    if best > 0.0:
        k = kmax
        while k + 1 < L and corr[k + 1] >= 0.5 * best:
            k += 1
        decay = lags[k] - lags[kmax]
    return lags[kmax], best, corr[k0], decay


# ----------------------------------------------------------------------------- Kalman beta
@njit(cache=True)
def kalman_beta_step(beta, P, x, y, R, q):
    """Scalar Kalman update of a random-walk regression coefficient, vectorised over markets.

    State: beta_t = beta_{t-1} + w, w~N(0, q)   Obs: y = beta*x + v, v~N(0, R).
    Arrays are updated in place. Entries with x == 0 or R <= 0 are skipped.
    """
    for i in range(beta.shape[0]):
        if x[i] == 0.0 or R[i] <= 0.0 or not np.isfinite(y[i]):
            continue
        Pp = P[i] + q
        S = x[i] * x[i] * Pp + R[i]
        K = Pp * x[i] / S
        beta[i] = beta[i] + K * (y[i] - beta[i] * x[i])
        P[i] = (1.0 - K * x[i]) * Pp


@njit(cache=True)
def ew_update(mean, var, x, alpha):
    """In-place EW mean/variance update (West); returns new (mean, var)."""
    d = x - mean
    mean = mean + alpha * d
    var = (1.0 - alpha) * (var + alpha * d * d)
    return mean, var


# ----------------------------------------------------------------------------- tick vol
@njit(cache=True)
def tick_realized_vol(t, v, n, cap, tq, window):
    """sqrt(sum of squared tick returns over (tq-window, tq]) / sqrt(window): per-sqrt-second vol."""
    j1 = ring_asof(t, n, cap, tq)
    if j1 < 1:
        return 0.0
    lo = n - cap
    if lo < 0:
        lo = 0
    acc = 0.0
    k = j1
    while k > lo and t[k % cap] > tq - window:
        d = v[k % cap] - v[(k - 1) % cap]
        acc += d * d
        k -= 1
    return np.sqrt(acc / window)
