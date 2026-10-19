import math

import numpy as np
import pytest

from quant_agency.cfo_agent import CFOAgent
from quant_agency.config import ArbConfig, CFOConfig
from quant_agency.cross_venue_arb import CrossVenueArb
from quant_agency.market_watchers import MarketBook, MarketMeta


def _book(fee_a=0.0, fee_b=0.0, extra_tri=False):
    metas = [MarketMeta("BTCUSDT", "binance", "BTCUSDT", "BTC", asset="BTC", fee_taker_bps=0.0),
             MarketMeta("ETHUSDT", "binance", "ETHUSDT", "ETH", asset="ETH", quote="USDT", fee_taker_bps=fee_a),
             MarketMeta("kraken:ETH/USD", "kraken", "ETH/USD", "ETH", asset="ETH", quote="USD", fee_taker_bps=fee_b)]
    if extra_tri:
        metas += [MarketMeta("ETHBTC", "binance", "ETHBTC", "ETH", asset="ETH", quote="BTC", fee_taker_bps=0.0)]
    return MarketBook(metas)


def _quote(b, i, t, bid, ask, sz=50.0):
    b.on_quote(i, t, bid, ask, sz, sz)


def _warm(book, arb, t0=0.0, n=8, usdt_usd_basis=1.0):
    """Quiet market with a constant ETHUSDT vs Kraken-USD basis of +2 bps so the arb module learns it."""
    for k in range(n):
        t = t0 + k * 0.2
        _quote(book, 1, t, 2000.00, 2000.40)
        _quote(book, 2, t, 2000.40 * 1.0002 - 0.4, 2000.40 * 1.0002)       # kraken mid ~ binance mid * 1.0002
        arb.update_basis(t)
    return t0 + n * 0.2


def _mk(fee_a, fee_b, hurdle=0.0):
    book = _book(fee_a, fee_b)
    cfo = CFOAgent(book, CFOConfig(fee_taker_bps=0.0, safety_hurdle_bps=hurdle, latency_s=0.15, max_notional_frac=0.05))
    arb = CrossVenueArb(book, cfo, ArbConfig(basis_min_samples=3, basis_update_s=0.1, scan_min_interval_s=0.0, record_gap_bps=0.3))
    return book, cfo, arb


def test_basis_is_learned_and_removed_from_the_gap():
    book, cfo, arb = _mk(0.0, 0.0)
    t = _warm(book, arb)
    k = 0
    assert arb.basis[k] == pytest.approx(math.log(2000.20) - math.log(2000.20 * 1.0002), abs=2e-5)
    assert arb.scan(t + 0.0) == []                       # no dislocation after removing the stable 2 bps basis


def test_locked_gap_above_cost_trades_and_books_profit():
    book, cfo, arb = _mk(fee_a=0.5, fee_b=0.5, hurdle=0.2)
    t = _warm(book, arb)
    # kraken suddenly bids 6 bps above binance's ask (basis-adjusted): sell kraken / buy binance
    _quote(book, 2, t, 2000.40 * 1.0002 * 1.0006, 2000.40 * 1.0002 * 1.0006 + 0.4)
    opps = arb.scan(t)
    assert len(opps) == 1 and opps[0].kind == "xvenue" and opps[0].approved
    o = opps[0]
    assert o.legs[0].idx == 2 and o.legs[0].side == -1 and o.legs[1].idx == 1 and o.legs[1].side == +1
    assert 4.0 < o.gap_bps < 6.5 and o.fee_bps == pytest.approx(1.0) and o.net_bps == pytest.approx(o.gap_bps - o.fee_bps - o.slip_bps - 0.2)
    # the dislocation persists through the order latency -> both legs fill
    _quote(book, 2, t + 0.1, 2000.40 * 1.0002 * 1.0006, 2000.40 * 1.0002 * 1.0006 + 0.4)
    done = arb.poll(t + 0.2)
    assert len(done) == 1 and done[0].exit_reason == "locked" and done[0].net_pnl_usd > 0
    assert done[0].net_pnl_usd == pytest.approx(o.notional * (o.gap_fill_bps - o.fee_bps - o.slip_bps) / 1e4, rel=1e-6)
    assert cfo.equity == pytest.approx(10000 + done[0].net_pnl_usd)
    assert arb.summary()["net_gt_0_at_fill"] == 1


def test_gap_below_total_execution_cost_is_rejected_but_shadow_tracked():
    book, cfo, arb = _mk(fee_a=3.0, fee_b=3.0, hurdle=0.0)       # 6 bps fees vs 5 bps gap
    t = _warm(book, arb)
    _quote(book, 2, t, 2000.40 * 1.0002 * 1.0005, 2000.40 * 1.0002 * 1.0005 + 0.4)
    opps = arb.scan(t)
    assert len(opps) == 1 and not opps[0].approved and opps[0].reason == "gap_below_cost"
    assert arb.poll(t + 0.2) == []                               # nothing traded
    assert opps[0].status == "shadow" and np.isfinite(opps[0].gap_fill_bps)
    assert arb.summary()["gross_gt_0"] == 1 and arb.summary()["net_gt_0_at_detect"] == 0


