import numpy as np
import pytest

from quant_agency.btc_oracle import BtcOracle
from quant_agency.config import HunterConfig
from quant_agency.inefficiency_hunter import InefficiencyHunter
from quant_agency.market_watchers import MarketBook
from quant_agency.sim import make_sim


@pytest.fixture(scope="module")
def run():
    metas, ev, truth = make_sim(n_alts=14, duration_s=420, seed=21, noise_alts=3)
    book = MarketBook(metas)
    o = BtcOracle()
    h = InefficiencyHunter(book, o, HunterConfig())
    sigs = []
    for (t, i, b, a, bq, aq) in ev:
        book.on_quote(i, t, b, a, bq, aq)
        if i == 0:
            o.on_book(t, b, a, bq, aq)
            h.dirty = True
        if h.dirty:
            sigs += h.scan(t)
    return h, sigs, truth, book


def test_lead_lag_and_beta_recovery(run):
    h, _, truth, _ = run
    m = h.model
    coupled = [i for i in range(1, len(truth.ids)) if truth.beta[i] > 0]
    assert len(coupled) >= 10
    lag_err = np.abs(m.lag[coupled] - truth.lag[coupled])
    assert np.median(lag_err) < 0.11 and lag_err.max() <= 0.25
    beta_rel = np.abs(m.beta[coupled] / truth.beta[coupled] - 1.0)
    assert np.median(beta_rel) < 0.2
    assert np.all(m.rho[coupled] > 0.6)


def test_decoupled_markets_never_fire(run):
    h, sigs, truth, _ = run
    dec = {truth.ids[i] for i in range(1, len(truth.ids)) if truth.beta[i] == 0.0}
    assert dec and not any(s.market in dec for s in sigs)


def test_signals_are_directionally_consistent(run):
    _, sigs, _, _ = run
    assert len(sigs) > 20
    for s in sigs:
        assert s.side == np.sign(s.btc_delta_bps)
        assert s.gap_bps * s.side > 0                          # market must be behind the fair value
        assert abs(s.gap_bps) >= 1.0 and s.gap_z >= 1.5
        assert s.age_s <= s.window_s + 1e-9                    # impulse still inside the lag window
        assert abs(s.actual_bps) <= 0.6 * abs(s.fair_bps) + 1e-9 or s.actual_bps * s.side <= 0


def test_gaps_close_after_signal(run):
    """Mid-to-mid, 5 s after the (latency-delayed) fill, the market has moved toward fair value."""
    _, sigs, _, book = run
    gains = []
    for s in sigs:
        m0 = book.mid_asof(s.idx, s.t + 0.15)
        m5 = book.mid_asof(s.idx, s.t + 5.15)
        if np.isfinite(m0) and np.isfinite(m5):
            gains.append(s.side * (m5 / m0 - 1) * 1e4)
    assert len(gains) > 20 and np.mean(gains) > 3.0 and np.mean(np.array(gains) > 0) > 0.8


def test_cooldown_and_once_per_market_per_window(run):
    _, sigs, _, _ = run
    by = {}
    for s in sigs:
        by.setdefault(s.market, []).append(s.t)
    for ts in by.values():
        assert np.all(np.diff(sorted(ts)) >= 5.0 - 1e-9)


def test_already_repriced_market_is_not_a_signal():
    metas, ev, truth = make_sim(n_alts=4, duration_s=300, seed=5, lag_range=(0.0, 0.0), noise_alts=0)
    book = MarketBook(metas); o = BtcOracle(); h = InefficiencyHunter(book, o, HunterConfig(window_base_s=0.5))
    n = 0
    for (t, i, b, a, bq, aq) in ev:
        book.on_quote(i, t, b, a, bq, aq)
        if i == 0:
            o.on_book(t, b, a, bq, aq); h.dirty = True
        if h.dirty:
            n += len(h.scan(t))
    # zero-lag markets track BTC; the Poisson tick staleness alone yields far fewer qualifying gaps than lagged ones
    assert n < 30


def test_directive_whitelist():
    metas, _, _ = make_sim(n_alts=2, duration_s=10)
    h = InefficiencyHunter(MarketBook(metas), BtcOracle(), HunterConfig())
    before = h.apply_directive({"z_thr": 4.5, "bogus": 1, "window_mult": 1.5})
    assert before == {"z_thr": 3.0, "window_mult": 2.0} and h.cfg.z_thr == 4.5 and not hasattr(h.cfg, "bogus")


def test_dead_market_quote_is_never_a_gap():
    """A market silent for minutes must not generate signals from its frozen quote."""
    metas, ev, truth = make_sim(n_alts=6, duration_s=360, seed=9, noise_alts=0)
    dead = "ALT03USDT"
    book = MarketBook(metas); o = BtcOracle(); h = InefficiencyHunter(book, o, HunterConfig())
    idx_dead = book.index[dead]
    sigs = []
    for (t, i, b, a, bq, aq) in ev:
        if i == idx_dead and t > ev[0][0] + 200.0:        # feed for this market dies at t=200 s
            continue
        book.on_quote(i, t, b, a, bq, aq)
        if i == 0:
            o.on_book(t, b, a, bq, aq); h.dirty = True
        if h.dirty:
            sigs += h.scan(t)
    late = [s for s in sigs if s.market == dead and s.t > ev[0][0] + 200.0 + h.cfg.max_quote_age_s + 1.0]
    assert not late
    assert any(s.market != dead and s.t > ev[0][0] + 260 for s in sigs)         # the rest keep working
