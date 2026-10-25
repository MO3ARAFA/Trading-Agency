"""Final sprint, kernel 2: category-specialist consensus copy with bracket exits (Phase 16 cache; periods as copy_sharp).

Declared before any result was computed (single configuration, no grid):
  * category of a market from its question text (CATS below, first match wins, else "other"; short-dated crypto "Up or Down" excluded);
  * specialist of category c, ranked on a window W: >= 80 % of its interior (0.15-0.85) copies in c, >= 20 closed copies in c over
    >= 10 markets (exits known inside W), not a market maker / median entry <= 0.85 (copy_sharp filters), copy-return t in c > 0;
    the top 10 per category by that t;
  * consensus trigger: a specialist of c BUYs token a of a market of c at 0.20 <= p <= 0.80 within 24 h after another specialist of c
    bought the same token; entry at that second buy, price + max(1c, 2 %) + taker fee; one entry per market;
  * exits, first of: take-profit when a print reaches entry + 0.12 (sold at that level - max(1c, 2 %) - fee); stop when a print
    reaches entry - 0.12 (sold at that print - max(1c, 2 %) - fee); a triggering specialist sells (its price - slip - fee);
    resolution (0/1). Prints are every public trade of the market (data-api /trades), the other token's prints counted as 1 - p.
  * P2 validation ranks on P1; P3 (out-of-sample) ranks on P1+P2. Pass: P3 mean > 0, market-clustered t > 2.5, account > 100.
"""
from __future__ import annotations

import json
import os
import re
import statistics
from collections import defaultdict
from typing import Dict, List, Optional

from quant_agency.copy_sharp import P1, P2, P3, copies_of, is_mm, load, simulate, slip, ts
from quant_agency.copy_study import DATA, _get, clustered

CATS = [("crypto", r"\b(bitcoin|btc|ethereum|eth|solana|sol|xrp|dogecoin|crypto|token|fdv|airdrop|megaeth|hyperliquid)\b"),
        ("economics", r"\b(fed|interest rate|rates?|cpi|inflation|gdp|unemployment|recession|jobs report|payrolls|bps|tariffs?)\b"),
        ("politics", r"\b(election|elected|president|presidential|trump|biden|senate|house|governor|mayor|prime minister|parliament|party|"
                     r"vote|nominee|democrat|republican|minister|cabinet|impeach|ceasefire|war|nato|putin|zelensky|israel|iran|china)\b"),
        ("weather", r"\b(temperature|°|degrees|rain|snow|hurricane|storm|earthquake|weather|heat)\b"),
        ("sports", r"(\bvs\.?\b|\bo/u\b|spread|\bwin\b|\bnba\b|\bnfl\b|\bmlb\b|\bnhl\b|\bufc\b|\bfc\b|match|game|cup|league|open|grand prix|"
                   r"set \d|map \d|tournament|champion|playoffs?|series|draw|halftime|goals?)")]
TP, SL, BAND, WINDOW, TOPN = 0.12, 0.12, (0.20, 0.80), 86400, 10
PRINTS = "runs/p16/prints"


def category(q: str) -> str:
    q = q.lower()
    if "up or down" in q:
        return "excluded"
    for name, rx in CATS:
        if re.search(rx, q):
            return name
    return "other"


def specialists(acts, markets, t_lo: int, t_hi: int) -> Dict[str, List[str]]:
    cat = {c: category(m["q"]) for c, m in markets.items()}
    out = defaultdict(list)
    for w, tr in acts.items():
        buys = [r["price"] for r in tr if r["side"] == "BUY" and t_lo <= r["t"] < t_hi]
        if not buys or statistics.median(buys) > 0.85 or is_mm(tr, t_lo, t_hi):
            continue
        cps = [c for c in copies_of(tr, markets, t_lo, t_hi, w) if c["exit_t"] is not None and c["exit_t"] < t_hi]
        if not cps:
            continue
        by = defaultdict(list)
        for c in cps:
            by[cat[c["cid"]]].append(c)
        top, rows = max(by.items(), key=lambda kv: len(kv[1]))
        if top in ("other", "excluded") or len(rows) < 0.8 * len(cps) or len(rows) < 20 or len({c["cid"] for c in rows}) < 10:
            continue
        s = clustered(rows)
        if s.get("se", 0) > 0 and s["t"] > 0:
            out[top].append((s["t"], w))
    return {c: [w for _, w in sorted(v, reverse=True)[:TOPN]] for c, v in out.items()}


def triggers(acts, markets, spec: Dict[str, List[str]], t_lo: int, t_hi: int) -> List[dict]:
    cat = {c: category(m["q"]) for c, m in markets.items()}
    buys = defaultdict(list)                                                # (cid, asset) -> [(t, wallet, price)]
    for c, ws in spec.items():
        for w in ws:
            for r in acts[w]:
                if r["side"] == "BUY" and t_lo <= r["t"] < t_hi and cat.get(r["cid"]) == c and BAND[0] <= r["price"] <= BAND[1]:
                    buys[(r["cid"], r["asset"])].append((r["t"], w, r["price"]))
    out, used = [], set()
    for (cid, asset), v in buys.items():
        v.sort()
        for i, (t, w, p) in enumerate(v):
            prior = {w2 for t2, w2, _ in v[:i] if w2 != w and t - t2 <= WINDOW}
            if prior and cid not in used:
                used.add(cid)
                out.append({"cid": cid, "asset": asset, "t": t, "price": p, "wallets": sorted(prior | {w}), "cat": cat[cid]})
                break
    return sorted(out, key=lambda x: x["t"])


