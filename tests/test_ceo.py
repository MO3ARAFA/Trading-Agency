import json
import itertools

import pytest

from quant_agency.agency import Agency
from quant_agency.ceo_agent import CEOState, Verdict, next_state
from quant_agency.config import AgencyConfig
from quant_agency.execution_engine import TradeResult
from tests.conftest import make_book

NOW = 1000.0
_sid = itertools.count(1)


def mk_agency(tmp_path=None):
    book = make_book(n_alt=3)
    cfg = AgencyConfig()
    cfg.ceo.review_interval_s = 1.0
    return Agency(book.metas, cfg, out_dir=str(tmp_path) if tmp_path else None, t0=0.0, wall0=1.7e9)


_t0 = itertools.count()


def add_rows(ag, market, n, gross, net, cohort="rejected_edge", approved=False, pred=0.0, gross1=None, imp_base=0, t_base=None):
    """Resolved markout rows at t+1s and t+5s (what the CFO's tracker would have produced)."""
    t0 = (NOW - 100.0) if t_base is None else t_base
    for k in range(n):
        sid = next(_sid)
        for h in (1.0, 5.0):
            ag.cfo.markouts.rows.append({"market": market, "cohort": cohort, "side": 1, "h": h, "t0": t0 + k * 0.01, "gap": 5.0,
                                         "pred": pred, "gross": (gross1 if (h == 1.0 and gross1 is not None) else gross),
                                         "net": net, "closure": 0.5, "approved": approved, "sid": sid, "imp": imp_base + k})


def add_trades(ag, n, net_bps, t_exit=NOW - 5.0, market="ALT1USDT"):
    for k in range(n):
        ag.engine.closed.append(TradeResult(oid=k, sid=k, market=market, side=1, mode="taker", t_entry=t_exit - 5, t_exit=t_exit,
                                            entry_px=100.0, exit_px=100.0, qty=1.0, notional=100.0, gross_bps=net_bps + 15,
                                            fees_usd=0.15, net_pnl_usd=net_bps / 1e4 * 100.0, net_bps=net_bps, R=net_bps / 5.0,
                                            exit_reason="time_stop", hold_s=5.0, entry_slip_bps=0.1, exit_slip_bps=0.1,
                                            spread_bps_entry=2.0, predicted_net_bps=3.0, gap_bps=10.0, predicted_slip_bps=0.2))


def kinds(ivs):
    return [iv.kind for iv in ivs]


# ---------------------------------------------------------------- pure state machine
@pytest.mark.parametrize("state,verdict,streak,halt_elapsed,expected", [
    (CEOState.NORMAL, Verdict.POOR, 0, False, CEOState.TIGHTENED),
    (CEOState.TIGHTENED, Verdict.POOR, 0, False, CEOState.DEFENSIVE),
    (CEOState.DEFENSIVE, Verdict.POOR, 0, False, CEOState.HALTED),
    (CEOState.NORMAL, Verdict.OK, 0, False, CEOState.NORMAL),
    (CEOState.TIGHTENED, Verdict.OK, 0, False, CEOState.TIGHTENED),
    (CEOState.TIGHTENED, Verdict.GOOD, 1, False, CEOState.TIGHTENED),     # hysteresis: one good review is not enough
    (CEOState.TIGHTENED, Verdict.GOOD, 2, False, CEOState.NORMAL),
    (CEOState.DEFENSIVE, Verdict.GOOD, 2, False, CEOState.TIGHTENED),
    (CEOState.NORMAL, Verdict.GOOD, 5, False, CEOState.NORMAL),
    (CEOState.HALTED, Verdict.GOOD, 9, False, CEOState.HALTED),           # verdicts are ignored while stood down
    (CEOState.HALTED, Verdict.POOR, 0, False, CEOState.HALTED),
    (CEOState.HALTED, Verdict.OK, 0, True, CEOState.DEFENSIVE),           # pause elapsed -> probation
])
def test_state_transition_table(state, verdict, streak, halt_elapsed, expected):
    assert next_state(state, verdict, streak, halt_elapsed) == expected


