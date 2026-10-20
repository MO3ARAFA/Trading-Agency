import numpy as np
import pytest

from quant_agency import hl_funding_basis as fb


def _hist(n=3000, seed=1, kind="perp_reverts", dev_bps=40.0, asset="AAA"):
    """Spot random walk; perp = spot + basis. A basis shock (+dev) every 400 minutes decays with a 10-minute half-life, by the perp (or by the spot, or never)."""
    rng = np.random.default_rng(seed)
    spot = 100.0 * np.exp(np.cumsum(rng.normal(0, 2e-4, n)))
    basis = np.full(n, 5.0)                                   # constant 5 bps premium: must not trigger anything
    shock = np.zeros(n)
    for t0 in range(500, n - 100, 400):
        shock[t0:] += 0.0
        shock[t0: t0 + 100] += dev_bps * 0.5 ** (np.arange(100) / 10.0)
    perp = spot * np.exp((basis + (shock if kind != "never" else 0.0)) / fb.BPS)
    if kind == "never":                                       # the shock is permanent (a level shift, not a deviation that closes)
        for t0 in range(500, n - 100, 400):
            perp[t0:] *= np.exp(dev_bps / fb.BPS)
    if kind == "spot_reverts":                                # the spot moves to meet the perp: spot falls by the shock, perp stays
        perp = spot.copy() * np.exp(basis / fb.BPS)
        spot2 = spot * np.exp(-shock / fb.BPS)
        spot2[:] = spot2
        perp = spot * np.exp((basis + 0.0) / fb.BPS)
        perp_level = perp * np.exp(shock / fb.BPS)
        # perp jumps with the shock and stays; spot gives the shock back later: model as spot lagging UP: spot = perp * exp(-(basis+shock decay))
        spot = perp_level * np.exp(-(basis + shock) / fb.BPS)
        perp = perp_level
    return fb.PairHistory(asset, 0, perp, np.full(n, 10.0), spot, np.full(n, 10.0))


def test_constant_premium_is_not_a_dislocation():
    h = _hist(dev_bps=0.0)
    ev = fb.find_events(h, fb.BasisConfig(), 8.0)
    assert ev == []


def test_events_found_with_entry_delay_and_cooldown():
    cfg = fb.BasisConfig()
    h = _hist(dev_bps=40.0)
    ev = fb.find_events(h, cfg, 15.0)
    assert len(ev) >= 5
    ts = [e["t"] for e in ev]
    assert all(b - a >= cfg.cooldown_min for a, b in zip(ts, ts[1:]))
    assert all(e["side"] == 1.0 and e["dev"] > 15.0 for e in ev)                   # perp rich -> short perp / long spot
    assert all(set(e["out"]) <= set(cfg.horizons_min) for e in ev)


def test_perp_reverting_basis_is_earned_on_the_perp_leg_and_hedged():
    s = fb.summarise(fb.find_events(_hist(kind="perp_reverts", dev_bps=60.0), fb.BasisConfig(), 15.0), (15,))
    d = s[15]
    assert d["perp"]["mean"] > 8.0 and abs(d["spot"]["mean"]) < 6.0 and d["hedged"]["mean"] > 8.0
    assert np.isfinite(d["reverted_frac"])                  # measured from the deviation seen at the trigger (which lags a decaying shock), so it can be small even when the perp leg earns
    assert d["net"]["hedged_perp_maker+spot"]["mean"] == pytest.approx(d["hedged"]["mean"] - 18.0)
    assert d["net"]["perp_only_maker"]["mean"] == pytest.approx(d["perp"]["mean"] - 3.0)


def test_permanent_level_shift_does_not_revert():
    s = fb.summarise(fb.find_events(_hist(kind="never", dev_bps=60.0), fb.BasisConfig(), 15.0), (30,))
    assert s[30]["perp"]["mean"] < 8.0                    # the shift is the new normal after the trailing median catches up; nothing to earn from the perp leg


def test_stale_minutes_are_not_quotes():
    h = _hist(dev_bps=60.0)
    h.hl_n[:] = 0.0                                       # no trades on the perp: every minute is a stale print
    assert np.isnan(fb.basis_series(h, fb.BasisConfig())).all()
    assert fb.find_events(h, fb.BasisConfig(), 8.0) == []


def test_train_test_split_selects_on_train_only():
    hs = [_hist(seed=s, kind="perp_reverts", dev_bps=50.0, asset=f"C{s}") for s in range(4)]
    r = fb.basis_study(hs, fb.BasisConfig(thresholds_bps=(15.0, 30.0)), split_frac=0.5, min_events=5)
    assert r["selected"] is not None and r["selected"]["thr"] in ("15.0", "30.0")
    assert r["cut_min"] == r["n_min"] // 2
    assert all(e["t"] < r["cut_min"] for e in r["events_train"]["15.0"]) and all(e["t"] >= r["cut_min"] for e in r["events_test"]["15.0"])


