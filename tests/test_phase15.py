import json

import numpy as np
import pytest

from quant_agency import alpha_tournament as at
from quant_agency import reward_farm as rf
from quant_agency import reward_share as rs
from quant_agency.polymarket_watcher import PmBooks


# ---------------------------------------------------------------- reward scoring (docs example: mid 0.50, v = 3 c, 100 at 0.49 scores ((3-1)/3)^2 x 100)
def test_reward_score_matches_the_docs_example():
    assert rs.score(1.0, 3.0) * 100 == pytest.approx((2 / 3) ** 2 * 100)
    assert rs.score(3.0, 3.0) == 0.0 and rs.score(-0.1, 3.0) == 0.0


def test_q_min_two_sided_rules():
    assert rs.q_min(90.0, 0.0, 0.5) == pytest.approx(30.0)          # single-sided scores at 1/3 in the 0.10-0.90 band
    assert rs.q_min(90.0, 0.0, 0.05) == 0.0                          # outside it, both sides are required
    assert rs.q_min(40.0, 60.0, 0.5) == pytest.approx(40.0)


def test_book_q_ignores_small_and_far_orders():
    yes = {"bids": [{"price": 0.49, "size": 100}, {"price": 0.40, "size": 1000}, {"price": 0.495, "size": 5}], "asks": [{"price": 0.51, "size": 100}]}
    no = {"bids": [], "asks": []}
    qo, qt = rs.book_q(yes, no, 0.5, 3.0, 10.0)
    assert qo == pytest.approx((2 / 3) ** 2 * 100) and qt == pytest.approx((2 / 3) ** 2 * 100)


def _farm(n=20.0):
    return rf.Farm("c", "q", "Y", "N", n, 4.5, 20.0, 144.0, "2027-01-01")


def _eng(tmp_path):
    e = rf.RewardFarm([_farm()], str(tmp_path))
    e.books.snapshot("Y", [{"price": "0.48", "size": "50"}], [{"price": "0.52", "size": "30"}])
    e.books.snapshot("N", [{"price": "0.48", "size": "50"}], [{"price": "0.52", "size": "40"}])
    return e


def test_quotes_join_the_best_ask_and_fill_through_the_queue(tmp_path):
    e = _eng(tmp_path)
    e.requote(0.0)
    f = e.farms["c"]
    assert f.asks["Y"].price == pytest.approx(0.52) and f.asks["N"].price == pytest.approx(0.52)
    import time as _t
    f.asks["Y"].t_live = 0.0
    e.on_trade("Y", 0.52, 25.0, "BUY")                                   # 30 displayed ahead of us: 5 left ahead
    assert f.cash == 0.0 and f.asks["Y"].ahead == pytest.approx(5.0)
    e.on_trade("Y", 0.52, 10.0, "SELL")                                  # a seller's trade does not consume asks
    e.on_trade("Y", 0.52, 15.0, "BUY")                                   # 5 ahead, then 10 of ours
    assert f.cash == pytest.approx(10 * 0.52) and f.held == {"N": 10.0} and f.pairs == pytest.approx(10.0) and f.stopped
    # equity: 5.2 cash + 10 pairs + 10 NO at the 0.48 bid - 20 capital
    assert f.equity(e.books) == pytest.approx(5.2 + 10 + 4.8 - 20)
    assert f.equity(e.books, "mid") == pytest.approx(5.2 + 10 + 5.0 - 20)


def test_reward_sampling_uses_the_published_formula(tmp_path):
    e = _eng(tmp_path)
    e.requote(0.0)
    f = e.farms["c"]
    for a in f.asks.values():
        a.t_live = 0.0
    e.sample(10.0)
    m = 0.5
    ours = rs.score(2.0, 4.5) * 20
    yb = {"bids": [{"price": 0.48, "size": 50}], "asks": [{"price": 0.52, "size": 30}]}
    nb = {"bids": [{"price": 0.48, "size": 50}], "asks": [{"price": 0.52, "size": 40}]}
    theirs = rs.q_min(*rs.book_q(yb, nb, m, 4.5, 20.0), m)
    assert f.rewards == pytest.approx(144.0 / 1440.0 * ours / (ours + theirs))
    assert f.scored == 1


def test_crossing_bid_fills_the_ask(tmp_path):
    e = _eng(tmp_path)
    e.requote(0.0)
    f = e.farms["c"]
    f.asks["N"].t_live = 0.0
    e.on_top("N")
    e.books.snapshot("N", [{"price": "0.53", "size": "50"}], [{"price": "0.55", "size": "40"}])
    e.on_top("N")
    assert f.cash == pytest.approx(20 * 0.52) and f.held == {"Y": 20.0}


# ---------------------------------------------------------------- tournament plumbing
def _panel(T=400, N=3, seed=0):
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.001, (T, N)), axis=0))
    o = np.vstack([c[:1], c[:-1]])
    return at.Panel("5m", np.arange(T) * 300.0, o, np.maximum(o, c), np.minimum(o, c), c, np.full((T, N), 1e5), ["A", "B", "C"], np.full(N, 1.0),
                    np.zeros((T, N)))


def test_simulate_costs_and_no_overlap():
    P = _panel()
    sig = np.zeros_like(P.c, dtype=int)
    sig[10, 0] = sig[12, 0] = -1                                          # the second signal overlaps the first hold
    tr = at.simulate(P, sig, 6, 0, len(P.t))
    assert len(tr) == 1
    r = tr[0]
    assert r["cost_bps"] == pytest.approx(2 * 4.5 + 2 * 1.5 * 1.0 + 2 * 2.0)
    assert r["gross_bps"] == pytest.approx(-(P.o[17, 0] / P.o[11, 0] - 1) * 1e4)


