import pytest

from quant_agency import queue_model as qm


def _hist(*quotes):
    h = qm.QuoteHist()
    for q in quotes:
        h.add(*q)
    return h


def _order(side=1, price=100.0, qty=3.0, t_send=1.0, lat=0.15):
    return qm.RestOrder(side, price, qty, t_send, t_send + lat)


def test_arrival_queue_positions_and_post_only_rejection():
    h = _hist((0.9, 100, 101, 10, 10), (1.2, 100, 101, 10, 10))
    out = []
    o = _order()
    qm.advance(o, 1.2, h, out)
    assert o.state == "resting" and o.ahead == 10
    inside = _order(price=100.5)
    qm.advance(inside, 1.2, h, out)
    assert inside.ahead == 0.0
    crossed = _order(price=101.0)
    qm.advance(crossed, 1.2, h, out)
    assert crossed.state == "rejected" and crossed.reject == "post_only_cross"
    ask = _order(side=-1, price=101.0)
    qm.advance(ask, 1.2, h, out)
    assert ask.ahead == 10


def test_strict_needs_a_cross_depletion_does_not():
    for model, expect in (("strict", 0.0), ("depletion", 3.0)):
        h = _hist((0.9, 100, 101, 10, 10))
        o = _order()
        out = []
        qm.advance(o, 1.2, h, out)
        qm.on_quote(o, 1.3, (1.3, 100, 101, 0.0001, 10), model, out)         # displayed size drained to ~0 at our level
        qm.on_quote(o, 1.4, (1.4, 99, 100.5, 10, 10), model, out) if model == "depletion" else None
        assert o.filled == pytest.approx(expect)


def test_trades_consume_queue_then_fill_and_sweep_through():
    h = _hist((0.9, 100, 101, 8, 10))
    o = _order(qty=3.0)
    out = []
    qm.advance(o, 1.2, h, out)
    qm.on_trade(o, 1.3, 100.0, 6.0, -1, "trades", out)
    assert o.ahead == pytest.approx(2.0) and o.filled == 0
    qm.on_trade(o, 1.4, 101.0, 99.0, +1, "trades", out)                         # wrong aggressor: ignored
    assert o.filled == 0
    qm.on_trade(o, 1.5, 100.0, 4.0, -1, "trades", out)
    assert o.filled == pytest.approx(2.0)
    qm.on_trade(o, 1.6, 99.0, 1.0, -1, "trades", out)
    assert o.filled == pytest.approx(3.0) and o.state == "filled"
    assert [f[2] for f in out] == [2.0, 1.0]


def test_cancel_latency_window_fills_flagged_and_after_window_blocked():
    h = _hist((0.9, 100, 101, 10, 10))
    o = _order(qty=2.0)
    out = []
    qm.advance(o, 1.2, h, out)
    assert qm.request_cancel(o, 2.0, 0.15, "shield")
    qm.on_quote(o, 2.1, (2.1, 99, 100, 10, 10), "strict", out)                  # inside the window
    assert o.filled == 2.0 and out[0][3] is True
    o2 = _order(qty=2.0)
    out2 = []
    qm.advance(o2, 1.2, h, out2)
    qm.request_cancel(o2, 2.0, 0.15, "shield")
    qm.advance(o2, 2.2, h, out2)                                                 # cancel effective at 2.15
    qm.on_quote(o2, 2.3, (2.3, 99, 100, 10, 10), "strict", out2)
    assert o2.state == "cancelled" and o2.filled == 0


def test_ask_side_mirror():
    h = _hist((0.9, 100, 101, 10, 6))
    o = _order(side=-1, price=101.0, qty=2.0)
    out = []
    qm.advance(o, 1.2, h, out)
    assert o.ahead == 6
    qm.on_trade(o, 1.3, 101.0, 8.0, +1, "trades", out)
    assert o.filled == pytest.approx(2.0)
    o2 = _order(side=-1, price=101.0, qty=2.0)
    qm.advance(o2, 1.2, h, [])
    out2 = []
    qm.on_quote(o2, 1.4, (1.4, 101, 102, 5, 5), "strict", out2)                  # bid reached our ask
    assert o2.filled == 2.0


def test_cancel_sent_while_inflight_lands_after_the_order_does():
    h = _hist((0.0, 0.49, 0.51, 10.0, 10.0))
    o = qm.RestOrder(+1, 0.49, 5.0, t_send=1.0, t_arr=1.15)
    assert qm.request_cancel(o, 1.05, 0.15, "shield")
    assert o.state == "inflight" and o.cancel_eff == pytest.approx(1.20)          # not instantaneous
    qm.advance(o, 1.16, h, [])
    assert o.state == "cancel_pending"                                            # it did land, and can fill until the cancel does
    qm.advance(o, 1.21, h, [])
    assert o.state == "cancelled"