def test_leg_risk_when_the_gap_vanishes_before_the_order_lands():
    book, cfo, arb = _mk(fee_a=0.5, fee_b=0.5)
    t = _warm(book, arb)
    _quote(book, 2, t, 2000.40 * 1.0002 * 1.0006, 2000.40 * 1.0002 * 1.0006 + 0.4)
    o = arb.scan(t)[0]
    assert o.approved
    # kraken re-prices back to normal before arrival (its bid leg misses) while binance ask is unchanged (buy leg fills)
    _quote(book, 2, t + 0.05, 2000.40 * 1.0002 - 0.4, 2000.40 * 1.0002)
    done = arb.poll(t + 0.2)
    assert len(done) == 1 and done[0].exit_reason == "leg_risk" and done[0].net_pnl_usd < 0
    assert o.status == "leg_risk"


def test_missed_when_both_legs_move_away():
    book, cfo, arb = _mk(fee_a=0.5, fee_b=0.5)
    t = _warm(book, arb)
    _quote(book, 2, t, 2000.40 * 1.0002 * 1.0006, 2000.40 * 1.0002 * 1.0006 + 0.4)
    o = arb.scan(t)[0]
    _quote(book, 2, t + 0.05, 2000.40 * 1.0002 - 0.4, 2000.40 * 1.0002)
    _quote(book, 1, t + 0.05, 2000.90, 2001.30)                      # binance ask ran away too
    assert arb.poll(t + 0.2) == [] and o.status == "missed"


def test_cfo_halt_and_quarantine_block_arb_trades():
    book, cfo, arb = _mk(fee_a=0.5, fee_b=0.5)
    t = _warm(book, arb)
    cfo.trip("test", t)
    _quote(book, 2, t, 2000.40 * 1.0002 * 1.0006, 2000.40 * 1.0002 * 1.0006 + 0.4)
    assert arb.scan(t)[0].reason == "halted"


def test_triangle_detects_synthetic_cross_and_cycle_math():
    # BTCUSDT 80000, ETHUSDT 2000 -> implied ETHBTC 0.025. Quote ETHBTC 6 bps too rich -> sell ETHBTC, buy ETHUSDT, sell BTC for USDT
    metas = [MarketMeta("BTCUSDT", "binance", "BTCUSDT", "BTC", asset="BTC", fee_taker_bps=0.0),
             MarketMeta("ETHUSDT", "binance", "ETHUSDT", "ETH", asset="ETH", fee_taker_bps=0.0),
             MarketMeta("ETHBTC", "binance", "ETHBTC", "ETH", asset="ETH", quote="BTC", fee_taker_bps=0.0)]
    book = MarketBook(metas)
    cfo = CFOAgent(book, CFOConfig(fee_taker_bps=0.0, safety_hurdle_bps=0.0, latency_s=0.15))
    arb = CrossVenueArb(book, cfo, ArbConfig(basis_min_samples=1, scan_min_interval_s=0.0))
    assert len(arb.tris) == 1
    for k in range(3):
        t = k * 0.1
        book.on_quote(0, t, 80000.0, 80000.1, 5, 5)
        book.on_quote(1, t, 2000.0, 2000.05, 500, 500)
        book.on_quote(2, t, 0.025 * 1.0006, 0.025 * 1.0006 + 0.0000025, 500, 500)
    opps = arb.scan(0.3)
    tri = [o for o in opps if o.kind == "triangle"]
    assert len(tri) == 1
    expect = math.log(0.025 * 1.0006 * 80000.0 / 2000.05) * 1e4
    assert tri[0].gap_bps == pytest.approx(expect, rel=1e-6) and tri[0].gap_bps > 4.0
    assert [l.side for l in tri[0].legs] == [+1, -1, -1]              # buy ETHUSDT, sell ETHBTC, sell BTCUSDT
    done = arb.poll(0.5)
    assert len(done) == 1 and done[0].exit_reason == "locked"


def test_no_false_triangle_on_consistent_quotes():
    metas = [MarketMeta("BTCUSDT", "binance", "BTCUSDT", "BTC", asset="BTC"), MarketMeta("ETHUSDT", "binance", "ETHUSDT", "ETH", asset="ETH"),
             MarketMeta("ETHBTC", "binance", "ETHBTC", "ETH", asset="ETH", quote="BTC")]
    book = MarketBook(metas)
    cfo = CFOAgent(book, CFOConfig())
    arb = CrossVenueArb(book, cfo, ArbConfig(scan_min_interval_s=0.0))
    for k in range(3):
        book.on_quote(0, k * 0.1, 80000.0, 80000.1, 5, 5)
        book.on_quote(1, k * 0.1, 2000.0, 2000.05, 500, 500)
        book.on_quote(2, k * 0.1, 0.025 - 1e-6, 0.025 + 1e-6, 500, 500)
    assert [o for o in arb.scan(0.3) if o.kind == "triangle"] == []


def test_episode_dedupe_and_lifetime():
    book, cfo, arb = _mk(0.5, 0.5)
    t = _warm(book, arb)
    hot = (2000.40 * 1.0002 * 1.0006, 2000.40 * 1.0002 * 1.0006 + 0.4)
    _quote(book, 2, t, *hot)
    assert len(arb.scan(t)) == 1
    _quote(book, 2, t + 0.05, *hot)
    assert arb.scan(t + 0.05) == []                                   # same episode, not re-counted
    _quote(book, 2, t + 0.4, 2000.40 * 1.0002 - 0.4, 2000.40 * 1.0002)
    arb.scan(t + 0.4)
    assert arb.episode_lifetimes and arb.episode_lifetimes[0] == pytest.approx(0.4, abs=1e-9)
