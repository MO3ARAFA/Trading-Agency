"""Phase 16B: interior-odds sharp-wallet selection + cash-recycling, exit-mirrored copy portfolio (pre-registration:
docs/PREREG_P16B_SHARP.json). Uses the Phase 16 cache (runs/p16: wallets' activity, market resolutions).

Periods (calendar): P1 [2026-06-27, 2026-08-11) rank, P2 [2026-08-11, 2026-08-26) validate, P3 [2026-08-26, now-1d) out-of-sample,
P4 [prereg commit, ...) forward (fetched later with --step forward).

A copy of one wallet BUY at price p (0.15 <= p <= 0.85, market not a short-dated crypto "Up or Down"):
  entry  = p + max(1c, 2% p), plus the taker fee rate*e*(1-e);
  exit   = the wallet's first SELL of the same token after the buy, at s - max(1c, 2% s) minus the fee, if it comes before the market
           closes; otherwise the resolved payout (0/1). Copies with neither are "open" (no return).
"""
from __future__ import annotations

import datetime as dt
import heapq
import json
import os
import statistics
from collections import defaultdict
from typing import Dict, List, Optional

from quant_agency.copy_study import OUT, clustered, wallet_trades

LO, HI = 0.15, 0.85
P1, P2, P3 = "2026-06-27T00:00:00Z", "2026-08-11T00:00:00Z", "2026-08-26T00:00:00Z"


def ts(s: Optional[str]) -> Optional[int]:
    if not s:
        return None
    s = s.replace(" ", "T").replace("Z", "+00:00")
    if s.endswith("+00"):
        s += ":00"
    try:
        return int(dt.datetime.fromisoformat(s).timestamp())
    except ValueError:
        return None


def allowed(m: Optional[dict]) -> bool:
    return bool(m) and "Up or Down" not in m["q"]


def slip(p: float) -> float:
    return max(0.01, 0.02 * p)


def copies_of(trades: List[dict], markets: Dict[str, dict], t_lo: int, t_hi: int, wallet: str = "") -> List[dict]:
    """Copies of the wallet's interior BUYs in [t_lo, t_hi), each with its exit (mirrored sell or resolution) or open."""
    sells = defaultdict(list)
    for r in trades:
        if r["side"] == "SELL":
            sells[r["asset"]].append((r["t"], r["price"]))
    for v in sells.values():
        v.sort()
    out = []
    for r in trades:
        if r["side"] != "BUY" or not (t_lo <= r["t"] < t_hi) or not (LO <= r["price"] <= HI):
            continue
        m = markets.get(r["cid"])
        if not allowed(m) or r["asset"] not in m["tokens"]:
            continue
        rate = m["fee"]
        e = r["price"] + slip(r["price"])
        cost = e + rate * e * (1 - e)
        close_t = ts(m.get("closedTime")) if m["closed"] else None
        sell = next(((t, p) for t, p in sells[r["asset"]] if t > r["t"]), None)
        c = {"wallet": wallet, "cid": r["cid"], "asset": r["asset"], "t": r["t"], "price": r["price"], "cost": cost, "w": 1.0}
        if sell and (close_t is None or sell[0] < close_t):
            x = max(0.01, sell[1] - slip(sell[1]))
            c.update(exit_t=sell[0], value=x - rate * x * (1 - x), how="mirror")
        elif close_t is not None and m["prices"][m["tokens"].index(r["asset"])] in (0.0, 1.0):
            c.update(exit_t=close_t, value=m["prices"][m["tokens"].index(r["asset"])], how="resolve")
        else:
            c.update(exit_t=None, value=None, how="open")
        if c["value"] is not None:
            c["ret"] = (c["value"] - cost) / cost
        out.append(c)
    return out


def is_mm(trades: List[dict], t_lo: int, t_hi: int, frac: float = 0.10) -> bool:
    """Buys both tokens of the same market within 1 h in >= frac of its markets."""
    by = defaultdict(list)
    for r in trades:
        if r["side"] == "BUY" and t_lo <= r["t"] < t_hi:
            by[r["cid"]].append((r["t"], r["asset"]))
    if not by:
        return False
    both = 0
    for v in by.values():
        v.sort()
        if any(a2 != a1 and t2 - t1 <= 3600 for (t1, a1), (t2, a2) in zip(v, v[1:])):
            both += 1
    return both / len(by) >= frac


def rank(acts: Dict[str, List[dict]], markets: Dict[str, dict], t_lo: int, t_hi: int) -> List[dict]:
    """Rank on [t_lo, t_hi) with exits known before t_hi only (no look-ahead)."""
    res = []
    for w, tr in acts.items():
        buys = [r["price"] for r in tr if r["side"] == "BUY" and t_lo <= r["t"] < t_hi]
        if not buys or statistics.median(buys) > HI or is_mm(tr, t_lo, t_hi):
            continue
        rows = [c for c in copies_of(tr, markets, t_lo, t_hi, w) if c["exit_t"] is not None and c["exit_t"] < t_hi]
        if len(rows) < 20 or len({c["cid"] for c in rows}) < 10:
            continue
        s = clustered(rows)
        if s.get("se", 0) > 0 and s["mean"] > 0:
            res.append({"wallet": w, **{k: s[k] for k in ("n", "markets", "mean", "t")}})
    return sorted(res, key=lambda x: -x["t"])


