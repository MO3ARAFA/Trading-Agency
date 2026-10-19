import math

import numpy as np
import pytest

from quant_agency.agency import Agency
from quant_agency.config import AgencyConfig
from quant_agency.maker_sniper import MakerSniper, Variant
from quant_agency.market_watchers import MarketMeta
from tests.conftest import mk_signal

LAT = 0.15


def _agency(venue="hyperliquid", tick=1.0, fee_m=1.5, fee_t=4.5, extra=None, **snipe):
    cfg = AgencyConfig()
    cfg.cfo.fee_maker_bps, cfg.cfo.fee_taker_bps = fee_m, fee_t
    for k, v in snipe.items():
        setattr(cfg.snipe, k, v)
    kind = "prediction" if venue == "polymarket" else "perp"
    m1 = MarketMeta("X", venue, "X", "X", tick=tick, kind=kind, fee_maker_bps=None if venue == "polymarket" else fee_m,
                    fee_taker_bps=None if venue == "polymarket" else fee_t, hunt=False,
                    fee_schedule=(0.07, 1.0, True) if venue == "polymarket" else None, extra=extra or {"min_size": 5.0})
    ag = Agency([MarketMeta("BTCUSDT", "binance", "BTCUSDT", "BTC"), m1], cfg, t0=0.0, wall0=1.8e9)
    return ag


def _sn(ag, variants, **kw):
    sn = MakerSniper(ag, ag.cfg.snipe, variants)
    ag.attach_sniper(sn)
    return sn


def Q(ag, t, bid, ask, bq=10.0, aq=10.0):
    ag.on_quote(1, t, bid, ask, bq, aq)


def sig(side=1, bid=100.0, ask=101.0, bq=10.0, aq=10.0, delta=+5.0, gap=20.0, **kw):
    base = dict(idx=1, market="X", side=side, bid=bid, ask=ask, bq=bq, aq=aq, mid=0.5 * (bid + ask), spread_bps=(ask - bid) / (0.5 * (bid + ask)) * 1e4,
                btc_delta_bps=delta, gap_bps=gap if side > 0 else -gap, sigma_res_bps=2.0, t=1.0)
    base.update(kw)
    return mk_signal(**base)


JOIN = lambda model, shield=True, exit="passive": [Variant("v", "join", exit, shield, model)]


def test_join_queues_behind_visible_size_and_strict_needs_a_cross():
    ag = _agency()
    sn = _sn(ag, JOIN("strict"))
    Q(ag, 0.9, 100, 101, 10, 10)
    sn.on_signal(sig(), 80_000.0)
    at = sn.active[1][0]
    Q(ag, 1.2, 100, 101, 10, 10)                     # order arrives at 1.15 behind 10 units
    assert at.entry.state == "resting" and at.entry.ahead == 10.0
    Q(ag, 1.5, 100, 101, 2, 10)                      # displayed size collapses: strict model gives NO fill
    assert at.entry.filled == 0
    Q(ag, 1.8, 99, 100, 10, 10)                      # ask falls to our bid: certain fill (price traded through)
    assert at.entry.filled == pytest.approx(2.0) and at.entry_px == 100.0


def test_depletion_model_is_the_optimistic_bound_and_fills_partially():
    ag = _agency(hl_notional=300.0)                  # qty = 3 units
    sn = _sn(ag, JOIN("depletion"))
    Q(ag, 0.9, 100, 101, 5, 10)
    sn.on_signal(sig(bq=5), 80_000.0)
    at = sn.active[1][0]
    Q(ag, 1.2, 100, 101, 5, 10)
    assert at.entry.ahead == 5.0
    Q(ag, 1.4, 100, 101, 2, 10)                      # 3 units depleted -> ahead 2
    assert at.entry.ahead == pytest.approx(2.0) and at.entry.filled == 0
    Q(ag, 1.6, 100, 101, 0.5, 10)                    # 1.5 more depleted -> ahead 0.5
    assert at.entry.filled == 0
    Q(ag, 1.7, 99, 100, 10, 10)                      # level vanished downwards (and ask touched): filled
    assert at.entry.filled == pytest.approx(3.0)


