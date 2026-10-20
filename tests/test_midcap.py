"""1-to-1 same-asset Binance spot -> Hyperliquid perp scanner: universe, detection, basis neutrality, tiers, latency sweep, placebo, evaluation."""
import json

import numpy as np
import pytest

from quant_agency.agency import Agency
from quant_agency.config import AgencyConfig
from quant_agency.market_watchers import MarketMeta
from quant_agency.midcap_crossvenue import XvConfig, XvScanner, build_xv_universe, hl_to_asset
from quant_agency import midcap_eval as me
from quant_agency import midcap_report as mr


# ------------------------------------------------------------------------------------------ universe
def _fixture():
    def b(sym, vol, spr, tick="0.001"):
        return ({"symbol": sym, "quoteVolume": str(vol)}, {"symbol": sym, "bidPrice": str(1.0 - spr / 2e4), "askPrice": str(1.0 + spr / 2e4)},
                {"symbol": sym, "status": "TRADING", "baseAsset": sym[:-4], "filters": [{"filterType": "PRICE_FILTER", "tickSize": tick}, {"filterType": "LOT_SIZE", "stepSize": "1"}, {"filterType": "NOTIONAL", "minNotional": "5"}]})
    spec = [("BTCUSDT", 9e8, 0.1, "0.01"), ("ETHUSDT", 4e8, 0.1, "0.01"), ("SOLUSDT", 2e8, 1.0, "0.01"), ("TAOUSDT", 1.5e7, 3.8, "0.01"), ("NEARUSDT", 1e8, 2.0, "0.001"),
            ("PEPEUSDT", 2.7e7, 24.0, "0.0000001"), ("BONKUSDT", 5e6, 6.0, "0.0000001"), ("WIDEUSDT", 5e6, 30.0, "0.001"), ("TICKYUSDT", 5e6, 5.0, "0.5"),
            ("THINUSDT", 3e5, 2.0, "0.001"), ("PAXGUSDT", 9e6, 0.0, "0.01"), ("LOWHLUSDT", 5e6, 2.0, "0.001")]
    b24, bbook, binfo = zip(*[b(*s) for s in spec])
    hl = [{"name": n} for n in ("BTC", "ETH", "SOL", "TAO", "NEAR", "kPEPE", "kBONK", "WIDE", "TICKY", "THIN", "PAXG", "LOWHL", "HLONLY")] + [{"name": "OLD", "isDelisted": True}]
    vols = {"BTC": 2e9, "ETH": 6e8, "SOL": 1.2e8, "TAO": 9.6e6, "NEAR": 1.4e8, "kPEPE": 8e6, "kBONK": 3e6, "WIDE": 4e6, "TICKY": 4e6, "THIN": 4e6, "PAXG": 2e6, "LOWHL": 1e5, "HLONLY": 9e7}
    px = {"BTC": 80000, "ETH": 3000, "SOL": 150, "TAO": 300, "NEAR": 4, "kPEPE": 0.004, "kBONK": 0.02, "WIDE": 1.0, "TICKY": 1.0, "THIN": 1.0, "PAXG": 4000, "LOWHL": 1.0, "HLONLY": 1.0}
    ctx = [{"dayNtlVlm": str(vols.get(u["name"], 0)), "midPx": str(px.get(u["name"], 1.0))} for u in hl]
    return {"b24": list(b24), "bbook": list(bbook), "binfo": {"symbols": list(binfo)}, "hl_meta": [{"universe": hl}, ctx]}


def test_hl_to_asset():
    assert hl_to_asset("kPEPE") == "PEPE" and hl_to_asset("SOL") == "SOL" and hl_to_asset("kBONK") == "BONK" and hl_to_asset("k") == "k"


