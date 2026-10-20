"""Sector oracles: universe building, member masks, per-leader hunters, hurdle scaling, observe-only sink, report aggregation."""
import json

import numpy as np
import pytest

from quant_agency.agency import Agency
from quant_agency.btc_oracle import BtcOracle
from quant_agency.config import AgencyConfig, HunterConfig
from quant_agency.inefficiency_hunter import InefficiencyHunter
from quant_agency.market_watchers import (SECTOR_DEFS, MarketBook, MarketMeta, SectorDef, leader_index, sector_assets, sector_members)
from quant_agency.sector_oracles import SectorConfig, SectorHub, build_universe
from quant_agency import sector_report as sr


# ------------------------------------------------------------------------------------------ universe
def _fixture():
    b24 = [{"symbol": s, "quoteVolume": str(v)} for s, v in (("BTCUSDT", 9e9), ("SOLUSDT", 2e8), ("JUPUSDT", 4e6), ("BONKUSDT", 3e6), ("WIFUSDT", 1e5),
                                                           ("PEPEUSDT", 2.5e7), ("DOGEUSDT", 2.2e7), ("SHIBUSDT", 8e6), ("RENDERUSDT", 2e6), ("TAOUSDT", 1.5e7), ("FETUSDT", 5e6))]
    bbook = [{"symbol": s, "bidPrice": str(1.0 - w / 2e4), "askPrice": str(1.0 + w / 2e4)}
             for s, w in (("BTCUSDT", 0.1), ("SOLUSDT", 1.0), ("JUPUSDT", 3.0), ("BONKUSDT", 55.0), ("WIFUSDT", 5.0), ("PEPEUSDT", 24.0), ("DOGEUSDT", 1.3),
                          ("SHIBUSDT", 20.0), ("RENDERUSDT", 5.5), ("TAOUSDT", 3.8), ("FETUSDT", 5.3))]
    filt = [{"filterType": "PRICE_FILTER", "tickSize": "0.001"}, {"filterType": "LOT_SIZE", "stepSize": "0.1"}, {"filterType": "NOTIONAL", "minNotional": "5"}]
    binfo = {"symbols": [{"symbol": x["symbol"], "status": "TRADING", "baseAsset": x["symbol"][:-4], "filters": filt} for x in b24]}
    gate_pairs = [{"id": f"{a}_USDT", "trade_status": "tradable"} for a in ("SOL", "JUP", "PEPE", "DOGE", "RENDER", "TAO")]
    gate_tickers = [{"currency_pair": f"{a}_USDT", "quote_volume": str(v)} for a, v in (("SOL", 5e6), ("JUP", 5e4), ("PEPE", 9e5), ("DOGE", 1e6), ("RENDER", 3e5), ("TAO", 2e5))]
    kraken = {f"P{k}": {"wsname": f"{a}/USD", "status": "online"} for k, a in enumerate(("SOL", "PEPE", "RENDER", "TAO", "JUP"))}
    hl = {"universe": [{"name": n} for n in ("SOL", "kPEPE", "DOGE", "TAO", "RENDER", "kBONK")] + [{"name": "JUP", "isDelisted": True}]}
    return {"b24": b24, "bbook": bbook, "binfo": binfo, "gate_pairs": gate_pairs, "gate_tickers": gate_tickers, "kraken_pairs": kraken, "hl_meta": hl}