def test_trade_prints_consume_the_queue_and_sweep_through():
    ag = _agency(hl_notional=300.0)
    sn = _sn(ag, JOIN("trades"))
    Q(ag, 0.9, 100, 101, 8, 10)
    sn.on_signal(sig(bq=8), 80_000.0)
    at = sn.active[1][0]
    Q(ag, 1.2, 100, 101, 8, 10)
    ag.on_market_trade(1, 1.3, 100.0, 6.0, -1)       # sell print at our price: queue 8 -> 2
    assert at.entry.ahead == pytest.approx(2.0) and at.entry.filled == 0
    ag.on_market_trade(1, 1.4, 101.0, 50.0, +1)      # buy-aggressor print at the ask must not touch a bid order
    assert at.entry.filled == 0
    ag.on_market_trade(1, 1.5, 100.0, 4.0, -1)       # 2 clears the queue, 2 fills us (qty 3 -> partial)
    assert at.entry.filled == pytest.approx(2.0)
    ag.on_market_trade(1, 1.6, 99.0, 5.0, -1)        # print THROUGH our price fills the rest
    assert at.entry.filled == pytest.approx(3.0)


def test_post_only_that_would_cross_at_arrival_is_rejected():
    ag = _agency()
    sn = _sn(ag, JOIN("strict"))
    Q(ag, 0.9, 100, 101)
    sn.on_signal(sig(), 80_000.0)
    Q(ag, 1.1, 99, 100)                              # ask already at our bid when the order lands (t=1.15)
    Q(ag, 1.2, 99, 100)
    r = sn.results[-1]
    assert r["outcome"] == "no_fill" and r["reason"] == "post_only_cross"


def test_penny_jump_starts_at_the_front_inside_a_wide_spread():
    ag = _agency(venue="polymarket", tick=0.01, pm_notional=50.0)
    sn = _sn(ag, [Variant("p", "penny", "passive", True, "strict")])
    Q(ag, 0.9, 0.45, 0.50, 100, 100)
    sn.on_signal(sig(bid=0.45, ask=0.50, bq=100, aq=100, gap=800.0), 80_000.0)
    at = sn.active[1][0]
    assert at.entry.price == pytest.approx(0.46) and at.entry.tif == "ALO"
    Q(ag, 1.2, 0.45, 0.50, 100, 100)
    assert at.entry.state == "resting" and at.entry.ahead == 0.0
    # a competitor already stepped inside: our price would be passive-behind
    ag2 = _agency(venue="polymarket", tick=0.01)
    sn2 = _sn(ag2, [Variant("p", "penny", "passive", True, "strict")])
    Q(ag2, 0.9, 0.45, 0.50, 100, 100)
    sn2.on_signal(sig(bid=0.45, ask=0.50, bq=100, aq=100, gap=800.0), 80_000.0)
    Q(ag2, 1.1, 0.47, 0.50, 5, 100)                  # bid moved to 0.47 > our 0.46 before arrival
    Q(ag2, 1.2, 0.47, 0.50, 5, 100)
    assert sn2.active[1][0].entry.ahead is None      # behind the touch: no free queue position


def test_penny_not_used_when_spread_is_one_tick():
    ag = _agency(venue="polymarket", tick=0.01)
    sn = _sn(ag, [Variant("p", "penny", "passive", True, "strict")])
    Q(ag, 0.9, 0.45, 0.46, 100, 100)
    sn.on_signal(sig(bid=0.45, ask=0.46, bq=100, aq=100, gap=800.0), 80_000.0)
    assert sn.active[1][0].entry.price == pytest.approx(0.45)      # joins instead


def test_cancel_latency_fills_are_charged_and_flagged():
    ag = _agency(hl_notional=200.0)
    sn = _sn(ag, JOIN("strict"))
    Q(ag, 0.9, 100, 101, 10, 10)
    sn.on_signal(sig(delta=+5.0), 80_000.0)
    Q(ag, 1.2, 100, 101, 10, 10)                     # resting
    S_ref = 80_000.0 / math.exp(5e-4)
    sn.poll(2.0, S_ref * math.exp(0.5e-4))           # impulse retained 10% < hold 40% -> cancel requested at t=2.0
    at = sn.active[1][0]
    assert at.entry.state == "cancel_pending" and at.entry.cancel_eff == pytest.approx(2.0 + LAT)
    Q(ag, 2.1, 99, 100, 10, 10)                      # price trades through our bid INSIDE the cancel window
    assert at.entry.filled == pytest.approx(2.0) and at.fill_during_cancel
    # a fill after the cancel became effective does not happen
    ag2 = _agency()
    sn2 = _sn(ag2, JOIN("strict"))
    Q(ag2, 0.9, 100, 101)
    sn2.on_signal(sig(delta=+5.0), 80_000.0)
    Q(ag2, 1.2, 100, 101)
    sn2.poll(2.0, S_ref * math.exp(0.5e-4))
    Q(ag2, 2.3, 99, 100)                             # after 2.15
    r = sn2.results[-1]
    assert r["outcome"] == "no_fill" and r["shield_cancel"] and not r["fill_during_cancel"]


