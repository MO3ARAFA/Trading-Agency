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


def _mk(closed_time="2026-09-01 00:00:00+00", prices=(1.0, 0.0), q="Will X win?", fee=0.0):
    return {"closed": True, "tokens": ["y", "n"], "prices": list(prices), "closedTime": closed_time, "fee": fee, "q": q}


def test_sharp_copies_mirror_exit_and_filters():
    from quant_agency.copy_sharp import copies_of, ts
    mk = {"c": _mk(), "d": _mk(q="Bitcoin Up or Down - 5m")}
    tr = [{"side": "BUY", "t": 100, "cid": "c", "asset": "y", "price": 0.40},
          {"side": "BUY", "t": 101, "cid": "c", "asset": "y", "price": 0.95},     # outside the interior band
          {"side": "BUY", "t": 102, "cid": "d", "asset": "y", "price": 0.40},     # short-dated crypto: excluded
          {"side": "SELL", "t": 200, "cid": "c", "asset": "y", "price": 0.60}]
    cs = copies_of(tr, mk, 0, 10**10)
    assert len(cs) == 1 and cs[0]["how"] == "mirror" and cs[0]["exit_t"] == 200
    assert abs(cs[0]["cost"] - 0.41) < 1e-12 and abs(cs[0]["value"] - 0.588) < 1e-12
    cs = copies_of(tr[:1], mk, 0, 10**10)                                         # no sell: held to resolution
    assert cs[0]["how"] == "resolve" and cs[0]["value"] == 1.0 and cs[0]["exit_t"] == ts("2026-09-01 00:00:00+00")


def test_sharp_mm_filter():
    from quant_agency.copy_sharp import is_mm
    tr = [{"side": "BUY", "t": 0, "cid": "c", "asset": "y"}, {"side": "BUY", "t": 600, "cid": "c", "asset": "n"}]
    assert is_mm(tr, 0, 10**6) and not is_mm(tr[:1], 0, 10**6)


def test_sharp_simulator_recycles_cash_and_caps_wallet():
    from quant_agency.copy_sharp import simulate
    c = lambda i, w, cid, t, ex: {"wallet": w, "cid": cid, "t": t, "exit_t": ex, "cost": 0.5, "value": 1.0}
    a = simulate([c(i, "a", f"m{i}", i, i + 0.5) for i in range(40)], end_t=100, bankroll=10, stake=5, per_wallet=15)
    assert a["taken"] == 40 and a["final"] == 10 + 40 * 5          # each 5 USD doubles and is recycled before the next
    b = simulate([c(i, "a", f"m{i}", i, 99) for i in range(5)], end_t=100, bankroll=100, stake=5, per_wallet=15)
    assert b["taken"] == 3 and b["skipped"]["wallet_cap"] == 2
    s = simulate([c(0, "a", "m", 0, 99), c(1, "b", "m", 1, 99)], end_t=100, bankroll=100, stake=5)
    assert s["skipped"]["same_market"] == 1
