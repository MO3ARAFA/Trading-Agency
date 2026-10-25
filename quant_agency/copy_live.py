"""Phase 16: live paper copy-trading of selected Polymarket wallets (paper only: nothing is signed or sent).

Every ``poll_s`` seconds the recent TRADE activity of each followed wallet is read (data-api /activity). For each new BUY:
  * we buy ``stake`` USD of the same outcome at the *current* best ask of the CLOB book (walking depth), plus the market's taker fee
    (Gamma feeSchedule), skipping it if the ask is more than ``max_chase`` above the wallet's own price or the order is below the
    venue minimum (5 shares);
  * positions are held to resolution; at any time they are marked at the best bid (liquidation value) and, once the market closes,
    at the resolved payout.
State is checkpointed every 60 s (``copy_state.json``); ``--resume`` continues a stopped session.

    python -m quant_agency.copy_live --wallets runs/p16/selected.json --duration 86400 --bankroll 100 --stake 2
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional

DATA = "https://data-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
GAMMA = "https://gamma-api.polymarket.com"


def _get(url: str, data: Optional[bytes] = None):
    for k in range(4):
        try:
            req = urllib.request.Request(url, data=data, headers={"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"})
            return json.loads(urllib.request.urlopen(req, timeout=30).read())
        except Exception:
            time.sleep(1 + k)
    return None


@dataclass
class Pos:
    wallet: str
    cid: str
    asset: str
    title: str
    t: float
    their_px: float
    px: float
    shares: float
    cost: float              # USD incl. fee
    fee: float
    payout: Optional[float] = None


@dataclass
class Book:
    bankroll: float
    cash: float
    positions: List[Pos] = field(default_factory=list)
    seen: Dict[str, int] = field(default_factory=dict)      # wallet -> last processed activity timestamp
    skipped: Dict[str, int] = field(default_factory=dict)


def fee_rate(cid: str, cache: Dict[str, float]) -> float:
    if cid not in cache:
        rows = _get(f"{GAMMA}/markets?condition_ids={cid}") or []
        m = rows[0] if rows else {}
        fs = m.get("feeSchedule") or {}
        cache[cid] = float(fs.get("rate") or 0.0) if m.get("feesEnabled") else (0.0 if m else 0.05)
    return cache[cid]


def buy_at_ask(asset: str, usd: float, rate: float) -> Optional[tuple]:
    b = _get(f"{CLOB}/book?token_id={asset}")
    if not b or not b.get("asks"):
        return None
    levels = sorted((float(a["price"]), float(a["size"])) for a in b["asks"])
    left, shares, cost = usd, 0.0, 0.0
    for px, sz in levels:
        unit = px + rate * px * (1 - px)
        q = min(sz, left / unit)
        shares += q
        cost += q * unit
        left -= q * unit
        if left <= 1e-6:
            break
    if shares < 5.0:
        return None
    vwap_with_fee = cost / shares
    return shares, vwap_with_fee, cost


def best_bid(asset: str) -> float:
    b = _get(f"{CLOB}/book?token_id={asset}")
    if not b or not b.get("bids"):
        return 0.0
    return max(float(x["price"]) for x in b["bids"])


def settle(bk: Book) -> None:
    for p in bk.positions:
        if p.payout is not None:
            continue
        rows = _get(f"{GAMMA}/markets?condition_ids={p.cid}&closed=true") or []
        for m in rows:
            toks = json.loads(m.get("clobTokenIds") or "[]")
            px = [float(x) for x in json.loads(m.get("outcomePrices") or "[]")]
            if m.get("closed") and p.asset in toks and px[toks.index(p.asset)] in (0.0, 1.0):
                p.payout = px[toks.index(p.asset)]
                bk.cash += p.payout * p.shares


def equity(bk: Book, marks: bool = True) -> dict:
    open_val = 0.0
    for p in bk.positions:
        if p.payout is None:
            open_val += p.shares * (best_bid(p.asset) if marks else p.px)
    settled = [p for p in bk.positions if p.payout is not None]
    return {"cash": round(bk.cash, 4), "open_bid_value": round(open_val, 4), "equity_bid": round(bk.cash + open_val, 4),
            "positions": len(bk.positions), "settled": len(settled), "settled_pnl": round(sum(p.payout * p.shares - p.cost for p in settled), 4)}


def run(wallets: List[str], duration_s: float, out: str, bankroll: float, stake: float, poll_s: float = 15.0, max_chase: float = 0.03,
        resume: Optional[str] = None) -> dict:
    os.makedirs(out, exist_ok=True)
    if resume and os.path.exists(resume):
        d = json.load(open(resume))
        bk = Book(d["bankroll"], d["cash"], [Pos(**p) for p in d["positions"]], d["seen"], d.get("skipped", {}))
    else:
        bk = Book(bankroll, bankroll)
    now0 = int(time.time())
    for w in wallets:
        bk.seen.setdefault(w, now0)                                         # copy only what happens from now on
    fees: Dict[str, float] = {}
    log = open(os.path.join(out, "copy_log.jsonl"), "a", buffering=1)
    t_end, last_ck = time.time() + duration_s, 0.0
    while time.time() < t_end:
        for w in wallets:
            rows = _get(f"{DATA}/activity?user={w}&type=TRADE&limit=50&start={bk.seen[w] + 1}") or []
            for r in sorted(rows, key=lambda r: r["timestamp"]):
                bk.seen[w] = max(bk.seen[w], int(r["timestamp"]))
                if r.get("side") != "BUY":
                    continue
                if bk.cash < stake:
                    bk.skipped["cash"] = bk.skipped.get("cash", 0) + 1
                    continue
                rate = fee_rate(r["conditionId"], fees)
                fill = buy_at_ask(r["asset"], stake, rate)
                if fill is None:
                    bk.skipped["book"] = bk.skipped.get("book", 0) + 1
                    continue
                shares, px, cost = fill
                if px > float(r["price"]) + max_chase:
                    bk.skipped["chase"] = bk.skipped.get("chase", 0) + 1
                    continue
                bk.cash -= cost
                p = Pos(w, r["conditionId"], r["asset"], (r.get("title") or "")[:80], time.time(), float(r["price"]), px, shares, cost, cost - shares * px)
                bk.positions.append(p)
                log.write(json.dumps({"kind": "copy", **asdict(p)}) + "\n")
        if time.time() - last_ck >= 60:
            last_ck = time.time()
            settle(bk)
            st = {"bankroll": bk.bankroll, "cash": bk.cash, "positions": [asdict(p) for p in bk.positions], "seen": bk.seen, "skipped": bk.skipped}
            json.dump(st, open(os.path.join(out, "copy_state.json.tmp"), "w"))
            os.replace(os.path.join(out, "copy_state.json.tmp"), os.path.join(out, "copy_state.json"))
            e = equity(bk)
            log.write(json.dumps({"kind": "equity", "t": time.time(), **e, "skipped": bk.skipped}) + "\n")
            print(f"[{time.strftime('%H:%M:%S')}] {e} skipped={bk.skipped}", flush=True)
        time.sleep(poll_s)
    settle(bk)
    return equity(bk)


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--wallets", default="runs/p16/selected.json")
    p.add_argument("--duration", type=float, default=86400.0)
    p.add_argument("--bankroll", type=float, default=100.0)
    p.add_argument("--stake", type=float, default=2.0)
    p.add_argument("--out", default="runs/p16/live")
    p.add_argument("--resume", default=None)
    a = p.parse_args(argv)
    wallets = json.load(open(a.wallets))
    out = os.path.join(a.out, time.strftime("%Y%m%d_%H%M%S")) if not a.resume else os.path.dirname(a.resume)
    print(json.dumps(run(wallets, a.duration, out, a.bankroll, a.stake, resume=a.resume)))


if __name__ == "__main__":
    main()