# ---------------------------------------------------------------- per-market quarantine
def test_ceo_quarantines_toxic_market_and_keeps_good_ones(tmp_path):
    ag = mk_agency(tmp_path)
    add_rows(ag, "ALT1USDT", 8, gross=-1.5, net=-8.0, gross1=-1.0, imp_base=0)       # toxic: negative from t+1s on
    add_rows(ag, "ALT2USDT", 8, gross=6.0, net=2.0, gross1=3.0, imp_base=100)
    ivs = ag.ceo.review(NOW)
    q = [iv for iv in ivs if iv.kind == "QUARANTINE_MARKET"]
    assert [iv.target for iv in q] == ["ALT1USDT"]
    assert "toxic_flow" in q[0].reason
    assert ag.cfo.is_blacklisted("ALT1USDT", NOW + 1) and not ag.cfo.is_blacklisted("ALT2USDT", NOW + 1)
    assert not ag.cfo.is_blacklisted("ALT1USDT", NOW + ag.ceo.cfg.quarantine_s + 1)      # released after the term
    # repeat offence -> longer quarantine
    t2 = NOW + 1500.0                                          # first term long expired
    add_rows(ag, "ALT1USDT", 8, gross=-1.5, net=-8.0, gross1=-1.0, imp_base=500, t_base=t2 - 50)
    ivs2 = ag.ceo.review(t2)
    assert [iv for iv in ivs2 if iv.kind == "QUARANTINE_MARKET"]
    assert ag.cfo.blacklist["ALT1USDT"][0] - t2 == pytest.approx(2 * ag.ceo.cfg.quarantine_s)


def test_quarantined_market_still_gets_shadow_markouts_in_kpis():
    ag = mk_agency()
    add_rows(ag, "ALT1USDT", 8, gross=-1.5, net=-8.0, gross1=-1.0)
    ag.ceo.review(NOW)
    add_rows(ag, "ALT1USDT", 4, gross=5.0, net=1.0, cohort="rejected_other", t_base=NOW + 5)   # shadow rows keep flowing
    k = ag.ceo.kpis(NOW + 20)
    assert k["markets"]["ALT1USDT"]["n"] == 4            # only post-quarantine evidence counts toward a re-trial


def test_no_quarantine_below_min_sample():
    ag = mk_agency()
    add_rows(ag, "ALT1USDT", 3, gross=-3.0, net=-10.0, gross1=-2.0)
    assert "QUARANTINE_MARKET" not in kinds(ag.ceo.review(NOW))


# ---------------------------------------------------------------- escalation ladder
def test_full_escalation_ladder_and_probation():
    ag = mk_agency()
    cfo, ceo = ag.cfo, ag.ceo
    add_trades(ag, 8, net_bps=-4.0, t_exit=NOW + 500)
    h0 = cfo.cfg.safety_hurdle_bps
    ivs = ceo.review(NOW + 1)                                                     # NORMAL -> TIGHTENED
    assert ceo.state == CEOState.TIGHTENED and "TIGHTEN_CFO" in kinds(ivs)
    assert cfo.cfg.safety_hurdle_bps == pytest.approx(h0 + ceo.cfg.hurdle_step_bps) and cfo.cfg.size_mult == pytest.approx(0.8)
    ivs = ceo.review(NOW + 31)                                                    # -> DEFENSIVE (maker-only)
    assert ceo.state == CEOState.DEFENSIVE and "DEFENSIVE_MAKER_ONLY" in kinds(ivs)
    assert cfo.cfg.mode_policy == "maker_only" and cfo.cfg.size_mult == pytest.approx(0.4)
    ivs = ceo.review(NOW + 61)                                                    # -> HALTED
    assert ceo.state == CEOState.HALTED and "HALT_TRADING" in kinds(ivs) and cfo.halted
    assert ceo.review(NOW + 91) == [] and cfo.halted                              # still standing down
    ivs = ceo.review(NOW + 61 + ceo.cfg.halt_pause_s + 1)                         # pause elapsed -> probation
    assert ceo.state == CEOState.DEFENSIVE and "RESUME_PROBATION" in kinds(ivs)
    assert not cfo.halted and cfo.cfg.mode_policy == "maker_only" and cfo.cfg.size_mult <= 0.4


def test_stale_pre_intervention_losses_do_not_escalate_again():
    ag = mk_agency()
    ceo = ag.ceo
    add_trades(ag, 8, net_bps=-4.0, t_exit=NOW)                                   # losses BEFORE the first intervention
    assert "TIGHTEN_CFO" in kinds(ceo.review(NOW + 1))
    assert ceo.state == CEOState.TIGHTENED
    assert ceo.review(NOW + 31) == [] and ceo.state == CEOState.TIGHTENED          # no fresh evidence -> no further escalation
    add_trades(ag, 8, net_bps=-4.0, t_exit=NOW + 40)                              # fresh losses under the new policy
    assert "DEFENSIVE_MAKER_ONLY" in kinds(ceo.review(NOW + 61)) and ceo.state == CEOState.DEFENSIVE


def test_probation_is_judged_on_fresh_evidence_only():
    ag = mk_agency()
    ceo = ag.ceo
    ceo.state = CEOState.HALTED
    ceo.halt_since = NOW - 1000
    ag.cfo.trip("ceo_halt", NOW - 1000)
    add_trades(ag, 8, net_bps=-4.0, t_exit=NOW - 900)                             # the losses that caused the halt
    assert "RESUME_PROBATION" in kinds(ceo.review(NOW))
    assert not ag.cfo.halted
    assert ceo.review(NOW + 30) == [] and ceo.state == CEOState.DEFENSIVE         # old losses no longer count


