import math

import pytest

from quant_agency.agency import Agency
from quant_agency.config import AgencyConfig
from quant_agency.high_conviction_sniper import BAttempt, HighConvictionSniper
from quant_agency.market_watchers import MarketMeta
from tests.conftest import mk_signal

S0 = 80_000.0


def _agency(venue="hyperliquid", tick=0.01, **cfo):
    cfg = AgencyConfig()
    cfg.cfo.fee_maker_bps, cfg.cfo.fee_taker_bps = 1.5, 4.5
    for k, v in cfo.items():
        setattr(cfg.cfo, k, v)
    pm = venue == "polymarket"
    m1 = MarketMeta("X", venue, "X", "X", tick=tick, kind="prediction" if pm else "perp", hunt=False,
                    fee_schedule=(0.07, 1.0, True) if pm else None, fee_maker_bps=None if pm else 1.5, fee_taker_bps=None if pm else 4.5,
                    extra={"min_size": 5.0})
    ag = Agency([MarketMeta("BTCUSDT", "binance", "BTCUSDT", "BTC"), m1], cfg, t0=0.0, wall0=1.8e9)
    hc = HighConvictionSniper(ag, cfg.hc)
    ag.attach_hc(hc)
    return ag, hc


def sig(side=1, bid=100.0, ask=100.01, gap=40.0, delta=+10.0, **kw):
    mid = 0.5 * (bid + ask)
    base = dict(idx=1, market="X", side=side, bid=bid, ask=ask, bq=50.0, aq=50.0, mid=mid, spread_bps=(ask - bid) / mid * 1e4,
                btc_delta_bps=delta, gap_bps=gap if side > 0 else -gap, sigma_res_bps=2.0, t=1.0, window_s=3.0)
    base.update(kw)
    return mk_signal(**base)


def Q(ag, t, bid, ask, bq=50.0, aq=50.0):
    ag.on_quote(1, t, bid, ask, bq, aq)


def test_floor_is_an_absolute_magnitude_rule_not_a_z_score():
    ag, hc = _agency()
    s = sig(bid=99.99, ask=100.0, gap=8.0)                        # 1 bp spread
    pred, floor, ratio = ag.cfo.b_floor(s)
    assert floor == pytest.approx(1.5 * (s.spread_bps + 4.5 + 1.5)) and pred < floor and ratio < 1
    d = ag.cfo.evaluate_sniper_b(s, 1.0)
    assert not d.approved and d.reason == "below_absolute_floor"
    big = sig(bid=99.99, ask=100.0, gap=40.0, btc_z=9.0)
    d2 = ag.cfo.evaluate_sniper_b(big, 1.0)
    assert d2.approved and d2.mode == "b_snipe" and d2.entry_mode == "taker" and d2.tp_bps > 0


def test_floor_multiple_is_ceo_tunable_and_blocks_marginal_trades():
    ag, hc = _agency()
    s = sig(bid=99.99, ask=100.0, gap=14.0)
    assert ag.cfo.evaluate_sniper_b(s, 1.0).approved                # 14 > 1.5 x 7.5
    ag.cfo.cfg.b_floor_mult = 2.5
    d = ag.cfo.evaluate_sniper_b(s, 1.0)
    assert not d.approved and d.reason == "below_absolute_floor"


def test_polymarket_floor_uses_the_price_dependent_taker_fee():
    ag, hc = _agency(venue="polymarket", tick=0.01)
    s = sig(bid=0.49, ask=0.51, gap=500.0)                          # 5 c on a 0.50 contract
    pred, floor, _ = ag.cfo.b_floor(s)
    assert floor == pytest.approx(1.5 * (s.spread_bps + 0.07 * 0.51 * 0.49 / 0.51 * 1e4))
    assert not ag.cfo.evaluate_sniper_b(s, 1.0).approved
    assert ag.cfo.evaluate_sniper_b(sig(bid=0.49, ask=0.51, gap=1500.0), 1.0).approved


def test_every_signal_spawns_tagged_shadows_but_only_floor_passing_ones_trade_the_account():
    ag, hc = _agency()
    for t in (0.9, 1.0):
        Q(ag, t, 100.0, 100.01)
    s_small = sig(gap=2.0, sid=1)
    dec = ag.cfo.evaluate_sniper_b(s_small, 1.0)
    hc.on_signal(s_small, S0, dec)
    kinds = sorted({type(a).__name__ for atts in hc.active.values() for a in atts})
    assert kinds == ["BAttempt", "TakerAttempt"] and not hc.account_open
    assert all(a.floor_ok is False for a in hc.active[1])
    s_big = sig(gap=60.0, sid=2)
    dec = ag.cfo.evaluate_sniper_b(s_big, 1.0)
    hc.on_signal(s_big, S0, dec)
    assert 1 in hc.account_open and hc.account_open[1].floor_ok is True


def _fire(ag, hc, gap=60.0, bid=100.0, ask=100.01):
    for t in (0.8, 0.9):
        Q(ag, t, bid, ask)
    s = sig(gap=gap, bid=bid, ask=ask)
    dec = ag.cfo.evaluate_sniper_b(s, 1.0)
    hc.on_signal(s, S0, dec)
    return hc.account_open[1], s