def test_cluster_mean():
    m, se, k = fb.cluster_mean([1, 1, 3, 3], ["a", "a", "b", "b"])
    assert m == 2 and k == 2 and se == pytest.approx(np.sqrt(8) / 4)
    assert fb.cluster_mean([], [])[2] == 0


def test_funding_study_levels_runs_and_breakeven():
    f = np.full(500, 1.25e-5)
    f[100:110] = 6e-4                                      # a 10-hour run at 6 bps/h
    h = fb.PairHistory("X", 0, np.ones(10), np.ones(10), np.ones(10), np.ones(10), np.column_stack([np.arange(500) * 3.6e6, f]))
    s = fb.funding_study([h])
    assert s["coin_hours"] == 500 and s["median_bps_h"] == pytest.approx(0.125)
    assert s["share_ge"]["5.0"]["pos"] == pytest.approx(10 / 500)
    assert s["runs_pos"]["5.0"]["episodes"] == 1 and s["runs_pos"]["5.0"]["median_h"] == 10 and s["runs_pos"]["5.0"]["share_ge_6h"] == 1.0
    assert s["persistence_pos"]["5.0"]["starts"] == 10 and s["persistence_pos"]["5.0"]["carry_1h_bps"] > 5.0
    assert s["breakeven_hours"]["hedged_perp_maker+spot"]["0.125"] == pytest.approx(18.0 / 0.125)         # 144 h at the floor
    assert s["breakeven_hours"]["perp_only_maker"]["3.0"] == pytest.approx(1.0)


def test_cache_roundtrip(tmp_path):
    h = _hist(n=200)
    h.funding = np.array([[0.0, 1e-5], [3.6e6, 2e-5]])
    p = str(tmp_path / "c.npz")
    fb.save_cache(p, [h])
    g = fb.load_cache(p)[0]
    assert g.asset == "AAA" and np.allclose(g.hl_close, h.hl_close) and np.allclose(g.funding, h.funding)


def test_bankroll_constraints():
    b = fb.Bankroll()
    assert b.can_open(0.0, 100.0) and b.can_open(160.0, 100.0) and not b.can_open(190.0, 100.0)      # 2x leverage cap
    assert not b.can_open(60.0, 100.0, n_open=4)                                  # at most 4 concurrent positions
    assert not b.can_open(0.0, 85.0)                                             # past the -10 % stop
    assert fb.dollars(100.0, 20.0) == pytest.approx(0.2)


# ------------------------------------------------------------------------------------------ hourly premium test
def _hourly_world(effect_bps=0.0, ncoins=12, n=1500, seed=3):
    """Hourly bars. Each coin gets a +60 bps perp premium that lasts one bar every ~40 bars; with ``effect_bps`` the coin's *spot* then drifts down by that much over the next 4 bars."""
    rng = np.random.default_rng(seed)
    mkt = np.cumsum(rng.normal(0, 30e-4, n))
    hs = []
    for c in range(ncoins):
        idio = rng.normal(0, 40e-4, n)
        shocks = [t for t in range(60 + 5 * c, n - 90, 40)]
        for t in shocks:
            idio[t + 1: t + 5] -= effect_bps / 4 / fb.BPS
        spot = 100 * np.exp(mkt + np.cumsum(idio))
        basis = np.full(n, 3.0)
        for t in shocks:
            basis[t] += 60.0
        perp = spot * np.exp(basis / fb.BPS)
        hs.append(fb.PairHistory(f"C{c}", 0, perp, np.full(n, 20.0), spot, np.full(n, 20.0)))
    return hs


def test_premium_test_detects_a_planted_effect_and_not_a_null():
    spec = dict(fb.PREMIUM_PRIMARY)
    real = fb.premium_test(_hourly_world(effect_bps=150.0), spec=spec)
    assert real["decision"] == "REJECT H0 (net > 0)" and real["primary"]["net_neutral"]["mean"] > 100.0
    assert real["primary"]["share_short_perp"] == 1.0                                   # every planted premium is a rich perp
    null = fb.premium_test(_hourly_world(effect_bps=0.0), spec=spec)
    assert null["decision"] in ("do not reject H0", "REJECT H0 (net > 0)") and abs(null["primary"]["neutral"]["mean"]) < 60.0
    assert null["primary"]["hedged"]["mean"] == pytest.approx(60.0, abs=5.0)           # here the premium is a one-bar spike that reverts, and the hedged spread earns exactly that


