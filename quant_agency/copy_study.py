"""Phase 16: does copying skilled Polymarket wallets pay after latency and fees? (pre-registered: docs/PREREG_P16_COPY.json)

Steps (cached under runs/p16):
  1. universe  - top wallets by traded volume (all-time and month leaderboards), not by profit;
  2. activity  - every TRADE of each wallet in [D-60d, now) (data-api /activity, newest first, capped per wallet and window);
  3. markets   - resolution and fee schedule of every traded market (Gamma /markets?condition_ids=...);
  4. evaluate  - rank wallets on [D-60d, D) only, then score the copies of the top K's buys made in [D, now-1d).
"""
from __future__ import annotations

import datetime as dt
import json
import math
import os
import time
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional

DATA = "https://data-api.polymarket.com"
GAMMA = "https://gamma-api.polymarket.com"
OUT = "runs/p16"


def _get(url: str, tries: int = 5):
    for k in range(tries):
        try:
            return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=60).read())
        except Exception:
            time.sleep(1.5 * (k + 1))
    return None


def _ts(s: str) -> int:
    return int(dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp())


# ------------------------------------------------------------------ 1. universe
def universe(n: int = 1000) -> List[str]:
    seen: Dict[str, None] = {}
    for period in ("all", "month"):
        for off in range(0, n, 50):
            rows = _get(f"{DATA}/v1/leaderboard?timePeriod={period}&orderBy=VOL&limit=50&offset={off}") or []
            for r in rows:
                seen.setdefault(r["proxyWallet"].lower())
            if len(rows) < 50:
                break
    return list(seen)


# ------------------------------------------------------------------ 2. activity
def wallet_trades(w: str, start: int, end: int, cap: int = 3000) -> List[dict]:
    out, off = [], 0
    while off < cap:
        rows = _get(f"{DATA}/activity?user={w}&type=TRADE&start={start}&end={end}&limit=500&offset={off}")
        if not rows:
            break
        out += [{"t": r["timestamp"], "cid": r["conditionId"], "asset": r["asset"], "side": r["side"], "price": float(r["price"]), "size": float(r["size"]),
                 "usd": float(r.get("usdcSize") or 0.0), "oi": r.get("outcomeIndex")} for r in rows]
        if len(rows) < 500:
            break
        off += 500
    return out


def fetch_activity(wallets: List[str], D: int, now: int, workers: int = 8) -> None:
    os.makedirs(f"{OUT}/act", exist_ok=True)

    def one(w):
        p = f"{OUT}/act/{w}.json"
        if os.path.exists(p):
            return w, -1
        sel = wallet_trades(w, D - 60 * 86400, D)
        cop = wallet_trades(w, D, now)
        json.dump({"sel": sel, "cop": cop}, open(p, "w"))
        return w, len(sel) + len(cop)
    with ThreadPoolExecutor(workers) as ex:
        for i, (w, n) in enumerate(ex.map(one, wallets)):
            if i % 50 == 0:
                print("activity", i, w, n, flush=True)


# ------------------------------------------------------------------ 3. markets
def fetch_markets(cids: List[str], workers: int = 8) -> Dict[str, dict]:
    path = f"{OUT}/markets.json"
    have = json.load(open(path)) if os.path.exists(path) else {}
    todo = [c for c in cids if c not in have]

    def batch(chunk):
        q = "&".join(f"condition_ids={c}" for c in chunk)
        rows = _get(f"{GAMMA}/markets?{q}&limit=100&closed=true") or []
        rows += _get(f"{GAMMA}/markets?{q}&limit=100") or []
        res = {}
        for m in rows:
            try:
                toks = json.loads(m.get("clobTokenIds") or "[]")
                px = [float(x) for x in json.loads(m.get("outcomePrices") or "[]")]
            except ValueError:
                continue
            fs = m.get("feeSchedule") or {}
            res[m["conditionId"]] = {"closed": bool(m.get("closed")), "tokens": toks, "prices": px, "closedTime": m.get("closedTime"),
                                     "fee": float(fs.get("rate") or 0.0) if m.get("feesEnabled") else 0.0, "q": (m.get("question") or "")[:80]}
        return res
    chunks = [todo[i:i + 20] for i in range(0, len(todo), 20)]
    with ThreadPoolExecutor(workers) as ex:
        for i, r in enumerate(ex.map(batch, chunks)):
            have.update(r)
            if i % 200 == 0:
                print("markets", i, len(chunks), flush=True)
                json.dump(have, open(path, "w"))
    json.dump(have, open(path, "w"))
    return have


def resolved_value(m: dict, asset: str, before: Optional[int] = None) -> Optional[float]:
    """Payout of one share of ``asset`` if the market resolved cleanly (prices 0/1), optionally only if it closed before ``before``."""
    if not m or not m["closed"] or asset not in m["tokens"]:
        return None
    if before is not None:
        ct = m.get("closedTime")
        if not ct:
            return None
        try:
            if _ts(ct.replace(" ", "T").replace("+00", "+00:00") if "+00" in ct and "+00:00" not in ct else ct.replace(" ", "T")) >= before:
                return None
        except ValueError:
            return None
    v = m["prices"][m["tokens"].index(asset)]
    return v if v in (0.0, 1.0) else None