def test_shield_off_variant_is_never_cancelled_by_the_oracle():
    ag = _agency()
    sn = _sn(ag, JOIN("strict", shield=False))
    Q(ag, 0.9, 100, 101)
    sn.on_signal(sig(delta=+5.0), 80_000.0)
    Q(ag, 1.2, 100, 101)
    sn.poll(2.0, 80_000.0 / math.exp(5e-4) * math.exp(-3e-4))       # BTC fully reversed
    assert sn.active[1][0].entry.state == "resting"


def test_shield_cancels_on_reversal_and_when_the_venue_already_converged():
    ag = _agency()
    sn = _sn(ag, JOIN("strict"))
    Q(ag, 0.9, 100, 101)
    sn.on_signal(sig(delta=+5.0), 80_000.0)
    Q(ag, 1.2, 100, 101)
    sn.poll(1.5, 80_000.0 * math.exp(-0.4e-4))                       # reversal beyond 0.3 bps since the signal
    assert sn.active[1][0].entry.state == "cancel_pending"
    ag = _agency()
    sn = _sn(ag, JOIN("strict"))
    Q(ag, 0.9, 100, 101)
    sn.on_signal(sig(delta=+5.0, gap=100.0), 80_000.0)               # gap = 1% of 100.5 ~ 1.005
    Q(ag, 1.2, 100, 101)
    Q(ag, 1.5, 100.9, 101.9)                                         # mid +0.9 >= 80% of the gap, order never filled
    sn.poll(1.6, 80_000.0)
    assert sn.active[1][0].entry.cancel_reason == "converged"


def _filled_attempt(model="strict", exit="passive", **ag_kw):
    ag = _agency(**ag_kw)
    sn = _sn(ag, JOIN(model, exit=exit))
    Q(ag, 0.9, 100, 101, 10, 10)
    sn.on_signal(sig(gap=40.0), 80_000.0)
    Q(ag, 1.2, 100, 101, 10, 10)
    Q(ag, 1.4, 99, 100, 10, 10)                                       # filled at 100.0 (qty 2)
    return ag, sn


def test_passive_exit_earns_maker_fees_and_the_spread_when_the_target_trades():
    ag, sn = _filled_attempt()
    at = sn.active[1][0]
    assert at.state == "exit" and at.exit is not None and at.exit.tif == "ALO"
    tgt_px = at.exit.price
    assert tgt_px > 100.5                                             # above the signal mid: converged ask
    # exit order lands (fill at 1.4 -> cancel of remainder none -> exit sent 1.4, arrives 1.55)
    Q(ag, 1.6, 101, 102, 10, 10)
    Q(ag, 2.0, tgt_px - 0.5, tgt_px + 0.5, 3, 10)                     # book walks up to our ask
    Q(ag, 2.5, tgt_px, tgt_px + 1.0, 3, 10)                           # bid reaches our sell price: filled
    r = sn.results[-1]
    assert r["outcome"] == "filled" and r["exit_kind"] == "passive"
    qty = r["qty"]
    assert r["gross_usd"] == pytest.approx((tgt_px - 100.0) * qty)
    assert r["fees_usd"] == pytest.approx(1.5e-4 * 100.0 * qty + 1.5e-4 * tgt_px * qty)       # maker both legs


