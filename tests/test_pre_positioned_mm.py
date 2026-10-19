import math
from types import SimpleNamespace

import pytest

from quant_agency.agency import Agency
from quant_agency.config import AgencyConfig
from quant_agency.market_watchers import MarketMeta
from quant_agency.polymarket_watcher import PmSpec
from quant_agency.pre_positioned_mm import FastImpulse, MMVariant, PrePositionedMM

W0 = 1.8e9
S0 = 80_000.0


def make(venue="polymarket", variants=None, spec_kind="above", t_end_off=7200.0, tick=0.01, fee_m=1.5, **mmcfg):
    cfg = AgencyConfig()
    cfg.cfo.fee_maker_bps, cfg.cfo.fee_taker_bps = fee_m, 4.5
    for k, v in mmcfg.items():
        setattr(cfg.mm, k, v)
    pm = venue == "polymarket"
    m1 = MarketMeta("X", venue, "X", "X", tick=tick, kind="prediction" if pm else "perp", hunt=False,
                    fee_schedule=(0.07, 1.0, True) if pm else None, fee_maker_bps=None if pm else fee_m, fee_taker_bps=None if pm else 4.5,
                    extra={"min_size": 5.0, "t_end": W0 + t_end_off} if pm else {})
    ag = Agency([MarketMeta("BTCUSDT", "binance", "BTCUSDT", "BTC"), m1], cfg, t0=0.0, wall0=W0)
    ag.pm = SimpleNamespace(wall=lambda t: W0 + t, specs={"X": PmSpec(kind=spec_kind, t_end=W0 + t_end_off, K=S0, B=S0 * 1.01)})
    vs = variants if variants is not None else [MMVariant("shield/strict", True, "strict"), MMVariant("noshield/strict", False, "strict")]
    mm = PrePositionedMM(ag, cfg.mm, vs)
    ag.attach_mm(mm)
    mm.fast.warm_n = 40
    return ag, mm


def calm(mm, t0, secs, S=S0, noisy=0.6):
    """BTC at 50 Hz: a noisy first part sets the EW variance (±1 bp), then it goes quiet (±0.1 bp): |Z| stays well below 1."""
    t = t0
    k = 0
    while t < t0 + secs:
        amp = 1.0e-4 if t < t0 + noisy * secs else 0.1e-4
        mm.poll(t, S * (1 + (amp if k % 2 else -amp)))
        t += 0.02
        k += 1
    return t


def jump(mm, t, bps, S=S0, steps=10, dt=0.01):
    """A ramped BTC jump; returns the time at which the impulse was first detected (poll time) and the end time."""
    n0 = mm.n_impulses
    det = None
    for k in range(1, steps + 1):
        tt = t + k * dt
        mm.poll(tt, S * (1 + bps * 1e-4 * k / steps))
        if det is None and mm.n_impulses > n0:
            det = tt
    return det, t + steps * dt


def Q(ag, t, bid, ask, bq=100.0, aq=100.0):
    ag.on_quote(1, t, bid, ask, bq, aq)


def qt(mm, name="shield/strict"):
    return mm.quoters[(1, name)]


def post_both(ag, mm, t):
    """Calm warm-up, then two quote events that make both quotes rest at the touch."""
    t = calm(mm, 0.0, 30.0)
    Q(ag, t, 0.49, 0.51)
    mm.poll(t + 0.01, S0)
    Q(ag, t + 0.3, 0.49, 0.51)
    return t + 0.3


def test_fast_impulse_calm_then_jump_flags_direction_and_blocks_calm():
    ag, mm = make()
    t = calm(mm, 0.0, 30.0)
    assert mm.fast.warm() and mm.calm
    n0 = mm.n_impulses
    t = calm(mm, t, 3.0, noisy=0.0)
    assert mm.n_impulses == n0                        # quiet tape: no impulse
    det, _ = jump(mm, t, +8.0)
    assert det is not None and mm.n_impulses == n0 + 1 and mm.imp_dir == +1 and not mm.calm
    assert mm.impulse_log[-1]["dir"] == 1 and mm.impulse_log[-1]["bps"] >= 0.3


