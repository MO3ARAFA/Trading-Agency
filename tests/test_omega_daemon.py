import json
import os

import pytest

from quant_agency import omega_daemon as od
from quant_agency.hf_paper_engine import HFPaperEngine
from quant_agency.omega_synth import SynthMarket


def test_synthetic_run_writes_artifacts_and_replay_is_identical(tmp_path):
    mk = SynthMarket(seed=3)
    tape = str(tmp_path / "tape.jsonl.gz")
    a = od.run_offline(mk.events(600), str(tmp_path / "a"), 600, 0.0, facts=mk.facts, record=tape)
    for f in ("omega_audit.jsonl", "omega_state.json", "omega_status.jsonl", "omega_summary.json"):
        assert os.path.exists(tmp_path / "a" / f)
    b = od.run_offline(od.read_tape(tape), str(tmp_path / "b"), 600, 0.0, facts=None)
    assert a["status"]["fills"] > 0
    assert a["status"]["fills"] == b["status"]["fills"] and a["status"]["equity"] == pytest.approx(b["status"]["equity"])
    assert a["model_pnl"] == b["model_pnl"]                       # the tape carries the safety answers: replay is exact


def test_dispatch_handles_every_event_kind():
    eng = HFPaperEngine(social_enabled=True)
    t = 1000.0
    for ev in ({"kind": "sol", "t": t, "px": 150.0},
               {"kind": "rules", "t": t, "rows": [{"pair": "X_USDT", "lot": 1.0, "min_quote": 3.0, "min_base": 0.0, "fee_bps": 20.0, "quote_vol": 1.0}]},
               {"kind": "create", "t": t, "mint": "m", "name": "N", "symbol": "S", "creator": "c"},
               {"kind": "print", "t": t, "venue": "pump", "key": "m", "side": 1, "qty": 1.0, "quote": 1e-8, "price": 1e-8, "v_quote": 31.0, "v_base": 1e9},
               {"kind": "quote", "t": t, "venue": "gate", "key": "X_USDT", "bid": 1.0, "ask": 1.01, "bq": 5.0, "aq": 5.0},
               {"kind": "tweet", "id": "1", "t": t, "author": "a", "text": "$S moon", "symbols": ["$S"]},
               {"kind": "safety", "t": t, "key": "m", "facts": {"mint_authority": None}},
               {"kind": "twitter", "t": t, "key": "m", "handle": "proj"},
               {"kind": "complete", "t": t, "mint": "m"}):
        od.dispatch(eng, ev)
    st = eng.uni.tokens["m"]
    assert eng.sol_usd == 150.0 and st.complete and st.twitter == "proj" and st.safety is not None and eng.social.tweets == 1
    assert eng.uni.tokens["X_USDT"].min_notional == 3.0


def test_truncated_tape_is_read_up_to_the_cut(tmp_path):
    import gzip
    p = tmp_path / "t.jsonl.gz"
    with gzip.open(p, "wt") as f:
        f.write(json.dumps({"kind": "sol", "t": 1.0, "px": 1.0}) + "\n" + '{"kind": "pr')
    assert [e["kind"] for e in od.read_tape(str(p))] == ["sol"]


def _footprint(eng):
    return {"tokens": len(eng.uni.tokens), "trackers": len(eng.social.trackers), "tweets_held": sum(len(t.ring) for t in eng.social.trackers.values()),
            "seen": len(eng.social.seen), "pending": len(eng.pending), "positions": len(eng.positions), "audit": len(eng.audit),
            "last_eval": len(eng.last_eval), "quotes": len(eng.quotes), "safety_asked": len(eng.safety_asked), "recent": len(eng.recent),
            "fill_times": len(eng.ceo.fill_times), "eq_hist": sum(len(b.eq_hist) for b in eng.ceo.books.values())}


def test_engine_state_is_bounded_over_synthetic_hours():
    """Every container the engine holds stops growing once its window is full: its peak size in synthetic hour 2-3 is not larger than
    in hour 1-2 (30 % slack for the market's own randomness). RSS over a long run is measured by the smoke test."""
    mk = SynthMarket(seed=11, create_rate=0.15, n_pairs=2, tweet_scale=0.3)
    eng = HFPaperEngine(social_enabled=True)
    samples = []
    last = None
    next_sample = 3600.0
    for ev in mk.events(3 * 3600):
        t = ev["t"]
        if last is None:
            last = t0 = t
        while t - last >= 0.5:
            last += 0.5
            eng.poll(last)
        od.dispatch(eng, ev, mk.facts)
        if t - t0 >= next_sample:                      # every 10 minutes after the first hour (all windows full)
            next_sample += 600.0
            samples.append(_footprint(eng))
    half = len(samples) // 2
    for k in samples[0]:
        if k == "seen":                                  # a count-capped LRU (checked against its cap below), not a time window
            continue
        first, second = max(s[k] for s in samples[:half]), max(s[k] for s in samples[half:])
        assert second <= max(1.3 * first, first + 50), f"{k}: peak {first} in hour 1-2 -> {second} in hour 2-3"
    assert max(s["audit"] for s in samples) < eng.cfg.audit_cap and max(s["seen"] for s in samples) <= eng.social.dedup
    assert max(s["tweets_held"] for s in samples) <= eng.social.max_symbols * 1000


def test_signal_study_scores_signals_on_a_tape(tmp_path):
    from quant_agency.omega_signal_study import study
    from quant_agency.omega_synth import write_tape
    mk = SynthMarket(seed=5, create_rate=1.0, n_pairs=0)
    p = str(tmp_path / "t.jsonl.gz")
    write_tape(p, mk.events(900))
    r = study([p])
    assert r["signals"] > 0 and r["round_trip_cost"] == pytest.approx(2 * 0.0125 + 2 * 0.000105 * 180.0 / 5.0)
    h = r["horizons"]["30"]
    assert h["n"] > 0 and h["net_mean"] == pytest.approx(h["gross_mean"] - r["round_trip_cost"], abs=1e-5)