def test_work_window_expiry_falls_back_to_a_taker_exit_with_taker_fee():
    ag, sn = _filled_attempt()
    at = sn.active[1][0]
    for k in range(1, 20):
        Q(ag, 1.6 + k * 0.5, 100.5, 101.5, 10, 10)                    # market goes nowhere
        sn.poll(1.6 + k * 0.5, 80_000.0)
    r = sn.results[-1]
    assert r["outcome"] == "filled" and r["exit_reason"] == "work_expired" and r["exit_kind"] == "taker"
    assert r["exit_px"] == pytest.approx(100.5)                       # sold at the bid
    assert r["fees_usd"] == pytest.approx(1.5e-4 * 100.0 * r["qty"] + 4.5e-4 * 100.5 * r["qty"])


def test_adverse_stop_exits_via_taker_after_latency_at_the_asof_bid():
    ag, sn = _filled_attempt()
    Q(ag, 1.6, 100, 101, 10, 10)
    Q(ag, 1.8, 98.0, 99.0, 10, 10)                                    # -200 bps adverse move vs fill mid
    Q(ag, 2.2, 97.0, 98.0, 10, 10)                                    # taker lands at 1.95 -> as-of bid 98.0
    r = sn.results[-1]
    assert r["exit_reason"] == "adverse_stop" and r["exit_px"] == pytest.approx(98.0) and r["net_usd"] < 0


def test_taker_taker_baseline_crosses_both_ways_with_taker_fees():
    ag = _agency()
    sn = _sn(ag, [Variant("tt", "taker", "taker", False, "strict")])
    Q(ag, 0.9, 100, 101, 10, 10)
    sn.on_signal(sig(gap=60.0), 80_000.0)
    Q(ag, 1.2, 100, 101, 10, 10)
    at = sn.active[1][0]
    assert at.entry_px == pytest.approx(101.0)
    for k in range(1, 40):
        Q(ag, 1.2 + k * 0.5, 100.0 + k * 0.1, 101.0 + k * 0.1, 10, 10)
    r = sn.results[-1]
    assert r["outcome"] == "filled" and not r["entry_maker"]
    assert r["fees_usd"] > 0 and r["exit_kind"] == "taker"


def test_polymarket_maker_is_free_and_taker_exit_pays_the_price_dependent_fee():
    ag = _agency(venue="polymarket", tick=0.01, pm_notional=50.0)
    sn = _sn(ag, [Variant("j", "join", "taker", True, "strict")])
    Q(ag, 0.9, 0.45, 0.50, 500, 500)
    sn.on_signal(sig(bid=0.45, ask=0.50, bq=500, aq=500, gap=1500.0, sigma_res_bps=200.0), 80_000.0)
    Q(ag, 1.2, 0.45, 0.50, 500, 500)
    Q(ag, 1.4, 0.44, 0.45, 500, 500)                                  # ask falls to our bid -> filled at 0.45
    for k in range(1, 70):
        Q(ag, 1.4 + k * 0.5, 0.52, 0.53, 500, 500)                    # market converges up: take profit via taker
        sn.poll(1.4 + k * 0.5, 80_000.0)
    r = sn.results[-1]
    assert r["outcome"] == "filled" and r["entry_maker"]
    fee_exit = 0.07 * 0.52 * (1 - 0.52) * r["qty"]                    # taker fee at the exit price, no maker fee at entry
    assert r["fees_usd"] == pytest.approx(fee_exit, rel=1e-6)
    assert r["net_cents"] == pytest.approx(r["net_usd"] / r["qty"] * 100)


def test_polymarket_minimum_size_is_enforced():
    ag = _agency(venue="polymarket", tick=0.01, pm_notional=1.0)
    sn = _sn(ag, JOIN("strict"))
    Q(ag, 0.9, 0.45, 0.50, 500, 500)
    sn.on_signal(sig(bid=0.45, ask=0.50, gap=500.0), 80_000.0)
    assert sn.results[-1]["reason"] == "below_min_size"


def test_variants_run_on_identical_signals_and_models_bracket_each_other():
    ag = _agency()
    cfg = ag.cfg.snipe
    sn = MakerSniper(ag, cfg)                                          # default variants x (strict, depletion)
    ag.attach_sniper(sn)
    Q(ag, 0.9, 100, 101, 10, 10)
    sn.on_signal(sig(), 80_000.0)
    names = sorted({(a.var.name, a.var.model) for a in sn.active[1]})
    assert len(sn.active[1]) == len(sn.variants) == 12 and len({n for n, _ in names}) == 6