def simulate(copies: List[dict], end_t: int, bankroll: float = 100.0, stake: float = 4.0, per_wallet: float = 15.0) -> dict:
    """Event-driven 100 USD account: cash recycles at each exit; one position per market; <= per_wallet USD open per wallet."""
    cash, open_heap, held, wexp = bankroll, [], set(), defaultdict(float)
    curve, taken, skip = [], 0, defaultdict(int)
    k = 0

    def release(upto):
        nonlocal cash
        while open_heap and open_heap[0][0] <= upto:
            _, _, c, usd = heapq.heappop(open_heap)
            cash += usd * c["value"] / c["cost"]
            held.discard(c["cid"])
            wexp[c["wallet"]] -= usd

    for c in sorted(copies, key=lambda c: c["t"]):
        release(c["t"])
        usd = max(stake, 5 * c["cost"])                                     # venue minimum 5 shares
        if c["cid"] in held:
            skip["same_market"] += 1
            continue
        if wexp[c["wallet"]] + usd > per_wallet:
            skip["wallet_cap"] += 1
            continue
        if cash < usd:
            skip["cash"] += 1
            continue
        cash -= usd
        taken += 1
        held.add(c["cid"])
        wexp[c["wallet"]] += usd
        k += 1
        heapq.heappush(open_heap, (c["exit_t"] if c["exit_t"] is not None and c["exit_t"] <= end_t else float("inf"), k, c, usd))
        curve.append((c["t"], round(cash + sum(u for *_, u in open_heap), 2)))
    release(end_t)
    stuck = sum(u for *_, u in open_heap)                                    # unresolved at the end: marked at cost
    return {"taken": taken, "skipped": dict(skip), "final": round(cash + stuck, 2), "cash": round(cash, 2), "open_at_cost": round(stuck, 2),
            "open_positions": len(open_heap), "curve": curve}


def load():
    markets = json.load(open(f"{OUT}/markets.json"))
    acts = {}
    for w in json.load(open(f"{OUT}/wallets.json")):
        p = f"{OUT}/act/{w}.json"
        if os.path.exists(p):
            a = json.load(open(p))
            acts[w] = a["sel"] + a["cop"]
    return acts, markets


def evaluate(acts, markets, wallets: List[str], t_lo: int, t_hi: int, end_t: int, stake: float, per_wallet: float) -> dict:
    cps = [c for w in wallets for c in copies_of(acts[w], markets, t_lo, t_hi, w)]
    done = [c for c in cps if c["value"] is not None and c["exit_t"] <= end_t]
    sim = simulate(cps, end_t, stake=stake, per_wallet=per_wallet)
    hows = defaultdict(int)
    for c in cps:
        hows[c["how"]] += 1
    return {"copies": len(cps), "closed": len(done), "how": dict(hows), "stats": clustered(done), "account": {k: v for k, v in sim.items() if k != "curve"},
            "curve": sim["curve"]}


def main(argv=None):
    import argparse
    import time
    ap = argparse.ArgumentParser()
    ap.add_argument("--step", choices=["validate", "oos", "forward"], required=True)
    a = ap.parse_args(argv)
    t1, t2, t3, now = ts(P1), ts(P2), ts(P3), int(time.time())
    os.makedirs(f"{OUT}/sharp", exist_ok=True)
    if a.step == "validate":                                                 # rank on P1, score P2 for each K
        acts, markets = load()
        ranked = rank(acts, markets, t1, t2)
        out = {"ranked": len(ranked)}
        for K in (10, 25, 50):
            ws = [r["wallet"] for r in ranked[:K]]
            r = evaluate(acts, markets, ws, t2, t3, now - 86400, 4.0, 15.0)
            out[K] = {k: v for k, v in r.items() if k != "curve"}
        json.dump(out, open(f"{OUT}/sharp/validate.json", "w"), indent=1, default=float)
        print(json.dumps(out, indent=1, default=float))
    elif a.step == "oos":                                                    # frozen rule: rank on P1+P2, score P3 once
        pre = json.load(open("docs/PREREG_P16B_SHARP.json"))
        acts, markets = load()
        ranked = rank(acts, markets, t1, t3)
        ws = [r["wallet"] for r in ranked[:pre["K"]]]
        json.dump(ws, open(f"{OUT}/sharp/selected.json", "w"))
        r = evaluate(acts, markets, ws, t3, now - 86400, now - 86400, pre["stake"], pre["per_wallet"])
        r["selected"] = ranked[:pre["K"]]
        json.dump(r, open(f"{OUT}/sharp/oos.json", "w"), indent=1, default=float)
        print(json.dumps({k: v for k, v in r.items() if k not in ("curve", "selected")}, indent=1, default=float))
    else:                                                                    # P4: trades after the pre-registration, scored later
        pre = json.load(open("docs/PREREG_P16B_SHARP.json"))
        ws = json.load(open(pre["forward"]["wallets_file"]))
        t4 = ts(pre["forward"]["start"])
        acts = {w: wallet_trades(w, t4, now) for w in ws}
        from quant_agency.copy_study import fetch_markets
        markets = fetch_markets(sorted({r["cid"] for v in acts.values() for r in v}))
        r = evaluate(acts, markets, ws, t4, now - 86400, now, pre["stake"], pre["per_wallet"])
        json.dump(r, open(f"{OUT}/sharp/forward.json", "w"), indent=1, default=float)
        print(json.dumps({k: v for k, v in r.items() if k != "curve"}, indent=1, default=float))


if __name__ == "__main__":
    main()