def test_universe_ids_filters_and_mapping():
    u = build_universe(_fixture())
    ids = [m.id for m in u.metas]
    assert ids[0] == "BTCUSDT"
    # leaders come first among Binance markets so their indices are stable
    assert set(ids[1:6]) == {"SOLUSDT", "PEPEUSDT", "RENDERUSDT", "DOGEUSDT", "TAOUSDT"} and ids[1] == "SOLUSDT"
    assert "gate:SOL_USDT" in ids and "kraken:SOL/USD" in ids and "hyperliquid:SOL" in ids
    assert "hyperliquid:kPEPE" in ids and "hyperliquid:PEPE" not in ids          # 1000x contracts carry the k prefix
    by = {m.id: m for m in u.metas}
    assert by["hyperliquid:kPEPE"].asset == "PEPE" and by["hyperliquid:kPEPE"].kind == "perp" and by["hyperliquid:kPEPE"].extra["unit_mult"] == 1000
    assert by["gate:SOL_USDT"].fee_taker_bps == 20.0 and by["kraken:SOL/USD"].fee_taker_bps == 40.0 and by["hyperliquid:SOL"].fee_taker_bps == 4.5
    assert by["SOLUSDT"].tick == 0.001 and by["SOLUSDT"].min_notional == 5.0
    # refusals are recorded with a reason
    assert "BONKUSDT" not in ids and "spread" in u.dropped["BONK"]["binance"]                 # 55 bps > 40 bps
    assert "WIFUSDT" not in ids and "volume" in u.dropped["WIF"]["binance"]                   # 0.1 M < 0.25 M
    assert "gate:JUP_USDT" not in ids and "volume" in u.dropped["JUP"]["gate"]
    assert "hyperliquid:JUP" not in ids and u.dropped["JUP"]["hyperliquid"] == "no perp"        # delisted
    assert "AGIX" in u.dropped and all("not listed" in v or "no perp" in v for v in u.dropped["AGIX"].values())
    assert len({m.id for m in u.metas}) == len(u.metas)


def test_leader_with_wide_spread_is_still_admitted_and_missing_leader_skips_sector():
    d = _fixture()
    u = build_universe(d)
    assert "PEPEUSDT" in [m.id for m in u.metas]                                             # 24 bps leader kept: the brief asks for PEPE
    d["b24"] = [x for x in d["b24"] if x["symbol"] != "TAOUSDT"]
    u2 = build_universe(d)
    names = [s["name"] for s in u2.sectors]
    assert "tao" not in names and "render" in names and "sector" in u2.dropped["TAO"]


def test_sector_members_exclude_only_the_binance_leader_and_include_its_other_venues():
    u = build_universe(_fixture())
    book = MarketBook(u.metas)
    sol = next(d for d in SECTOR_DEFS if d.name == "sol")
    mask = sector_members(book, sol)
    ids = {book.ids[i] for i in np.where(mask)[0]}
    assert "SOLUSDT" not in ids and {"gate:SOL_USDT", "kraken:SOL/USD", "hyperliquid:SOL", "JUPUSDT"} <= ids
    assert "PEPEUSDT" not in ids and "BTCUSDT" not in ids and not mask[0]
    assert leader_index(book, sol) == book.index["SOLUSDT"]
    # the DOGE variant shares PEPE's ecosystem, with PEPE a member and DOGE the oracle
    doge = next(d for d in SECTOR_DEFS if d.name == "doge")
    ids_d = {book.ids[i] for i in np.where(sector_members(book, doge))[0]}
    assert "PEPEUSDT" in ids_d and "DOGEUSDT" not in ids_d and "hyperliquid:DOGE" in ids_d
    assert doge.variant_of == "pepe" and set(doge.group) == set(next(d for d in SECTOR_DEFS if d.name == "pepe").group)


def test_every_group_asset_is_enumerated_once():
    a = sector_assets()
    assert len(a) == len(set(a)) and {"SOL", "PEPE", "RENDER", "DOGE", "TAO", "JUP", "FET"} <= set(a)