def test_calm_quotes_two_sided_at_the_touch_with_min_size():
    ag, mm = make()
    t = post_both(ag, mm, 0.0)
    q = qt(mm)
    assert q.bid is not None and q.ask is not None
    assert q.bid.price == 0.49 and q.ask.price == 0.51 and q.bid.qty == pytest.approx(math.floor(25 / 0.5 * 100) / 100)
    assert q.bid.state == "resting" and q.ask.state == "resting"
    assert q.bid.ahead == 100.0                       # joins behind the visible size


def test_real_hl_spread_is_gated_out_by_fee_economics():
    ag, mm = make(venue="hyperliquid", tick=1.0)
    t = calm(mm, 0.0, 30.0)
    for k in range(6):
        Q(ag, t + 0.1 * k, 79_999.0, 80_000.0)        # 1 tick = 1.25 bp wide vs 2 x 1.5 bp maker fee
    q = qt(mm)
    assert q.bid is None and q.ask is None and q.n["posted"] == 0 and q.n["gated_out"] >= 1


def test_wide_hl_book_quotes_when_the_maker_fee_is_zero():
    ag, mm = make(venue="hyperliquid", tick=1.0, fee_m=0.0)
    t = calm(mm, 0.0, 30.0)
    for k in range(4):
        Q(ag, t + 0.1 * k, 79_960.0, 80_040.0, 5.0, 5.0)    # 10 bp wide
    q = qt(mm)
    assert q.bid is not None and q.ask is not None and q.n["posted"] == 2


def test_bullish_impulse_cancels_the_ask_keeps_the_bid_and_charges_cancel_latency():
    ag, mm = make()
    t = post_both(ag, mm, 0.0)
    det, _ = jump(mm, t + 0.1, +8.0)
    q = qt(mm)
    assert q.bid is not None and q.bid.state == "resting"                 # favourable side stays
    assert q.ask is None and len(q.old) == 1 and q.old[0].state == "cancel_pending"
    assert q.old[0].cancel_eff == pytest.approx(det + 0.15)
    # the market reprices through the stale ask INSIDE the cancel window: the fill is real and flagged
    Q(ag, det + 0.05, 0.51, 0.53)
    assert q.inv < 0 and q.n["fills_in_cancel"] == 1
    assert q.ep["entry_in_shield"] is True
    # noshield identical policy never cancels
    n = qt(mm, "noshield/strict")
    assert n.inv < 0 and n.n["shield_cancels"] == 0 and n.n["fills_in_cancel"] == 0


def test_cancel_landing_before_the_reprice_avoids_the_fill():
    ag, mm = make()
    t = post_both(ag, mm, 0.0)
    det, _ = jump(mm, t + 0.1, +8.0)
    Q(ag, det + 0.20, 0.51, 0.53)                     # after cancel_eff: the shield won the race
    q, n = qt(mm), qt(mm, "noshield/strict")
    assert q.inv == 0.0 and not q.old
    assert n.inv < 0                                   # without the shield the same reprice fills the stale ask


def test_bearish_impulse_cancels_the_bid_instead():
    ag, mm = make()
    t = post_both(ag, mm, 0.0)
    det, _ = jump(mm, t + 0.1, -8.0)
    q = qt(mm)
    assert q.ask is not None and q.ask.state == "resting" and q.bid is None and q.old[0].side == +1


def test_below_contract_flips_the_vulnerable_side():
    ag, mm = make(spec_kind="below")
    t = post_both(ag, mm, 0.0)
    det, _ = jump(mm, t + 0.1, +8.0)                  # BTC up -> a 'below' contract falls -> the BID is stale-rich
    q = qt(mm)
    assert q.bid is None and q.old and q.old[0].side == +1 and q.ask is not None