def test_universe_matching_filters_and_order():
    u = build_xv_universe(_fixture(), XvConfig(n_pairs=50))
    ids = [m.id for m in u.metas]
    n = len(u.pairs)
    assert ids[0] == "BTCUSDT" and ids[1] == "ETHUSDT" and ids[n] == "hyperliquid:BTC" and ids[n + 1] == "hyperliquid:ETH"      # BTC first (book index 0), Binance block then HL block
    assets = [p["asset"] for p in u.pairs]
    assert assets[:2] == ["BTC", "ETH"] and all(p["baseline"] for p in u.pairs[:2]) and not any(p["baseline"] for p in u.pairs[2:])
    # mid-caps ranked by Hyperliquid volume
    assert assets[2:] == ["NEAR", "SOL", "TAO", "BONK"]
    assert "hyperliquid:kBONK" in ids and "hyperliquid:BONK" not in ids
    d = u.dropped
    assert "spread" in d["PEPE"] and "spread" in d["WIDE"]                       # PEPE: 24 bps one-tick book
    assert "one tick" in d["TICKY"] and "Binance 24h volume" in d["THIN"] and "gold" in d["PAXG"] and "HL 24h volume" in d["LOWHL"]
    assert "HLONLY" not in d and "OLD" not in d                                  # no Binance spot -> not a pair at all; delisted skipped
    by = {m.id: m for m in u.metas}
    assert all(not m.hunt and not m.tradable for m in u.metas) and by["hyperliquid:SOL"].fee_taker_bps == 4.5 and by["hyperliquid:SOL"].kind == "perp"
    assert by["hyperliquid:kBONK"].extra["unit_mult"] == 1000


def test_universe_cap_and_missing_btc():
    u = build_xv_universe(_fixture(), XvConfig(n_pairs=2))
    assert [p["asset"] for p in u.pairs] == ["BTC", "ETH", "NEAR", "SOL"] and "rank" in u.dropped["TAO"]
    d = _fixture()
    d["hl_meta"][0]["universe"] = [x for x in d["hl_meta"][0]["universe"] if x["name"] != "BTC"]
    d["hl_meta"][1] = d["hl_meta"][1][1:]
    with pytest.raises(ValueError):
        build_xv_universe(d, XvConfig())


# ------------------------------------------------------------------------------------------ synthetic two-venue world
DT = 0.05


def _world(seed=5, dur=600.0, hl_lag=(0.6, 0.0, None), premium_bps=20.0, jumps=True):
    """Binance AAA/BBB/CCC (+BTC at idx 0); perps: AAA lags 0.6 s, BBB is contemporaneous, CCC ignores Binance. Constant spot/perp premium."""
    rng = np.random.default_rng(seed)
    n = int(dur / DT)
    t = np.arange(n) * DT
    metas = [MarketMeta("BTCUSDT", "binance", "BTCUSDT", "BTC", asset="BTC", hunt=False, tradable=False)]
    for c in ("AAA", "BBB", "CCC"):
        metas.append(MarketMeta(f"{c}USDT", "binance", f"{c}USDT", c, asset=c, fee_taker_bps=7.5, hunt=False, tradable=False))
    for c in ("AAA", "BBB", "CCC"):
        metas.append(MarketMeta(f"hyperliquid:{c}", "hyperliquid", c, c, asset=c, kind="perp", fee_taker_bps=4.5, fee_maker_bps=1.5, hunt=False, tradable=False))
    walks = {}
    for k, c in enumerate(("AAA", "BBB", "CCC")):
        inc = rng.normal(0, 0.4e-4 * np.sqrt(DT), n)
        if jumps:
            for tj in np.arange(40.0 + 9 * k, dur - 20, 47.0):          # staggered so coins do not share 10-s blocks
                kk = int(tj / DT)
                inc[kk: kk + 4] += rng.choice([-1, 1]) * 22e-4 / 4
        walks[c] = np.cumsum(inc)
    ev = []

    def quotes(idx, series, p0, lag, rate, spread_bps, prem=0.0):
        for k in np.where(rng.random(n) < rate * DT)[0]:
            kk = max(int(k - lag / DT), 0)
            mid = p0 * np.exp(series[kk] + prem * 1e-4)
            h = mid * spread_bps * 1e-4 / 2
            ev.append((float(t[k]) + 1000.0, idx, mid - h, mid + h, 5000.0 / mid, 5000.0 / mid))

    quotes(0, np.cumsum(rng.normal(0, 0.5e-4 * np.sqrt(DT), n)), 80000.0, 0.0, 30.0, 0.2)
    for k, c in enumerate(("AAA", "BBB", "CCC")):
        quotes(1 + k, walks[c], 10.0 * (k + 1), 0.0, 12.0, 1.0)
        series = walks[c] if hl_lag[k] is not None else np.cumsum(rng.normal(0, 0.4e-4 * np.sqrt(DT), n))
        quotes(4 + k, series, 10.0 * (k + 1), hl_lag[k] or 0.0, 8.0, 2.0, premium_bps)
    ev.sort(key=lambda e: e[0])
    return metas, ev