def test_account_attempt_updates_cfo_and_engine_ledger():
    ag = _agency()
    sn = _sn(ag, [])
    Q(ag, 0.9, 10_000, 10_001, 10, 10)                                # 1 bp spread (HL BTC-like)
    s = sig(bid=10_000, ask=10_001, gap=60.0, sigma_res_bps=2.0)
    dec = ag.cfo.evaluate_snipe(s, 1.0)
    assert dec.approved and dec.mode == "snipe" and dec.entry_mode in ("join", "penny")
    sn.on_signal(s, 80_000.0, dec)
    assert sn.has_position(1)
    Q(ag, 1.2, 10_000, 10_001, 10, 10)
    Q(ag, 1.4, 9_999, 10_000, 10, 10)
    for k in range(1, 40):
        Q(ag, 1.4 + k * 0.5, 10_050, 10_051, 10, 10)
        sn.poll(1.4 + k * 0.5, 80_000.0)
    assert not sn.has_position(1) and ag.engine.closed and ag.engine.closed[-1].mode == "snipe"
    assert ag.cfo.equity == pytest.approx(10_000 + ag.engine.closed[-1].net_pnl_usd)
    assert ag.cfo._snipe_n == 1


def test_cfo_snipe_cost_model_polymarket_penny_and_learning():
    ag = _agency(venue="polymarket", tick=0.01)
    cfo = ag.cfo
    s = sig(bid=0.45, ask=0.50, bq=500, aq=500, gap=1500.0, sigma_res_bps=200.0)
    d = cfo.evaluate_snipe(s, 1.0)
    assert d.approved and d.entry_mode == "penny"                      # 5-tick spread: penny-jump is better EV than joining
    assert d.fee_bps == pytest.approx(0.0 + 0.0 + 0.5 * 0.07 * (1 - 0.45) * 1e4, rel=1e-6)   # maker entry/exit free, taker fallback weighted 50%
    # a market with a tiny gap is rejected on edge, a wide HL spread on the gate
    assert not cfo.evaluate_snipe(sig(bid=0.45, ask=0.50, gap=30.0, sid=2), 2.0).approved
    cfo.cfg.snipe_gate_bps = 8.0
    ag2 = _agency()
    assert ag2.cfo.evaluate_snipe(sig(bid=100.0, ask=101.0, gap=500.0), 1.0).reason == "spread_too_wide"   # 100 bps spread on HL
    # learning: repeated unfilled attempts push P(fill) down, shortfalls raise the adverse buffer
    p0 = cfo.cfg.snipe_p_fill
    for _ in range(10):
        cfo.on_snipe_result({"outcome": "no_fill", "venue": "polymarket"})
    assert cfo.cfg.snipe_p_fill < p0
    b0 = cfo.cfg.snipe_adverse_bps["polymarket"]
    for _ in range(6):
        cfo.on_snipe_result({"outcome": "filled", "venue": "polymarket", "exit_kind": "taker", "pred_net_bps": 300.0, "net_bps": -200.0})
    assert cfo.cfg.snipe_adverse_bps["polymarket"] > b0


# ---------------------------------------------------------------- CEO monitoring of the maker sniper
def _ceo_agency():
    ag = _agency()
    sn = _sn(ag, [])
    return ag, sn


def _acc_row(venue="hyperliquid", filled=True, net_bps=-3.0, fdc=False, shield=False, t_end=1000.0, reason=""):
    r = {"variant": "ACCOUNT", "model": "strict", "account": True, "entry_mode": "join", "market": "X", "venue": venue, "kind": "perp", "side": 1, "sid": 1,
         "imp": 1, "t0": t_end - 5, "t_end": t_end, "outcome": "filled" if filled else "no_fill", "reason": reason, "gap_bps": 5.0, "spread_bps": 1.0, "mid0": 100.0,
         "shield_cancel": shield, "fill_during_cancel": fdc, "notional": 100.0, "pred_net_bps": 1.0}
    if filled:
        r.update({"net_bps": net_bps, "net_usd": net_bps / 1e4 * 100, "fill_t": t_end - 4, "wait_s": 1.0, "exit_kind": "taker", "exit_reason": "work_expired"})
    return r


