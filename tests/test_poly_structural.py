import gzip
import json

import numpy as np
import pytest

from quant_agency import poly_structural as ps
from quant_agency.polymarket_watcher import PmBooks

NOW = 1_800_000_000.0


# ------------------------------------------------------------------------------------------ universe
def _mk(q, tok, bb, ba, v24, hrs=100.0, neg=False, fee=False, accepting=True):
    return {"question": q, "clobTokenIds": json.dumps([tok, tok + "n"]), "bestBid": bb, "bestAsk": ba, "volume24hr": v24, "liquidity": 1000, "enableOrderBook": True,
            "acceptingOrders": accepting, "closed": False, "orderPriceMinTickSize": 0.01, "orderMinSize": 5, "endDate": _iso(NOW + hrs * 3600),
            **({"feesEnabled": True, "feeSchedule": {"rate": 0.02, "exponent": 1, "takerOnly": True}} if fee else {})}


def _iso(ts):
    import datetime as dt
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _events():
    ev = [{"slug": "slow-a", "title": "A", "negRisk": False, "markets": [_mk("a1", "A1", 0.40, 0.45, 2000), _mk("a2", "A2", 0.30, 0.34, 1500), _mk("a3", "A3", 0.50, 0.56, 1200),
                                                                      _mk("a4", "A4", 0.20, 0.26, 900)]},                       # 4 candidates, per_event cap = 3
          {"slug": "fast", "title": "F", "negRisk": False, "markets": [_mk("f1", "F1", 0.40, 0.45, 9000, hrs=5.0)]},                # < 24 h
          {"slug": "tight", "title": "T", "negRisk": False, "markets": [_mk("t1", "T1", 0.40, 0.41, 9000)]},                       # 1c spread
          {"slug": "thin", "title": "H", "negRisk": False, "markets": [_mk("h1", "H1", 0.40, 0.45, 100)]},                         # volume
          {"slug": "extreme", "title": "X", "negRisk": False, "markets": [_mk("x1", "X1", 0.01, 0.05, 9000)]},                     # mid < 5c
          {"slug": "closed", "title": "C", "negRisk": False, "markets": [_mk("c1", "C1", 0.40, 0.45, 9000, accepting=False)]}]
    ev.append({"slug": "grp-sell", "title": "G1", "negRisk": True, "markets": [_mk("g1", "G1", 0.40, 0.44, 500, neg=True), _mk("g2", "G2", 0.33, 0.36, 500), _mk("g3", "G3", 0.30, 0.33, 500)]})
    ev.append({"slug": "grp-fair", "title": "G2", "negRisk": True, "markets": [_mk("h1", "J1", 0.30, 0.34, 700), _mk("h2", "J2", 0.30, 0.34, 700), _mk("h3", "J3", 0.30, 0.34, 700)]})
    ev.append({"slug": "grp-small", "title": "G3", "negRisk": True, "markets": [_mk("s1", "S1", 0.30, 0.34, 700), _mk("s2", "S2", 0.30, 0.34, 700)]})      # < 3 legs
    return ev


def test_universe_filters_caps_and_groups():
    u = ps.build_poly_universe(_events(), NOW, ps.PsConfig(n_groups=1))
    slow = {m.token for m in u.slow}
    assert {"A1", "A2", "A3"} <= slow and "A4" not in slow                           # per-event cap, most active first
    assert not ({"F1", "T1", "H1", "X1", "C1"} & slow)                              # 5 h to expiry, 1c spread, 100 USD volume, 1c mid, not accepting orders
    assert u.counts["groups"] == 2 and set(u.groups) == {"grp-sell"}                 # the cached sum of bids (1.03) ranks first; the 2-leg group is not a group
    assert u.group_info["grp-sell"]["complete"] and u.groups["grp-sell"][0].kind == "leg" and u.groups["grp-sell"][0].n_legs == 3
    toks = u.tokens(ps.PsConfig())
    assert "A1" in toks and "A1n" in toks and "G1" in toks                           # quoted markets bring their NO token (mirror check); group legs bring the YES token