def test_round_trip_captures_the_spread_with_zero_fee_on_polymarket():
    ag, mm = make()
    t = post_both(ag, mm, 0.0)
    q = qt(mm, "noshield/strict")
    Q(ag, t + 0.5, 0.47, 0.49)                         # ask falls to our bid: long filled at 0.49
    assert q.inv > 0 and q.avg == pytest.approx(0.49)
    Q(ag, t + 0.7, 0.47, 0.51)                         # exit ask posted at the touch, then arrives
    Q(ag, t + 1.0, 0.47, 0.51)
    assert q.ask is not None and q.ask.price == 0.51 and q.ask.qty == pytest.approx(q.inv)
    Q(ag, t + 1.3, 0.51, 0.53)                         # bid lifts to our ask: exit filled
    assert q.inv == 0.0
    r = mm.rows(variant="noshield/strict")[-1]
    assert r["exit_kind"] == "passive" and r["gross_cents"] == pytest.approx(2.0) and r["net_cents"] == pytest.approx(2.0)
    assert r["fees_usd"] == 0.0


def test_long_inventory_is_flattened_by_taker_on_a_bearish_impulse():
    ag, mm = make()
    t = post_both(ag, mm, 0.0)
    q = qt(mm)
    Q(ag, t + 0.5, 0.47, 0.49)
    assert q.inv > 0
    det, end = jump(mm, t + 0.6, -8.0)
    assert q.taker is not None and q.n["shield_flatten"] == 1
    Q(ag, det + 0.2, 0.47, 0.49)                       # taker arrives, sells at the as-of bid
    assert q.inv == 0.0
    r = mm.rows(variant="shield/strict")[-1]
    assert r["exit_reason"] == "shield_flatten" and r["exit_kind"] == "taker" and r["fees_usd"] > 0


def test_favourable_inventory_exits_into_the_converged_price_not_the_stale_touch():
    ag, mm = make()
    t = post_both(ag, mm, 0.0)
    q = qt(mm)
    Q(ag, t + 0.5, 0.47, 0.49)                         # long at 0.49
    Q(ag, t + 0.8, 0.47, 0.51)                         # exit ask posted at 0.51
    Q(ag, t + 1.0, 0.47, 0.51)
    assert q.ask is not None
    det, end = jump(mm, t + 1.1, +8.0)                 # bullish: the exit ask is the vulnerable side
    assert q.ask is None and q.old and q.old[0].side == -1
    mm.on_signal(SimpleNamespace(idx=1, side=1, gap_bps=400.0, spread_bps=400.0, mid=0.50), S0)
    assert q.conv_px is not None and q.conv_px > 0.51
    Q(ag, det + 0.4, 0.51, 0.53)                       # cancel landed; the market moved
    Q(ag, det + 0.7, 0.51, 0.53)
    assert q.ask is not None and q.ask.price == pytest.approx(q.conv_px)


def test_quotes_pulled_and_inventory_flattened_before_expiry():
    ag, mm = make(t_end_off=200.0)                     # 200 s to expiry > pull (180) after warm-up? warm-up takes 30 s -> ttl 170 s: no new quotes
    t = calm(mm, 0.0, 30.0)
    Q(ag, t, 0.49, 0.51)
    Q(ag, t + 0.3, 0.49, 0.51)
    assert qt(mm).bid is None and qt(mm).n["posted"] == 0
    ag2, mm2 = make(t_end_off=400.0)
    t = post_both(ag2, mm2, 0.0)                       # ttl ~370 s: quoting allowed
    q = qt(mm2)
    Q(ag2, t + 0.5, 0.47, 0.49)
    assert q.inv > 0
    Q(ag2, 400.0 - 80.0 - 0.0 - 0.0, 0.47, 0.49)       # ttl 80 s < flat (90): flatten
    mm2.poll(400.0 - 80.0 + 0.02, S0)
    assert q.taker is not None or q.inv == 0.0
    assert q.ep is None or q.ep["reason"] == "expiry"


def test_polymarket_stop_is_in_ticks_not_percent():
    ag, mm = make()
    t = post_both(ag, mm, 0.0)
    q = qt(mm, "noshield/strict")
    Q(ag, t + 0.5, 0.47, 0.49)                         # long at 0.49
    assert q.inv > 0
    Q(ag, t + 0.9, 0.45, 0.47)                         # mid 0.46: 3 ticks below 0.49 -> stop
    assert q.taker is not None and q.ep["reason"] == "adverse_stop"