# ------------------------------------------------------------------------------------------ synthetic world
def _world(seed=3, dur=420.0, lead_lag=1.0, beta=1.2):
    """BTC (idx 0, independent), LEAD (idx 1, the sector leader), MEM (idx 2, follows LEAD with lag/beta), BTCF (idx 3, follows BTC), OTH (idx 4, follows LEAD but outside the group)."""
    rng = np.random.default_rng(seed)
    dt = 0.05
    n = int(dur / dt)
    t = np.arange(n) * dt

    def walk(sig_bps, jump_every=25.0, jump_bps=18.0, start=30.0):
        inc = rng.normal(0, sig_bps * 1e-4 * np.sqrt(dt), n)
        for tj in np.arange(start, dur, jump_every):
            k = int(tj / dt)
            inc[k: k + 4] += rng.choice([-1, 1]) * jump_bps * 1e-4 / 4
        return np.cumsum(inc)

    btc, lead = walk(0.5, 31.0, start=47.0), walk(1.2)          # jump times never coincide, so BTC and LEAD are genuinely unrelated
    metas = [MarketMeta("BTCUSDT", "binance", "BTCUSDT", "BTC", asset="BTC"),
             MarketMeta("LEADUSDT", "binance", "LEADUSDT", "LEAD", asset="LEAD", fee_taker_bps=7.5),
             MarketMeta("gate:MEM_USDT", "gate", "MEM_USDT", "MEM", asset="MEM", fee_taker_bps=20.0),
             MarketMeta("BTCFUSDT", "binance", "BTCFUSDT", "BTCF", asset="BTCF", fee_taker_bps=7.5),
             MarketMeta("OTHUSDT", "binance", "OTHUSDT", "OTH", asset="OTH", fee_taker_bps=7.5)]
    ev = []

    def quotes(idx, series, p0, lag, b, rate, spread_bps=2.0):
        for k in np.where(rng.random(n) < rate * dt)[0]:
            kk = max(int(k - lag / dt), 0)
            mid = p0 * np.exp(b * series[kk])
            h = mid * spread_bps * 1e-4 / 2
            ev.append((float(t[k]) + 1000.0, idx, mid - h, mid + h, 50.0, 50.0))

    quotes(0, btc, 80000.0, 0.0, 1.0, 40.0, 0.2)
    quotes(1, lead, 50.0, 0.0, 1.0, 20.0, 1.0)
    quotes(2, lead, 10.0, lead_lag, beta, 6.0)
    quotes(3, btc, 3.0, lead_lag, 1.0, 6.0)
    quotes(4, lead, 7.0, lead_lag, 1.0, 6.0)
    ev.sort(key=lambda e: e[0])
    return metas, ev


def _run(metas, ev, sc, group=("LEAD", "MEM"), cfg=None):
    cfg = cfg or AgencyConfig()
    ag = Agency(metas, cfg, t0=ev[0][0], wall0=0.0)
    defs = (SectorDef("t", "LEAD", group, "test"),)
    hub = SectorHub(ag, sc, defs)
    ag.attach_sectors(hub)
    scan_idx = hub.scan_idx
    last = ev[0][0]
    for (tt, i, b, a, bq, aq) in ev:
        ag.on_quote(i, tt, b, a, bq, aq)
        if i == 0 or i in scan_idx:
            ag.scan(tt)
        if tt - last >= 0.05:
            ag.housekeeping(tt)
            last = tt
    ag.housekeeping(ev[-1][0] + 40.0)
    hub.poll(ev[-1][0] + 40.0)
    return ag, hub


@pytest.fixture(scope="module")
def sector_run():
    metas, ev = _world()
    return _run(metas, ev, SectorConfig(sectors=("t",), gap_vol_mult=0.5, max_spread_bps=40.0, latencies_s=(0.15,)))


def test_sector_hunter_fires_only_on_members_and_with_its_own_tag(sector_run):
    ag, hub = sector_run
    sigs = hub.signals
    sec = [s for s in sigs if s.oracle == "t"]
    assert len(sec) >= 8
    assert {s.market for s in sec} == {"gate:MEM_USDT"}                    # LEAD itself, BTCF (BTC follower) and OTH (outside the group) never fire for it
    assert all(s.sid > 10_000_000 and s.impulse_id > 10_000_000 for s in sec)   # id space disjoint from the BTC hunter's
    assert all(np.sign(s.gap_bps) == s.side for s in sec)


def test_baseline_btc_hunter_is_unchanged_in_scope(sector_run):
    ag, hub = sector_run
    btc = [s for s in hub.signals if s.oracle == "BTC"]
    assert btc and {s.market for s in btc} == {"BTCFUSDT"}                  # only the market that really follows BTC; the LEAD followers are not BTC-coupled
    assert all(s.sid < 10_000_000 for s in btc)
    assert ag.hunter.model.members[1:].all() and not ag.hunter.model.members[0]


def test_model_calibrates_leader_lag_and_beta(sector_run):
    ag, hub = sector_run
    m = hub.sectors[0].hunter.model
    i = ag.book.index["gate:MEM_USDT"]
    assert m.calibrated[i] and abs(m.lag[i] - 1.0) <= 0.2 and abs(m.beta[i] - 1.2) < 0.3
    assert not m.calibrated[ag.book.index["BTCFUSDT"]] and not m.calibrated[ag.book.index["OTHUSDT"]]      # masked out of calibration
    assert [r["market"] for r in m.table()] == ["gate:MEM_USDT"]


