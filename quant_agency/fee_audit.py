"""On-chain check of Polymarket taker fees against Gamma's per-market fee schedule.

Gamma reports ``feesEnabled`` / ``feeType`` / ``feeSchedule`` per market; the public docs list category rates. They disagree for many
markets (``feesEnabled: true`` with ``feeType: zero_fees``, rate 0). The exchange's fill event on Polygon carries the fee actually charged,
so this module reads recent public trades (data-api), fetches each transaction receipt from a public Polygon RPC, decodes the fill events
and compares ``fee / (shares x p(1-p))`` with the schedule's rate.

    python -m quant_agency.fee_audit --events 1075157 1234567 --out runs/p13/fee_audit.json
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.request
from typing import Dict, List, Optional, Sequence

RPC = "https://polygon-bor-rpc.publicnode.com"
DATA = "https://data-api.polymarket.com"
GAMMA = "https://gamma-api.polymarket.com"
# topic0 of the exchange's fill event (CTF exchange in use since 2026); data words: side, token id, USDC amount, share amount, fee, ...
FILL_TOPIC = "0xd543adfd945773f1a62f74f0ee55a5e3b9b1a28262980ba90b1a89f2ea84d8ee"


def _get(url: str, data: Optional[bytes] = None, tries: int = 4):
    for k in range(tries):
        try:
            req = urllib.request.Request(url, data=data, headers={"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"})
            return json.loads(urllib.request.urlopen(req, timeout=30).read())
        except Exception:
            if k == tries - 1:
                raise
            time.sleep(2.0 * (k + 1))


def decode_fills(receipt: dict) -> List[dict]:
    """Fill events of one transaction receipt -> [{token, usdc, shares, fee}] (6-decimal units converted)."""
    out = []
    for log in receipt.get("logs", []):
        if not log.get("topics") or log["topics"][0] != FILL_TOPIC:
            continue
        d = log["data"][2:]
        w = [int(d[i:i + 64], 16) for i in range(0, len(d), 64)]
        if len(w) < 5:
            continue
        out.append({"maker": "0x" + log["topics"][2][-40:], "taker": "0x" + log["topics"][3][-40:], "token": str(w[1]),
                    "usdc": w[2] / 1e6, "shares": w[3] / 1e6, "fee": w[4] / 1e6})
    return out


def implied_rate(fill: dict) -> Optional[float]:
    """fee / (shares x p(1-p)) with p = usdc / shares; None for an empty fill."""
    if fill["shares"] <= 0:
        return None
    p = fill["usdc"] / fill["shares"]
    v = fill["shares"] * p * (1 - p)
    return fill["fee"] / v if v > 0 else None


def audit_market(m: dict, n_trades: int = 3) -> dict:
    """Recent taker trades of one Gamma market: the highest implied fee rate among their fills (the taker fill carries the fee)."""
    fs = m.get("feeSchedule") or {}
    row = {"question": (m.get("question") or "")[:80], "conditionId": m.get("conditionId"), "feesEnabled": bool(m.get("feesEnabled")),
           "feeType": m.get("feeType"), "schedule_rate": fs.get("rate"), "trades": 0, "max_rate": None, "fills": []}
    try:
        trades = _get(f"{DATA}/trades?market={m['conditionId']}&limit={n_trades}&takerOnly=true")
    except Exception as e:
        row["error"] = repr(e)[:120]
        return row
    toks = set(json.loads(m["clobTokenIds"]) if isinstance(m.get("clobTokenIds"), str) else m.get("clobTokenIds") or [])
    for t in trades[:n_trades]:
        try:
            rc = _get(RPC, json.dumps({"jsonrpc": "2.0", "id": 1, "method": "eth_getTransactionReceipt", "params": [t["transactionHash"]]}).encode())["result"]
        except Exception:
            continue
        fills = [f for f in decode_fills(rc) if f["token"] in toks]
        rates = [r for r in (implied_rate(f) for f in fills) if r is not None]
        row["trades"] += 1
        row["fills"] += [{"usdc": f["usdc"], "shares": f["shares"], "fee": f["fee"]} for f in fills]
        if rates:
            row["max_rate"] = max(rates + ([row["max_rate"]] if row["max_rate"] is not None else []))
        time.sleep(0.3)
    return row


def audit_events(eids: Sequence[str], n_trades: int = 3, max_markets: int = 3) -> List[dict]:
    """The ``max_markets`` most traded open markets of each event."""
    rows = []
    for eid in eids:
        ev = _get(f"{GAMMA}/events/{eid}")
        live = sorted((m for m in ev.get("markets", []) if not m.get("closed")), key=lambda m: -float(m.get("volume24hr") or 0))
        for m in live[:max_markets]:
            r = audit_market(m, n_trades)
            r["event"] = ev.get("title")
            rows.append(r)
    return rows


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--events", nargs="+", required=True, help="Gamma event ids")
    p.add_argument("--trades", type=int, default=3)
    p.add_argument("--markets", type=int, default=3, help="most traded open markets per event")
    p.add_argument("--out", default="runs/p13/fee_audit.json")
    a = p.parse_args(argv)
    rows = audit_events(a.events, a.trades, a.markets)
    json.dump(rows, open(a.out, "w"), indent=1)
    for r in rows:
        print(f"{r['event'][:40]:40s} | {r['question'][:50]:50s} | enabled={r['feesEnabled']!s:5s} type={r['feeType']} rate={r['schedule_rate']} | "
              f"trades={r['trades']} max on-chain rate={r['max_rate']}")


if __name__ == "__main__":
    main()