def test_in_play_ended_and_game_start_markets_are_not_slow():
    ev = [{"slug": "ended-match", "title": "m1", "negRisk": False, "ended": True, "markets": [_mk("e1", "E1", 0.40, 0.45, 9000)]},
          {"slug": "live-match", "title": "m2", "negRisk": False, "live": True, "markets": [_mk("l1", "L1", 0.40, 0.45, 9000)]},
          {"slug": "match-today", "title": "m3", "negRisk": False, "markets": [dict(_mk("s1", "S1", 0.40, 0.45, 9000), gameStartTime="2026-10-20 10:50:00+00")]},   # generic endDate 100 h away, game starts in 3 h
          {"slug": "match-far", "title": "m4", "negRisk": False, "markets": [dict(_mk("s2", "S2", 0.40, 0.45, 9000), gameStartTime=_iso(NOW + 72 * 3600).replace("T", " ").replace("Z", "+00"))]},
          {"slug": "plain", "title": "m5", "negRisk": False, "markets": [_mk("p1", "P1", 0.40, 0.45, 9000)]}]
    import datetime as dt
    now = dt.datetime(2026, 10, 20, 7, 50, tzinfo=dt.timezone.utc).timestamp()
    for e in ev:
        for m in e["markets"]:
            m["endDate"] = _iso(now + 100 * 3600)
    u = ps.build_poly_universe(ev, now, ps.PsConfig())
    assert {m.token for m in u.slow} == {"S2", "P1"} and u.counts["in_play_or_ended_excluded"] == 2
    assert ps._parse_ts("2026-10-20 10:50:00+00") == dt.datetime(2026, 10, 20, 10, 50, tzinfo=dt.timezone.utc).timestamp()
    assert ps._parse_ts("2026-10-20T10:50:00Z") == ps._parse_ts("2026-10-20 10:50:00+00:00") and ps._parse_ts("junk") is None


def test_maker_stats_use_the_market_as_the_unit():
    from quant_agency.queue_model import RestOrder
    def att(tok, k, px, mark):
        a = ps.Attempt(k, tok, "slow", "join", "trades", 1, px, 5.0, 0.0, 0.04, 0.42, 0.01, RestOrder(1, px, 5.0, 0.0, 0.4), 1e9)
        a.fill_t, a.fill_px, a.fill_qty = 1.0, px, 5.0
        a.marks = {60.0: mark, 300.0: mark}
        return a
    busy = [att("A", k, 0.40, 0.36) for k in range(30)]                   # one moving market fills 30 times at -4c
    rest = [att("B", 100, 0.40, 0.41), att("C", 101, 0.40, 0.41)]         # two quiet markets fill once each at +1c
    s = ps.maker_stats(busy + rest, hours=1.0, n_markets=3, qty=5.0)["slow|join|trades"]
    assert s["fills"] == 32 and s["markets_with_fills"] == 3 and s["top_market_fill_share"] == pytest.approx(30 / 32)
    assert s["markout_300s_c"] == pytest.approx((30 * -4 + 2 * 1) / 32)               # fill-weighted: dominated by the busy market
    assert s["markout_300s_market_mean_c"] == pytest.approx((-4 + 1 + 1) / 3) and s["markout_300s_markets"] == 3


def test_fee_per_share():
    assert ps.fee_per_share(None, 0.4) == 0.0
    assert ps.fee_per_share((0.02, 1.0, True), 0.5) == pytest.approx(0.02 * 0.25)
    assert ps.fee_per_share((0.02, 1.0, True), 0.0) == pytest.approx(0.0, abs=1e-6)


# ------------------------------------------------------------------------------------------ messages
def book(tok, bids, asks):
    return {"event_type": "book", "asset_id": tok, "bids": [{"price": str(p), "size": str(s)} for p, s in bids], "asks": [{"price": str(p), "size": str(s)} for p, s in asks]}


