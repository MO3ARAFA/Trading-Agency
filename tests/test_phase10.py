import json
import os

import numpy as np
import pytest

from quant_agency import p10_eval as ev
from quant_agency import regime_daemon as rd
from quant_agency import tape_tools as tt
from quant_agency.regime import RollingSigma60
from tests.test_sleeves_and_exits import _ag, fire, sig, Q, S0


# ------------------------------------------------------------------ the pre-impulse sigma60
def test_pre_impulse_sigma_excludes_the_triggering_impulse():
    r = RollingSigma60(keep=100)
    px = 80_000.0
    for k in range(0, 200):
        px *= 1.00001                                     # 0.1 bp / s baseline
        if k == 190:
            px *= 1.0010                                  # a 10 bp impulse in the last 10 s
        r.update(1000.0 + k + 0.5, px)
    now, pre = r.value(1199.9), r.value(1199.9 - 15.0)
    assert now > 1.0 and pre < 0.2                        # sigma_now sees the jump; sigma_pre is the baseline it broke out of
    assert r.value(1199.9 - 15.0) == pytest.approx(0.1, abs=0.02)


def test_gate_tags_every_signal_and_only_gates_the_account():
    ag, hc, sl = _ag()
    hc.bcfg.max_sigma60 = 0.50
    t = 100.0
    px = S0
    for k in range(0, 200):                               # turbulent baseline: 3 bp / s random-sign moves
        px *= 1 + (3e-4 if k % 2 else -3e-4)
        hc.on_btc_mid(t + k, px)
    for tt_ in (298.0, 299.0):
        Q(ag, 1, tt_, 100.0, 100.01)
    s = sig(gap=60.0, t=300.0, sid=77)
    tags = hc.regime_tags(300.0)
    assert tags["sigma_pre"] > 0.5 and not tags["gate_ok"]
    dec = hc.cfo_for(1).evaluate_sniper_b(s, 300.0, regime_ok=tags["gate_ok"])
    assert not dec.approved and dec.reason == "regime_gate"
    hc.on_signal(s, S0, dec)
    assert not hc.account_open                            # no account attempt ...
    assert any(a.sig.sid == 77 for a in hc.active[1])      # ... but the shadows still ran
    for at in hc.active[1]:
        at.advance(310.0)
    hc.finalize(320.0)
    rows = [r for r in hc.results if r["sid"] == 77]
    assert rows and all(r["gate_ok"] is False and r["sigma_pre"] > 0.5 for r in rows)


def test_unknown_baseline_never_passes_a_positive_gate_and_gate_off_always_passes():
    ag, hc, sl = _ag()
    hc.bcfg.max_sigma60 = 0.50
    assert hc.regime_tags(50.0)["gate_ok"] is False        # no history -> NaN -> conservative
    hc.bcfg.max_sigma60 = 0.0
    assert hc.regime_tags(50.0)["gate_ok"] is True


# ------------------------------------------------------------------ tapes
def test_rotation_and_concatenation_preserve_the_event_stream(tmp_path):
    from quant_agency.agency import Agency
    from quant_agency.market_watchers import MarketMeta
    ag = Agency([MarketMeta("BTCUSDT", "binance", "BTCUSDT", "BTC")], t0=0.0, wall0=1.8e9)
    ag.start_recording()
    stem = str(tmp_path / "x")
    for k in range(10):
        ag.on_quote(0, 1.0 + k, 80000.0 + k, 80000.01 + k, 1.0, 1.0)
        if k == 4:
            tt.rotate_tape(ag, stem, 1, {"wall0": 1.8e9})
    p2 = tt.rotate_tape(ag, stem, 2, {"wall0": 1.8e9})
    assert os.path.basename(p2) == "x_part0002.npz"
    out = str(tmp_path / "full.npz")
    assert tt.concat_tapes(sorted([tt.part_path(stem, 1), p2]), out) == 10
    z = np.load(out)
    assert np.allclose(z["b"], 80000.0 + np.arange(10)) and (np.diff(z["t"]) > 0).all()
    with pytest.raises(ValueError):
        tt.concat_tapes([p2, tt.part_path(stem, 1)], out)


# ------------------------------------------------------------------ daemon + evaluator
def test_continuous_mode_builds_the_single_process_command_and_flags_overrides_as_validation():
    a = rd.parse(["--continuous", "--n-star", "608", "--dry-run"])
    cfg, plan = rd.build(a)
    assert plan.continuous and plan.n_star == 608
    d = rd.Daemon(cfg, plan)
    argv = d._argv_continuous()
    for flag in ("--phase7", "--shadow-log", "--rotate-min", "--max-sigma60", "--stop-file", "--count-file"):
        assert flag in argv
    assert argv[argv.index("--b-exit") + 1] == "fixed0.7" and argv[argv.index("--max-sigma60") + 1] == "0.5"
    a2 = rd.parse(["--continuous", "--n-star", "608", "--max-sigma60", "0.9", "--dry-run"])
    _, plan2 = rd.build(a2)
    assert plan2.validation and "p10v" in rd.Daemon(rd.DaemonConfig(), plan2)._argv_continuous()[rd.Daemon(rd.DaemonConfig(), plan2)._argv_continuous().index("--tag") + 1]


def _write_run(tmp, name, vals, gate=True):
    d = tmp / name
    d.mkdir()
    with open(d / "b_shadow.jsonl", "w") as f:
        for k, v in enumerate(vals):
            f.write(json.dumps({"variant": "B/fixed0.7", "model": "strict", "venue": "polymarket", "floor_ok": True, "gate_ok": gate, "sigma_pre": 0.2, "sigma_now": 0.3,
                                "outcome": "filled", "net_bps": v, "imp": k // 2, "sid": k}) + "\n")
    return str(d)


def test_p10_eval_refuses_validation_runs_and_selects_the_gated_population(tmp_path):
    with pytest.raises(SystemExit):
        ev.load_rows([_write_run(tmp_path, "p10v1_x", [1.0])])
    r1 = _write_run(tmp_path, "p10r1_a", [100.0, -50.0, 300.0, 20.0])
    r2 = _write_run(tmp_path, "p10r2_b", [10.0, 10.0], gate=False)
    rows = ev.load_rows([r1, r2])
    assert len(ev.sel(rows, "strict")) == 4 and len(ev.sel(rows, "strict", gated=False)) == 6
    assert len({r["cl"] for r in rows}) == 3                                           # 2 impulses in run 1, 1 in run 2: ids restart per run, clusters do not collide
    assert ev.test(ev.sel(rows, "strict"))["n"] == 4


def test_continuous_defaults_come_from_the_preregistration_and_are_not_validation():
    spec = json.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "PREREG_PHASE10.json")))
    cfg, plan = rd.build(rd.parse(["--continuous", "--dry-run"]))
    assert plan.n_star == spec["n_star"] == 608 and plan.max_sigma60 == spec["max_sigma60"] == 0.5 and plan.cap_capture_h == 72.0 and plan.session_h == 1.5 and not plan.validation
    argv = rd.Daemon(cfg, plan)._argv_continuous()
    assert argv[argv.index("--tag") + 1].startswith("p10r") and argv[argv.index("--duration") + 1] == "5400"
