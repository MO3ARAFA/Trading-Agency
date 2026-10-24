import pytest

from quant_agency.omega_governance import GovConfig, OmegaCEO, OState, SleeveBook


def _ceo(tmp_path, **kw):
    return OmegaCEO(GovConfig(kill_file=str(tmp_path / "KILL"), review_every_s=0.0, **kw))


def test_sleeve_book_accounting():
    b = SleeveBook("s", 40.0)
    b.open(1, 5.0, 0.1)
    assert b.cash == 35.0 and b.equity == 40.0
    b.mark(1, 4.0)
    assert b.equity == 39.0
    pnl = b.close(1, 4.5, 0.05)
    assert pnl == pytest.approx(-0.5) and b.cash == 39.5 and b.round_trips == 1 and b.wins == 0
    b.failed_tx(0.02)
    assert b.equity == pytest.approx(39.48) and b.fees == pytest.approx(0.17)
    assert not b.can_open(100.0)


def test_hourly_drawdown_quarantines_only_that_sleeve(tmp_path):
    ceo = _ceo(tmp_path)
    mm, bs = ceo.books["meme_momentum"], ceo.books["breakout_scalp"]
    mm.open(1, 5.0, 0.0)
    bs.open(2, 5.0, 0.0)
    ceo.review(0.0)
    mm.mark(1, 0.5)                                       # -4.5: not yet
    assert ceo.review(10.0) == []
    mm.mark(1, -0.1)                                      # -5.1 within the hour
    ev = ceo.review(20.0)
    assert [e.kind for e in ev] == ["QUARANTINE"] and mm.state == OState.QUARANTINED
    assert ceo.to_flatten == ["meme_momentum"] and bs.state == OState.NORMAL and ceo.size_mult("breakout_scalp") == 1.0
    assert ceo.size_mult("meme_momentum") == 0.0 and not mm.can_open(1.0)
    mm.close(1, 0.0, 0.0)
    ev = ceo.review(20.0 + 1800.0)
    assert ev[0].kind == "PROBATION" and ceo.size_mult("meme_momentum") == 0.5
    mm.open(3, 3.0, 0.0)
    mm.mark(3, 0.4)                                       # -2.6 >= half the limit during probation
    ev = ceo.review(1900.0)
    assert ev[0].kind == "QUARANTINE" and mm.until - 1900.0 == pytest.approx(3600.0)   # second quarantine lasts twice as long


def test_probation_restores_after_clean_hour(tmp_path):
    ceo = _ceo(tmp_path)
    b = ceo.books["social_sentiment"]
    b.state, b.since = OState.PROBATION, 0.0
    ceo.review(10.0)
    assert b.state == OState.PROBATION
    assert ceo.review(3601.0)[0].kind == "RESTORE" and b.state == OState.NORMAL


def test_drawdown_window_is_rolling(tmp_path):
    ceo = _ceo(tmp_path)
    b = ceo.books["meme_momentum"]
    b.open(1, 10.0, 0.0)
    ceo.review(0.0)
    b.mark(1, 7.0)
    ceo.review(1800.0)                                    # -3 in the first half hour
    b.mark(1, 5.5)
    assert ceo.review(4000.0) == []                       # the old peak (10) has left the hour; from 7 to 5.5 is -1.5


def test_account_kill_and_kill_file(tmp_path):
    ceo = _ceo(tmp_path)
    for i, b in enumerate(ceo.books.values()):
        b.open(i, 10.0, 0.0)
        b.mark(i, 3.0)                                    # -21 total
    ev = ceo.review(1.0)
    assert ceo.halted and {e.kind for e in ev} == {"HALT"} and all(b.state == OState.HALTED for b in ceo.books.values())
    assert sorted(ceo.to_flatten) == sorted(ceo.books)
    ceo2 = _ceo(tmp_path)
    (tmp_path / "KILL").write_text("")
    assert ceo2.review(0.0) and ceo2.halted and "kill" in ceo2.halt_reason


def test_fill_rate_cap(tmp_path):
    ceo = _ceo(tmp_path, max_fills_per_hour=1000)
    for i in range(1000):
        ceo.note_fill(i * 1.0)
    assert not ceo.fill_budget_ok(1000.0)
    assert ceo.fill_budget_ok(3600.0 + 0.5)               # the first fill left the window


def test_snapshot_round_trip(tmp_path):
    ceo = _ceo(tmp_path)
    b = ceo.books["meme_momentum"]
    b.open(7, 4.0, 0.1)
    b.state, b.n_quarantines = OState.PROBATION, 2
    snap = ceo.snapshot()
    c2 = _ceo(tmp_path)
    c2.restore(snap)
    b2 = c2.books["meme_momentum"]
    assert b2.cash == b.cash and b2.open_cost == {7: 4.0} and b2.state == OState.PROBATION and b2.n_quarantines == 2
