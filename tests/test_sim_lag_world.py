import json

import numpy as np

from quant_agency.sim_lag_world import WorldCfg, make_world, save_world


def test_world_is_deterministic_sorted_and_has_prints_and_specs(tmp_path):
    a = make_world(WorldCfg(regime="volatile", duration_s=60.0, seed=3))
    b = make_world(WorldCfg(regime="volatile", duration_s=60.0, seed=3))
    assert np.array_equal(a["t"], b["t"]) and np.array_equal(a["b"], b["b"])
    assert np.all(np.diff(a["t"]) >= 0)
    assert (a["i"] < -1).any() and (a["i"] == 0).any()
    ids = [m.id for m in a["metas"]]
    assert ids[0] == "BTCUSDT" and "hyperliquid:BTC" in ids and any(i.startswith("pm:synth") for i in ids)
    assert set(a["extra"]["specs"]) == set(a["extra"]["pm_ids"])
    p = tmp_path / "w.npz"
    save_world(a, str(p))
    z = np.load(p)
    assert json.loads(str(z["extra"]))["world"]["regime"] == "volatile"


def test_lagging_venue_reprices_d_mm_after_binance_and_informed_flow_precedes_it():
    w = make_world(WorldCfg(regime="volatile", duration_s=120.0, seed=5, D_mm_hl=1.0, D_inf=0.3, informed_prob=1.0))
    j = next(j for j in w["jumps"] if j["bps"] > 0)
    i = w["metas"].index(next(m for m in w["metas"] if m.id == "hyperliquid:BTC"))
    m = w["i"] == i
    t, bid = w["t"][m], w["b"][m]
    before = bid[np.searchsorted(t, j["t"]) - 1]
    at_inf = bid[np.searchsorted(t, j["t_done"] + 0.5) - 1]          # after the informed taker, before the market makers
    after = bid[np.searchsorted(t, j["t_done"] + 1.6) - 1]
    assert after > before + 1.0                                       # converged only after D_mm
    prints = (w["i"] == -(i + 2)) & (w["t"] > j["t_done"] + 0.25) & (w["t"] < j["t_done"] + 0.45)
    assert prints.any() and (w["aq"][prints] == 0).all() and (w["bq"][prints] == 1.0).any()      # a buy-aggressor sweep at ~D_inf
    assert at_inf <= after
