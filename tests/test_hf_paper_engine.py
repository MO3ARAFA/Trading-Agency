import json
import math
import os

import pytest

from quant_agency import hf_paper_engine as hf
from quant_agency.meme_discovery import Quote, TokenCreated, TradePrint, curve_buy, curve_sell
from quant_agency.omega_governance import GovConfig, OState

SOL = 100.0


def _eng(tmp_path=None, **kw):
    gov = kw.pop("gov", None) or GovConfig(kill_file=str(tmp_path / "KILL") if tmp_path else "/nonexistent/KILL", review_every_s=0.0)
    e = hf.HFPaperEngine(hf.EngineConfig(gov=gov, **kw), out_dir=str(tmp_path / "out") if tmp_path else None)
    e.set_sol_usd(SOL)
    return e


def _pp(t, vs, vt, side=1, fee=125.0, user="u", key="m", real=None):
    px = vs / vt
    return TradePrint(t, "pump", key, side, 1e5, 1e5 * px, px, px, vs, vt, (vs - 30.0) if real is None else real, fee, user)


def _ready_pump(e, key="m", vs=40.0, vt=8e8):
    e.on_create(TokenCreated(-100.0, key, "N", "SYM", "dev"))
    e.on_print(_pp(0.0, vs, vt, key=key))
    st = e.uni.tokens[key]
    e.set_safety(key, {"mint_authority": None, "freeze_authority": None, "top10_share": 0.1})
    return st


def _open(e, st, sleeve="meme_momentum", stop=0.08, tp=0.15, passive=False):
    e._open(sleeve, st, stop, tp, 0.06, 0.05, 90.0, "test", passive=passive)


def test_sizing_rules(tmp_path):
    e = _eng(tmp_path)
    st = _ready_pump(e)
    assert e.size_usd("meme_momentum", st, 0.08) == pytest.approx(5.0)          # max trade
    assert e.size_usd("meme_momentum", st, 0.6) == pytest.approx(2.5)           # 1.5 USD risk / 60 % stop
    assert e.size_usd("meme_momentum", st, 0.9) == 0.0                          # 1.67 USD < 2 USD floor: no trade
    e.ceo.books["meme_momentum"].state = OState.PROBATION
    assert e.size_usd("meme_momentum", st, 0.08) == pytest.approx(2.5)
    e.ceo.books["meme_momentum"].state = OState.QUARANTINED
    assert e.size_usd("meme_momentum", st, 0.08) == 0.0
    g = e.uni.get("P_USDT", "gate", 0.0)
    g.min_notional = 3.0
    e.ceo.books["breakout_scalp"].state = OState.PROBATION                       # 2.5 USD < Gate's 3 USD minimum
    assert e.size_usd("breakout_scalp", g, 0.006) == 0.0


def test_pump_fill_as_of_landing_with_fees_and_adverse_model(tmp_path):
    e = _eng(tmp_path, pump_latency_s=1.0)
    st = _ready_pump(e)
    _open(e, st)
    assert len(e.pending) == 1
    e.on_print(_pp(0.5, 41.0, 7.8e8))                    # lands on this state (last print before landing)
    e.on_print(_pp(0.9, 40.5, 7.9e8))
    e.on_print(_pp(1.5, 45.0, 7.0e8))                    # after landing: must not be used
    pos = next(iter(e.positions.values()))
    sol_in = 5.0 / SOL - (e.cfg.sol_tx_fee_sol + e.cfg.sol_priority_fee_sol)
    tok, fee_sol, _ = curve_buy(40.5, 7.9e8, sol_in, 125.0)
    assert pos.qty == pytest.approx(math.floor(tok / 1e-6) * 1e-6)
    assert pos.cost_usd == pytest.approx(5.0)
    assert pos.fees_usd == pytest.approx((fee_sol + 0.000105) * SOL)
    worst_tok, _, _ = curve_buy(41.0, 7.8e8, sol_in, 125.0)                      # the worst state seen while in flight
    assert pos.shadow["adverse"]["qty"] == pytest.approx(math.floor(worst_tok / 1e-6) * 1e-6)
    assert pos.shadow["adverse"]["qty"] < pos.qty


