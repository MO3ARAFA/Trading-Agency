"""Polymarket liquidity-reward share estimator (docs.polymarket.com/market-makers/liquidity-rewards).

For a rewarded binary market with max spread v (cents), min size m and daily rate R, every resting order within v of the midpoint scores
S = ((v - s) / v)^2 x size (s = its distance from the midpoint in cents; the docs' in-game multiplier b is taken as 1). Per sample:
  Q_one = sum S x bid size on YES + sum S x ask size on NO,   Q_two = sum S x ask size on YES + sum S x bid size on NO
  Q_min = max(min(Q_one, Q_two), max(Q_one, Q_two) / 3) if 0.10 <= mid <= 0.90, else min(Q_one, Q_two)
and a maker's share of R is its Q_min over the sum of every maker's Q_min. We do not see other makers' identities, so the competition is
approximated by scoring the whole visible book as one maker (its Q_min); our share = ours / (ours + book's). This *overstates* the
competition's Q_min when several makers each quote only one side (their individual Q_min is smaller), so the estimate of our share is
conservative.

The account quotes from a complete set: split N USDC into N YES + N NO (no fee, exactly 1 USDC per pair), then rest an ask of N YES at
mid + d and an ask of N NO at (1 - mid) + d. Both are asks, one on each outcome, so the position is two-sided by the formula above and
needs no extra collateral.
"""
from __future__ import annotations

import json
import urllib.request
from typing import Dict, List, Optional, Tuple

CLOB = "https://clob.polymarket.com"


def score(dist_c: float, v: float) -> float:
    return ((v - dist_c) / v) ** 2 if 0 <= dist_c < v else 0.0


def book_q(yes_book: dict, no_book: dict, mid: float, v: float, min_size: float) -> Tuple[float, float]:
    """(Q_one, Q_two) of everything resting in the two books (orders below the minimum size do not score)."""
    def side(levels, ref, is_bid):
        q = 0.0
        for lv in levels:
            px, sz = float(lv["price"]), float(lv["size"])
            if sz < min_size:
                continue
            q += score(abs(px - ref) * 100.0, v) * sz
        return q
    q_one = side(yes_book.get("bids", []), mid, True) + side(no_book.get("asks", []), 1 - mid, False)
    q_two = side(yes_book.get("asks", []), mid, False) + side(no_book.get("bids", []), 1 - mid, True)
    return q_one, q_two


def q_min(q_one: float, q_two: float, mid: float) -> float:
    if 0.10 <= mid <= 0.90:
        return max(min(q_one, q_two), max(q_one, q_two) / 3.0)
    return min(q_one, q_two)


def our_q(n: float, d_c: float, v: float, mid: float) -> float:
    """Asks of n YES at mid + d and n NO at (1 - mid) + d: Q_one gets the NO ask, Q_two the YES ask."""
    s = score(d_c, v) * n
    return q_min(s, s, mid)


def tick_round_up(px: float, tick: float = 0.01) -> float:
    import math
    return math.ceil(px / tick - 1e-9) * tick


def estimate(market: dict, n_pairs: float, books: Dict[str, dict]) -> Optional[dict]:
    rate = sum(float(c.get("rate_per_day") or 0) for c in market.get("rewards_config") or [])
    v, m = float(market["rewards_max_spread"]), float(market["rewards_min_size"])
    toks = {t["outcome"].lower(): t["token_id"] for t in market["tokens"]}
    yb, nb = books.get(toks.get("yes")), books.get(toks.get("no"))
    if not rate or yb is None or nb is None or n_pairs < m:
        return None
    try:
        bb, ba = max(float(x["price"]) for x in yb["bids"]), min(float(x["price"]) for x in yb["asks"])
    except ValueError:
        return None
    mid = (bb + ba) / 2.0
    qo, qt = book_q(yb, nb, mid, v, m)
    theirs = q_min(qo, qt, mid)
    ask_y = max(tick_round_up(mid + 0.005), ba)                       # never inside the current best ask's queue front: join it or a tick out
    d = (ask_y - mid) * 100.0
    ours = our_q(n_pairs, d, v, mid)
    share = ours / (ours + theirs) if ours > 0 else 0.0
    return {"question": market["question"][:70], "rate": rate, "v": v, "min_size": m, "mid": round(mid, 4), "spread_c": round((ba - bb) * 100, 2),
            "our_dist_c": round(d, 2), "ours": round(ours, 1), "theirs": round(theirs, 1), "share": share, "usd_per_day": share * rate,
            "capital": n_pairs, "ret_per_day": share * rate / n_pairs, "vol24": market.get("volume_24hr"), "condition_id": market["condition_id"],
            "tokens": toks}


def fetch_books(token_ids: List[str]) -> Dict[str, dict]:
    out = {}
    for i in range(0, len(token_ids), 400):
        req = urllib.request.Request(CLOB + "/books", data=json.dumps([{"token_id": t} for t in token_ids[i:i + 400]]).encode(),
                                     headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"})
        for b in json.loads(urllib.request.urlopen(req, timeout=60).read()):
            out[b["asset_id"]] = b
    return out


def reward_markets(pages: int = 10) -> List[dict]:
    out, cur = [], ""
    for _ in range(pages):
        req = urllib.request.Request(f"{CLOB}/rewards/markets/multi?order_by=rate_per_day&position=DESC&page_size=500" + (f"&next_cursor={cur}" if cur else ""),
                                     headers={"User-Agent": "Mozilla/5.0"})
        r = json.loads(urllib.request.urlopen(req, timeout=60).read())
        page = [x for x in r["data"] if x.get("rewards_config")]
        out += page
        cur = r.get("next_cursor")
        if not page or not cur or cur == "LTE=":
            break
    return out
