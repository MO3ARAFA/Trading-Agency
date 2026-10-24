import json
import math

import pytest

from quant_agency import complete_set_arb as csa


def _mkt(i, closed=False, yes_px=None, other=False, fees=False, accepting=True):
    m = {"question": f"Outcome {i}?", "clobTokenIds": json.dumps([f"y{i}", f"n{i}"]), "closed": closed, "acceptingOrders": accepting,
         "enableOrderBook": True, "orderMinSize": 5, "orderPriceMinTickSize": 0.01, "negRiskOther": other}
    if fees:
        m.update(feesEnabled=True, feeSchedule={"rate": 0.04, "exponent": 1})
    if yes_px is not None:
        m["outcomePrices"] = json.dumps([str(yes_px), str(1 - yes_px)])
    return m


def _event(n=3, augmented=False, **kw):
    return {"id": "e1", "slug": "s", "title": "T", "negRisk": True, "negRiskAugmented": augmented, "endDate": "2026-11-10T00:00:00Z",
            "markets": [_mkt(i, **kw) for i in range(n)]}


NOW = csa._ts("2026-10-24T00:00:00Z")


def test_fee_formula_and_edges():
    assert csa.fee_usd(10, 0.5, 0.04) == pytest.approx(10 * 0.04 * 0.25)
    assert csa.fee_usd(10, 0.5, 0.0) == 0.0
    assert csa.fee_usd(0, 0.5, 0.04) == 0.0
    assert csa.fee_usd(1, 0.2, 0.05, 2.0) == pytest.approx(0.05 * 0.16 ** 2)


def test_ladder_best_first():
    asks = [{"price": "0.60", "size": "10"}, {"price": "0.55", "size": "0"}, {"price": "0.50", "size": "3"}]
    assert csa.ladder_from_clob(asks) == [(0.50, 3.0), (0.60, 10.0)]


def test_walk_sets_depth_and_marginal_stop():
    # two legs: 0.40+0.50 = 0.90 for 10 sets, then 0.40+0.58 = 0.98 (marginal 0.02), then 0.40+0.62 > 1
    lads = [[(0.40, 100.0)], [(0.50, 10.0), (0.58, 5.0), (0.62, 50.0)]]
    f = csa.walk_sets(lads, [(0, 1), (0, 1)], 1.0, 0.005)
    assert f.sets == pytest.approx(15)
    assert f.cost == pytest.approx(10 * 0.90 + 5 * 0.98)
    assert f.net == pytest.approx(15 - f.cost)
    assert f.worst_marginal == pytest.approx(0.02)
    assert f.takes[1] == {0.50: 10.0, 0.58: 5.0}
    # a higher marginal floor stops after the first level
    assert csa.walk_sets(lads, [(0, 1), (0, 1)], 1.0, 0.05).sets == pytest.approx(10)


def test_walk_sets_caps_bind_exactly():
    lads = [[(0.40, 100.0)], [(0.50, 100.0)]]
    f = csa.walk_sets(lads, [(0, 1), (0, 1)], 1.0, 0.0, max_capital=9.0)
    assert f.capital == pytest.approx(9.0) and f.sets == pytest.approx(10.0)
    assert csa.walk_sets(lads, [(0, 1), (0, 1)], 1.0, 0.0, max_sets=7).sets == pytest.approx(7)


def test_walk_sets_fees_reduce_margin():
    lads = [[(0.49, 100.0)], [(0.49, 100.0)]]
    assert csa.walk_sets(lads, [(0, 1), (0, 1)], 1.0, 0.005).sets > 0
    # 2 x 0.05 x 0.49 x 0.51 = 0.025 > 0.02 gross
    assert csa.walk_sets(lads, [(0.05, 1), (0.05, 1)], 1.0, 0.0).sets == 0
    assert csa.walk_sets([[(0.5, 1)], []], [(0, 1), (0, 1)], 1.0, 0.0).sets == 0


def test_parse_event_exhaustiveness():
    ev = csa.parse_event(_event())
    assert ev.exhaustive_buyable and len(ev.legs) == 3
    assert not csa.parse_event(_event(augmented=True)).exhaustive_buyable
    e = _event()
    e["markets"][1]["negRiskOther"] = True
    assert not csa.parse_event(e).exhaustive_buyable
    # a leg that is live but not accepting orders -> incomplete
    e = _event()
    e["markets"][2]["acceptingOrders"] = False
    assert not csa.parse_event(e).exhaustive_buyable
    # an eliminated candidate already settled NO keeps the event complete; an unresolved closed one does not
    e = _event(n=4)
    e["markets"][3] = _mkt(3, closed=True, yes_px=0)
    assert csa.parse_event(e).exhaustive_buyable
    e["markets"][3] = _mkt(3, closed=True)
    assert not csa.parse_event(e).exhaustive_buyable
    assert csa.parse_event({**_event(), "negRisk": False}) is None
    assert csa.parse_event({**_event(), "closed": True}) is None
    assert csa.parse_event(_event(fees=True)).legs[0].fee_rate == 0.04


