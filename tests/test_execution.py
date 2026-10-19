import pytest

from quant_agency.cfo_agent import CFOAgent
from quant_agency.config import CFOConfig
from quant_agency.execution_engine import ExecutionEngine
from tests.conftest import make_book, mk_signal

LAT = 0.15


def _setup(fee=1.0, **cfo_kw):
    book = make_book(tick=0.01, step=0.001)
    cfo = CFOAgent(book, CFOConfig(fee_taker_bps=fee, fee_maker_bps=fee, latency_s=LAT, **cfo_kw))
    eng = ExecutionEngine(book, cfo)
    book.on_quote(1, 99.0, 99.99, 100.01, 5000.0, 5000.0)
    return book, cfo, eng


def _approved(cfo, **sig_kw):
    sig = mk_signal(**sig_kw)
    dec = cfo.evaluate(sig, sig.t)
    assert dec.approved, dec.reason
    return sig, dec


def test_taker_payload_is_ioc_with_tick_rounded_limit_above_ask():
    book, cfo, eng = _setup()
    sig, dec = _approved(cfo, gap_bps=30.0)
    p = eng.prepare(sig, dec, 100.0)
    assert p.order_type == "LIMIT" and p.time_in_force == "IOC" and p.side == "BUY"
    assert p.price >= sig.ask and p.price <= sig.ask * 1.002
    assert abs(p.price / 0.01 - round(p.price / 0.01)) < 1e-6              # on the tick grid
    assert abs(p.qty / 0.001 - round(p.qty / 0.001)) < 1e-6                # on the step grid
    assert p.qty * p.price <= dec.notional + 0.1
    assert p.tp_price > sig.mid > p.stop_price                             # convergence TP above, adverse stop below
    assert 10.0 <= p.time_stop_s <= 30.0
    ep = p.exchange_params()
    assert ep["type"] == "LIMIT" and ep["timeInForce"] == "IOC" and ep["symbol"] == "ALT1USDT"


def test_maker_payload_joins_the_touch_post_only():
    book, cfo, eng = _setup()
    cfo.apply_directive({"mode_policy": "maker_only"})
    sig, dec = _approved(cfo, gap_bps=30.0, side=1)
    p = eng.prepare(sig, dec, 100.0)
    assert p.order_type == "LIMIT_MAKER" and p.price == pytest.approx(sig.bid)
    sig2, dec2 = _approved(cfo, gap_bps=-30.0, side=-1, sid=2)
    p2 = eng.prepare(sig2, dec2, 100.0)
    assert p2.side == "SELL" and p2.price == pytest.approx(sig2.ask) and p2.tp_price < sig2.mid < p2.stop_price


def test_taker_fills_at_asof_quote_not_a_later_one_and_closes_on_take_profit():
    book, cfo, eng = _setup(fee=1.0)
    sig, dec = _approved(cfo, gap_bps=30.0)
    p = eng.prepare(sig, dec, 100.0)
    assert eng.submit(p, sig, dec, 100.0)
    book.on_quote(1, 100.0, 99.99, 100.01, 5000, 5000)
    book.on_quote(1, 100.40, 100.20, 100.22, 5000, 5000)       # market jumps AFTER order arrival (t=100.15)
    assert eng.poll(100.2) == []
    pos = eng.positions[1]
    assert pos.entry_px == pytest.approx(100.01)                # filled at as-of(100.15), no look-ahead
    assert cfo.exposure["ALT1USDT"] > 0
    eng.on_quote(1, 100.40)                                     # mid 100.21 >= tp -> take profit triggered
    assert pos.exit_reason == "take_profit"
    book.on_quote(1, 101.0, 100.30, 100.32, 5000, 5000)
    out = eng.poll(100.40 + LAT + 0.01)
    assert len(out) == 1
    tr = out[0]
    assert tr.exit_reason == "take_profit" and tr.exit_px == pytest.approx(100.20)   # sells at the bid as-of exit time
    fees = pos.qty * 100.01 * 1e-4 + pos.qty * 100.20 * 1e-4
    assert tr.net_pnl_usd == pytest.approx(pos.qty * (100.20 - 100.01) - fees, rel=1e-9)
    assert tr.R == pytest.approx(tr.net_pnl_usd / (tr.notional * pos.p.stop_bps / 1e4))
    assert "ALT1USDT" not in cfo.exposure and cfo.equity == pytest.approx(10000 + tr.net_pnl_usd)