def change(tok, side, price, size, bb=None, ba=None):
    pc = {"asset_id": tok, "side": side, "price": str(price), "size": str(size)}
    if bb is not None:
        pc["best_bid"], pc["best_ask"] = str(bb), str(ba)
    return {"event_type": "price_change", "price_changes": [pc]}


def trade(tok, px, sz, side="SELL"):
    return {"event_type": "last_trade_price", "asset_id": tok, "price": str(px), "size": str(sz), "side": side}


def _engine(cfg=None, ev=None):
    cfg = cfg or ps.PsConfig(n_groups=2, min_set_shares=5.0)
    u = ps.build_poly_universe(ev or _events(), NOW, cfg)
    ctrl = [ps.PmMarket("C9", "C9n", "ctrl", "ctrl", False, 0.01, 5, NOW + 3600, 0, 0, None, "control")]
    return ps.PolyStructural(u, ctrl, cfg), u


# ------------------------------------------------------------------------------------------ structural scanner
def test_exclusive_sell_set_is_found_netted_for_fees_and_tracked():
    eng, u = _engine()
    t = 100.0
    # grp-sell: bids 0.40 + 0.33 + 0.30 = 1.03 > 1 -> buy NO on every leg for 3 - 1.03... locked margin 0.03 per set
    for tok, b, a in (("G1", 0.40, 0.44), ("G2", 0.33, 0.36), ("G3", 0.30, 0.33)):
        eng.on_message(t, book(tok, [(b, 100)], [(a, 100)]))
    ev = eng.scan.evaluate("grp-sell", t)
    assert ev["sum_bid"] == pytest.approx(1.03) and ev["sell"]["gross"] == pytest.approx(0.03) and ev["sell"]["net"] == pytest.approx(0.03)      # no fee schedule here
    assert ev["buy"]["ok"] is False and ev["exhaustive_like"] is False                                                                        # sum of asks 1.13 and sum of mids 1.08: not exhaustive
    assert list(eng.scan.open) == [("grp-sell", "sell")]
    o = eng.scan.open[("grp-sell", "sell")]
    assert o.max_net == pytest.approx(0.03) and o.min_shares == 100 and o.n_legs == 3
    eng.on_message(t + 7.0, book("G2", [(0.30, 100)], [(0.36, 100)]))                       # a leg's bid drops: the margin disappears
    assert not eng.scan.open and len(eng.scan.closed) == 1 and eng.scan.closed[0].duration == pytest.approx(0.0, abs=7.1)


def test_sell_set_needs_depth_and_every_leg():
    eng, _ = _engine()
    for tok, b, a in (("G1", 0.40, 0.44), ("G2", 0.33, 0.36), ("G3", 0.30, 0.33)):
        eng.on_message(10.0, book(tok, [(b, 2 if tok == "G3" else 100)], [(a, 100)]))      # the thinnest leg only shows 2 shares < the 5-share minimum order
    assert not eng.scan.open
    eng2, _ = _engine()
    eng2.on_message(10.0, book("G1", [(0.40, 100)], [(0.44, 100)]))
    eng2.on_message(10.0, book("G2", [(0.33, 100)], [(0.36, 100)]))                        # G3 has no book yet -> incomplete, nothing evaluated
    assert not eng2.scan.open and eng2.scan.n_incomplete >= 1


def test_fees_can_kill_a_locked_margin():
    ev = _events()
    for e in ev:
        if e["slug"] == "grp-sell":
            for m in e["markets"]:
                m["feesEnabled"], m["feeSchedule"] = True, {"rate": 0.10, "exponent": 1, "takerOnly": True}
    eng, _ = _engine(ev=ev)
    for tok, b, a in (("G1", 0.40, 0.44), ("G2", 0.33, 0.36), ("G3", 0.30, 0.33)):
        eng.on_message(5.0, book(tok, [(b, 100)], [(a, 100)]))
    r = eng.scan.evaluate("grp-sell", 5.0)
    fee = sum(0.10 * ((1 - b) * b) for b in (0.40, 0.33, 0.30))                              # NO legs are bought at 1 - bid
    assert r["sell"]["gross"] == pytest.approx(0.03) and r["sell"]["net"] == pytest.approx(0.03 - fee) and r["sell"]["net"] < 0
    assert not eng.scan.open


