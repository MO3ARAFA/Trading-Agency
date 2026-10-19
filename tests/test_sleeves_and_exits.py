import math

import pytest

from quant_agency.agency import Agency
from quant_agency.config import AgencyConfig
from quant_agency.high_conviction_sniper import BAttempt, HighConvictionSniper, parse_exit
from quant_agency.market_watchers import MarketMeta
from quant_agency.sleeves import SleeveSet, SleeveState
from tests.conftest import mk_signal

S0 = 80_000.0


def _ag(exit_name="fixed0.7", venues=("hyperliquid", "polymarket"), **hc):
    cfg = AgencyConfig()
    cfg.cfo.fee_maker_bps, cfg.cfo.fee_taker_bps = 1.5, 4.5
    cfg.hc.account_exit = exit_name
    cfg.cfo.b_tp_mult = parse_exit(exit_name)[1]
    for k, v in hc.items():
        setattr(cfg.hc, k, v)
    metas = [MarketMeta("BTCUSDT", "binance", "BTCUSDT", "BTC"),
             MarketMeta("HL", "hyperliquid", "HL", "HL", tick=0.01, kind="perp", hunt=False, fee_maker_bps=1.5, fee_taker_bps=4.5),
             MarketMeta("PM", "polymarket", "PM", "PM", tick=0.01, kind="prediction", hunt=False, fee_schedule=(0.07, 1.0, True), extra={"min_size": 5.0})]
    ag = Agency(metas, cfg, t0=0.0, wall0=1.8e9)
    sl = SleeveSet(ag.book, cfg.cfo, capital=10_000.0)
    ag.attach_sleeves(sl)
    hc_ = HighConvictionSniper(ag, cfg.hc, sl)
    ag.attach_hc(hc_, govern=False)
    return ag, hc_, sl


def sig(idx=1, side=1, bid=100.0, ask=100.01, gap=60.0, delta=+10.0, market="HL", **kw):
    mid = 0.5 * (bid + ask)
    base = dict(idx=idx, market=market, side=side, bid=bid, ask=ask, bq=50.0, aq=50.0, mid=mid, spread_bps=(ask - bid) / mid * 1e4,
                btc_delta_bps=delta, gap_bps=gap if side > 0 else -gap, sigma_res_bps=2.0, t=1.0, window_s=3.0)
    base.update(kw)
    return mk_signal(**base)


def Q(ag, i, t, bid, ask, bq=50.0, aq=50.0):
    ag.on_quote(i, t, bid, ask, bq, aq)


def fire(ag, hc, idx=1, market="HL", **kw):
    for t in (0.8, 0.9):
        Q(ag, idx, t, kw.get("bid", 100.0), kw.get("ask", 100.01))
    s = sig(idx=idx, market=market, **kw)
    dec = hc.cfo_for(idx).evaluate_sniper_b(s, 1.0)
    hc.on_signal(s, S0, dec)
    return hc.account_open.get(idx), s


def fill_row(venue, net_bps, imp, t=5.0, sleeve_market="X"):
    return {"variant": "ACCOUNT", "model": "strict", "account": True, "venue": venue, "market": sleeve_market, "outcome": "filled", "net_bps": net_bps,
            "imp": imp, "t_end": t, "exit_kind": "taker"}


# ------------------------------------------------------------------ isolation
def test_each_sleeve_has_its_own_cfo_config_equity_and_blacklist():
    ag, hc, sl = _ag()
    a, b = sl.sleeves["hyperliquid"], sl.sleeves["polymarket"]
    assert a.cfo is not b.cfo and a.cfo is not ag.cfo and a.cfo.cfg is not b.cfo.cfg and a.cfo.cfg is not ag.cfo.cfg
    a.cfo.cfg.b_floor_mult = 3.0
    a.cfo.exposure["X"] = 123.0
    a.cfo.blacklist["X"] = (1e9, "t")
    assert b.cfo.cfg.b_floor_mult == 1.5 and ag.cfo.cfg.b_floor_mult == 1.5 and b.cfo.exposure == {} and b.cfo.blacklist == {}


def test_a_halted_polymarket_sleeve_does_not_throttle_hyperliquid():
    ag, hc, sl = _ag()
    pm, hl = sl.sleeves["polymarket"], sl.sleeves["hyperliquid"]
    pm.cfo.trip("test", 1.0)
    pm._apply(SleeveState.HALTED)
    d_pm = pm.cfo.evaluate_sniper_b(sig(idx=2, market="PM", bid=0.49, ask=0.50, gap=1500.0), 2.0)
    d_hl = hl.cfo.evaluate_sniper_b(sig(), 2.0)
    assert not d_pm.approved and d_pm.reason == "halted"
    assert d_hl.approved
    at, _ = fire(ag, hc, idx=1, market="HL")
    assert at is not None and at.account                           # the HL sleeve still opens account trades
    assert ag.cfo.halted is False                                   # and the legacy/global book is untouched


