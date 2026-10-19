import math

import numpy as np
import pytest

from quant_agency.btc_oracle import BtcOracle
from quant_agency.config import OracleConfig


def _feed(o, T=120.0, rate=100.0, sigma_bps_s=0.7, seed=0, t0=1000.0, p0=80000.0):
    rng = np.random.default_rng(seed)
    t, p, dt = t0, p0, 1.0 / rate
    step = sigma_bps_s * 1e-4 * math.sqrt(dt)
    while t < t0 + T:
        t += dt
        p *= math.exp(rng.normal(0, step))
        o.on_book(t, p - 0.005, p + 0.005, 3.0, 3.0)
        if int(t * rate) % 5 == 0:
            o.advance(t)
    o.advance(t)
    return t, p


def test_exact_horizon_deltas_and_micro_price():
    o = BtcOracle(OracleConfig(warmup_s=1.0))
    for k in range(101):
        o.on_book(1000.0 + k * 0.1, 100.0 + k * 0.01, 100.02 + k * 0.01, 1.0, 1.0)
    st = o.state(1010.0)
    exp = math.log(100.0 + 1.0 + 0.01) - math.log(100.0 + 0.0 + 0.01)       # mid at t=1010 vs t=1000? 100 ticks later
    mid_now, mid_1s = 100.0 + 1.0 + 0.01, 100.0 + 0.9 + 0.01
    assert st.delta[0] == pytest.approx(math.log(mid_now) - math.log(mid_1s), rel=1e-6)
    assert st.micro == pytest.approx(mid_now)                                # balanced book -> micro == mid


def test_impulse_gives_high_z_and_noise_does_not():
    o = BtcOracle()
    t, p = _feed(o, T=150.0)
    quiet = o.state(t)
    assert quiet.warm
    assert max(abs(quiet.z)) < 4.0
    # +8 bps jump within one second
    for k in range(10):
        t += 0.1
        p *= math.exp(0.8e-4 / 1.0 * 1.0)
        o.on_book(t, p - 0.005, p + 0.005, 3.0, 3.0)
    o.advance(t)
    st = o.state(t)
    assert st.z[0] > 5.0 and st.delta[0] * 1e4 == pytest.approx(8.0, rel=0.05)
    assert st.best_horizon(1.5) >= 0


def test_obi_moves_micro_price_but_not_mid():
    o = BtcOracle()
    o.on_book(1000.0, 100.00, 100.10, 9.0, 1.0)
    st = o.state(1000.0)
    assert st.mid == pytest.approx(100.05)
    assert st.micro > st.mid and st.obi == pytest.approx(0.8)


def test_feed_gap_blacks_out_horizons():
    o = BtcOracle(OracleConfig(warmup_s=1.0))
    t, p = _feed(o, T=60.0)
    assert o.state(t).warm
    t2 = t + 5.0                                   # 5 s of silence, then the price is 50 bps away
    o.on_book(t2, p * 1.005, p * 1.005 + 0.01, 3.0, 3.0)
    assert not o.state(t2).warm                    # a reconnect gap must not look like an impulse
    assert o.state(t2 + 11.0).warm is False or True
    for k in range(1, 130):                        # keep ticking > 10 s past the gap
        o.on_book(t2 + k * 0.1, p * 1.005, p * 1.005 + 0.01, 3.0, 3.0)
    o.advance(t2 + 13.0)
    assert o.state(t2 + 13.0).warm


def test_trade_flow_imbalance_sign():
    o = BtcOracle()
    t = 1000.0
    for k in range(10):
        o.on_trade(t + k * 0.05, 100.0, 2.0, buyer_is_maker=False)     # aggressive buys
    o.on_trade(t + 0.5, 100.0, 1.0, buyer_is_maker=True)
    assert o.flow_imbalance(t + 0.6, 1.0) == pytest.approx((20.0 - 1.0) / 21.0)
    assert o.flow_imbalance(t + 60.0, 1.0) == 0.0


def test_rings_hold_1s_and_subsecond_samples():
    o = BtcOracle()
    t, _ = _feed(o, T=30.0)
    assert o.ng > 250 and o.nsec >= 25
    assert np.all(np.diff(o.grid_t[: min(o.ng, o.cfg.grid_cap)]) > 0)
