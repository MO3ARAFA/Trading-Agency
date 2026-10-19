import numpy as np
import pytest

from quant_agency import mathkit as mk


def test_micro_price_pulls_toward_thin_side():
    bid, ask = 100.00, 100.10
    # bid-heavy book -> ask is the side about to be consumed -> micro above mid
    assert mk.micro_price(bid, ask, 9.0, 1.0) == pytest.approx(100.09)
    assert mk.micro_price(bid, ask, 1.0, 9.0) == pytest.approx(100.01)
    assert mk.micro_price(bid, ask, 5.0, 5.0) == pytest.approx(100.05)
    assert mk.micro_price(bid, ask, 0.0, 0.0) == pytest.approx(100.05)


def test_obi_bounds_and_sign():
    assert mk.obi(9.0, 1.0) == pytest.approx(0.8)
    assert mk.obi(1.0, 9.0) == pytest.approx(-0.8)
    assert mk.obi(0.0, 0.0) == 0.0


def test_ring_asof_with_wraparound():
    cap = 8
    t = np.zeros(cap)
    n = 0
    for k in range(20):                              # writes 0..19, only 12..19 valid
        t[n % cap] = float(k)
        n += 1
    assert mk.ring_asof(t, n, cap, 19.5) == 19
    assert mk.ring_asof(t, n, cap, 15.0) == 15
    assert mk.ring_asof(t, n, cap, 12.0) == 12
    assert mk.ring_asof(t, n, cap, 11.9) == -1       # overwritten history is unavailable, not wrong
    assert mk.ring_asof(t, 0, cap, 5.0) == -1


def test_ring_window_is_anchored_at_t0():
    cap = 16
    t = np.arange(10.0)
    v = t * 2.0
    tt, vv = mk.ring_window(np.pad(t, (0, 6)), np.pad(v, (0, 6)), 10, cap, 3.5, 7.0)
    assert tt[0] == 3.5 and vv[0] == pytest.approx(6.0)      # value known at 3.5 is the t=3 tick
    assert tt[-1] == 7.0
    assert np.all(np.diff(tt) > 0)


def _async_pair(lag, beta, seed=1, T=600.0):
    rng = np.random.default_rng(seed)
    tx = np.sort(rng.uniform(0, T, 20000))
    x = np.cumsum(rng.normal(0, 1e-4, tx.size))
    ty = np.sort(rng.uniform(0, T, 5000))
    y = beta * np.interp(ty - lag, tx, x) + rng.normal(0, 2e-5, ty.size)
    return tx, x, ty, y


def test_hy_recovers_lag_and_beta_on_asynchronous_ticks():
    tx, x, ty, y = _async_pair(lag=0.5, beta=1.3)
    lags = np.arange(-5, 31) * 0.1
    cov, corr, rvx, rvy = mk.hy_leadlag(tx, x, ty, y, lags)
    lag, peak, rho0, decay = mk.leadlag_summary(corr, lags)
    assert lag == pytest.approx(0.5, abs=0.11)
    assert peak > 0.8
    assert abs(rho0) < 0.2                                   # contemporaneous corr is ~0: pure lead-lag
    k = int(np.argmin(np.abs(lags - 0.5)))
    assert cov[k] / rvx == pytest.approx(1.3, rel=0.15)


def test_hy_is_antisymmetric_in_lead_direction():
    tx, x, ty, y = _async_pair(lag=0.8, beta=1.0, seed=2)
    lags = np.arange(-30, 31) * 0.1
    _, c_xy, _, _ = mk.hy_leadlag(tx, x, ty, y, lags)       # y lags x -> peak at positive lag
    _, c_yx, _, _ = mk.hy_leadlag(ty, y, tx, x, lags)       # swapped: x "lags" y -> peak at negative lag
    assert lags[np.argmax(c_xy)] > 0 > lags[np.argmax(c_yx)]


def test_hy_independent_series_has_no_peak():
    rng = np.random.default_rng(3)
    tx = np.sort(rng.uniform(0, 600, 15000))
    x = np.cumsum(rng.normal(0, 1e-4, tx.size))
    ty = np.sort(rng.uniform(0, 600, 4000))
    y = np.cumsum(rng.normal(0, 1e-4, ty.size))
    lags = np.arange(-5, 31) * 0.1
    _, corr, _, _ = mk.hy_leadlag(tx, x, ty, y, lags)
    assert np.max(np.abs(corr)) < 0.25


def test_hy_cov_of_series_with_itself_is_realized_variance():
    t = np.sort(np.random.default_rng(4).uniform(0, 100, 500))
    x = np.cumsum(np.random.default_rng(5).normal(0, 1e-3, t.size))
    assert mk.hy_cov(t, x, t, x, 0.0) == pytest.approx(mk.realized_var(x), rel=1e-9)


def test_kalman_beta_converges_and_tracks_regime_change():
    rng = np.random.default_rng(6)
    beta = np.array([0.2])
    P = np.array([1.0])
    R = np.array([(2e-4) ** 2])
    for k in range(600):
        true = 1.5 if k < 300 else 0.7
        x = np.array([rng.normal(0, 5e-4)])
        y = true * x + rng.normal(0, 2e-4, 1)
        mk.kalman_beta_step(beta, P, x, y, R, 1e-5)
        if k == 299:
            assert beta[0] == pytest.approx(1.5, abs=0.15)
    assert beta[0] == pytest.approx(0.7, abs=0.2)             # random-walk state adapts to the new beta


def test_kalman_skips_degenerate_observations():
    beta, P, R = np.array([1.0]), np.array([0.1]), np.array([1e-8])
    mk.kalman_beta_step(beta, P, np.array([0.0]), np.array([1e-3]), R, 1e-5)
    mk.kalman_beta_step(beta, P, np.array([1e-4]), np.array([np.nan]), R, 1e-5)
    assert beta[0] == 1.0 and P[0] == 0.1


def test_tick_realized_vol_matches_sqrt_sum_squares():
    cap = 64
    t = np.zeros(cap); v = np.zeros(cap)
    for k in range(11):
        t[k] = k * 1.0
        v[k] = 0.001 * (-1) ** k
    out = mk.tick_realized_vol(t, v, 11, cap, 10.0, 10.0)
    assert out == pytest.approx(np.sqrt(10 * (0.002) ** 2 / 10.0), rel=1e-9)