def prints(cid: str, t0: int, t1: int) -> List[tuple]:
    os.makedirs(PRINTS, exist_ok=True)
    path = f"{PRINTS}/{cid}_{t0}.json"
    if os.path.exists(path):
        return [tuple(x) for x in json.load(open(path))]
    out, a = [], t0
    while a < t1:
        b = min(t1, a + 6 * 3600)
        rows = _get(f"{DATA}/trades?market={cid}&limit=500&takerOnly=false&start={a}&end={b}") or []
        if len(rows) >= 500 and b - a > 300:                                # saturated: shrink the window
            t1_ = a + (b - a) // 4
            rows = _get(f"{DATA}/trades?market={cid}&limit=500&takerOnly=false&start={a}&end={t1_}") or []
            b = t1_
        out += [(r["timestamp"], r["asset"], float(r["price"])) for r in rows]
        a = b + 1
        if len(out) > 20000:
            break
    out.sort()
    json.dump(out, open(path, "w"))
    return out


def exit_of(tg: dict, acts, markets, horizon: int) -> dict:
    m = markets[tg["cid"]]
    rate = m["fee"]
    e = tg["price"] + slip(tg["price"])
    cost = e + rate * e * (1 - e)
    close_t = ts(m.get("closedTime")) if m["closed"] else None
    end = min(close_t or horizon, horizon)
    sp_sell = min((r["t"], r["price"]) for w in tg["wallets"] for r in acts[w] if r["side"] == "SELL" and r["asset"] == tg["asset"] and r["t"] > tg["t"]) \
        if any(r["side"] == "SELL" and r["asset"] == tg["asset"] and r["t"] > tg["t"] for w in tg["wallets"] for r in acts[w]) else None
    stop_scan = min(end, sp_sell[0]) if sp_sell else end
    res = None
    for t, asset, p in prints(tg["cid"], tg["t"] + 1, stop_scan):
        q = p if asset == tg["asset"] else 1.0 - p
        if q >= e + TP:
            x = e + TP - slip(e + TP)
            res = (t, x - rate * x * (1 - x), "take")
            break
        if q <= e - SL:
            x = max(0.01, q - slip(q))
            res = (t, x - rate * x * (1 - x), "stop")
            break
    if res is None and sp_sell and (close_t is None or sp_sell[0] < close_t):
        x = max(0.01, sp_sell[1] - slip(sp_sell[1]))
        res = (sp_sell[0], x - rate * x * (1 - x), "mirror")
    if res is None and close_t is not None and close_t <= horizon and m["prices"][m["tokens"].index(tg["asset"])] in (0.0, 1.0):
        res = (close_t, m["prices"][m["tokens"].index(tg["asset"])], "resolve")
    c = {**tg, "wallet": tg["wallets"][0], "cost": cost, "w": 1.0}
    if res is None:
        return {**c, "exit_t": None, "value": None, "how": "open"}
    return {**c, "exit_t": res[0], "value": res[1], "how": res[2], "ret": (res[1] - cost) / cost}


def run(acts, markets, rank_lo: int, rank_hi: int, t_lo: int, t_hi: int, horizon: int) -> dict:
    spec = specialists(acts, markets, rank_lo, rank_hi)
    tg = triggers(acts, markets, spec, t_lo, t_hi)
    rows = [exit_of(t, acts, markets, horizon) for t in tg]
    done = [r for r in rows if r["value"] is not None]
    sim = simulate(rows, horizon, stake=4.0, per_wallet=15.0)
    hows, cats = defaultdict(int), defaultdict(int)
    for r in rows:
        hows[r["how"]] += 1
        cats[r["cat"]] += 1
    return {"specialists": {c: len(v) for c, v in spec.items()}, "triggers": len(tg), "by_cat": dict(cats), "how": dict(hows),
            "stats": clustered(done), "account": {k: v for k, v in sim.items() if k != "curve"}, "curve": sim["curve"], "rows": rows}


def main(argv=None):
    import argparse
    import time
    ap = argparse.ArgumentParser()
    ap.add_argument("--step", choices=["validate", "oos"], required=True)
    a = ap.parse_args(argv)
    t1, t2, t3, now = ts(P1), ts(P2), ts(P3), int(time.time()) - 86400
    acts, markets = load()
    if a.step == "validate":
        r = run(acts, markets, t1, t2, t2, t3, now)
        path = "runs/p16/sharp/k2_validate.json"
    else:
        r = run(acts, markets, t1, t3, t3, now, now)
        path = "runs/p16/sharp/k2_oos.json"
    json.dump(r, open(path, "w"), indent=1, default=float)
    print(json.dumps({k: v for k, v in r.items() if k not in ("curve", "rows")}, indent=1, default=float))


if __name__ == "__main__":
    main()
