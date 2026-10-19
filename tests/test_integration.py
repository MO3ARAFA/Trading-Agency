"""End-to-end: synthetic lead-lag market -> oracle -> watchers -> hunter -> CFO -> execution -> CEO."""
import argparse

import numpy as np
import pytest

from quant_agency.agency import Agency
from quant_agency.config import AgencyConfig
from quant_agency.run_live import run_replay
from quant_agency.sim import make_sim


def run_sim(fee=0.0, duration=300.0, seed=7, latency=None, review=20.0, n_alts=20, record=False):
    metas, ev, truth = make_sim(n_alts=n_alts, duration_s=duration, seed=seed)
    cfg = AgencyConfig()
    cfg.cfo.fee_taker_bps = cfg.cfo.fee_maker_bps = fee
    cfg.ceo.review_interval_s = review
    ag = Agency(metas, cfg, t0=ev[0][0])
    if record:
        ag.start_recording()
    if latency is not None:                       # reality differs from what the CFO models
        ag.engine.cfg.latency_s = latency
        ag.cfo.markouts.lat = latency
    for (t, i, b, a, bq, aq) in ev:
        ag.on_quote(i, t, b, a, bq, aq)
        ag.step(t)
    return ag, truth


@pytest.fixture(scope="module")
def zero_fee():
    return run_sim(fee=0.0)


def test_pipeline_detects_gaps_trades_and_gaps_close(zero_fee):
    ag, _ = zero_fee
    assert ag.hunter.n_signals > 30 and ag.cfo.n_approved > 10 and len(ag.engine.closed) > 5
    tb = ag.cfo.markouts.table(now=ag.last_t)
    assert tb[5.0]["n"] > 30 and tb[5.0]["gross"] > 3.0 and tb[5.0]["hit_gross"] > 0.7      # gaps do close
    assert tb[1.0]["gross"] < tb[5.0]["gross"]                                              # ...with a lag (markout curve rises)
    assert sum(t.net_pnl_usd for t in ag.engine.closed) > 0
    assert not ag.hunter.calib_errors


def test_every_approved_trade_had_positive_predicted_edge_and_a_payload(zero_fee):
    ag, _ = zero_fee
    assert ag.engine.payload_log
    for p in ag.engine.payload_log:
        assert p["expected_net_bps"] > 0 and p["qty"] > 0 and p["notional"] >= 10.0
        assert p["order_type"] in ("LIMIT", "LIMIT_MAKER") and p["time_stop_s"] <= 30.0
    assert ag.decide_lat.summary()["n"] == len(ag.engine.payload_log)


def test_costs_gate_trading():
    free, _ = run_sim(fee=0.0, duration=240)
    costly, _ = run_sim(fee=7.5, duration=240)
    assert costly.cfo.n_approved < free.cfo.n_approved
    assert costly.cfo.reasons["net_edge_below_hurdle"] > free.cfo.reasons["net_edge_below_hurdle"]
    for t in costly.engine.closed:
        assert t.predicted_net_bps > 0


def test_unmodelled_latency_is_caught_by_the_ceo():
    """CFO models 150 ms; orders really land 2 s late so the gap has closed: predicted edge is not realised."""
    ag, _ = run_sim(fee=0.5, duration=300, latency=2.0)
    kinds = [iv.kind for iv in ag.ceo.interventions]
    assert "CFO_EDGE_RECALIBRATION" in kinds
    assert ag.cfo.cfg.edge_credit < 1.0
    assert ag.ceo.state.value != "NORMAL" or ag.cfo.cfg.safety_hurdle_bps > 1.0
    assert all(iv.reason and iv.before is not None and iv.after is not None for iv in ag.ceo.interventions)
    # and the intervention was warranted: approved cohort realised less than it predicted
    appr = ag.cfo.markouts.agg(ag.cfo.markouts.select(ag.last_t, 1e9, h=5.0, approved_only=True))
    assert appr["n"] > 5 and appr["net"] < appr["pred"]


def test_runs_are_deterministic():
    a1, _ = run_sim(fee=0.0, duration=150, seed=3)
    a2, _ = run_sim(fee=0.0, duration=150, seed=3)
    s1 = [(s.market, round(s.t, 6), round(s.gap_bps, 6)) for s in a1.signals]
    s2 = [(s.market, round(s.t, 6), round(s.gap_bps, 6)) for s in a2.signals]
    assert s1 == s2 and len(s1) > 5
    assert a1.cfo.equity == a2.cfo.equity


def test_recorded_tape_replays_identically(tmp_path):
    orig, _ = run_sim(fee=0.0, duration=200, seed=5, record=True)
    path = str(tmp_path / "tape.npz")
    orig.save_tape(path)
    cfg = AgencyConfig()
    cfg.cfo.fee_taker_bps = cfg.cfo.fee_maker_bps = 0.0
    cfg.ceo.review_interval_s = 20.0
    ag, _, _ = run_replay(argparse.Namespace(replay=path, status_every=1e9), cfg, str(tmp_path / "run"))
    assert ag.hunter.n_signals > 0
    assert abs(ag.hunter.n_signals - orig.hunter.n_signals) <= max(2, int(0.05 * orig.hunter.n_signals))
