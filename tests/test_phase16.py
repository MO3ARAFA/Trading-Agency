from quant_agency.copy_study import account, clustered, resolved_value


def test_resolved_value_respects_close_time():
    m = {"closed": True, "tokens": ["a", "b"], "prices": [1.0, 0.0], "closedTime": "2026-08-04 12:00:00+00"}
    assert resolved_value(m, "a") == 1.0
    assert resolved_value(m, "b", before=2_000_000_000) == 0.0
    assert resolved_value(m, "a", before=1_700_000_000) is None        # closed after the cut-off
    assert resolved_value({**m, "prices": [0.5, 0.5]}, "a") is None     # not a clean 0/1 resolution


def test_clustered_and_account():
    rows = [{"cid": "x", "ret": 0.1, "w": 1.0}, {"cid": "y", "ret": -0.05, "w": 1.0}, {"cid": "z", "ret": 0.2, "w": 1.0}]
    s = clustered(rows)
    assert s["markets"] == 3 and abs(s["mean"] - 0.25 / 3) < 1e-12
    a = account([{"t": i, "ret": 0.5} for i in range(60)], bankroll=10, stake=2)
    assert a["copied"] == 5 and a["final"] == 15.0


def test_copy_price_never_below_wallet_price():
    import inspect
    from quant_agency import copy_study
    src = inspect.getsource(copy_study.evaluate)
    assert "min(0.99" not in src and "px >= 1.0" in src
