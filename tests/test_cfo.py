import types

import numpy as np
import pytest

from quant_agency.cfo_agent import CFOAgent, MarkoutTracker, _cluster_se
from quant_agency.config import CFOConfig
from tests.conftest import make_book, mk_signal


def _cfo(book, **kw):
    cfg = CFOConfig(fee_taker_bps=1.0, fee_maker_bps=1.0, **kw)
    return CFOAgent(book, cfg)


def test_net_edge_matches_brief_formula(book2):
    cfo = _cfo(book2)
    sig = mk_signal(gap_bps=12.0, spread_bps=2.0)
    d = cfo.evaluate(sig, now=100.0)
    assert d.approved and d.mode == "taker"
    # NetEdge = credit*|Gap| - (Spread + Fees + Slippage + SafetyHurdle)
    assert d.spread_bps == pytest.approx(2.0)                # live full spread
    assert d.fee_bps == pytest.approx(2.0)                   # round-trip taker fee
    assert d.hurdle_bps == pytest.approx(1.0)
    assert d.slip_bps > 0
    assert d.net_edge_bps == pytest.approx(12.0 - (d.spread_bps + d.fee_bps + d.slip_bps + d.hurdle_bps))
    assert d.tp_bps >= d.spread_bps + d.fee_bps + d.slip_bps   # TP never below break-even cost


def test_gating_boundary_around_breakeven(book2):
    cfo = _cfo(book2)
    cost = 2.0 + 2.0 + 1.0                                   # spread + fees + hurdle (+ slippage ~0.4)
    lo = cfo.evaluate(mk_signal(gap_bps=cost), 100.0)        # slippage pushes this under water
    hi = cfo.evaluate(mk_signal(gap_bps=cost + 1.0, sid=2), 101.0)
    assert not lo.approved and lo.reason == "net_edge_below_hurdle" and lo.cohort == "rejected_edge"
    assert hi.approved


def test_fees_can_eat_the_whole_gap(book2):
    cfo = CFOAgent(book2, CFOConfig(fee_taker_bps=7.5, fee_maker_bps=7.5))
    d = cfo.evaluate(mk_signal(gap_bps=12.0), 100.0)         # 12 bps gap vs 15 bps round-trip fees
    assert not d.approved and d.reason == "net_edge_below_hurdle"
    assert d.net_edge_bps < 0


def test_wide_spread_and_short_policy_and_in_position(book2):
    cfo = _cfo(book2)
    assert cfo.evaluate(mk_signal(gap_bps=50.0, spread_bps=20.0), 1.0).reason == "spread_too_wide"
    assert cfo.evaluate(mk_signal(gap_bps=50.0, sid=2), 1.0, has_position=True).reason == "in_position"
    assert cfo.evaluate(mk_signal(gap_bps=50.0, sid=3), 1.0, tradable=False).reason == "watch_only"
    cfo.cfg.allow_short = False
    assert cfo.evaluate(mk_signal(gap_bps=-50.0, side=-1, sid=4), 1.0).reason == "short_disabled"


def test_edge_credit_haircut_reduces_edge(book2):
    cfo = _cfo(book2)
    full = cfo.evaluate(mk_signal(gap_bps=12.0), 1.0)
    cfo.apply_directive({"edge_credit": 0.4})
    half = cfo.evaluate(mk_signal(gap_bps=12.0, sid=2), 2.0)
    assert full.approved and not half.approved
    assert half.gap_credit_bps == pytest.approx(4.8)      # 0.4 * 12 bps


def test_sizing_caps(book2):
    cfo = _cfo(book2)
    eq = cfo.equity
    d = cfo.evaluate(mk_signal(gap_bps=30.0), 1.0)
    assert d.approved and 0 < d.notional <= cfo.cfg.max_notional_frac * eq + 1e-6
    assert d.qty * 100.01 == pytest.approx(d.notional, rel=1e-6)
    cfo.apply_directive({"size_mult": 0.5})
    d2 = cfo.evaluate(mk_signal(gap_bps=30.0, sid=2), 2.0)
    assert d2.notional == pytest.approx(0.5 * d.notional, rel=1e-6)
    # liquidity cap: tiny top-of-book -> tiny size -> below exchange minimum
    d3 = cfo.evaluate(mk_signal(gap_bps=30.0, aq=0.5, sid=3), 3.0)
    assert not d3.approved and d3.reason == "size_below_min"


def test_exposure_caps_bind(book2):
    cfo = _cfo(book2)
    cfo.on_open("ALT1USDT", 1, cfo.cfg.max_market_frac * cfo.equity, 1.0)   # market already at its cap
    assert cfo.evaluate(mk_signal(gap_bps=30.0), 1.0).reason == "exposure_cap"
    cfo2 = _cfo(book2)
    cfo2.on_open("ALT2USDT", 1, cfo2.cfg.max_beta_net_frac * cfo2.equity, 1.0)   # beta-weighted net long at cap
    assert cfo2.evaluate(mk_signal(gap_bps=30.0, side=1), 1.0).reason == "exposure_cap"
    assert cfo2.evaluate(mk_signal(gap_bps=-30.0, side=-1, sid=2), 1.0).approved   # but the hedge side is fine


def _tr(market="ALT1USDT", pnl=-1.0, fees=0.1):
    return types.SimpleNamespace(market=market, net_pnl_usd=pnl, fees_usd=fees)