def test_zero_reported_fee_is_floored(tmp_path):
    e = _eng(tmp_path, pump_latency_s=0.5)
    st = _ready_pump(e)
    e.on_print(_pp(0.1, 40.0, 8e8, fee=0.0))
    assert e._fee_bps(st) == 125.0


def test_slippage_limit_fails_the_transaction(tmp_path):
    e = _eng(tmp_path, pump_latency_s=1.0, pump_slippage_bps=500)
    st = _ready_pump(e)
    _open(e, st)
    e.on_print(_pp(0.5, 44.0, 7.3e8))                    # +20 % before landing
    e.poll(1.2)
    b = e.ceo.books["meme_momentum"]
    assert not e.positions and e.stats["failed_tx"] == 1
    assert b.cash == pytest.approx(40.0 - 0.000105 * SOL)


def test_stop_exit_and_round_trip_accounting(tmp_path):
    e = _eng(tmp_path, pump_latency_s=0.5)
    st = _ready_pump(e)
    _open(e, st)
    e.poll(0.6)
    pos = next(iter(e.positions.values()))
    e.on_print(_pp(1.0, 36.0, 8.9e8, side=-1))           # about -18 %: stop
    assert pos.closing
    e.poll(1.6)
    assert not e.positions
    rt = e.recent[-1]
    got, _, _ = curve_sell(36.0, 8.9e8, pos.qty, 125.0)
    assert rt["reason_out"] == "stop" and rt["got_usd"] == pytest.approx((got - 0.000105) * SOL, abs=1e-5)
    b = e.ceo.books["meme_momentum"]
    assert b.round_trips == 1 and b.cash == pytest.approx(40.0 - 5.0 + rt["got_usd"], abs=1e-4)
    assert e.ceo.equity == pytest.approx(100.0 + rt["pnl_usd"], abs=1e-4)


def test_creator_dump_and_time_stop_exits(tmp_path):
    e = _eng(tmp_path, pump_latency_s=0.5)
    st = _ready_pump(e)
    e.on_print(_pp(0.2, 40.0, 8e8, user="dev"))
    _open(e, st)
    e.poll(0.6)
    e.on_print(_pp(1.0, 40.0, 8e8, side=-1, user="dev"))  # the creator sells more than half of what he bought
    assert next(iter(e.positions.values())).closing
    e.poll(2.0)
    assert e.recent[-1]["reason_out"] == "creator_dump"
    st2 = _ready_pump(e, key="m2")
    _open(e, st2)
    e.poll(2.6)
    e.poll(200.0)
    e.poll(201.0)
    assert e.recent[-1]["reason_out"] == "time_stop"


def test_one_position_per_token_max_open_and_rate_cap(tmp_path):
    e = _eng(tmp_path, pump_latency_s=0.5, max_open_per_sleeve=2)
    st = _ready_pump(e)
    _open(e, st)
    e.poll(0.6)
    e._entries(st)                                       # already holding: nothing new
    assert len(e.pending) == 0
    for k in ("a", "b", "c"):
        _open(e, _ready_pump(e, key=k))
    assert e.stats["skip_meme_momentum_max_open"] == 2
    e2 = _eng(tmp_path, gov=GovConfig(kill_file=str(tmp_path / "K2"), max_fills_per_hour=2, review_every_s=0.0))
    s2 = _ready_pump(e2)
    e2.ceo.note_fill(0.0)
    _open(e2, s2)
    assert e2.stats["skip_rate_cap"] == 1 and not e2.pending


def test_quarantine_flattens_only_that_sleeve(tmp_path):
    e = _eng(tmp_path, pump_latency_s=0.5)
    st = _ready_pump(e)
    _open(e, st)
    e.poll(0.6)
    e.ceo.books["meme_momentum"].mark(next(iter(e.positions)), -1.0)          # -6 USD: breach
    e.poll(1.0)
    assert e.ceo.books["meme_momentum"].state == OState.QUARANTINED
    e.poll(2.0)
    assert not e.positions and e.recent[-1]["reason_out"] == "governance_flatten"
    assert e.ceo.books["breakout_scalp"].state == OState.NORMAL


def _gate(e, pair="P_USDT", lot=0.01, minq=3.0):
    e.set_pair_rules([{"pair": pair, "lot": lot, "min_quote": minq, "min_base": 0.0, "fee_bps": 20.0, "quote_vol": 1e6}])
    return e.uni.tokens[pair]