def _pairs(metas):
    out = []
    for c in ("AAA", "BBB", "CCC"):
        out.append({"asset": c, "binance": f"{c}USDT", "hl": f"hyperliquid:{c}", "baseline": False, "hl_vol": 1e6, "bn_vol": 1e7, "bn_spread_bps": 1.0, "tick_bps": 1.0})
    return out


def _run(metas, ev, cfg=None, hook=None):
    ag = Agency(metas, AgencyConfig(), t0=ev[0][0], wall0=0.0)
    xv = XvScanner(ag, cfg or XvConfig(), _pairs(metas))
    ag.attach_xv(xv)
    last = ev[0][0]
    for k, (tt, i, b, a, bq, aq) in enumerate(ev):
        ag.on_quote(i, tt, b, a, bq, aq)
        if tt - last >= 0.05:
            ag.housekeeping(tt)
            last = tt
    ag.housekeeping(ev[-1][0] + 40.0)
    xv.poll(ev[-1][0] + 40.0)
    return ag, xv


@pytest.fixture(scope="module")
def world_run():
    metas, ev = _world()
    return _run(metas, ev), metas, ev


def _gross(xv, asset, lat, h, tier=4.0):
    return [r["gross"] for r in xv.trackers[lat].rows if r["x_asset"] == asset and abs(r["h"] - h) < 1e-9 and r["gap"] >= tier]


def test_lagging_perp_is_found_contemporaneous_and_decoupled_are_not_profitable(world_run):
    (ag, xv), _, _ = world_run
    by = {a: [s for s in xv.signals if s.tag["x_asset"] == a] for a in ("AAA", "BBB", "CCC")}
    assert len(by["AAA"]) >= 8
    assert all(s.market == "hyperliquid:AAA" and s.oracle == "xv" for s in by["AAA"])
    assert all(np.sign(s.gap_bps) == s.side == np.sign(s.tag["x_dB"]) for s in xv.signals)           # the perp is still to move in the Binance direction
    g_a, g_b, g_c = (np.mean(_gross(xv, a, 0.15, 5.0, 8.0)) for a in ("AAA", "BBB", "CCC"))
    assert g_a > 8.0                                  # a 22 bps jump, the perp follows 0.6 s later -> most of the gap is still there 150 ms after the tick
    assert abs(g_c) < 4.0                             # the perp that never follows: the 'gap' is just the Binance jump, no catch-up
    assert len(by["BBB"]) < 0.5 * len(by["AAA"]) or g_b < 0.5 * g_a


def test_constant_premium_is_basis_neutral():
    metas, ev = _world(jumps=False, premium_bps=35.0)
    _, xv = _run(metas, ev)
    assert xv.n_signals <= 3                          # a 35 bps spot/perp premium is not a gap; only noise could trip the 4 bps floor


def test_scan_runs_on_binance_ticks_only_and_needs_history(world_run):
    (ag, xv), metas, ev = world_run
    n_b = {c: sum(1 for e in ev if e[1] == 1 + k) for k, c in enumerate(("AAA", "BBB", "CCC"))}
    assert [int(x) for x in xv.n_eval] == [n_b["AAA"], n_b["BBB"], n_b["CCC"]]
    assert all(s.t - ag.t0 > 1.0 for s in xv.signals)


def test_cooldown_between_signals_of_a_pair(world_run):
    (_, xv), _, _ = world_run
    for a in ("AAA", "BBB", "CCC"):
        ts = sorted(s.t for s in xv.signals if s.tag["x_asset"] == a)
        assert np.all(np.diff(ts) >= 3.0 - 1e-9)


def test_hurdle_is_spread_plus_round_trip_fee_plus_depth_slippage(world_run):
    (_, xv), _, _ = world_run
    s = xv.signals[0]
    c = xv.cfg
    top = s.tag["x_top_usd"]
    slip = 0.5 * s.spread_bps * min(c.clip_usd / top, 4.0)
    assert s.tag["x_hurdle"] == pytest.approx(s.spread_bps + 2 * c.fee_taker_hl_bps + slip)
    assert s.net_gap_bps == pytest.approx(abs(s.gap_bps) - s.tag["x_hurdle"])
    assert s.tag["x_spread_h"] == pytest.approx(s.spread_bps) and top == pytest.approx((s.ask if s.side > 0 else s.bid) * (s.aq if s.side > 0 else s.bq))