def test_gap_hurdle_scales_with_leader_volatility(sector_run):
    ag, hub = sector_run
    sec = [s for s in hub.signals if s.oracle == "t"]
    for s in sec:
        want = max(1.0, 0.5 * s.beta * s.lead_sigma_bps)
        assert s.hurdle_bps == pytest.approx(want, rel=1e-6)
        assert abs(s.gap_bps) >= s.hurdle_bps - 1e-9
    assert max(s.hurdle_bps for s in sec) > 1.0                           # the volatility term actually binds on some impulses
    assert all(s.hurdle_bps == 1.0 for s in hub.signals if s.oracle == "BTC")      # the baseline keeps the flat 1 bp rule


def test_net_gap_uses_cfo_cost_model(sector_run):
    ag, hub = sector_run
    s = next(x for x in hub.signals if x.oracle == "t")
    px = s.ask if s.side > 0 else s.bid
    sp, fee, slip = ag.cfo.costs(s, 1000.0 / px, "taker")
    assert fee == pytest.approx(2 * 20.0)                                 # Gate taker fee, both sides
    assert s.net_gap_bps == pytest.approx(abs(s.gap_bps) - (sp + fee + slip))


def test_observe_only_registers_markouts_and_trades_nothing(sector_run):
    ag, hub = sector_run
    tr = hub.trackers[0.15]
    assert tr.rows and {r["oracle"] for r in tr.rows} >= {"t", "BTC"}
    assert len(ag.engine.closed) == 0 and ag.cfo.n_approved == 0 and ag.cfo.markouts.rows == []      # CFO book / engine untouched
    r = next(x for x in tr.rows if x["oracle"] == "t" and x["h"] == 5.0)
    assert {"asset", "net_gap", "lag_s", "beta", "hurdle", "lsig", "fee_in", "fee_out"} <= set(r)
    # the follower really catches up: positive gross markout at 5 s on the lagging member
    g = [x["gross"] for x in tr.rows if x["oracle"] == "t" and x["h"] == 5.0]
    assert np.mean(g) > 2.0 and np.mean(np.array(g) > 0) > 0.7


def test_leader_tick_triggers_scan_only_for_its_hunter():
    metas, ev = _world(dur=200.0)
    ag, hub = _run(metas, ev, SectorConfig(sectors=("t",), latencies_s=(0.15,)))
    assert hub.scan_idx == {1}
    assert hub.sectors[0].hunter.n_scans > 100 and ag.hunter.n_scans > 100


def test_unique_impulse_ids_across_hunters(sector_run):
    ag, hub = sector_run
    rows = hub.trackers[0.15].rows
    by = {}
    for r in rows:
        by.setdefault(r["imp"], set()).add(r["oracle"])
    assert all(len(v) == 1 for v in by.values())                           # no impulse id is shared between two oracles


def test_net_gate_suppresses_when_costs_exceed_gap():
    metas, ev = _world(dur=250.0)
    book = MarketBook(metas)
    o = BtcOracle()
    h = InefficiencyHunter(book, o, HunterConfig(max_spread_bps=40.0), name="x", members=np.array([0, 0, 1, 0, 0]), id_base=5_000_000,
                           cost_model=lambda s: (s.spread_bps, 1e6, 0.0), net_gate=True)
    for (tt, i, b, a, bq, aq) in ev:
        book.on_quote(i, tt, b, a, bq, aq)
        if i == 1:
            o.on_book(tt, b, a, bq, aq); h.dirty = True
        if h.dirty:
            assert h.scan(tt) == []
    assert h.n_net_suppressed > 0 and h.n_signals == 0


def test_reset_quiets_every_sector_hunter(sector_run):
    ag, hub = sector_run
    t = ag.last_t
    ag.on_feed_reset(t, [hub.sectors[0].leader_idx], hold_s=15.0)
    assert hub.sectors[0].oracle.blackout_until > t
    assert (hub.sectors[0].hunter.cooldown_until[hub.sectors[0].leader_idx] >= t + 15.0)
    ag.on_feed_reset(t + 100.0, None, hold_s=20.0)
    assert (hub.sectors[0].hunter.cooldown_until >= t + 120.0).all()