def test_evaluate_yes_and_no_sets():
    ev = csa.parse_event(_event())
    cfg = csa.CsaConfig(min_annualized=0.0)
    books = {"y0": [(0.30, 20.0)], "y1": [(0.30, 20.0)], "y2": [(0.30, 20.0)],
             "n0": [(0.60, 20.0)], "n1": [(0.60, 20.0)], "n2": [(0.60, 20.0)]}
    ops = {o.kind: o for o in csa.evaluate_event(ev, books, cfg, NOW)}
    assert ops["yes_set"].fill.sets == pytest.approx(20) and ops["yes_set"].fill.net == pytest.approx(2.0)
    assert ops["no_set"].fill.payout == pytest.approx(40) and ops["no_set"].fill.net == pytest.approx(40 - 36)
    assert ops["yes_set"].days == pytest.approx(17 + csa.RESOLUTION_BUFFER_DAYS)
    # augmented: never a YES set, still a NO set
    ops = {o.kind for o in csa.evaluate_event(csa.parse_event(_event(augmented=True)), books, cfg, NOW)}
    assert ops == {"no_set"}
    # too little depth (< 5 shares) -> nothing
    thin = {k: [(p, 4.0)] for k, [(p, _)] in books.items()}
    assert csa.evaluate_event(ev, thin, cfg, NOW) == []
    # too far from resolution
    assert csa.evaluate_event(ev, books, csa.CsaConfig(max_days=5), NOW) == []
    # capital cap
    o = [o for o in csa.evaluate_event(ev, books, cfg, NOW, max_capital=4.5) if o.kind == "yes_set"][0]
    assert o.fill.capital == pytest.approx(4.5)


def test_evaluate_rejects_low_annualized_return():
    ev = csa.parse_event(_event())
    books = {"y0": [(0.33, 20.0)], "y1": [(0.33, 20.0)], "y2": [(0.329, 20.0)]}      # 0.011 per set over 19 days ~ 21% / yr
    assert csa.evaluate_event(ev, books, csa.CsaConfig(min_marginal=0.0, min_return=0.0, min_annualized=0.10, use_no_sets=False), NOW)
    assert not csa.evaluate_event(ev, books, csa.CsaConfig(min_marginal=0.0, min_return=0.0, min_annualized=0.50, use_no_sets=False), NOW)


def _op(eid="e1", capital=10.0, net=0.2, days=10.0):
    f = csa.SetFill(capital + net, capital, 0.0, capital + net, 0.01, [0.5])
    return csa.Opportunity(NOW, eid, "T", "yes_set", 2, f, days, ["a", "b"])


def test_risk_manager_limits(tmp_path):
    rm = csa.RiskManager(csa.RiskLimits(bankroll=100, max_per_event=25, max_deployed=40, max_open_events=2, max_days=30, kill_file=str(tmp_path / "KILL")))
    assert rm.approve(_op()) == (True, "ok")
    rm.book(_op())
    assert rm.room("e1") == pytest.approx(15)
    assert rm.approve(_op(capital=16))[1] == "capital_limit"
    assert rm.approve(_op(days=31))[1] == "lockup_too_long"
    assert rm.approve(_op(net=-0.1))[1] == "not_profitable"
    rm.book(_op(eid="e2", capital=25))
    assert rm.deployed == pytest.approx(35) and rm.room("e3") == pytest.approx(5)
    assert rm.approve(_op(eid="e3", capital=1))[1] == "max_open_events"
    rm.settle("e1")
    assert rm.positions[0].status == "settled" and rm.positions[0].pnl == pytest.approx(0.2)
    rm.settle("e2", payout_override=20.0)
    assert rm.positions[1].status == "void" and rm.positions[1].pnl == pytest.approx(-5.0)
    assert rm.cash == pytest.approx(100 + 0.2 - 5.0)
    (tmp_path / "KILL").write_text("")
    assert rm.room("e9") == 0.0
    ok, why = rm.approve(_op(eid="e9", capital=1))
    assert not ok and "kill" in why and rm.halted


def test_deplete_removes_paper_takes():
    books = {"a": [(0.4, 10.0), (0.5, 5.0)], "b": [(0.3, 2.0)]}
    out = csa.deplete(books, {"a": {0.4: 10.0}, "b": {0.3: 5.0}})
    assert out == {"a": [(0.5, 5.0)]}