def test_adverse_stop_and_time_stop():
    book, cfo, eng = _setup()
    sig, dec = _approved(cfo, gap_bps=30.0)
    p = eng.prepare(sig, dec, 100.0); eng.submit(p, sig, dec, 100.0)
    book.on_quote(1, 100.0, 99.99, 100.01, 5000, 5000)
    eng.poll(100.2)
    book.on_quote(1, 100.5, 99.50, 99.52, 5000, 5000)           # -50 bps: through the stop
    eng.on_quote(1, 100.5)
    out = eng.poll(100.8)
    assert out and out[0].exit_reason == "adverse_stop" and out[0].net_pnl_usd < 0
    # time stop with no further quotes
    sig2, dec2 = _approved(cfo, gap_bps=30.0, sid=2, t=200.0)
    p2 = eng.prepare(sig2, dec2, 200.0); eng.submit(p2, sig2, dec2, 200.0)
    book.on_quote(1, 200.0, 99.99, 100.01, 5000, 5000)
    eng.poll(200.2)
    assert eng.poll(200.2 + p2.time_stop_s - 1.0) == []
    out2 = eng.poll(200.2 + p2.time_stop_s + 1.0)
    assert out2 and out2[0].exit_reason == "time_stop"


def test_ioc_rejected_when_price_moved_through_limit():
    book, cfo, eng = _setup()
    sig, dec = _approved(cfo, gap_bps=30.0)
    p = eng.prepare(sig, dec, 100.0); eng.submit(p, sig, dec, 100.0)
    book.on_quote(1, 100.1, 100.30, 100.32, 5000, 5000)         # market already ran away before arrival
    eng.poll(100.2)
    assert not eng.positions and eng.rejected_exec.get("ioc_price_moved") == 1 and 1 not in eng.active_idx


def test_maker_fills_only_when_market_trades_through_and_expires_otherwise():
    book, cfo, eng = _setup()
    cfo.apply_directive({"mode_policy": "maker_only"})
    sig, dec = _approved(cfo, gap_bps=40.0)
    p = eng.prepare(sig, dec, 100.0); eng.submit(p, sig, dec, 100.0)
    eng.poll(100.2)                                             # arrives, rests at the bid 99.99
    assert not eng.positions and 1 in eng.pending_idx
    book.on_quote(1, 100.5, 99.99, 100.01, 5000, 5000)          # same quote: touching is NOT a fill
    eng.on_quote(1, 100.5)
    assert not eng.positions
    book.on_quote(1, 101.0, 99.97, 99.99, 5000, 5000)           # ask drops to our bid: sellers came through
    eng.on_quote(1, 101.0)
    assert eng.positions[1].entry_px == pytest.approx(99.99) and eng.positions[1].p.mode == "maker"
    # second order never fills -> TTL expiry, feeds the realised fill probability
    sig2, dec2 = _approved(cfo, gap_bps=40.0, sid=2, t=300.0, idx=2, market="ALT2USDT", bid=49.99, ask=50.01, mid=50.0)
    book.on_quote(2, 300.0, 49.99, 50.01, 5000, 5000)
    p2 = eng.prepare(sig2, dec2, 300.0); eng.submit(p2, sig2, dec2, 300.0)
    eng.poll(300.2); eng.poll(300.2 + cfo.cfg.maker_ttl_s + 0.1)
    assert eng.rejected_exec.get("maker_ttl_expired") == 1 and 2 not in eng.pending_idx


def test_post_only_that_would_cross_is_rejected():
    book, cfo, eng = _setup()
    cfo.apply_directive({"mode_policy": "maker_only"})
    sig, dec = _approved(cfo, gap_bps=40.0)
    p = eng.prepare(sig, dec, 100.0); eng.submit(p, sig, dec, 100.0)
    book.on_quote(1, 100.1, 99.80, 99.99, 5000, 5000)           # ask fell to our bid before arrival
    eng.poll(100.2)
    assert eng.rejected_exec.get("post_only_would_cross") == 1


def test_flatten_all_cancels_pending_and_closes_positions():
    book, cfo, eng = _setup()
    sig, dec = _approved(cfo, gap_bps=30.0)
    p = eng.prepare(sig, dec, 100.0); eng.submit(p, sig, dec, 100.0)
    book.on_quote(1, 100.0, 99.99, 100.01, 5000, 5000)
    eng.poll(100.2)
    eng.flatten_all(101.0, "kill_switch")
    book.on_quote(1, 101.1, 99.99, 100.01, 5000, 5000)
    out = eng.poll(101.0 + LAT + 0.01)
    assert out and out[0].exit_reason == "kill_switch" and not eng.positions


def test_below_min_notional_is_not_submitted():
    book = make_book(min_notional=1000.0)
    cfo = CFOAgent(book, CFOConfig(fee_taker_bps=1.0))
    eng = ExecutionEngine(book, cfo)
    sig = mk_signal(gap_bps=30.0)
    dec = cfo.evaluate(sig, 1.0)
    assert dec.approved
    assert eng.prepare(sig, dec, 1.0) is None and eng.rejected_exec["below_min_notional"] == 1
