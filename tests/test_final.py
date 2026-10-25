import types

import numpy as np

from quant_agency.fast_arb_scanner import bid_value
from quant_agency.listing_short_capped import trigger
from quant_agency.specialist_consensus import category


def test_listing_trigger_needs_close_below_day0_typical_and_lower_high():
    hi = np.array([[10.0], [12.0], [11.0], [9.0], [9.0], [9.0], [9.0], [9.0]])
    lo = np.array([[6.0], [8.0], [8.0], [7.0], [7.0], [7.0], [7.0], [7.0]])
    c = np.array([[8.0], [11.0], [8.5], [7.5], [8.0], [8.0], [8.0], [8.0]])
    D = types.SimpleNamespace(first=np.array([0]), c=c, days=np.arange(8))
    # day0 typical = 8.0; day1 close 11 (no); day2 close 8.5 (no); day3 close 7.5 < 8 and high 9 < 12 -> enter at day 4 open
    assert trigger(D, hi, lo, 0) == 4
    c2 = c.copy()
    c2[1:6] = 9.0                                   # never closes below the day-0 typical price within 5 days
    assert trigger(types.SimpleNamespace(first=np.array([0]), c=c2, days=np.arange(8)), hi, lo, 0) is None


def test_categories():
    assert category("Bitcoin Up or Down - 5m") == "excluded"
    assert category("Will the Fed cut rates in December?") == "economics"
    assert category("Counter-Strike: G2 vs FURIA - Map 1 Winner") == "sports"
    assert category("Will Trump win the 2028 election?") == "politics"
    assert category("Will it snow in NYC on Christmas?") == "weather"


def test_bid_value_walks_depth_and_flags_thin_books():
    book = {"bids": [{"price": "0.40", "size": "5"}, {"price": "0.50", "size": "5"}]}
    v = bid_value(book, 8)
    assert abs(v - (5 * (0.5 - 0.05 * 0.25) + 3 * (0.4 - 0.05 * 0.24))) < 1e-12
    assert bid_value(book, 20) == float("-inf")