def test_validation_mask_blocks_blown_out_or_stale_books():
    metas, ev = _world(dur=60.0)
    book = MarketBook(metas)
    for (tt, i, b, a, bq, aq) in ev:
        book.on_quote(i, tt, b, a, bq, aq)
    t = ev[-1][0]
    ok = book.validation_mask(t, max_spread_bps=40.0, max_age_s=10.0, wide_ratio=3.0, min_ticks=30)
    assert ok.all()
    assert not book.validation_mask(t + 60.0, max_age_s=10.0).any()                     # everything stale a minute later
    i = 2                                                                              # blow the spread out for a while
    mid = book.state[i, 10]
    for k in range(40):
        book.on_quote(i, t + 0.1 * k, mid * (1 - 60e-4), mid * (1 + 60e-4), 1.0, 1.0)
    assert not book.validation_mask(t + 4.0, max_spread_bps=200.0, wide_ratio=3.0)[i]  # spread >> its own slow norm
    assert book.validation_mask(t + 4.0, max_spread_bps=200.0, wide_ratio=0.0)[i]      # gate off -> only absolute checks apply


def test_replay_of_a_sector_tape_reproduces_the_direct_run(tmp_path):
    """A tape whose `extra` carries the sector map is replayed through the same hub and gives the same signals (deterministic, no network)."""
    import dataclasses
    from argparse import Namespace
    from quant_agency import run_live
    metas, ev = _world(dur=300.0)
    sc = SectorConfig(sectors=("t",), latencies_s=(0.15,))
    ag0 = Agency(metas, AgencyConfig(), t0=ev[0][0], wall0=0.0)
    ag0.start_recording()
    for (tt, i, b, a, bq, aq) in ev:
        ag0.on_quote(i, tt, b, a, bq, aq)
    tape = str(tmp_path / "t.npz")
    ag0.save_tape(tape, extra={"sectors": {"names": ["t"], "config": dataclasses.asdict(sc)}})
    direct_ag, direct_hub = _run(metas, ev, sc)
    args = Namespace(replay=tape, status_every=1e9, sector_mult=0.5, sector_list="t", phase7=False, phase6=False, phase5=False, hl_maker_bps=None)
    # the leader is not in the default SECTOR_DEFS, so register the test sector for the replay
    import quant_agency.sector_oracles as so
    import quant_agency.market_watchers as mw
    test_def = SectorDef("t", "LEAD", ("LEAD", "MEM"), "test")
    old = so.SECTOR_DEFS
    try:
        orig_init = so.SectorHub.__init__
        so.SectorHub.__init__ = lambda self, ag, sc=None, defs=(test_def,): orig_init(self, ag, sc, defs)
        ag, _, t_end = run_live.run_replay(args, AgencyConfig(), str(tmp_path / "out"))
    finally:
        so.SectorHub.__init__ = orig_init
    assert ag.sectors is not None and ag.sectors.n_obs["t"] == direct_hub.n_obs["t"] > 0
    assert ag.sectors.n_obs["BTC"] == direct_hub.n_obs["BTC"]


# ------------------------------------------------------------------------------------------ report
def _row(oracle, sid, imp, h, gross, gap=10.0, spread=2.0, lat=0.15, venue="binance", asset="A", lag=0.5, net0=None, net=None, ng=-5.0, t0=1000.0, market="AUSDT"):
    net0 = gross - spread if net0 is None else net0
    return {"oracle": oracle, "sid": sid, "imp": imp, "h": h, "gross": gross, "gap": gap, "spread": spread, "lat": lat, "venue": venue, "asset": asset,
            "lag_s": lag, "net0": net0, "net": net0 - 15.0 if net is None else net, "net_gap": ng, "lsig": 5.0, "fee_in": 7.5, "fee_out": 7.5, "t0": t0, "market": market,
            "ldelta": 8.0, "fair": gap, "hurdle": 1.0}