def test_exhaustive_buy_set_requires_an_exhaustive_group():
    ev = _events()
    eng, _ = _engine(ev=ev)
    for tok in ("J1", "J2", "J3"):                                                           # asks 0.325 x 3 = 0.975 < 1 and mids sum to 0.95: exhaustive-like
        eng.on_message(1.0, book(tok, [(0.31, 100)], [(0.325, 100)]))
    r = eng.scan.evaluate("grp-fair", 1.0)
    assert r["exhaustive_like"] and r["buy"]["ok"] and r["buy"]["gross"] == pytest.approx(0.025)
    assert ("grp-fair", "buy") in eng.scan.open
    eng2, _ = _engine(ev=ev)
    for tok in ("J1", "J2", "J3"):                                                           # asks 0.20 x 3 = 0.60: far from 1, so not exhaustive: no guaranteed payout
        eng2.on_message(1.0, book(tok, [(0.10, 100)], [(0.20, 100)]))
    r2 = eng2.scan.evaluate("grp-fair", 1.0)
    assert not r2["exhaustive_like"] and not r2["buy"]["ok"] and ("grp-fair", "buy") not in eng2.scan.open


def test_mirror_check_flags_a_free_lunch_only_when_present():
    eng, _ = _engine()
    eng.on_message(1.0, book("A1", [(0.40, 50)], [(0.45, 50)]))
    eng.on_message(1.0, book("A1n", [(0.55, 50)], [(0.60, 50)]))                            # mirror: ask NO = 1 - bid YES = 0.60, bid NO = 1 - ask YES = 0.55
    assert eng.mirror.n >= 1 and eng.mirror.n_cross == 0 and eng.mirror.min_ask_sum == pytest.approx(1.05) and eng.mirror.max_bid_sum == pytest.approx(0.95)
    eng.on_message(2.0, book("A1n", [(0.55, 50)], [(0.52, 50)]))        # NO ask 0.52 + YES ask 0.45 = 0.97 < 1: crossed
    assert eng.mirror.n_cross == 1


# ------------------------------------------------------------------------------------------ maker simulation
def _quote_book(eng, t, bid=0.40, ask=0.46, bq=100, aq=100, tok="A1"):
    eng.on_message(t, book(tok, [(bid, bq)], [(ask, aq)]))


def test_join_bid_fills_only_after_the_queue_ahead_is_consumed_and_markouts_use_later_quotes():
    cfg = ps.PsConfig(n_groups=2)
    eng, u = _engine(cfg)
    t = 100.0
    _quote_book(eng, t)
    eng.poll(t + 0.1)                                                                         # posts 12 virtual orders on A1 (2 policies x 3 models x 2 sides) once a quote exists
    assert sum(1 for k in eng.sim.live if k[0] == "A1" and k[1] == "join" and k[3] > 0) == 3
    eng.poll(t + 1.0)                                                                         # orders arrive: join behind 100 shares
    eng.on_message(t + 2.0, trade("A1", 0.40, 60, "SELL"))
    eng.poll(t + 2.1)
    fills = lambda m: [a for a in list(eng.sim.live.values()) + eng.sim.finished + eng.sim.pending_marks if a.policy == "join" and a.side > 0 and a.model == m and a.token == "A1" and a.fill_qty > 0]
    assert not fills("trades")                                                                # 60 < 100 ahead
    eng.on_message(t + 3.0, trade("A1", 0.40, 60, "SELL"))                                    # the second print eats the rest of the queue and fills us (min size 5)
    assert fills("trades") and fills("trades")[0].fill_qty == pytest.approx(5.0) and fills("trades")[0].fill_px == pytest.approx(0.40)
    assert not fills("strict")                                                                # strict needs the ask to cross our bid
    assert not fills("depletion")                                                             # displayed size at the level never fell
    # the market then drifts down: markouts at +60 / +300 s are taken from the quotes at those times
    _quote_book(eng, t + 40.0, bid=0.37, ask=0.43)
    _quote_book(eng, t + 250.0, bid=0.34, ask=0.40)
    eng.poll(t + 400.0)
    a = fills("trades")[0]
    assert a.marks[60.0] == pytest.approx(0.40)                                               # as-of t+63: the (0.37, 0.43) quote of t+40
    assert a.marks[300.0] == pytest.approx(0.37)                                              # mid of 0.34 / 0.40 at t+300
    st = ps.maker_stats([a], hours=1.0, n_markets=1, qty=5.0)["slow|join|trades"]
    assert st["fills"] == 1 and st["markout_300s_c"] == pytest.approx((0.37 - 0.40) * 100) and st["usd_per_fill_300s"] == pytest.approx(-0.03 * 5)