def test_rolling_std_excludes_the_current_bar():
    x = np.array([[1.0], [1.0], [1.0], [100.0]])
    s = at.rolling_std(x, 3)
    assert s[3, 0] == pytest.approx(0.0, abs=1e-6)                        # the spike itself is not in its own window


def test_split_bounds_are_disjoint_and_ordered():
    b = at.split_bounds(1000)
    assert b["train"] == (0, 500) and b["val"] == (500, 750) and b["oos"] == (750, 1000)


def test_governed_farm_quarantine_withdraws_quotes(tmp_path):
    from quant_agency.omega_governance import GovConfig, OState
    from quant_agency.reward_sleeve import GovernedFarm
    e = _eng(tmp_path)
    e.requote(0.0)
    g = GovernedFarm(e, 20.0, gas_usd=0.05, gov=GovConfig(bankroll=20.0, alloc={"reward_farm": 20.0}, kill_file=str(tmp_path / "K"), review_every_s=0.0))
    assert g.equity_change() == pytest.approx(-0.10)                       # split + merge gas, nothing else yet
    g.review(0.0)
    f = e.farms["c"]
    f.cash, f.pairs, f.held = 0.0, 0.0, {"N": 20.0}                      # all YES sold at 0 (absurd) -> 20 NO at the 0.48 bid
    e.books.snapshot("N", [{"price": "0.10", "size": "50"}], [{"price": "0.12", "size": "40"}])
    g.review(10.0)
    assert g.book.state == OState.QUARANTINED and not f.asks and not g.quoting_allowed()


def test_r2_buys_back_the_sold_outcome_and_requotes(tmp_path):
    f = _farm()
    f.fee_rate = 0.04
    e = rf.RewardFarm([f], str(tmp_path), hedge=True)
    e.books.snapshot("Y", [{"price": "0.48", "size": "50"}], [{"price": "0.52", "size": "30"}])
    e.books.snapshot("N", [{"price": "0.48", "size": "50"}], [{"price": "0.52", "size": "40"}])
    e.requote(0.0)
    f.asks["Y"].t_live = 0.0
    e.on_trade("Y", 0.53, 5.0, "BUY")                                     # trades through: all 20 YES sold at 0.52
    assert f.held == {"N": 20.0} and e.buybacks
    e.books.snapshot("Y", [{"price": "0.50", "size": "50"}], [{"price": "0.54", "size": "10"}, {"price": "0.55", "size": "50"}])
    import time as _time
    e.requote(_time.time() + 5.0)                                         # buy back 10 @ 0.54 + 10 @ 0.55 + fee
    cost = 10 * 0.54 + 10 * 0.55
    fee = 10 * 0.04 * 0.54 * 0.46 + 10 * 0.04 * 0.55 * 0.45
    assert f.pairs == pytest.approx(20.0) and not f.held and f.hedge_cost == pytest.approx(cost + fee)
    assert f.equity(e.books) == pytest.approx(20 * 0.52 - cost - fee)
    assert not f.stopped and f.asks                                        # quoting resumed


# ---------------------------------------------------------------- R3: passive bid pairs, toxicity gate, zero-fee merge
from quant_agency import reward_mm as rm


def _mm(tmp_path):
    x = rm.Mkt("c", "q", "Y", "N", 20.0, 4.5, 144.0, "2027")
    e = rm.RewardMM([x], str(tmp_path))
    e.books.snapshot("Y", [{"price": "0.49", "size": "100"}], [{"price": "0.51", "size": "100"}])
    e.books.snapshot("N", [{"price": "0.49", "size": "100"}], [{"price": "0.51", "size": "100"}])
    return e, x


def test_r3_quotes_two_bids_that_cost_at_most_098(tmp_path):
    e, x = _mm(tmp_path)
    e.requote(0.0)
    assert x.bids["Y"].price == pytest.approx(0.49) and x.bids["N"].price == pytest.approx(0.49)
    assert x.bids["Y"].price + x.bids["N"].price <= 0.98 + 1e-9


def test_r3_both_fills_merge_into_usdc(tmp_path):
    e, x = _mm(tmp_path)
    e.requote(0.0)
    for b in x.bids.values():
        b.t_live = 0.0
    e.on_trade("Y", 0.48, 5.0, "SELL")                                     # trades through our 0.49 YES bid
    e.on_trade("N", 0.48, 5.0, "SELL")
    assert x.merges == 1 and not any(v > 1e-9 for v in x.held.values())
    assert x.cash == pytest.approx(20 * (1 - 0.49 - 0.49) - rm.GAS_MERGE)


def test_r3_toxicity_gate_pulls_a_threatened_bid(tmp_path):
    e, x = _mm(tmp_path)
    e.requote(0.0)
    e.books.snapshot("Y", [{"price": "0.49", "size": "10"}], [{"price": "0.51", "size": "500"}])   # OBI = -0.96 against the YES bid
    e.on_top("Y")
    assert x.bids["Y"].cancel_at is not None and x.pulls == 1
    import time as _t
    e.requote(_t.time() + 2.0)
    assert "Y" not in x.bids


def test_r3_one_sided_fill_keeps_the_other_bid_resting(tmp_path):
    e, x = _mm(tmp_path)
    e.requote(0.0)
    for b in x.bids.values():
        b.t_live = 0.0
    e.on_trade("Y", 0.48, 5.0, "SELL")
    assert x.held == {"Y": 20.0} and "N" in x.bids and x.done.get("Y")
    assert x.equity(e.books) == pytest.approx(-20 * 0.49 + 20 * 0.49)       # paid 9.8, holds 20 YES worth 0.49 at the bid