def test_losses_in_one_sleeve_move_only_that_sleeves_governor_and_equity():
    ag, hc, sl = _ag()
    pm, hl = sl.sleeves["polymarket"], sl.sleeves["hyperliquid"]
    for k in range(6):
        pm.add_result(fill_row("polymarket", -900.0, f"i{k}"))
    ev = sl.review(100.0)
    assert [e.sleeve for e in ev] == ["polymarket_b"] and ev[0].kind == "SLEEVE_TIGHTEN"
    assert pm.state == SleeveState.TIGHTENED and pm.cfo.cfg.b_floor_mult == 2.0 and pm.cfo.cfg.size_mult == 0.5
    assert hl.state == SleeveState.NORMAL and hl.cfo.cfg.b_floor_mult == 1.5 and hl.cfo.cfg.size_mult == 1.0
    assert hl.cfo.equity == 10_000.0 and ag.cfo.equity == 10_000.0


def test_governor_escalates_to_halt_then_resumes_on_probation_without_touching_the_other_sleeve():
    ag, hc, sl = _ag()
    pm, hl = sl.sleeves["polymarket"], sl.sleeves["hyperliquid"]
    t = 100.0
    kinds = []
    for rnd in range(4):
        for k in range(6):
            pm.add_result(fill_row("polymarket", -900.0, f"r{rnd}:{k}", t=t))
        t += 40.0
        kinds += [e.kind for e in sl.review(t)]
    assert kinds == ["SLEEVE_TIGHTEN", "SLEEVE_DEFENSIVE", "SLEEVE_HALT"] and pm.state == SleeveState.HALTED and pm.cfo.halted
    assert hl.state == SleeveState.NORMAL and not hl.cfo.halted
    assert hl.cfo.evaluate_sniper_b(sig(), t).approved
    ev = sl.review(t + pm.scfg.halt_cooldown_s + 1.0)
    assert ev and ev[0].kind == "SLEEVE_RESUME_PROBATION" and pm.state == SleeveState.DEFENSIVE and not pm.cfo.halted and pm.cfo.cfg.size_mult == 0.25


def test_cfo_breaker_inside_a_sleeve_halts_only_that_sleeve():
    ag, hc, sl = _ag()
    pm, hl = sl.sleeves["polymarket"], sl.sleeves["hyperliquid"]
    pm.cfo.equity = pm.cfo.peak * (1 - 0.05)
    pm.cfo.trip("portfolio_drawdown", 1.0)
    ev = sl.review(50.0)
    assert ev[0].kind == "SLEEVE_BREAKER_HALT" and pm.state == SleeveState.HALTED and hl.state == SleeveState.NORMAL and not hl.cfo.halted


def test_account_results_book_into_the_venue_sleeve_not_the_global_cfo():
    ag, hc, sl = _ag()
    at, s = fire(ag, hc, idx=1, market="HL")
    Q(ag, 1, 1.2, 100.0, 100.01)
    Q(ag, 1, 1.4, 100.0, 100.01)
    tp = at.exit.price
    Q(ag, 1, 1.8, tp + 0.01, tp + 0.02)
    assert at.state == "done" and at.result["net_usd"] > 0
    assert sl.sleeves["hyperliquid"].cfo.equity > 10_000.0 and sl.sleeves["polymarket"].cfo.equity == 10_000.0 and ag.cfo.equity == 10_000.0
    assert len(sl.sleeves["hyperliquid"].results) == 1 and not sl.sleeves["polymarket"].results and not ag.engine.closed


def test_architecture_a_is_not_part_of_the_phase7_wiring():
    ag, hc, sl = _ag()
    assert ag.mm is None and ag.ceo.hc is None                         # no A, and the global CEO does not govern B


# ------------------------------------------------------------------ exit policies
def test_parse_exit():
    assert parse_exit("fixed0.7") == ("fixed", 0.7) and parse_exit("wide2.0") == ("wide", 2.0) and parse_exit("adaptive") == ("adaptive", 1.0) and parse_exit("trail")[0] == "trail"


def _shadow(hc, name, idx=1):
    return next(a for a in hc.active[idx] if isinstance(a, BAttempt) and a.xname == name and not a.account and a.var.model == "strict")


def test_wider_take_profit_rests_further_out_with_a_longer_horizon():
    ag, hc, sl = _ag()
    fire(ag, hc)
    for t in (1.2, 1.4):
        Q(ag, 1, t, 100.0, 100.01)
    px = {x: _shadow(hc, x).exit.price for x in ("fixed0.7", "fixed1.0", "wide1.5", "wide2.0")}
    assert px["fixed0.7"] < px["fixed1.0"] < px["wide1.5"] < px["wide2.0"]
    w = _shadow(hc, "wide2.0")
    f = _shadow(hc, "fixed1.0")
    assert w.work_deadline - w.entry_fill_t == pytest.approx(hc.bcfg.horizon_s["hyperliquid"]) and f.work_deadline - f.entry_fill_t < 12.0