# ------------------------------------------------------------------ 4. evaluate
def clustered(rows: List[dict], key: str = "ret", w: str = "w") -> dict:
    n = len(rows)
    if n < 2:
        return {"n": n}
    tot_w = sum(r[w] for r in rows)
    mu = sum(r[key] * r[w] for r in rows) / tot_w
    cl = defaultdict(float)
    for r in rows:
        cl[r["cid"]] += r[w] * (r[key] - mu)
    se = math.sqrt(sum(v * v for v in cl.values())) / tot_w
    return {"n": n, "markets": len(cl), "mean": mu, "se": se, "t": mu / se if se > 0 else float("nan"), "win": sum(r[key] > 0 for r in rows) / n}


def evaluate(pre: dict, markets: Dict[str, dict], wallets: List[str], now: int) -> dict:
    D = _ts(pre["D"])
    scores = []
    for w in wallets:
        p = f"{OUT}/act/{w}.json"
        if not os.path.exists(p):
            continue
        a = json.load(open(p))
        rows = []
        for tr in a["sel"]:
            if tr["side"] != "BUY" or not (0.0 < tr["price"] < 1.0):
                continue
            v = resolved_value(markets.get(tr["cid"]), tr["asset"], before=D)
            if v is None:
                continue
            rows.append({"cid": tr["cid"], "ret": (v - tr["price"]) / tr["price"], "w": 1.0, "usd": tr["usd"]})
        if len(rows) >= 30 and sum(r["usd"] for r in rows) >= 2000:
            s = clustered(rows)
            scores.append((s["t"], w, s))
    scores.sort(key=lambda x: -x[0] if x[0] == x[0] else 1e9)
    top = [w for _, w, _ in scores[:25]]
    copies = []
    for w in top:
        a = json.load(open(f"{OUT}/act/{w}.json"))
        for tr in a["cop"]:
            if tr["side"] != "BUY" or not (0.0 < tr["price"] < 1.0) or tr["t"] >= now - 86400:
                continue
            m = markets.get(tr["cid"])
            v = resolved_value(m, tr["asset"])
            if v is None:
                continue
            px = tr["price"] + max(0.01, 0.02 * tr["price"])         # never better than the wallet's own fill
            if px >= 1.0:
                continue                                              # nothing left to buy below 1.00: no copy possible
            fee = (m["fee"] if m else 0.05) * px * (1 - px)
            copies.append({"cid": tr["cid"], "wallet": w, "t": tr["t"], "price": tr["price"], "px": px, "ret": (v - px - fee) / (px + fee), "w": 1.0,
                           "payout": v})
    res = {"wallets_ranked": len(scores), "top": [{"wallet": w, "t": round(t, 2), "n": s["n"], "mean": round(s["mean"], 4)} for t, w, s in scores[:25]],
           "copy": clustered(copies), "copies": len(copies)}
    res["account"] = account(copies)
    return res, copies


def account(copies: List[dict], bankroll: float = 100.0, stake: float = 2.0) -> dict:
    """Copy every trade with ``stake`` USD (if cash allows) in time order; P&L realised at the market's close (approximated: the
    copy window's trades are settled in order, cash recycled only after settlement is not modelled -> stake is spent and returned
    with the payout at the end; this is conservative on capacity)."""
    cash, pnl, taken = bankroll, 0.0, 0
    for c in sorted(copies, key=lambda c: c["t"]):
        if cash < stake:
            continue
        cash -= stake
        pnl += stake * c["ret"]
        taken += 1
    return {"copied": taken, "pnl_usd": round(pnl, 2), "final": round(bankroll + pnl, 2)}


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--step", choices=["fetch", "evaluate"], required=True)
    a = p.parse_args(argv)
    pre = json.load(open("docs/PREREG_P16_COPY.json"))
    D, now = _ts(pre["D"]), int(time.time())
    os.makedirs(OUT, exist_ok=True)
    wp = f"{OUT}/wallets.json"
    if not os.path.exists(wp):
        json.dump(universe(), open(wp, "w"))
    wallets = json.load(open(wp))
    if a.step == "fetch":
        print("wallets", len(wallets), flush=True)
        fetch_activity(wallets, D, now)
        cids = set()
        for w in wallets:
            pth = f"{OUT}/act/{w}.json"
            if os.path.exists(pth):
                d = json.load(open(pth))
                cids |= {t["cid"] for t in d["sel"] + d["cop"] if t["side"] == "BUY"}
        print("markets to fetch", len(cids), flush=True)
        fetch_markets(sorted(cids))
    else:
        markets = json.load(open(f"{OUT}/markets.json"))
        res, copies = evaluate(pre, markets, wallets, now)
        json.dump({**res, "copies_rows": copies}, open(f"{OUT}/copy_eval.json", "w"), default=float)
        print(json.dumps({k: v for k, v in res.items() if k != "top"}, indent=1, default=float))
        print("top wallets:", res["top"][:10])


if __name__ == "__main__":
    main()