def test_strict_model_fills_when_the_ask_comes_down_through_the_bid():
    eng, _ = _engine()
    _quote_book(eng, 10.0)
    eng.poll(10.1)
    eng.poll(11.0)
    eng.on_message(12.0, book("A1", [(0.36, 100)], [(0.40, 100)]))                          # the ask falls to our bid price: certain fill for the strict model
    eng.poll(12.1)
    got = [a for a in list(eng.sim.live.values()) + eng.sim.finished + eng.sim.pending_marks if a.model == "strict" and a.policy == "join" and a.side > 0 and a.fill_qty > 0]
    assert got and got[0].fill_px == pytest.approx(0.40)


def test_penny_policy_improves_by_a_tick_only_inside_a_wide_spread():
    eng, _ = _engine()
    _quote_book(eng, 5.0, bid=0.40, ask=0.46)                                                # 6c spread = 6 ticks: penny bid 0.41, penny ask 0.45
    eng.poll(5.1)
    px = {(k[1], k[3]): a.price for k, a in eng.sim.live.items() if k[0] == "A1" and k[2] == "trades"}
    assert px[("join", 1)] == pytest.approx(0.40) and px[("join", -1)] == pytest.approx(0.46)
    assert px[("penny", 1)] == pytest.approx(0.41) and px[("penny", -1)] == pytest.approx(0.45)
    eng2, _ = _engine()
    _quote_book(eng2, 5.0, bid=0.40, ask=0.42)                                               # 2 ticks: no penny quote
    eng2.poll(5.1)
    assert not any(k[1] == "penny" for k in eng2.sim.live if k[0] == "A1")


def test_orders_expire_and_repost_and_stop_near_expiry():
    cfg = ps.PsConfig(ttl_s=30.0, repost_s=5.0)
    eng, _ = _engine(cfg)
    for t in np.arange(0.0, 80.0, 1.0):
        _quote_book(eng, float(t))                                                            # a live, unchanged market so the quote is never stale
        eng.poll(float(t))
    assert len(eng.sim.finished) >= 12                                                        # first generation (12 orders on A1) cancelled at the 30 s TTL
    assert all(a.fill_qty == 0 for a in eng.sim.finished if a.token == "A1")
    nxt = [a for a in list(eng.sim.live.values()) if a.token == "A1"]
    assert nxt and min(a.t_send for a in nxt) > 30.0                                          # reposted
    u = eng.uni.slow[0]
    u.t_end = 90.0                                                                            # < 120 s to expiry: no new orders
    before = len(eng.sim.live)
    eng.poll(81.0)
    eng.poll(120.0)
    assert not any(a.t_send > 85.0 and a.token == u.token for a in eng.sim.live.values())