def test_adaptive_widens_only_when_binance_keeps_going_and_never_oversells_during_the_cancel():
    ag, hc, sl = _ag()
    fire(ag, hc)
    for t in (1.2, 1.4):
        Q(ag, 1, t, 100.0, 100.01)
    at = _shadow(hc, "adaptive")
    p0 = at.exit.price
    hc.poll(1.6, S0 * (1 + 0.5e-4))                                    # BTC barely extended: no widening
    assert at.level == 0 and at.exit.price == p0
    hc.poll(2.6, S0 * (1 + 2.5e-4))                                    # +2.5 bp on a 10 bp impulse = 25 % extension >= 20 %
    assert at.level == 1 and at.scratch_state == "pending" and len(at.exit_prev) == 1 and at.exit is None
    assert not at.scratched                                            # a widen is not a scratch
    t_c = at.exit_prev[0].cancel_eff
    Q(ag, 1, t_c + 0.01, 100.0, 100.01)
    hc.poll(t_c + 0.02, S0 * (1 + 2.5e-4))
    assert at.exit is not None and at.exit.price > p0 and at.scratch_state is None
    # the old TP filling inside its cancel window is kept and the new order is sized to what is left
    ag2, hc2, _ = _ag()
    fire(ag2, hc2)
    for t in (1.2, 1.4):
        Q(ag2, 1, t, 100.0, 100.01)
    at2 = _shadow(hc2, "adaptive")
    old = at2.exit.price
    hc2.poll(2.6, S0 * (1 + 2.5e-4))
    Q(ag2, 1, 2.65, old + 0.01, old + 0.02)                            # market trades through the old TP during the cancel
    assert at2.state == "done" and at2.result["exit_px"] == pytest.approx(old) and at2.exit is None


def test_trail_has_no_resting_tp_and_exits_when_the_venue_captured_the_gap_and_binance_velocity_faded():
    ag, hc, sl = _ag()
    fire(ag, hc)
    for t in (1.2, 1.4):
        Q(ag, 1, t, 100.0, 100.01)
    at = _shadow(hc, "trail")
    assert at.state == "exit" and at.exit is None and at.hold_deadline is not None
    hc.poll(1.45, S0)
    gap_px = 60.0 / 1e4 * at.mid0
    Q(ag, 1, 1.6, 100.0 + gap_px, 100.01 + gap_px)                     # venue did >= 100 % of the credited gap
    hc.poll(2.0, S0)                                                   # Binance flat over the last second: velocity 0 <= 0.2 bps
    assert at.trail_exit_reason == "trail_capture" and at.scratch_state == "pending"
    Q(ag, 1, 2.2, 100.0 + gap_px, 100.01 + gap_px)
    hc.poll(2.25, S0)
    assert at.exit is not None and at.exit.price == pytest.approx(100.01 + gap_px)      # passive at the touch
    Q(ag, 1, 2.5, 100.01 + gap_px, 100.02 + gap_px)
    assert at.state == "done" and at.result["exit_kind"] == "passive" and at.result["trail_reason"] == "trail_capture"


def test_trail_stays_in_while_binance_velocity_is_still_supportive():
    ag, hc, sl = _ag()
    fire(ag, hc)
    for t in (1.2, 1.4):
        Q(ag, 1, t, 100.0, 100.01)
    at = _shadow(hc, "trail")
    for k in range(10):                                                # BTC still grinding up 1 bp per 0.1 s
        hc.poll(1.5 + 0.1 * k, S0 * (1 + (1.0 + k) * 1e-4))
    gap_px = 60.0 / 1e4 * at.mid0
    Q(ag, 1, 2.5, 100.0 + gap_px, 100.01 + gap_px)
    hc.poll(2.55, S0 * (1 + 11e-4))
    assert at.scratch_state is None and at.trail_exit_reason == ""     # captured the gap but the impulse is still running: hold


def test_trail_time_stop_is_a_taker_exit():
    ag, hc, sl = _ag()
    fire(ag, hc)
    for t in (1.2, 1.4):
        Q(ag, 1, t, 100.0, 100.01)
    at = _shadow(hc, "trail")
    hc.poll(1.4 + ag.cfg.snipe.max_hold_s + 1.0, S0)
    Q(ag, 1, 1.4 + ag.cfg.snipe.max_hold_s + 1.5, 100.0, 100.01)
    assert at.state == "done" and at.result["exit_reason"] == "time_stop"
