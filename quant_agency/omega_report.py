"""Omega run report: one or more run directories (live / synthetic / replay) -> markdown tables.

    python -m quant_agency.omega_report --runs runs/omega/live_X runs/omega_smoke/synth_Y --out docs/OMEGA_MEME_ENGINE.md --head H.md --tail T.md
"""
from __future__ import annotations

import argparse
import json
import math
import os
from collections import Counter, defaultdict
from typing import Dict, List, Sequence


def load(run: str) -> dict:
    summ = json.load(open(os.path.join(run, "omega_summary.json")))
    rows = [json.loads(l) for l in open(os.path.join(run, "omega_audit.jsonl"))] if os.path.exists(os.path.join(run, "omega_audit.jsonl")) else []
    status = [json.loads(l) for l in open(os.path.join(run, "omega_status.jsonl"))] if os.path.exists(os.path.join(run, "omega_status.jsonl")) else []
    return {"dir": run, "summary": summ, "audit": rows, "status": status}


def _ms(xs: Sequence[float]):
    n = len(xs)
    if n == 0:
        return float("nan"), float("nan")
    m = sum(xs) / n
    se = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1) / n) if n > 1 else float("nan")
    return m, se


def run_section(r: dict, label: str) -> List[str]:
    s, au = r["summary"], r["audit"]
    st = s["status"]
    closes = [x for x in au if x["kind"] == "close"]
    opens = [x for x in au if x["kind"] == "open"]
    fails = [x for x in au if x["kind"] == "failed_tx"]
    rss = [x.get("rss_mb") for x in r["status"] if x.get("rss_mb") == x.get("rss_mb") and x.get("rss_mb") is not None]
    hours = max(st["elapsed_s"] / 3600.0, 1e-9)
    L = [f"### {label}", "",
         f"`{os.path.basename(r['dir'])}` · {st['elapsed_s'] / 60:.0f} min of market time · {st['prints']:,} trade prints · "
         f"{s['stats'].get('quotes', 0):,} quotes · {s['stats'].get('creates', 0):,} launches · {s['stats'].get('tweets', 0):,} tweets", "",
         f"**{st['fills']} fills ({st['fills'] / hours:.0f} per hour)**, {len(closes)} round trips, {len(fails)} failed transactions, "
         f"account equity **{st['equity']:.2f} USD** (from 100.00). "
         f"Resident memory {min(rss):.0f} → {max(rss):.0f} MB (first / largest status sample)." if rss else f"**{st['fills']} fills**.", ""]
    if s.get("wall_s"):
        L += [f"Processed {s.get('events', 0):,} events in {s['wall_s']:.0f} s of wall time ({s.get('events', 0) / max(s['wall_s'], 1e-9):,.0f} events/s).", ""]
    by = defaultdict(list)
    for c in closes:
        by[c["sleeve"]].append(c)
    L += ["| sleeve | round trips | win rate | mean net / trade (USD) | ± s.e. | mean net / trade (% of cost) | fees paid (USD) | gross before fees (USD) | net (USD) | hold (median s) |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for sl, cs in sorted(by.items()):
        pn = [c["pnl_usd"] for c in cs]
        m, se = _ms(pn)
        ret = [c["ret"] for c in cs if c.get("ret") is not None]
        fees = sum(c["fees_usd"] for c in cs)
        holds = sorted(c["hold_s"] for c in cs)
        L.append(f"| {sl} | {len(cs)} | {sum(p > 0 for p in pn) / len(pn):.0%} | {m:+.4f} | {se:.4f} | {100 * _ms(ret)[0]:+.2f} % | {fees:.3f} | "
                 f"{sum(pn) + fees:+.3f} | {sum(pn):+.3f} | {holds[len(holds) // 2]:.0f} |")
    if not by:
        L.append("| – | 0 | | | | | | | | |")
    L += ["", "Exit reasons: " + ", ".join(f"{k} {v}" for k, v in Counter(c["reason_out"] for c in closes).most_common()) if closes else "No round trip.", ""]
    mp = s.get("model_pnl") or {}
    if mp:
        L += ["| sleeve × fill model | n | net (USD) | mean (USD) |", "|---|---|---|---|"]
        for k, v in sorted(mp.items()):
            L.append(f"| {k} | {v['n']} | {v['sum_usd']:+.4f} | {v['mean_usd']:+.4f} |")
        L.append("")
    gov = s.get("gov_events") or []
    L += ["Governance: " + ("; ".join(f"{g['sleeve']} {g['kind']} ({g['reason'][:70]})" for g in gov[:8]) if gov else "no breaker fired."), ""]
    sl_cost = [o for o in opens if o.get("venue") == "pump"]
    if sl_cost:
        fee_pct = [o["fees_usd"] / o["cost_usd"] for o in sl_cost if o["cost_usd"]]
        L += [f"pump.fun entries: mean entry cost {100 * _ms(fee_pct)[0]:.2f} % of notional (curve fee + network), mean latency "
              f"{_ms([o['latency'] for o in sl_cost])[0]:.2f} s, mean slippage vs decision price {100 * _ms([o['slip'] for o in sl_cost if o.get('slip') is not None])[0]:+.2f} %.", ""]
    return L


def build(runs: Sequence[dict], labels: Sequence[str], head: str = "", tail: str = "") -> str:
    L = [head.strip(), ""] if head else []
    for r, lab in zip(runs, labels):
        L += run_section(r, lab)
    if tail:
        L += [tail.strip(), ""]
    return "\n".join(L)


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--runs", nargs="+", required=True, help="run directories, optionally label=dir")
    p.add_argument("--head", default=None)
    p.add_argument("--tail", default=None)
    p.add_argument("--out", default="docs/OMEGA_MEME_ENGINE.md")
    a = p.parse_args(argv)
    pairs = [x.split("=", 1) if "=" in x else (os.path.basename(x), x) for x in a.runs]
    md = build([load(d) for _, d in pairs], [l for l, _ in pairs], open(a.head).read() if a.head else "", open(a.tail).read() if a.tail else "")
    open(a.out, "w").write(md)
    print("wrote", a.out)


if __name__ == "__main__":
    main()