def test_gate_taker_fill_beyond_top_of_book(tmp_path):
    e = _eng(tmp_path, gate_latency_s=0.1)
    st = _gate(e)
    e.on_quote(Quote(0.0, "gate", "P_USDT", 0.999, 1.0, 100.0, 3.0))
    _open(e, st, sleeve="breakout_scalp", stop=0.006)
    e.on_quote(Quote(0.2, "gate", "P_USDT", 0.999, 1.0, 100.0, 3.0))
    pos = next(iter(e.positions.values()))
    qty = math.floor(5.0 / 1.002 / 1.0 / 0.01) * 0.01
    notional = 3.0 * 1.0 + (qty - 3.0) * 1.001
    assert pos.qty == pytest.approx(qty) and pos.cost_usd == pytest.approx(notional * 1.002)


def test_gate_passive_entry_runs_three_queue_models(tmp_path):
    e = _eng(tmp_path, gate_latency_s=0.1)
    st = _gate(e)
    for i in range(3):
        e.on_quote(Quote(i * 0.1, "gate", "P_USDT", 1.0, 1.002, 100.0, 100.0))
    _open(e, st, sleeve="breakout_scalp", stop=0.006, passive=True)
    e.on_quote(Quote(0.5, "gate", "P_USDT", 1.0, 1.002, 100.0, 100.0))          # resting behind 100 at the bid
    e.on_print(TradePrint(0.6, "gate", "P_USDT", -1, 103.0, 103.0, 1.0))        # sells 103 at our price: queue ahead 100, we get 3
    assert not e.positions                                                     # partial
    e.on_print(TradePrint(0.7, "gate", "P_USDT", -1, 5.0, 4.995, 0.999))        # trades through: rest filled
    pos = next(iter(e.positions.values()))
    assert pos.entry_px == pytest.approx(1.0) and pos.shadow["strict"] == {"filled": False}
    assert pos.shadow["depletion"] == {"filled": False}                        # displayed size never dropped


def test_passive_entry_expires(tmp_path):
    e = _eng(tmp_path, gate_latency_s=0.1)
    st = _gate(e)
    for i in range(3):
        e.on_quote(Quote(i * 0.1, "gate", "P_USDT", 1.0, 1.002, 100.0, 100.0))
    _open(e, st, sleeve="breakout_scalp", stop=0.006, passive=True)
    e.poll(30.0)
    assert not e.pending and e.stats["passive_expired"] == 1


def test_audit_flush_bounds_memory_and_snapshot_resume(tmp_path):
    e = _eng(tmp_path, pump_latency_s=0.5, flush_every_s=300.0, snapshot_every_s=60.0)
    st = _ready_pump(e)
    _open(e, st)
    e.poll(0.6)
    assert e.audit
    e.poll(301.0)
    assert e.audit == [] and os.path.getsize(tmp_path / "out" / "omega_audit.jsonl") > 0
    snap = tmp_path / "out" / "omega_state.json"
    assert snap.exists()
    e2 = _eng(tmp_path)
    e2.load_snapshot(str(snap))
    assert set(e2.positions) == set(e.positions) and e2.ceo.books["meme_momentum"].cash == pytest.approx(e.ceo.books["meme_momentum"].cash)


def test_momentum_signal_on_a_burst(tmp_path):
    e = _eng(tmp_path, pump_latency_s=0.5)
    e.on_create(TokenCreated(-300.0, "m", "N", "SYM", "dev"))
    vs, vt = 40.0, 8e8
    for i in range(60):                                  # quiet two minutes
        t = -120.0 + 2 * i
        e.on_print(_pp(t, vs, vt, side=1 if i % 2 else -1, user=f"q{i}"))
    e.set_safety("m", {"mint_authority": None, "freeze_authority": None, "top10_share": 0.1})
    for i in range(20):                                  # then 20 buys from 20 wallets in 20 s: +~10 %
        vs2 = vs + 0.12
        vt = vs * vt / vs2
        vs = vs2
        p = TradePrint(i * 1.0, "pump", "m", 1, 1e5, 0.12, vs / vt, vs / vt, vs, vt, vs - 30.0, 125.0, f"b{i}")
        e.on_print(p)
    assert e.stats["signal_momentum"] >= 1 and (e.pending or e.positions)