def test_block_statistics_and_cluster_se():
    rows = []
    for k in range(10):
        imp = 1 + k // 5                                              # 2 impulses x 5 signals
        for h, gr in ((1.0, 1.0), (3.0, 3.0), (5.0, 6.0 if k < 5 else 2.0), (10.0, 8.0), (30.0, 9.0)):
            rows.append(_row("sol", k, imp, h, gr, gap=10.0 + k, spread=2.0))
    b = sr.block(rows)
    assert b["n_sig"] == 10 and b["n_imp"] == 2
    assert b["gap_med"] == pytest.approx(np.median(np.arange(10, 20)))
    assert b["gap_ge"]["10.0"] == 1.0 and b["gap_ge"]["20.0"] == 0.0
    c5 = b["curves"]["5.0"]
    assert c5["gross"] == pytest.approx(4.0) and c5["hit"] == 1.0
    assert c5["gross_se"] == pytest.approx(2.0)                     # two clusters, means 6 and 2 -> sd 2.83 / sqrt(2)
    assert c5["net0"] == pytest.approx(2.0) and c5["breakeven_fee"] == pytest.approx(1.0)
    assert c5["fee_sweep"]["2.0"] == pytest.approx(-2.0)
    assert c5["capture"] == pytest.approx(4.0 / np.mean(np.arange(10, 20)))
    assert b["s2g_med"] == pytest.approx(np.median(2.0 / np.arange(10, 20)))


def test_half_capture_horizon_interpolates():
    curves = {"1.0": {"capture": 0.1}, "3.0": {"capture": 0.3}, "5.0": {"capture": 0.7}, "10.0": {"capture": 0.9}}
    assert sr.half_capture_horizon(curves) == pytest.approx(4.0)
    assert sr.half_capture_horizon({"1.0": {"capture": 0.1}, "5.0": {"capture": 0.2}}) is None