def test_trade_burstiness_poisson_vs_burst():
    rng = np.random.default_rng(1)
    pois = np.sort(rng.uniform(0, 3600, 600))
    burst = np.sort(np.concatenate([rng.uniform(i * 600, i * 600 + 20, 100) for i in range(6)]))
    r = ps.trade_burstiness({"p": list(pois)}, 0.0, 3600.0)
    b = ps.trade_burstiness({"b": list(burst)}, 0.0, 3600.0)
    assert 0.5 < r["fano_median"] < 1.8 and b["fano_median"] > 10 and r["trades_per_min_median"] == pytest.approx(10.0)


# ------------------------------------------------------------------------------------------ maker-lock sets
def test_set_maker_locks_a_margin_only_when_every_leg_fills():
    cfg = ps.PsConfig(n_groups=2, set_ttl_s=120.0)
    eng, _ = _engine(cfg)
    # grp-fair legs J1..J3: bids 0.30 each (sum 0.90 < 1), asks 0.36 (sum of mids 0.99: exhaustive-like)
    for tok in ("J1", "J2", "J3"):
        eng.on_message(1.0, book(tok, [(0.30, 20)], [(0.36, 20)]))
    eng.poll(1.1)
    eng.poll(2.0)
    assert "grp-fair" in eng.setsim.live
    for k, tok in enumerate(("J1", "J2", "J3")):
        eng.on_message(5.0 + k, trade(tok, 0.30, 40, "SELL"))                                  # sweeps the 20 ahead and fills our 5
    eng.poll(10.0)
    assert len(eng.setsim.done) == 1
    s = eng.setsim.done[0]
    assert s["complete"] and s["legs_filled"] == 3 and s["locked_usd"] == pytest.approx(5.0 * (1.0 - 0.90))
    eng2, _ = _engine(cfg)
    for tok in ("J1", "J2", "J3"):
        eng2.on_message(1.0, book(tok, [(0.30, 20)], [(0.36, 20)]))
    eng2.poll(1.1)
    eng2.poll(2.0)
    eng2.on_message(5.0, trade("J1", 0.30, 40, "SELL"))                                         # only one leg fills
    eng2.poll(200.0)
    s2 = eng2.setsim.done[0]
    assert not s2["complete"] and s2["legs_filled"] == 1 and s2["locked_usd"] == 0.0


# ------------------------------------------------------------------------------------------ end to end
def test_engine_end_to_end_and_replay_roundtrip(tmp_path):
    cfg = ps.PsConfig(n_groups=2)
    eng, u = _engine(cfg)
    msgs = []
    t = 10.0
    for tok, b, a in (("G1", 0.40, 0.44), ("G2", 0.33, 0.36), ("G3", 0.30, 0.33)):
        msgs.append((t, book(tok, [(b, 100)], [(a, 100)])))
    msgs.append((t, book("A1", [(0.40, 100)], [(0.46, 100)])))
    msgs.append((t + 20, trade("A1", 0.40, 150, "SELL")))
    msgs.append((t + 50, change("A1", "BUY", 0.40, 0, 0.38, 0.44)))
    msgs.append((t + 400, change("A1", "BUY", 0.38, 100, 0.38, 0.44)))
    path = str(tmp_path / "ev.jsonl.gz")
    with gzip.open(path, "wt") as f:
        for tt, m in msgs:
            f.write(f"{tt:.4f}\t{json.dumps(m)}\n")
    tp = 10.0
    for tt, m in msgs:
        while tp < tt:                                                                         # poll once a second between messages, as the live loop does
            eng.poll(tp)
            tp += 1.0
        eng.on_message(tt, m)
    while tp < 460.0:
        eng.poll(tp)
        tp += 1.0
    res = eng.finish(460.0)
    assert res["scan"]["groups"] == 2 and any(o["kind"] == "sell_set" for o in res["opps"])
    assert res["maker"]["slow|join|trades"]["fills"] >= 1
    rep = ps.replay(path, u, eng.control, cfg)
    assert rep["scan"]["evals"] > 0 and any(o["kind"] == "sell_set" for o in rep["opps"])