def test_portfolio_drawdown_breaker_halts_and_requests_flatten(book2):
    cfo = _cfo(book2)
    t = 1000.0
    for k in range(5):
        cfo.on_trade_closed(_tr(market=f"M{k}", pnl=-45.0), t + k)          # -$225 = 2.25% > 2% breaker
    assert cfo.halted and cfo.halt_reason == "portfolio_drawdown" and cfo.flatten_requested
    assert cfo.evaluate(mk_signal(gap_bps=50.0), t + 10).reason == "halted"
    cfo.apply_directive({"resume": True})
    assert not cfo.halted and cfo.drawdown_frac() == 0.0                     # drawdown clock restarted


def test_per_market_breaker_quarantines_only_that_market(book2):
    cfo = _cfo(book2)
    cfo.on_trade_closed(_tr(pnl=-45.0), 1000.0)                              # > 0.4% of equity in ALT1
    assert cfo.is_blacklisted("ALT1USDT", 1001.0)
    assert not cfo.is_blacklisted("ALT2USDT", 1001.0)
    assert cfo.evaluate(mk_signal(gap_bps=50.0), 1001.0).reason == "quarantined"
    assert not cfo.is_blacklisted("ALT1USDT", 1000.0 + cfo.cfg.breaker_cooldown_s + 1)   # expires


def test_directive_bounds_and_mode_policy(book2):
    cfo = _cfo(book2)
    b = cfo.apply_directive({"safety_hurdle_bps": 999, "size_mult": -3, "edge_credit": 7, "mode_policy": "bogus", "unknown": 1})
    assert cfo.cfg.safety_hurdle_bps == 25.0 and cfo.cfg.size_mult == 0.0 and cfo.cfg.edge_credit == 1.0
    assert cfo.cfg.mode_policy == "auto" and "unknown" not in b
    cfo.apply_directive({"size_mult": 1.0, "safety_hurdle_bps": 0.5, "mode_policy": "maker_only"})
    d = cfo.evaluate(mk_signal(gap_bps=40.0, window_s=0.6), 1.0)
    assert d.approved and d.mode == "maker"                                  # policy overrides urgency
    assert d.spread_bps == 0.0 and d.fee_bps == pytest.approx(2.0)          # maker entry earns the spread


def test_urgent_window_prefers_taker_in_auto(book2):
    cfo = _cfo(book2)
    d = cfo.evaluate(mk_signal(gap_bps=40.0, window_s=1.0), 1.0)
    assert d.mode == "taker"


def test_revoke_keeps_counters_consistent(book2):
    cfo = _cfo(book2)
    d = cfo.evaluate(mk_signal(gap_bps=40.0), 1.0)
    cfo.revoke(d, "size_below_min")
    assert not d.approved and cfo.n_approved == 0 and cfo.reasons["ok"] == 0 and cfo.reasons["size_below_min"] == 1


# ------------------------------------------------------------------ markouts
def test_markout_gross_net_and_closure_are_exact():
    book = make_book()
    book.on_quote(1, 10.00, 99.99, 100.01, 1, 1)        # at/after fill (t0+0.15 -> still this quote)
    book.on_quote(1, 11.00, 100.09, 100.11, 1, 1)       # 1 s later the market has repriced +10 bps
    mt = MarkoutTracker(book, horizons=(1.0,), latency_s=0.15, fee_taker_bps=1.0)
    sig = mk_signal(t=10.0, gap_bps=10.0, mid=100.0, side=1)
    cfo = CFOAgent(book, CFOConfig())
    mt.register(sig, cfo.evaluate(sig, 10.0))
    assert mt.poll(11.0) == 0                           # too early: needs t0+lat+h
    assert mt.poll(11.2) == 1
    r = mt.rows[0]
    assert r["gross"] == pytest.approx((100.10 - 100.00) / 100.00 * 1e4)
    assert r["net"] == pytest.approx((100.09 - 100.01) / 100.01 * 1e4 - 2.0)
    assert r["closure"] == pytest.approx(1.0)


def test_markout_short_side_sign():
    book = make_book()
    book.on_quote(1, 10.0, 99.99, 100.01, 1, 1)
    book.on_quote(1, 11.0, 99.89, 99.91, 1, 1)          # market falls 10 bps
    mt = MarkoutTracker(book, (1.0,), 0.15, 0.0)
    sig = mk_signal(t=10.0, side=-1, gap_bps=-10.0, mid=100.0)
    mt.register(sig, CFOAgent(book, CFOConfig()).evaluate(sig, 10.0))
    mt.poll(11.2)
    assert mt.rows[0]["gross"] == pytest.approx(10.0, abs=1e-6)
    assert mt.rows[0]["net"] == pytest.approx((99.99 - 99.91) / 99.99 * 1e4, rel=1e-6)   # sell at bid, cover at ask


def test_cluster_se_is_larger_than_naive_when_rows_share_an_impulse():
    rows = []
    for imp, val in enumerate((5.0, -5.0, 5.0, -5.0)):
        rows += [{"imp": imp, "net": val + 0.01 * j, "gross": val} for j in range(25)]   # 25 markets per impulse
    naive = np.std([r["net"] for r in rows], ddof=1) / np.sqrt(len(rows))
    assert _cluster_se(rows, "net") > 5 * naive