def test_analyse_warmup_trim_baseline_and_render(tmp_path):
    info = {"t_start": 0.0, "t_end": 1000.0, "main_latency_s": 0.15, "config": {"observe_notional_usd": 1000},
            "sectors": [{"name": "sol", "leader": "SOL", "label": "L1", "variant_of": "", "group": ["SOL", "JUP"], "leader_idx": 1, "members": ["JUPUSDT"]}],
            "markets": [{"id": "JUPUSDT", "venue": "binance", "asset": "JUP", "kind": "spot", "fee_taker_bps": 7.5}],
            "summary": {"BTC": {"members": 5, "calibrated": 5, "impulses": 3, "scans": 10, "signals": 4, "gap_vol_mult": 0.0},
                        "sol": {"members": 2, "calibrated": 2, "impulses": 3, "scans": 10, "signals": 4, "gap_vol_mult": 0.5}}}
    rows = []
    sid = 0
    for oracle, imp0, gap, gr in (("BTC", 1, 1.5, 0.2), ("sol", 10_000_001, 12.0, 4.0)):
        for k in range(6):
            sid += 1
            for h in sr.HZ:
                rows.append(_row(oracle, sid, imp0 + k // 2, h, gr, gap=gap, asset="JUP", market="JUPUSDT", t0=500.0))
    rows.append(_row("sol", 99, 10_000_099, 5.0, 100.0, t0=50.0))                    # inside the warm-up window: must be dropped
    rows.append(_row("sol", 98, 10_000_098, 5.0, 100.0, lat=0.5, t0=500.0))          # other latency: only in the sensitivity table
    for h in sr.HZ:                                                                   # BTC signal on the leader's own Binance market: excluded from the baseline
        rows.append(_row("BTC", 97, 97, h, 100.0, asset="SOL", market="SOLUSDT", t0=500.0))
    d = tmp_path / "run"
    d.mkdir()
    (d / "sector_markouts.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
    (d / "sector_map.json").write_text(json.dumps(info))
    models = {"BTC": [{"market": "JUPUSDT", "lag_s": 0.4, "rho": 0.5, "beta": 1.0, "decay_s": 0.3, "calibrated": True}],
              "sol": [{"market": "JUPUSDT", "lag_s": 0.8, "rho": 0.7, "beta": 1.1, "decay_s": 0.5, "calibrated": True}]}
    (d / "sector_models.json").write_text(json.dumps(models))
    res = sr.analyse(sr.load_run(str(d)), warm_s=180.0)
    assert res["oracles"]["sol"]["n_sig"] == 6 and res["oracles"]["BTC"]["n_sig"] == 7        # warm-up row dropped, other-latency row dropped
    assert res["baseline"]["sol"]["n_sig"] == 6                                              # the SOLUSDT BTC row is excluded from the baseline
    assert res["oracles"]["sol"]["curves"]["5.0"]["gross"] == pytest.approx(4.0)
    assert set(res["latency_sens"]["sol"]) == {"0.15", "0.5"}
    mc = res["models"]["sol"]
    assert mc["lag_med"] == 0.8 and mc["btc_same_markets"]["lag_med"] == 0.4 and mc["paired_lag"]["median_diff"] == pytest.approx(0.4)
    md = sr.render_md(res, notes="NOTE-MARKER")
    for needle in ("NOTE-MARKER", "Headline table", "Same assets, two oracles", "Reaction speed", "By venue", "Fees", "Latency sensitivity"):
        assert needle in md
    assert md.count("| sol |") >= 2


def test_tail_events_and_own_asset_split():
    rows = []
    for k, (gap, venue, asset, imp) in enumerate(((12.0, "hyperliquid", "SOL", 10_000_001), (15.0, "kraken", "JUP", 10_000_001), (3.0, "binance", "JUP", 10_000_002), (30.0, "gate", "JUP", 10_000_003))):
        for h in sr.HZ:
            rows.append(_row("sol", k, imp, h, 4.0, gap=gap, venue=venue, asset=asset, t0=600.0 + k, market=f"m{k}"))
    t = sr.tail_events(rows, t_start=0.0, thr=10.0)
    assert t["n_sig"] == 3 and t["n_imp"] == 2 and [e["n"] for e in t["events"]] == [2, 1]
    assert t["events"][0]["gap"] == pytest.approx(13.5) and set(t["events"][0]["venues"]) == {"hyperliquid", "kraken"}
    assert set(t["venues"]) == {"hyperliquid", "kraken", "gate"}                       # the 3 bps binance signal is not a tail signal
    assert t["pooled"]["curves"]["5.0"]["gross"] == pytest.approx(4.0)


def test_placebo_shift_moves_only_leaders_and_keeps_time_order():
    from quant_agency.run_live import placebo_shift
    t = np.arange(0.0, 100.0, 1.0)
    idx = np.where(np.arange(100) % 4 == 0, 0, np.where(np.arange(100) % 4 == 1, 1, 2))      # BTC, leader, member, member
    b = t * 10.0
    tt, ii, bb, aa, bq, aq = placebo_shift(t, idx, b, b, b, b, {0, 1}, 30.0)
    assert len(tt) == 100 and np.all(np.diff(tt) >= 0)
    assert sorted(tt[ii == 2]) == sorted(t[idx == 2])                                         # member timestamps are untouched
    for j in (0, 1):
        old, new = t[idx == j], tt[ii == j]
        assert sorted(new) == sorted(np.mod(old - t[0] + 30.0, t[-1] - t[0] + 1e-6) + t[0])   # leader streams rotated
    assert bb[np.argsort(tt)][0] == bb[0] and set(bb) == set(b)                               # payloads travel with their timestamps


def test_placebo_block_keeps_clusters_distinct(tmp_path):
    dirs = []
    for k in range(2):
        d = tmp_path / f"p{k}"
        d.mkdir()
        rows = [_row("sol", 1, 10_000_001, h, 1.0 + k, t0=500.0) for h in sr.HZ]            # identical ids in both runs on purpose
        (d / "sector_markouts.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
        (d / "sector_map.json").write_text(json.dumps({"t_start": 0.0, "main_latency_s": 0.15, "placebo_shift": 100.0 * (k + 1)}))
        dirs.append(str(d))
    pb = sr.placebo_block(dirs, 180.0)
    b = pb["oracles"]["sol"]
    assert pb["n_runs"] == 2 and pb["shifts"] == [100.0, 200.0] and b["n_sig"] == 2 and b["n_imp"] == 2
    assert b["curves"]["5.0"]["gross"] == pytest.approx(1.5)
