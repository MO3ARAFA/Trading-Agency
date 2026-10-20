import json

import pytest

from quant_agency import phase12_report as pr
from quant_agency.hl_funding_basis import Bankroll


def _pm(tmp_path):
    d = tmp_path / "pm"
    d.mkdir()
    maker = {}
    for kind in ("slow", "control"):
        for pol in ("join", "penny"):
            for mod in ("strict", "trades", "depletion"):
                maker[f"{kind}|{pol}|{mod}"] = {"attempts": 100, "fills": 10, "fill_rate": 0.1, "fills_per_market_hour": 0.5, "spread_capture_c": 1.2, "markout_60s_c": -0.4, "markout_60s_se": 0.2,
                                                "markout_300s_c": -1.0, "markout_300s_se": 0.5, "usd_per_fill_300s": -0.05}
    res = {"hours": 1.0, "msgs": 1234567, "feed": {"reconnects": 1}, "universe_counts": {"events": 2100, "markets": 41000, "live": 34000, "slow_candidates": 385, "groups": 880},
           "n_slow": 80, "n_control": 8, "scan": {"groups": 40, "evals": 5000, "incomplete": 100},
           "mirror": {"checks": 30000, "min_ask_sum": 1.01, "max_bid_sum": 0.99, "crossed": 0},
           "opps": [{"gid": "g1", "kind": "buy_set", "n_legs": 3, "max_net": 0.0048, "max_gross": 0.013, "min_shares": 7.9, "exhaustive_like": True, "duration": 146.0, "days_to_end": 15.0},
                    {"gid": "g2", "kind": "sell_set", "n_legs": 10, "max_net": 0.01, "max_gross": 0.02, "min_shares": 50, "exhaustive_like": False, "duration": 20.0, "days_to_end": float("nan")}],
           "worst": {"g1|buy": {"gid": "g1", "kind": "buy", "best_net": 0.0048, "best_gross": 0.013, "shares": 7.9, "n": 3, "exh": True}},
           "maker": maker, "burst": {"slow": {"markets_with_trades": 20, "trades_per_min_median": 0.5, "fano_median": 1.1, "fano_p90": 3.0},
                                     "control": {"markets_with_trades": 8, "trades_per_min_median": 90.0, "fano_median": 4.0, "fano_p90": 6.0}},
           "sets": [{"complete": True, "locked_usd": 0.25, "legs_filled": 3, "pnl_mark_usd": 0.0}, {"complete": False, "locked_usd": 0.0, "legs_filled": 1, "pnl_mark_usd": -0.02}]}
    (d / "pm_result.json").write_text(json.dumps(res))
    (d / "pm_universe.json").write_text(json.dumps({"group_info": {"g1": {"title": "Who wins the Senate"}, "g2": {"title": "Fed cuts"}}}))
    return str(d)


def _hist(tmp_path):
    h = tmp_path / "hist"
    h.mkdir()
    (h / "funding_study.json").write_text(json.dumps({
        "coins": 51, "coin_hours": 110160, "median_bps_h": 0.125, "pct": {"1": -0.68, "5": -0.24, "50": 0.125, "95": 0.256, "99": 0.89},
        "share_ge": {"1.0": {"pos": 0.0075, "neg": 0.0053}, "3.0": {"pos": 0.0002, "neg": 0.0017}, "5.0": {"pos": 0.0, "neg": 0.0009}},
        "persistence_pos": {"1.0": {"starts": 824, "carry_4h_bps": 3.8, "carry_8h_bps": 6.4, "carry_24h_bps": 14.4}, "3.0": {"starts": 17, "carry_4h_bps": 5.2, "carry_8h_bps": 9.1, "carry_24h_bps": 20.9}},
        "runs_pos": {"1.0": {"median_h": 1.0, "share_ge_3h": 0.27, "share_ge_6h": 0.08}, "3.0": {"median_h": 1.0, "share_ge_3h": 0.0, "share_ge_6h": 0.0}},
        "breakeven_hours": {k: {"0.125": c / 0.125, "1.0": c, "3.0": c / 3, "5.0": c / 5} for k, c in (("perp_only_maker", 3.0), ("perp_only_taker", 9.0), ("hedged_perp_maker+spot", 18.0))}}))
    cell = {"n": 100, "clusters": 50, "mean_abs_dev": 20.0, "perp": {"mean": 1.0, "se": 2.0}, "spot": {"mean": -1.0, "se": 2.0}, "hedged": {"mean": 0.1, "se": 0.5}, "reverted_frac": 0.5,
            "net": {"perp_only_maker": {"mean": -2.0, "se": 2.0}, "perp_only_taker": {"mean": -8.0, "se": 2.0}, "hedged_perp_maker+spot": {"mean": -17.9, "se": 0.5}}}
    (h / "basis_study.json").write_text(json.dumps({"cut_min": 2695, "train": {"15.0": {"events": 100, "by_h": {"15": cell}}}, "test": {"15.0": {"events": 90, "by_h": {"15": cell}}}, "selected": {"thr": "30.0", "h": 30, "train_net_perp_maker": 24.8}}))
    (h / "dev_path.json").write_text(json.dumps({"path": {"0": 26.1, "5": 17.2, "30": 15.9}}))
    (h / "premium_test.json").write_text(json.dumps({"coins": 60, "bars_used": 2316, "decision": "do not reject H0", "spec": {"thr_bps": 30.0, "h_bars": 4, "cost_bps": 6.0, "min_clusters": 30},
                                                      "primary": {"n": 350, "clusters": 254, "net_neutral": {"mean": 15.5, "se": 17.8, "t": 0.87, "p1": 0.194}},
                                                      "cells": {"30|4": {"n": 350, "clusters": 254, "neutral": {"mean": 21.5, "se": 17.8}, "raw_perp": {"mean": 26.9, "se": 23.1}, "hedged": {"mean": 31.6, "se": 1.5},
                                                                         "net_neutral": {"mean": 15.5, "se": 17.8, "t": 0.87, "p1": 0.194}}}}))
    for n in ("xvr_s1_basis.json", "xvr_s2_basis.json"):
        (h / n).write_text(json.dumps({"events": 2, "cells": {"8|300": {"n": 2, "hedged_mid": {"mean": 4.2, "se": 3.0}, "hedged_cross": {"mean": -2.0, "se": 3.1}}}}))
    return str(h)


def test_report_builds_every_section(tmp_path):
    md = pr.build(_pm(tmp_path), _hist(tmp_path), "NOTE-MARKER", Bankroll())
    for needle in ("NOTE-MARKER", "The 100 USD account in numbers", "Track 1", "Structural scan", "Passive quoting", "Maker lock", "Track 2", "Funding", "Basis reversion at 5 / 15 / 30 minutes",
                   "quote level", "pre-declared test", "How this compares with Phases 1"):
        assert needle in md
    assert "0 crossed" in md and "Who wins the Senate" in md and "do not reject H0" in md
    assert "0.0100 USD per basis point" not in md and "$0.0020" not in md


def test_dollars_and_capital_arithmetic(tmp_path):
    md = pr.build(_pm(tmp_path), _hist(tmp_path), "", Bankroll())
    # buy-set: net 0.0048 on capital 1 - 0.013 = 0.987 over 15 days -> annualised ~ 11.8 %
    ret = 0.0048 / 0.987
    assert f"{100 * ret:.0f}%" in md
    assert f"{100 * ret * 365 / 15:.0f}%" in md
    assert "**0.50 USD**" in md                                   # the largest dollar opportunity is g2: 0.01 per set x 50 shares
    assert "One basis point of 20 USD is 0.0020 USD" in md