def test_deescalation_needs_two_good_reviews():
    ag = mk_agency()
    cfo, ceo = ag.cfo, ag.ceo
    ceo.state = CEOState.TIGHTENED
    cfo.apply_directive({"safety_hurdle_bps": 2.0, "size_mult": 0.6})
    add_trades(ag, 8, net_bps=+3.0, t_exit=NOW + 500)
    assert ceo.review(NOW + 1) == [] and ceo.state == CEOState.TIGHTENED          # one good review: nothing changes
    ivs = ceo.review(NOW + 31)
    assert ceo.state == CEOState.NORMAL and "RELAX_CFO" in kinds(ivs)
    assert cfo.cfg.safety_hurdle_bps == pytest.approx(1.5) and cfo.cfg.size_mult == pytest.approx(0.75)
    assert cfo.cfg.mode_policy == "auto"


def test_statistically_insignificant_losses_do_not_escalate():
    ag = mk_agency()
    for k in range(8):                                                            # mean -1.1 bps but huge variance
        add_trades(ag, 1, net_bps=(-30.0 if k % 2 else 28.0), t_exit=NOW + 500)
    ag.engine.closed[0].net_bps = -2.2
    ivs = ag.ceo.review(NOW + 1)
    assert ag.ceo.state == CEOState.NORMAL and "TIGHTEN_CFO" not in kinds(ivs)


def test_breaker_trip_is_acknowledged_and_halts_state():
    ag = mk_agency()
    ag.cfo.trip("portfolio_drawdown", NOW)
    ivs = ag.ceo.review(NOW + 1)
    assert ag.ceo.state == CEOState.HALTED and "BREAKER_ACK" in kinds(ivs)


def test_drawdown_alone_turns_verdict_poor():
    ag = mk_agency()
    ag.cfo.equity = ag.cfo.peak * (1 - 0.6 * ag.cfo.cfg.portfolio_dd_frac)
    ivs = ag.ceo.review(NOW)
    assert ag.ceo.state == CEOState.TIGHTENED and "TIGHTEN_CFO" in kinds(ivs)


# ---------------------------------------------------------------- CEO audits the CFO's numbers
def test_cfo_edge_overstatement_triggers_credit_haircut():
    ag = mk_agency()
    add_rows(ag, "ALT1USDT", 15, gross=1.0, net=-2.0, cohort="approved", approved=True, pred=3.0)
    ivs = ag.ceo.review(NOW)
    assert "CFO_EDGE_RECALIBRATION" in kinds(ivs)
    assert ag.cfo.cfg.edge_credit == pytest.approx(0.85)
    iv = [i for i in ivs if i.kind == "CFO_EDGE_RECALIBRATION"][0]
    assert "predicted net +3.00bps but realised -2.00bps" in iv.reason
    assert iv.before == {"edge_credit": 1.0}


def test_realised_slippage_above_model_scales_slippage_coeffs():
    ag = mk_agency()
    add_trades(ag, 8, net_bps=2.0, t_exit=NOW + 500)
    for t in ag.engine.closed:
        t.entry_slip_bps, t.predicted_slip_bps = 3.0, 0.3
    ivs = ag.ceo.review(NOW + 1)
    assert "CFO_SLIPPAGE_RECALIBRATION" in kinds(ivs)
    assert ag.cfo.cfg.slip_depth_coeff == pytest.approx(0.625) and ag.cfo.cfg.slip_vol_coeff == pytest.approx(0.3125)


def test_fee_bleed_switches_taker_to_maker_only():
    ag = mk_agency()
    ag.ceo.state = CEOState.TIGHTENED
    add_rows(ag, "ALT1USDT", 20, gross=3.0, net=-8.0, gross1=1.0)                 # gaps close (+3) but costs eat them
    add_trades(ag, 8, net_bps=-4.0, t_exit=NOW + 500)
    ivs = ag.ceo.review(NOW + 1)
    iv = [i for i in ivs if i.kind == "DEFENSIVE_MAKER_ONLY"]
    assert iv and "fee bleed" in iv[0].reason and ag.cfo.cfg.mode_policy == "maker_only"


def test_missed_opportunity_loosens_hurdle_when_rejected_signals_were_profitable():
    ag = mk_agency()
    ag.cfo.cfg.safety_hurdle_bps = 2.0
    add_rows(ag, "ALT1USDT", 15, gross=6.0, net=3.0, cohort="rejected_edge")
    ivs = ag.ceo.review(NOW)
    assert "LOOSEN_HURDLE" in kinds(ivs) and ag.cfo.cfg.safety_hurdle_bps == pytest.approx(1.5)


