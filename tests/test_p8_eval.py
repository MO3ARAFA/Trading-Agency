import numpy as np
import pytest

from quant_agency import p8_eval as ev


def _row(tape, sid, xvar, bps, cents, imp, model="strict", floor=True, venue="polymarket", outcome="filled", usd=0.0):
    return {"venue": venue, "variant": f"B/{xvar}", "model": model, "floor_ok": floor, "outcome": outcome, "xvar": xvar, "sid": sid, "net_bps": bps,
            "net_cents": cents, "imp": imp, "net_usd": usd}


def _res(entries):
    rows = []
    for sid, (cb, bb, imp) in enumerate(entries):
        rows.append(_row("t", sid, "trail", cb, cb / 100, imp))
        rows.append(_row("t", sid, "fixed0.7", bb, bb / 100, imp))
    return [{"tape": "t", "rows": rows}]


def test_cluster_se_collapses_entries_sharing_an_impulse():
    x = np.array([10.0, 10.0, -10.0, -10.0])
    _, se_indep, _ = ev.cluster_stats(x, [1, 2, 3, 4])
    _, se_clus, _ = ev.cluster_stats(x, [1, 1, 2, 2])
    assert se_clus > se_indep                                  # perfectly correlated pairs carry half the information


def test_paired_uses_only_floor_passed_filled_entries_of_the_requested_model():
    res = _res([(100, 50, "a"), (200, 100, "b")])
    res[0]["rows"].append(_row("t", 99, "trail", 999, 9, "c", floor=False))             # floor-failed: excluded
    res[0]["rows"].append(_row("t", 98, "trail", 999, 9, "d", model="trades"))          # other model: excluded
    res[0]["rows"].append(_row("t", 97, "trail", 999, 9, "e", venue="hyperliquid"))     # other venue: excluded
    res[0]["rows"].append(_row("t", 96, "trail", 0, 0, "f", outcome="no_fill"))          # unfilled: excluded
    recs = ev.paired(res, "strict")
    assert len(recs) == 2 and {r["key"] for r in recs} == {("t", 0), ("t", 1)}


def test_analyse_paired_difference_and_one_sided_p():
    rng = np.random.default_rng(0)
    entries = [(float(500 + rng.normal(0, 100)), float(100 + rng.normal(0, 100)), i) for i in range(60)]
    a = ev.analyse(ev.paired(_res(entries), "strict"))
    assert a["n"] == 60 and a["trail"]["t"] > ev.T_ADJ and a["diff"]["mean"] == pytest.approx(400, abs=60) and a["diff"]["p1"] < 1e-6
    assert a["diff"]["lo"] < a["diff"]["mean"] < a["diff"]["hi"]


def test_thresholds_are_the_preregistered_ones():
    assert (ev.T_ONE_SIDED, ev.T_RAW, ev.T_ADJ, ev.N_TARGET) == (1.645, 2.0, 2.63, 70)
    assert (ev.CANDIDATE, ev.BASELINE) == ("trail", "fixed0.7")


def test_stop_counter_counts_only_the_candidate_strict_floor_passed_polymarket_fills():
    from tests.test_sleeves_and_exits import _ag
    ag, hc, sl = _ag()
    base = {"model": "strict", "floor_ok": True, "gate_ok": True, "outcome": "filled", "venue": "polymarket", "variant": "B/fixed0.7", "imp": 1, "account": False, "t_end": 1.0, "sid": 1}
    class _At:  # minimal attempt stub: not an account attempt
        account = False
    for r in (base, dict(base, model="trades"), dict(base, floor_ok=False), dict(base, venue="hyperliquid"), dict(base, outcome="no_fill"), dict(base, variant="B/trail"), dict(base, gate_ok=False), dict(base)):
        hc._on_result(_At(), dict(r))
    assert hc.n_floor_fills == 2                                       # only fixed0.7 / strict / floor-passed / gate-passed / filled / Polymarket


def test_regime_estimator_scales_and_classifies():
    from quant_agency.regime_check import classify, parkinson_bps_per_sqrt_s
    flat = [[0, "80000", "80004", "79996", "80000"]] * 20                 # 1 bp high-low per minute
    wide = [[0, "80000", "80040", "79960", "80000"]] * 20                 # 10 bp high-low per minute
    a, b = parkinson_bps_per_sqrt_s(flat), parkinson_bps_per_sqrt_s(wide)
    assert b == pytest.approx(10 * a, rel=1e-6) and classify(a) == "quiet" and classify(b) != "quiet" and classify(float("nan")) == "unknown"


def test_inspect_run_renders_without_a_summary(tmp_path):
    import json
    from quant_agency.inspect_run import render
    (tmp_path / "sleeve_events.jsonl").write_text(json.dumps({"sleeve": "polymarket_b", "kind": "SLEEVE_TIGHTEN", "from_state": "NORMAL", "to_state": "TIGHTENED", "reason": "x"}) + "\n{broken")
    (tmp_path / "trades.jsonl").write_text(json.dumps({"sleeve": "polymarket_b", "market": "pm:x", "side": 1, "entry_px": 0.4, "exit_px": 0.5, "exit_reason": "passive_fill", "net_pnl_usd": 1.0}) + "\n")
    out = render(str(tmp_path))
    assert "SLEEVE_TIGHTEN" in out and "polymarket_b" in out and "still going" in out