def test_latency_sweep_decays_as_the_perp_catches_up(world_run):
    (_, xv), _, _ = world_run
    g = {lat: np.mean(_gross(xv, "AAA", lat, 5.0, 8.0)) for lat in (0.0, 0.15, 0.5, 1.0)}
    assert g[0.0] > g[0.15] > g[0.5] > g[1.0] - 1e-9
    assert g[0.0] > 12.0 and g[1.0] < 4.0              # by 1 s the 0.6 s-lagged perp has already repriced


def test_rows_carry_tags_and_tracker_fields(world_run):
    (_, xv), _, _ = world_run
    r = next(x for x in xv.trackers[0.15].rows if x["x_asset"] == "AAA" and x["h"] == 5.0)
    assert {"x_dB", "x_dH", "x_hz", "x_hl_age", "x_top_usd", "x_hurdle", "x_spread_h", "x_slip", "hin", "hout", "net0", "gross", "imp"} <= set(r)
    assert r["net0"] == pytest.approx(r["gross"] - r["hin"] - r["hout"], abs=0.5)                      # crossing both spreads
    assert r["net"] == pytest.approx(r["net0"] - 9.0, abs=1e-6)                                         # 4.5 bps per side from the perp's fee schedule


def test_time_shift_placebo_kills_the_edge(world_run):
    from quant_agency.run_live import placebo_shift
    (_, xv), metas, ev = world_run
    a = np.array(ev)
    t, idx, b, aa, bq, aq = a[:, 0], a[:, 1].astype(int), a[:, 2], a[:, 3], a[:, 4], a[:, 5]
    t2, i2, b2, a2, bq2, aq2 = placebo_shift(t, idx, b, aa, bq, aq, {0, 1, 2, 3}, 211.0)
    _, xp = _run(metas, list(zip(t2, i2, b2, a2, bq2, aq2)))
    real = np.mean(_gross(xv, "AAA", 0.15, 5.0, 8.0))
    plc = _gross(xp, "AAA", 0.15, 5.0, 8.0)
    assert real > 8.0 and (len(plc) < 0.3 * len(_gross(xv, "AAA", 0.15, 5.0, 8.0)) or abs(np.mean(plc)) < 0.35 * real)


def test_feed_reset_quiets_the_pair(world_run):
    (ag, xv), _, _ = world_run
    t = ag.last_t
    xv.reset(t, [xv.pairs[0]["h"]], 15.0)
    assert xv.cool[0] >= t + 15.0 and xv.cool[1] < t + 15.0
    xv.reset(t, None, 20.0)
    assert (xv.cool >= t + 20.0).all()


def test_agency_in_xv_mode_is_measure_only(world_run):
    (ag, xv), _, _ = world_run
    assert len(ag.engine.closed) == 0 and ag.cfo.n_approved == 0 and ag.arb.n_scans == 0 and ag.hunter.n_signals == 0


# ------------------------------------------------------------------------------------------ evaluation & report
def _row(asset="X", lat=0.15, h=5.0, gap=15.0, hurdle=12.0, gross=10.0, net0=None, top=2000.0, cl="r:1", base=False, side=1, hin=1.0, hout=1.0):
    net0 = gross - hin - hout if net0 is None else net0
    return {"x_asset": asset, "lat": lat, "h": h, "gap": gap, "x_hurdle": hurdle, "gross": gross, "net0": net0, "net": net0 - 9.0, "x_top_usd": top, "cl": cl, "imp": 1,
            "x_baseline": base, "side": side, "hin": hin, "hout": hout, "x_spread_h": 2.0, "x_hl_age": 0.2, "x_spread_b": 1.0, "t0": 1000.0, "sid": 1}


def test_primary_subset_and_decision_rule():
    rows = []
    for k in range(20):                                                   # 20 clusters, each net0 = 16 - 2 = ... gross 18 -> net0 16 -> net 7
        rows.append(_row(asset=f"A{k}", gross=18.0, cl=f"r:{k}"))
    rows += [_row(gap=11.0, hurdle=12.0, cl="r:100"),                    # below the full-cost hurdle -> not in the primary subset
             _row(top=500.0, cl="r:101"),                                 # touch worth < 1000 USD -> excluded
             _row(base=True, cl="r:102"),                                 # BTC/ETH baseline -> excluded
             _row(lat=0.5, cl="r:103"), _row(h=3.0, cl="r:104")]
    p = me.primary(rows)
    assert p["n"] == 20 and p["clusters"] == 20 and p["mean"] == pytest.approx(7.0) and p["gross_mean"] == pytest.approx(18.0)
    assert me.count_clusters(rows) == {"signals": 20, "clusters": 20}              # the stopping statistic sees counts only
    noisy = [_row(gross=18.0 if k % 2 else -10.0, cl=f"r:{k}") for k in range(20)]
    q = me.primary(noisy)
    assert q["clusters"] == 20 and q["decision"] in ("REJECT H0 (net > 0)", "do not reject H0")
    few = me.primary(rows[:5])
    assert few["clusters"] == 5 and few["decision"].startswith("underpowered")
    assert me.primary([])["n"] == 0