# ---------------------------------------------------------------- hunter retuning
def test_false_gap_rate_raises_impulse_threshold():
    ag = mk_agency()
    z0 = ag.hunter.cfg.z_thr
    add_rows(ag, "ALT1USDT", 12, gross=-1.0, net=-9.0, imp_base=0)
    add_rows(ag, "ALT2USDT", 8, gross=2.0, net=-5.0, imp_base=50)
    ivs = ag.ceo.review(NOW)
    assert "RETUNE_IMPULSE" in kinds(ivs) and ag.hunter.cfg.z_thr == pytest.approx(z0 + ag.ceo.cfg.z_step)


def test_high_vol_regime_raises_z_and_shortens_lag_window():
    ag = mk_agency()
    ag.oracle.m2[:] = (3e-4) ** 2
    ag.oracle.m2_slow[:] = (1e-4) ** 2                                            # fast vol 3x slow vol
    ivs = ag.ceo.review(NOW)
    assert "RETUNE_IMPULSE" in kinds(ivs)
    assert ag.hunter.cfg.z_thr == pytest.approx(3.25)
    assert ag.hunter.cfg.window_mult == pytest.approx(2.0 / 1.6)
    ag.oracle.m2[:] = (0.5e-4) ** 2                                               # calm regime: relax
    ag.ceo.review(NOW + 30)
    assert ag.hunter.cfg.z_thr == pytest.approx(2.75) and ag.hunter.cfg.window_mult > 2.0


# ---------------------------------------------------------------- audit trail
def test_audit_trail_is_complete_and_machine_readable(tmp_path):
    ag = mk_agency(tmp_path)
    add_rows(ag, "ALT1USDT", 8, gross=-1.5, net=-8.0, gross1=-1.0)
    add_trades(ag, 8, net_bps=-4.0, t_exit=NOW + 500)
    ivs = ag.ceo.review(NOW + 1)
    ag.close()
    lines = [json.loads(l) for l in open(tmp_path / "ceo_audit.jsonl")]
    assert len(lines) == len(ivs) == len(ag.ceo.interventions) >= 2
    for rec in lines:
        assert {"iid", "t", "kind", "target", "state_before", "state_after", "reason", "evidence", "before", "after"} <= rec.keys()
        assert rec["reason"]
    tight = [r for r in lines if r["kind"] == "TIGHTEN_CFO"][0]
    assert tight["state_before"] == "NORMAL" and tight["state_after"] == "TIGHTENED"
    assert tight["before"]["hurdle"] < tight["after"]["hurdle"]
    assert ag.ceo.reviews[-1]["verdict"] == "POOR"


def test_review_cadence_is_respected():
    ag = mk_agency()
    ag.ceo.cfg.review_interval_s = 30.0
    assert ag.ceo.maybe_review(100.0) == []             # first call only arms the timer
    n = len(ag.ceo.reviews)
    ag.ceo.maybe_review(110.0)
    assert len(ag.ceo.reviews) == n
    ag.ceo.maybe_review(131.0)
    assert len(ag.ceo.reviews) == n + 1


def test_ceo_flattens_when_it_halts_trading():
    ag = mk_agency()
    flat = []
    ag.engine.flatten_all = lambda now, why="": flat.append(why)
    ag.ceo.state = CEOState.DEFENSIVE
    add_trades(ag, 8, net_bps=-4.0, t_exit=NOW + 500)
    ag.ceo.review(NOW + 1)
    assert ag.cfo.halted and flat == ["breaker_flatten"]


def test_tuning_requires_fresh_evidence_it_does_not_ratchet_on_stale_signals():
    ag = mk_agency()
    z0 = ag.hunter.cfg.z_thr
    add_rows(ag, "ALT1USDT", 14, gross=-1.0, net=-9.0)
    ag.ceo.review(NOW)
    z1 = ag.hunter.cfg.z_thr
    assert z1 == pytest.approx(z0 + ag.ceo.cfg.z_step)
    for k in range(1, 5):                                      # same 14 signals, four more reviews: nothing new to learn
        ag.ceo.review(NOW + 30 * k)
    assert ag.hunter.cfg.z_thr == pytest.approx(z1)
    add_rows(ag, "ALT1USDT", 14, gross=-1.0, net=-9.0, imp_base=100, t_base=NOW + 125)   # fresh evidence arrives
    ag.ceo.review(NOW + 150)
    assert ag.hunter.cfg.z_thr == pytest.approx(z1 + ag.ceo.cfg.z_step)


def test_edge_haircut_does_not_compound_on_the_same_evidence():
    ag = mk_agency()
    add_rows(ag, "ALT1USDT", 15, gross=1.0, net=-2.0, cohort="approved", approved=True, pred=3.0)
    ag.ceo.review(NOW)
    c1 = ag.cfo.cfg.edge_credit
    ag.ceo.review(NOW + 30); ag.ceo.review(NOW + 60)
    assert ag.cfo.cfg.edge_credit == pytest.approx(c1)