def test_premium_test_never_uses_the_discovery_window_and_needs_clusters():
    hs = _hourly_world(effect_bps=150.0, n=1500)
    spec = dict(fb.PREMIUM_PRIMARY)
    r = fb.premium_test(hs, spec=spec)
    assert r["bars_used"] == 1500 - spec["exclude_last_bars"]
    ev = fb.premium_events(hs, fb.HOURLY, 30.0, r["bars_used"])
    assert ev and max(e["t"] + 4 for e in ev) < r["bars_used"] + 1
    small = fb.premium_test(_hourly_world(effect_bps=150.0, ncoins=1, n=400), spec=spec)
    assert small["decision"].startswith("underpowered") or small["decision"].startswith("no events")


def test_market_neutral_adjustment_removes_a_common_drift():
    hs = _hourly_world(effect_bps=0.0)
    for h in hs:                                                                         # add a strong common downtrend to spot AND perp: the raw short-perp leg 'earns' it, the neutral one must not
        drift = np.exp(-np.arange(len(h.bn_close)) * 20e-4)
        h.bn_close = h.bn_close * drift
        h.hl_close = h.hl_close * drift
    r = fb.premium_test(hs, spec=dict(fb.PREMIUM_PRIMARY))["cells"]["30|4"]
    assert r["raw_perp"]["mean"] > 40.0 and abs(r["neutral"]["mean"]) < 0.5 * r["raw_perp"]["mean"]


def _tape(tmp_path, shock_bps=30.0, revert=False, seconds=3400):
    """One pair, 1 Hz quotes on both venues; a basis shock at t=2400 s (perp jumps up by shock_bps) that either stays or reverts after 300 s."""
    rng = np.random.default_rng(2)
    t = np.arange(0.0, seconds, 1.0)
    spot = 100.0 * np.exp(np.cumsum(rng.normal(0, 1e-5, len(t))))
    basis = np.full(len(t), 3.0)
    basis[2400:] += shock_bps
    if revert:
        basis[2700:] -= shock_bps
    perp = spot * np.exp(basis / fb.BPS)
    rows = []
    for k, tt in enumerate(t):
        rows.append((tt, 0, spot[k] * (1 - 1e-5), spot[k] * (1 + 1e-5)))
        rows.append((tt + 0.01, 1, perp[k] * (1 - 1e-4), perp[k] * (1 + 1e-4)))
    a = np.array(rows)
    metas = [{"id": "AAAUSDT"}, {"id": "hyperliquid:AAA"}]
    extra = {"xv": {"pairs": [{"asset": "AAA", "binance": "AAAUSDT", "hl": "hyperliquid:AAA"}]}}
    p = str(tmp_path / "tape.npz")
    np.savez_compressed(p, t=a[:, 0], i=a[:, 1].astype(np.int32), b=a[:, 2], a=a[:, 3], metas=np.array(json.dumps(metas)), extra=np.array(json.dumps(extra)))
    return p


import json


def test_tape_basis_study_finds_the_shock_and_prices_at_the_touch(tmp_path):
    cfg = fb.TapeBasisConfig(eq_lo_s=1200, eq_hi_s=120, eq_min_valid=600, thresholds_bps=(15.0,), horizons_s=(300,), cooldown_s=900)
    r = fb.tape_basis_study(_tape(tmp_path, 30.0, revert=True), cfg)
    assert r["events"] == 1
    e = r["events_rows"][0]
    assert e["side"] == 1.0 and 2400 <= e["t"] <= 2500 and e["dev"] > 15.0
    c = r["cells"]["15|300"]
    assert c["spread_h"] == pytest.approx(2.0, abs=0.2) and c["spread_b"] == pytest.approx(0.2, abs=0.1)
    assert c["hedged_mid"]["mean"] > 20.0                                              # the shock reverts after 300 s: the hedged spread earns it (mid to mid)
    assert c["hedged_cross"]["mean"] < c["hedged_mid"]["mean"] - 1.5                    # crossing both spreads costs ~2.2 bps


def test_tape_basis_study_permanent_shift_earns_nothing(tmp_path):
    cfg = fb.TapeBasisConfig(eq_lo_s=1200, eq_hi_s=120, eq_min_valid=600, thresholds_bps=(15.0,), horizons_s=(300,), cooldown_s=900)
    r = fb.tape_basis_study(_tape(tmp_path, 30.0, revert=False), cfg)
    assert r["events"] == 1 and abs(r["cells"]["15|300"]["hedged_mid"]["mean"]) < 6.0
