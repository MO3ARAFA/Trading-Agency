import math

import numpy as np
import pytest

from quant_agency.agency import Agency
from quant_agency.cfo_agent import CFOAgent
from quant_agency.config import AgencyConfig, CFOConfig, PolyConfig
from quant_agency.market_watchers import MarketBook, MarketMeta, maker_fee_bps, taker_fee_bps
from quant_agency.polymarket_watcher import (PmBooks, PmSpec, PolymarketWatcher, candidate_slugs, fair_prob, handle_clob_message,
                                              ncdf, parse_threshold)

from tests.conftest import mk_signal

SIG = 6.2e-5          # ~35 % annualised, per sqrt-second
NOW = 1_800_000_000.0


def test_ncdf_basics():
    assert ncdf(0) == 0.5 and ncdf(8) == pytest.approx(1.0) and ncdf(-8) == pytest.approx(0.0)
    assert ncdf(1.0) + ncdf(-1.0) == pytest.approx(1.0)


def test_threshold_probabilities():
    spec = PmSpec("above", t_end=NOW + 3600, K=80_000)
    assert fair_prob(spec, 80_000, NOW, SIG) == pytest.approx(0.5)
    up = fair_prob(spec, 80_000 * math.exp(1e-3), NOW, SIG)
    dn = fair_prob(spec, 80_000 * math.exp(-1e-3), NOW, SIG)
    assert dn < 0.5 < up and up + dn == pytest.approx(1.0, abs=1e-9)
    below = PmSpec("below", t_end=NOW + 3600, K=80_000)
    assert fair_prob(below, 80_000 * math.exp(1e-3), NOW, SIG) == pytest.approx(1 - up)
    # time decay: closer to expiry the same 10 bps moneyness is nearly certain
    assert fair_prob(PmSpec("above", t_end=NOW + 60, K=80_000), 80_080, NOW, SIG) > 0.98
    assert fair_prob(spec, 80_000, NOW + 4000, SIG) is None            # expired


def test_range_probabilities_partition_the_line():
    t_end = NOW + 7200
    S = 80_500.0
    parts = [PmSpec("below", t_end, K=79_000), PmSpec("range", t_end, K=79_000, B=81_000), PmSpec("above", t_end, K=81_000)]
    assert sum(fair_prob(p, S, NOW, SIG) for p in parts) == pytest.approx(1.0, abs=1e-12)


def test_updown_terminal_and_twap():
    term = PmSpec("updown_terminal", t_end=NOW + 1800, t_start=NOW - 1800, S0=80_000)
    assert fair_prob(term, 80_000, NOW, SIG) == pytest.approx(0.5)
    assert fair_prob(term, 80_040, NOW, SIG) > 0.5 > fair_prob(term, 79_960, NOW, SIG)
    assert fair_prob(PmSpec("updown_terminal", NOW + 60, t_start=NOW - 60), 80_000, NOW, SIG) is None   # S0 unknown yet
    tw = PmSpec("updown_twap", t_end=NOW + 30, t_start=NOW - 270, S0=80_000)
    # average so far is 20 bps above the start price with 30 s left: very likely "Up" even if spot is back at the start
    assert fair_prob(tw, 80_000, NOW, SIG, A_bar=80_160) > 0.95
    assert fair_prob(tw, 80_000, NOW, SIG, A_bar=79_840) < 0.05
    # at the very start of the window the TWAP market is a coin flip
    tw0 = PmSpec("updown_twap", t_end=NOW + 300, t_start=NOW, S0=80_000)
    assert fair_prob(tw0, 80_000, NOW, SIG, A_bar=80_000) == pytest.approx(0.5, abs=1e-6)


def test_polymarket_fee_schedule_is_price_dependent_and_maker_free():
    meta = MarketMeta("pm:x", "polymarket", "tok", "BTC", fee_schedule=(0.07, 1.0, True), kind="prediction")
    assert taker_fee_bps(meta, 0.5, 7.5) == pytest.approx(350.0)         # 7% * .25 / .5
    assert taker_fee_bps(meta, 0.1, 7.5) == pytest.approx(630.0)
    assert taker_fee_bps(meta, 0.9, 7.5) == pytest.approx(70.0)
    assert maker_fee_bps(meta, 7.5) == 0.0
    plain = MarketMeta("BTCUSDC", "binance", "BTCUSDC", "BTC", fee_taker_bps=0.0)
    assert taker_fee_bps(plain, 80_000, 7.5) == 0.0 and taker_fee_bps(MarketMeta("a", "binance", "a", "a"), 1.0, 7.5) == 7.5