def test_account_variant_is_cfo_sized_books_exposure_and_a_trade_result():
    ag, mm = make(variants=[MMVariant("ACCOUNT", True, "strict")])
    t = calm(mm, 0.0, 30.0)
    Q(ag, t, 0.49, 0.51)
    Q(ag, t + 0.3, 0.49, 0.51)
    q = qt(mm, "ACCOUNT")
    assert q.bid is not None
    assert q.bid.qty * 0.5 <= ag.cfo.cfg.max_notional_frac * ag.cfo.cfg.capital_usd + 1e-6      # CFO cap, not the shadow notional
    Q(ag, t + 0.5, 0.47, 0.49)
    assert 1 in mm.account_open and "X" in ag.cfo.exposure
    Q(ag, t + 0.8, 0.47, 0.51)
    Q(ag, t + 1.1, 0.47, 0.51)
    Q(ag, t + 1.4, 0.51, 0.53)
    assert q.inv == 0.0 and not mm.account_open and "X" not in ag.cfo.exposure
    assert len(mm.account_results) == 1 and ag.engine.closed[-1].mode == "quote"
    assert ag.cfo.equity == pytest.approx(ag.cfo.cfg.capital_usd + mm.account_results[0]["net_usd"])


def test_ceo_extends_the_shield_hold_when_fills_land_in_the_cancel_window():
    ag, mm = make(variants=[MMVariant("ACCOUNT", True, "strict")])
    base = {"variant": "ACCOUNT", "model": "strict", "shield": True, "account": True, "venue": "polymarket", "market": "X", "outcome": "filled",
            "net_bps": -400.0, "entry_in_cancel": True, "exit_in_cancel": False, "in_shield_cancel": True, "exit_kind": "taker", "t_end": 5.0}
    for k in range(9):
        mm.account_results.append(dict(base, imp=k))
    before = mm.cfg.requote_hold_s["polymarket"]
    ag.ceo._mm_review(10.0, [])
    assert mm.cfg.requote_hold_s["polymarket"] > before
    assert any(iv.kind == "MM_EXTEND_SHIELD" for iv in ag.ceo.interventions)


def test_shadow_variants_ignore_the_ceo_venue_switch_but_the_account_obeys_it():
    ag, mm = make(variants=[MMVariant("shield/strict", True, "strict"), MMVariant("ACCOUNT", True, "strict")])
    ag.cfo.cfg.mm_blocked = ("polymarket",)
    ag.cfo.cfg.requote_hold = None
    mm.cfg.requote_hold_s["polymarket"] = 99.0                       # CEO lengthened the hold: shadows keep the prior
    t = calm(mm, 0.0, 30.0)
    Q(ag, t, 0.49, 0.51)
    Q(ag, t + 0.3, 0.49, 0.51)
    assert qt(mm, "shield/strict").bid is not None
    assert qt(mm, "ACCOUNT").bid is None
    assert mm.hold_s("polymarket", False) == 6.0 and mm.hold_s("polymarket", True) == 99.0


def test_cfo_quote_sizing_uses_the_binary_worst_case_not_notional():
    ag, mm = make()
    c = ag.cfo
    d_mid = c.evaluate_quote(1, 1.0, 0.50, 400.0)
    d_low = c.evaluate_quote(1, 1.0, 0.20, 1000.0)
    assert d_mid.approved and d_low.approved
    # a short at 0.20 can lose 0.80/share (4x its notional): the clip must shrink with the worst case, not stay at the notional cap
    eq, f = c.equity, c.cfg.risk_per_trade_frac
    assert d_low.notional <= f * eq / (0.5 * 0.80 / 0.20) + 1e-6
    assert d_low.notional < d_mid.notional
    # expiry guard: no quote inside the CFO's 60 s window
    assert c.evaluate_quote(1, 1.0, 0.50, 400.0, ttl_s=30.0).reason == "near_expiry"
    # HL-style fee economics: a 1.25 bp book cannot pay 2 x 1.5 bp
    ag2, mm2 = make(venue="hyperliquid", tick=1.0)
    d = ag2.cfo.evaluate_quote(1, 1.0, 80_000.0, 1.25)
    assert not d.approved and d.reason == "spread_too_thin_for_fees"