def test_resolution_backtest_buckets():
    plain_ok = _event(n=3)
    plain_ok["markets"] = [_mkt(0, closed=True, yes_px=1), _mkt(1, closed=True, yes_px=0), _mkt(2, closed=True, yes_px=0)]
    plain_none = {**plain_ok, "id": "e2", "markets": [_mkt(0, closed=True, yes_px=0), _mkt(1, closed=True, yes_px=0)]}
    aug_two = {**plain_ok, "id": "e3", "negRiskAugmented": True, "markets": [_mkt(0, closed=True, yes_px=1), _mkt(1, closed=True, yes_px=1),
                                                                           _mkt(2, closed=True, yes_px=1, other=True)]}
    unclean = {**plain_ok, "id": "e4", "markets": [_mkt(0, closed=True, yes_px=0.5), _mkt(1, closed=True, yes_px=0.5)]}
    r = csa.resolution_backtest([plain_ok, plain_none, aug_two, unclean, {"negRisk": False}])
    assert r["events"] == 4
    assert r["plain"] == {"exactly_one": 1, "none": 1, "unclean": 1}
    assert r["augmented"] == {"several": 1}
    assert len(r["plain_examples"]) == 2 and len(r["aug_examples"]) == 1


def test_realised_payout_uses_venue_prices():
    mk = [_mkt(0, closed=True, yes_px=1), _mkt(1, closed=True, yes_px=0), _mkt(2, closed=True, yes_px=0)]
    assert csa.realised_payout("yes_set", 10, mk, ["y0", "y1", "y2"]) == pytest.approx(10)
    assert csa.realised_payout("no_set", 10, mk, ["n0", "n1", "n2"]) == pytest.approx(20)
    mk[2] = _mkt(2)                       # still open
    assert csa.realised_payout("yes_set", 10, mk, ["y0", "y1", "y2"]) is None


def test_paper_log_and_settlement_roundtrip(tmp_path, monkeypatch):
    eng = csa.PaperArb(str(tmp_path), lim=csa.RiskLimits(kill_file=str(tmp_path / "KILL")))
    ev = csa.parse_event(_event())
    op = csa.evaluate_event(ev, {"y0": [(0.3, 20.0)], "y1": [(0.3, 20.0)], "y2": [(0.3, 20.0)]}, csa.CsaConfig(min_annualized=0.0), NOW)[0]
    eng.log("seen", **op.row())
    pos = eng.risk.book(op)
    eng.log("fill", pid=pos.pid, tokens=op.tokens, vwap=op.fill.legs_vwap, **op.row())
    eng._f.close()
    mk = [_mkt(0, closed=True, yes_px=0), _mkt(1, closed=True, yes_px=1), _mkt(2, closed=True, yes_px=0)]

    class R:
        def read(self):
            return json.dumps({"markets": mk}).encode()

    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: R())
    res = csa.settle_run(str(tmp_path))
    assert res["settled"] == 1 and res["pnl_settled"] == pytest.approx(2.0) and res["shortfalls"] == []


def test_tie_prone_families_get_no_yes_set():
    e = {**_event(), "slug": "nfl-dal-gb-2026-10-19-highest-scoring-quarter"}
    books = {f"y{i}": [(0.30, 20.0)] for i in range(3)}
    assert csa.evaluate_event(csa.parse_event(e), books, csa.CsaConfig(min_annualized=0.0), NOW) == []


def test_fee_stress_on_zero_fee_schedule():
    e = _event()
    for m in e["markets"]:
        m.update(feesEnabled=True, feeSchedule={"rate": 0, "exponent": 1})
    ev = csa.parse_event(e)
    books = {f"y{i}": [(0.32, 20.0)] for i in range(3)}            # 0.04 gross per set
    op = csa.evaluate_event(ev, books, csa.CsaConfig(min_annualized=0.0, use_no_sets=False), NOW)[0]
    assert op.fill.fees == 0.0
    assert op.net_stressed == pytest.approx(op.fill.net - 20 * 3 * 0.05 * 0.32 * 0.68)
    # trading under the stressed schedule: 3 x 0.05 x 0.2176 = 0.0326 per set -> marginal 0.0074 >= 0.005, still bought
    op2 = csa.evaluate_event(ev, books, csa.CsaConfig(min_annualized=0.0, use_no_sets=False, fee_stress_rate=0.05), NOW)[0]
    assert op2.fill.net == pytest.approx(op.net_stressed)
    assert not csa.evaluate_event(ev, books, csa.CsaConfig(min_annualized=0.0, use_no_sets=False, fee_stress_rate=0.07), NOW)