def test_cfo_prices_the_polymarket_fee_and_rejects_small_gaps():
    metas = [MarketMeta("BTCUSDT", "binance", "BTCUSDT", "BTC"),
             MarketMeta("pm:x:above-80000", "polymarket", "tok", "BTC", kind="prediction", tick=0.01, fee_schedule=(0.07, 1.0, True),
                        spread_gate_bps=5000.0, hunt=False, asset="BTC-PM")]
    book = MarketBook(metas)
    cfo = CFOAgent(book, CFOConfig(fee_taker_bps=0.0, safety_hurdle_bps=0.0))
    big = mk_signal(idx=1, market="pm:x:above-80000", gap_bps=1200.0, spread_bps=200.0, bid=0.49, ask=0.51, mid=0.5, aq=5000, bq=5000,
                    sigma_res_bps=200.0)
    d = cfo.evaluate(big, 1.0)
    assert d.fee_bps == pytest.approx(2 * 0.07 * (1 - 0.51) * 1e4) and d.spread_bps == pytest.approx(200.0)   # 2 x ~343 bps taker (priced at the 0.51 ask)
    small = mk_signal(idx=1, market="pm:x:above-80000", gap_bps=600.0, spread_bps=200.0, bid=0.49, ask=0.51, mid=0.5, aq=5000, bq=5000, sid=2,
                      sigma_res_bps=200.0)
    assert not cfo.evaluate(small, 2.0).approved                                            # 6% gap < 2% spread + 7% fees
    cfo.apply_directive({"mode_policy": "maker_only"})
    dm = cfo.evaluate(small, 3.0)
    assert dm.mode == "maker" and dm.fee_bps == pytest.approx(0.07 * (1 - 0.51) * 1e4)   # maker entry free, one taker exit


def test_threshold_parsing():
    assert parse_threshold("Will the price of Bitcoin be above $80,000 on October 20?") == ("above", 80000.0, 0.0)
    assert parse_threshold("Will the price of Bitcoin be less than $74,000 on October 20?") == ("below", 74000.0, 0.0)
    assert parse_threshold("Will the price of Bitcoin be between $78,000 and $80,000 on October 20?") == ("range", 78000.0, 80000.0)
    assert parse_threshold("Will it rain?") is None


def test_candidate_slugs_cover_all_families():
    s = dict(candidate_slugs(1792437408.0, 1200.0, PolyConfig()))
    assert "btc-updown-5m-1792437300" in s and s["btc-updown-5m-1792437300"] == "updown_5m"
    assert "btc-updown-15m-1792437300" in s and "btc-updown-4h-1792425600" in s
    assert any(k.startswith("bitcoin-up-or-down-october-19-2026-") and k.endswith("pm-et") for k in s)
    assert "bitcoin-above-on-october-20-2026" in s and "bitcoin-price-on-october-20-2026" in s


def test_clob_book_maintenance_top_of_book():
    books = PmBooks()
    seen = []
    handle_clob_message([{"event_type": "book", "asset_id": "T", "bids": [{"price": "0.48", "size": "100"}, {"price": "0.47", "size": "50"}],
                          "asks": [{"price": "0.52", "size": "80"}, {"price": "0.53", "size": "10"}]}], books, seen.append)
    assert books.top("T") == (0.48, 0.52, 100.0, 80.0)
    handle_clob_message({"event_type": "price_change", "price_changes": [{"asset_id": "T", "side": "BUY", "price": "0.49", "size": "30"},
                                                                          {"asset_id": "T", "side": "SELL", "price": "0.52", "size": "0"}]},
                        books, seen.append)
    assert books.top("T") == (0.49, 0.53, 30.0, 10.0) and seen == ["T", "T"]
    handle_clob_message({"event_type": "price_change", "price_changes": [{"asset_id": "T", "side": "BUY", "price": "0.49", "size": "0"}]}, books, seen.append)
    assert books.top("T")[0] == 0.48