def test_net_variants_use_fee_tiers_on_net0():
    r = _row(gross=10.0, hin=1.0, hout=2.0)
    v = me.net_variants(r)
    assert v["taker_taker_9"] == pytest.approx(7.0 - 9.0) and v["taker_in_maker_out_6"] == pytest.approx(7.0 - 6.0) and v["maker_maker_3"] == pytest.approx(7.0 - 3.0)
    assert v["maker_exit_at_mid_opt_6"] == pytest.approx(10.0 - 1.0 - 6.0)


def test_confirmatory_runs_must_be_named_xvr(tmp_path):
    d = tmp_path / "xvv_test"
    d.mkdir()
    (d / "xv_markouts.jsonl").write_text("")
    with pytest.raises(SystemExit):
        me.main(["--runs", str(d)])


def test_report_end_to_end(tmp_path):
    def mk(name, shift=None, scale=1.0):
        d = tmp_path / name
        d.mkdir()
        rows = []
        sid = 0
        for blk in range(30):
            for asset in ("AAA", "BBB"):
                sid += 1
                for lat in mr.LATS:
                    for h in mr.HZ:
                        g = (14.0 - 4 * lat) * scale
                        r = _row(asset=asset, lat=lat, h=h, gap=16.0, gross=g, cl=f"{name}:{blk}", base=False)
                        r.update({"imp": blk, "sid": sid, "t0": 1000.0 + blk * 20, "market": f"hyperliquid:{asset}"})
                        rows.append(r)
        for blk in range(5):
            sid += 1
            for lat in mr.LATS:
                for h in mr.HZ:
                    r = _row(asset="BTC", lat=lat, h=h, gap=5.0, gross=0.5, cl=f"{name}:{blk}", base=True)
                    r.update({"imp": blk, "sid": sid, "t0": 1000.0 + blk * 20, "market": "hyperliquid:BTC"})
                    rows.append(r)
        (d / "xv_markouts.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
        pairs = [{"asset": "BTC", "baseline": True}, {"asset": "AAA", "baseline": False}, {"asset": "BBB", "baseline": False}]
        (d / "xv_map.json").write_text(json.dumps({"t_start": 0.0, "t_end": 3660.0, "warm_s": 60.0, "pairs": pairs, "placebo_shift": shift}))
        (d / "xv_universe.json").write_text(json.dumps({"pairs": pairs, "dropped": {"PEPE": "spread"}}))
        return str(d)
    real = mr.load_set([mk("xvr_a")])
    pl = mr.load_set([mk("xvp_100", 100.0, 0.05), mk("xvp_200", 200.0, 0.05)])
    res = mr.analyse(real, pl)
    assert res["hours"] == pytest.approx(1.0) and res["n_mid"] == 2 and res["n_base"] == 1
    assert res["primary"]["clusters"] == 30 and res["primary"]["n"] == 60
    assert res["primary"]["gross_mean"] == pytest.approx(14.0 - 4 * 0.15)
    occ = {(o["baseline"], o["tier"]): o for o in res["occurrence"]}
    assert occ[(False, "10")]["signals"] == 60 and occ[(False, "10")]["events"] == 60 and occ[(True, "10")]["signals"] == 0 and occ[(True, "4")]["signals"] == 5
    assert occ[(False, "10")]["per_coin_hour"] == pytest.approx(60 / 1.0 / 2)
    t = res["tier_lat"]["10|0.5"]
    assert t["gross"]["mean"] == pytest.approx(12.0) and t["fee"]["maker_maker_3"]["mean"] == pytest.approx(12.0 - 2.0 - 3.0)
    assert res["placebo"]["n_runs"] == 2 and res["placebo"]["tiers"]["10"]["per_run"] == 60
    md = mr.render_md(res, real, notes="NOTE-MARKER")
    for needle in ("NOTE-MARKER", "Pre-registered primary test", "How often", "Markouts by tier and latency", "Control: Binance legs", "Could it have been traded", "By coin", "Universe"):
        assert needle in md
