import numpy as np
import pytest

from quant_agency import p9_eval as ev
from quant_agency.p9_regime import power_at, required_n


def test_required_n_reproduces_the_preregistered_value_and_is_monotone():
    n = required_n(155.68424518681516, 1225.7906089348487, 0.7746478873239436)
    assert n == 386                                                   # the value locked in docs/PREREG_PHASE9
    assert power_at(155.68424518681516, 1225.7906089348487, n, 0.7746478873239436) >= 0.80
    assert power_at(155.68424518681516, 1225.7906089348487, n - 1, 0.7746478873239436) < 0.80
    assert required_n(300.0, 1225.79, 0.77) < n < required_n(100.0, 1225.79, 0.77)       # larger effect -> fewer entries
    assert required_n(-5.0, 1000.0, 0.8) is None and required_n(0.0, 1000.0, 0.8) is None


def test_power_is_alpha_at_zero_effect_and_halves_with_a_halved_effect():
    assert power_at(0.0, 1200.0, 400, 0.77) == pytest.approx(0.05, abs=0.01)
    assert power_at(78.0, 1226.0, 386, 0.77) == pytest.approx(0.34, abs=0.03)


def test_primary_test_rejects_only_when_t_exceeds_the_one_sided_student_critical_value():
    rng = np.random.default_rng(3)
    x = rng.normal(0, 1000, 200)
    a = ev.primary_test(x - x.mean(), list(range(200)))
    assert not a["reject"] and a["t_crit"] == pytest.approx(1.653, abs=0.01)
    b = ev.primary_test(x - x.mean() + 400.0, list(range(200)))
    assert b["reject"] and b["p1"] < 0.05


def test_p9_eval_refuses_validation_and_foreign_tapes():
    for bad in ("tapes/p9v_seg1.npz", "tapes/p8_tape_1.npz", "tapes/other.npz"):
        with pytest.raises(SystemExit):
            ev.evaluate([bad])