# --------------------------------------------------------------- scanner on a lagging market
def _agency():
    cfg = AgencyConfig()
    cfg.cfo.fee_taker_bps = 0.0
    metas = [MarketMeta("BTCUSDT", "binance", "BTCUSDT", "BTC", tick=0.01, step=1e-5),
             MarketMeta("pm:t:above-80000", "polymarket", "TOK", "BTC", kind="prediction", tick=0.01, step=0.01, min_notional=1.0, asset="BTC-PM",
                        fee_schedule=(0.07, 1.0, True), spread_gate_bps=5000.0, hunt=False, extra={"family": "above"})]
    ag = Agency(metas, cfg, t0=0.0, wall0=NOW)
    spec = {"pm:t:above-80000": PmSpec("above", t_end=NOW + 3600, K=80_000.0)}
    w = PolymarketWatcher(ag, [metas[1]], spec, {"pm:t:above-80000": "TOK"}, PolyConfig(), wall0=NOW, t0=0.0)
    ag.attach_polymarket(w)
    return ag, w


def _drive(ag, w, pm_follows: bool, jump: bool = True):
    """BTC: near-flat (0.02 bps/sqrt-s) with a +6 bps move during [60, 61). PM mid is either frozen at 0.50 or tracks fair value."""
    rng = np.random.default_rng(1)
    p = 80_000.0
    sigs, t, hist = [], 0.0, []
    while t < 70.0:
        t += 0.01
        p *= math.exp(rng.normal(0, 0.02e-4 * math.sqrt(0.01)))
        if jump and 60.0 <= t < 61.0:
            p *= math.exp(6e-4 / 100)
        hist.append(p)
        ag.on_quote(0, t, p - 0.005, p + 0.005, 3.0, 3.0)
        ag.oracle.advance(t)
        if int(round(t * 100)) % 10 == 0:
            if pm_follows:
                S_lag = hist[max(len(hist) - 6, 0)]                    # follows BTC with a 50 ms delay
                spec = w.specs["pm:t:above-80000"]
                mid = round(fair_prob(spec, S_lag, w.wall(t), w.sigma_s(ag.oracle.state(t))), 3)
                mid = min(max(mid, 0.1), 0.9)
            else:
                mid = 0.5
            ag.on_quote(1, t, mid - 0.005, mid + 0.005, 500.0, 500.0)
        if t > 55:
            sigs += w.scan(t, ag.oracle.state(t))
    return sigs


def test_stale_prediction_market_after_btc_impulse_is_a_signal():
    ag, w = _agency()
    sigs = _drive(ag, w, pm_follows=False)
    assert sigs, "a stale 50c market must be flagged when BTC jumps +6 bps"
    assert all(60.0 <= s.t <= 62.0 for s in sigs[:1])
    s = sigs[0]
    assert s.side == +1 and s.gap_bps > 0 and s.market == "pm:t:above-80000"
    assert s.beta == 1.0 and 0.0 <= s.age_s <= w.cfg.window_s and s.spread_bps == pytest.approx(200.0, rel=0.05)
    assert s.fair_bps > 0 and abs(s.actual_bps) < 1e-9                  # fair probability rose, the CLOB mid did not


def test_prediction_market_that_already_repriced_is_not_a_signal():
    ag, w = _agency()
    assert _drive(ag, w, pm_follows=True) == []


def test_flat_btc_produces_no_prediction_signals():
    ag, w = _agency()
    assert _drive(ag, w, pm_follows=False, jump=False) == []


def test_downward_impulse_sells_the_up_token():
    ag, w = _agency()
    rng = np.random.default_rng(3)
    p, t, sigs = 80_000.0, 0.0, []
    while t < 70.0:
        t += 0.01
        p *= math.exp(rng.normal(0, 0.02e-4 * math.sqrt(0.01)))
        if 60.0 <= t < 61.0:
            p *= math.exp(-6e-4 / 100)
        ag.on_quote(0, t, p - 0.005, p + 0.005, 3.0, 3.0)
        ag.oracle.advance(t)
        if int(round(t * 100)) % 10 == 0:
            ag.on_quote(1, t, 0.495, 0.505, 500.0, 500.0)
        if t > 55:
            sigs += w.scan(t, ag.oracle.state(t))
    assert sigs and sigs[0].side == -1 and sigs[0].gap_bps < 0
