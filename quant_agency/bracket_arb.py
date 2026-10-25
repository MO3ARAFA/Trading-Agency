"""Phase 15, Track 4: monotonicity arbitrage across cumulative date brackets on Polymarket.

In an event whose markets are "X by date d1", "X by d2", ... (d1 < d2), YES(d2) must be worth at least YES(d1). A pair with
ask(YES_d2) + ask(NO_d1) + taker fees < 1 pays >= 1 in every state (X by d1: YES_d2 pays 1; between: both pay; never: NO_d1 pays 1).
The scan walks every live non-NegRisk event with >= 2 markets whose questions differ only by a date, orders them by end date, and
prices every earlier/later pair at the best asks (depth >= 5 shares) with each market's fee schedule.
"""
from __future__ import annotations

import json
import re
import urllib.request
from typing import Dict, List

from .reward_share import fetch_books

GAMMA = "https://gamma-api.polymarket.com"
_DATE = re.compile(r"\b(by|before|in)\b.*$", re.I)


def _get(u):
    return json.loads(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"}), timeout=60).read())


def events(pages: int = 21) -> List[dict]:
    out = []
    for p in range(pages):
        part = _get(f"{GAMMA}/events?active=true&closed=false&limit=100&offset={100 * p}")
        if not part:
            break
        out += [e for e in part if not e.get("negRisk") and len(e.get("markets") or []) >= 2]
    return out


def ladders(evs: List[dict]) -> List[List[dict]]:
    out = []
    for e in evs:
        ms = [m for m in e["markets"] if not m.get("closed") and m.get("acceptingOrders") and m.get("clobTokenIds")]
        stems: Dict[str, List[dict]] = {}
        for m in ms:
            q = m.get("question") or ""
            if not re.search(r"\b(by|before)\b", q, re.I):
                continue
            stems.setdefault(_DATE.sub("", q).strip().lower(), []).append(m)
        for g in stems.values():
            if len(g) >= 2:
                out.append(sorted(g, key=lambda m: m.get("endDate") or ""))
    return out


def scan(min_shares: float = 5.0) -> dict:
    lad = ladders(events())
    toks = []
    for g in lad:
        for m in g:
            toks += json.loads(m["clobTokenIds"])
    books = fetch_books(toks)
    opps, pairs = [], 0

    def ask(tok):
        b = books.get(tok)
        if not b or not b.get("asks"):
            return None
        lv = min(((float(a["price"]), float(a["size"])) for a in b["asks"]), key=lambda x: x[0])
        return lv if lv[1] >= min_shares else None
    for g in lad:
        for i in range(len(g)):
            for j in range(i + 1, len(g)):
                e_, l_ = g[i], g[j]
                if (e_.get("endDate") or "") >= (l_.get("endDate") or ""):
                    continue
                ye = json.loads(e_["clobTokenIds"])
                yl = json.loads(l_["clobTokenIds"])
                a_no_e, a_yes_l = ask(ye[1]), ask(yl[0])
                pairs += 1
                if not a_no_e or not a_yes_l:
                    continue
                def fee(m, p):
                    fs = m.get("feeSchedule") or {}
                    return (float(fs.get("rate") or 0) if m.get("feesEnabled") else 0.0) * p * (1 - p)
                cost = a_no_e[0] + a_yes_l[0] + fee(e_, a_no_e[0]) + fee(l_, a_yes_l[0])
                if cost < 1.0:
                    opps.append({"early": e_["question"][:80], "late": l_["question"][:80], "cost": round(cost, 4), "edge": round(1 - cost, 4),
                                 "shares": min(a_no_e[1], a_yes_l[1]), "late_end": l_.get("endDate")})
    return {"ladders": len(lad), "pairs": pairs, "opportunities": sorted(opps, key=lambda o: -o["edge"])}


if __name__ == "__main__":
    r = scan()
    print(r["ladders"], "ladders,", r["pairs"], "pairs,", len(r["opportunities"]), "with cost < 1")
    for o in r["opportunities"][:15]:
        print(o)