def test_taker_entry_then_resting_maker_take_profit_at_the_converged_touch():
    ag, hc = _agency()
    at, s = _fire(ag, hc)
    Q(ag, 1.2, 100.0, 100.01)                                       # entry arrives 1.15: IOC lifts the ask
    assert at.entry.state == "filled" and at.entry_px == pytest.approx(100.01) and at.state == "exit"
    Q(ag, 1.4, 100.0, 100.01)                                       # exit order (ALO) arrives and rests above the touch
    assert at.exit.state == "resting" and at.exit.price > 100.01
    tp_px = at.exit.price
    Q(ag, 1.8, tp_px + 0.01, tp_px + 0.02)                            # market converges: the bid lifts to our ask
    assert at.state == "done" and at.result["exit_kind"] == "passive" and at.result["gross_usd"] > 0
    assert at.result["exit_px"] == pytest.approx(tp_px)


def test_stall_triggers_a_scratch_with_cancel_latency_then_a_passive_exit_at_the_touch():
    ag, hc = _agency()
    at, s = _fire(ag, hc)
    Q(ag, 1.2, 100.0, 100.01)
    Q(ag, 1.4, 100.0, 100.01)
    old = at.exit
    assert old.state == "resting"
    S_ref = at.S_ref
    S_stall = S_ref * (1 + 0.2 * 10.0 * 1e-4)                       # only 20 % of the impulse is left, venue has not moved
    hc.poll(1.2 + at.bcfg.stall_after_s["hyperliquid"] + 0.1, S_stall)
    assert at.scratched and old.state == "cancel_pending" and old in at.exit_prev and at.exit is None
    t_c = old.cancel_eff
    Q(ag, t_c + 0.01, 100.0, 100.01)
    hc.poll(t_c + 0.02, S_stall)
    assert at.exit is not None and at.exit.price == pytest.approx(100.01) and at.exit.kind == "exit"     # passive at the *touch*, not the converged price
    Q(ag, t_c + 0.3, 100.0, 100.01)
    Q(ag, t_c + 0.5, 100.01, 100.02)                                  # bid reaches our ask
    assert at.state == "done" and at.result["scratched"] is True and at.result["exit_kind"] == "passive"


def test_take_profit_filled_inside_the_scratch_cancel_window_is_not_oversold():
    ag, hc = _agency()
    at, s = _fire(ag, hc)
    Q(ag, 1.2, 100.0, 100.01)
    Q(ag, 1.4, 100.0, 100.01)
    tp = at.exit.price
    t_s = 1.2 + at.bcfg.stall_after_s["hyperliquid"] + 0.1
    hc.poll(t_s, at.S_ref * 1.0002)
    assert at.scratched
    Q(ag, t_s + 0.05, tp + 0.01, tp + 0.02)                           # TP fills before the cancel lands
    assert at.state == "done" and at.result["qty"] == pytest.approx(at.qty_pos) and at.exit is None
    assert at.result["exit_px"] == pytest.approx(tp)


def test_genuine_reversal_stops_out_with_a_taker_but_a_mere_stall_does_not():
    ag, hc = _agency()
    at, s = _fire(ag, hc)
    Q(ag, 1.2, 100.0, 100.01)
    Q(ag, 1.4, 100.0, 100.01)
    Q(ag, 1.6, 99.99, 100.00)                                        # slightly under water (inside the CFO stop)
    hc.poll(1.7, S0 * (1 - 6.0e-4))                                  # BTC fell back 6 bp from the signal level (> half of the 10 bp impulse)
    assert at.rev_stopped and at.taker_exit is not None
    Q(ag, 2.0, 99.99, 100.00)
    assert at.state == "done" and at.result["exit_reason"] == "reversal_stop" and at.result["exit_kind"] in ("taker", "mixed")


def test_ceo_raises_the_floor_when_fired_snipes_lose_and_disables_at_the_cap():
    ag, hc = _agency()
    base = {"variant": "ACCOUNT", "model": "strict", "account": True, "venue": "polymarket", "market": "X", "outcome": "filled", "net_bps": -600.0,
            "exit_kind": "taker", "scratched": False, "t_end": 5.0}
    seen = []
    for rnd in range(8):
        for k in range(6):
            hc.account_results.append(dict(base, imp=f"{rnd}:{k}", t_end=5.0 + rnd))
        ag.ceo.b_epoch = -1e18
        ag.ceo._b_review(10.0 + rnd, [])
        seen.append(ag.cfo.cfg.b_floor_mult)
        if "polymarket" in ag.cfo.cfg.b_blocked:
            break
    assert seen[0] == 2.0 and max(seen) <= 4.0 and "polymarket" in ag.cfo.cfg.b_blocked
    kinds = [iv.kind for iv in ag.ceo.interventions]
    assert "B_RAISE_FLOOR" in kinds and "B_DISABLE_VENUE" in kinds