def test_ceo_raises_adverse_buffer_then_disables_a_venue_that_keeps_losing():
    ag, sn = _ceo_agency()
    cfo = ag.cfo
    b0 = cfo.cfg.snipe_adverse_bps["hyperliquid"]
    now = 1000.0
    for rnd in range(3):
        sn.account_results += [_acc_row(net_bps=-4.0 + 0.01 * k, t_end=now + 1) for k in range(8)] + [_acc_row(filled=False, t_end=now + 1) for _ in range(2)]
        ivs = ag.ceo.review(now + 2)
        now += 100.0
        kinds_ = [i.kind for i in ivs]
        if rnd < 2:
            assert "SNIPE_RAISE_ADVERSE_BUFFER" in kinds_
        else:
            assert "SNIPE_DISABLE_VENUE" in kinds_
    assert cfo.cfg.snipe_adverse_bps["hyperliquid"] > b0 and "hyperliquid" in cfo.cfg.snipe_blocked
    s = sig(bid=10_000, ask=10_001, gap=500.0)
    assert cfo.evaluate_snipe(s, 5000.0).reason == "venue_disabled"


def test_ceo_buffer_raise_survives_the_cfo_online_learning():
    ag, sn = _ceo_agency()
    ag.cfo.set_snipe_base("hyperliquid", 1.0)
    for _ in range(5):
        ag.cfo.on_snipe_result({"outcome": "filled", "venue": "hyperliquid", "exit_kind": "taker", "pred_net_bps": 0.5, "net_bps": 0.4})
    assert ag.cfo.cfg.snipe_adverse_bps["hyperliquid"] >= 1.0


def test_ceo_tightens_shield_when_fills_inside_the_cancel_window_lose():
    ag, sn = _ceo_agency()
    h0 = sn.cfg.hold_frac
    rows = [_acc_row(net_bps=-1.0, fdc=True) for _ in range(4)] + [_acc_row(net_bps=0.5) for _ in range(4)] + [_acc_row(filled=False) for _ in range(2)]
    sn.account_results += rows
    ivs = ag.ceo.review(1002.0)
    assert [i.kind for i in ivs].count("SNIPE_SHIELD_TIGHTEN") == 1 and sn.cfg.hold_frac == pytest.approx(h0 + 0.1)


def test_ceo_relaxes_a_shield_that_pulls_almost_everything():
    ag, sn = _ceo_agency()
    h0 = sn.cfg.hold_frac
    sn.account_results += [_acc_row(filled=False, shield=True, reason="shield") for _ in range(18)]
    ivs = ag.ceo.review(1002.0)
    assert [i.kind for i in ivs].count("SNIPE_RELAX_SHIELD") == 1 and sn.cfg.hold_frac == pytest.approx(h0 - 0.1)


def test_ceo_ignores_thin_or_profitable_maker_evidence():
    ag, sn = _ceo_agency()
    sn.account_results += [_acc_row(net_bps=-5.0) for _ in range(3)]                  # too few attempts
    assert [i for i in ag.ceo.review(1002.0) if i.kind.startswith("SNIPE")] == []
    ag2, sn2 = _ceo_agency()
    sn2.account_results += [_acc_row(net_bps=+2.0) for _ in range(9)]
    assert [i for i in ag2.ceo.review(1002.0) if i.kind.startswith("SNIPE")] == []


def test_finalize_flushes_open_attempts_without_inventing_fills():
    ag = _agency()
    sn = _sn(ag, JOIN("strict"))
    Q(ag, 0.9, 100, 101)
    sn.on_signal(sig(), 80_000.0)
    Q(ag, 1.2, 100, 101)
    sn.finalize(2.0)
    assert not any(sn.active.values()) and sn.results[-1]["outcome"] == "no_fill" and sn.results[-1]["reason"] == "end_of_run"


def test_ceo_disables_a_venue_whose_adverse_buffer_is_already_capped():
    ag, sn = _ceo_agency()
    ag.cfo.set_snipe_base("hyperliquid", 400.0)
    sn.account_results += [_acc_row(net_bps=-8.0, t_end=1000.0) for _ in range(8)] + [_acc_row(filled=False, t_end=1000.0) for _ in range(2)]
    ivs = ag.ceo.review(1002.0)
    assert [i.kind for i in ivs].count("SNIPE_DISABLE_VENUE") == 1 and "hyperliquid" in ag.cfo.cfg.snipe_blocked
