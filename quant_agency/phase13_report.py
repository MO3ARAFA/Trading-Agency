"""Phase 13 report: resolution backtest + live paper sessions of ``complete_set_arb`` -> docs/PHASE13_COMPLETE_SET_ARB.md.

    python -m quant_agency.phase13_report --runs runs/p13/paper_* --backtest docs/live_runs/phase13/resolution_backtest.json
"""
from __future__ import annotations

import argparse
import json
import os
import urllib.request
from collections import defaultdict
from typing import Dict, List, Optional, Sequence

from .complete_set_arb import GAMMA, fee_usd

STRESS_RATE = 0.05


def load_run(d: str) -> dict:
    rows = [json.loads(l) for l in open(os.path.join(d, "csa_log.jsonl"))]
    summ = os.path.join(d, "csa_summary.json")
    return {"dir": d, "rows": rows, "summary": json.load(open(summ)) if os.path.exists(summ) else {}}


def _fee_flags(eid: str, cache: Dict[str, Dict[str, bool]]) -> Dict[str, bool]:
    """token -> Gamma ``feesEnabled`` for every leg of ``eid`` (empty if Gamma cannot be reached)."""
    if eid not in cache:
        out: Dict[str, bool] = {}
        try:
            req = urllib.request.Request(f"{GAMMA}/events/{eid}", headers={"User-Agent": "Mozilla/5.0"})
            for m in json.loads(urllib.request.urlopen(req, timeout=30).read()).get("markets", []):
                toks = json.loads(m["clobTokenIds"]) if isinstance(m.get("clobTokenIds"), str) else m.get("clobTokenIds") or []
                for t in toks:
                    out[str(t)] = bool(m.get("feesEnabled"))
        except Exception:
            pass
        cache[eid] = out
    return cache[eid]


def stressed_net(f: dict, cache: Dict[str, Dict[str, bool]]) -> Optional[float]:
    """Net of a logged fill if every fee-enabled leg paid ``STRESS_RATE``; fee at each leg's VWAP (p(1-p) is concave, so this is >= the
    exact per-level fee: conservative)."""
    if f.get("net_stressed") is not None:
        return f["net_stressed"]
    flags = _fee_flags(f["eid"], cache)
    if not flags:
        return None
    extra = sum(fee_usd(f["sets"], v, STRESS_RATE) for t, v in zip(f["tokens"], f["vwap"]) if flags.get(str(t), True))
    return f["payout"] - f["cost"] - max(extra, f["fees"])


def usd(x: float) -> str:
    return f"{x:,.2f}"


def backtest_section(bt: dict) -> List[str]:
    p, a = bt["payout"]["plain"], bt["payout"]["augmented"]
    L = ["## 2. Backtest of the payoff: what did one set actually pay?", "",
         f"{bt['events']:,} closed NegRisk events whose end date falls between {bt['end_min'][:10]} and {bt['end_max'][:10]} (Gamma, one-day "
         "windows; days with more than 2,100 closed events are a sample, not a census; ≈ 85 % are sports). Each set is paid at the venue's "
         "resolved prices, so 50-50 and several-YES resolutions count as the venue paid them.", "",
         "| events | n | exactly one named YES | none | unclean (50-50 etc.) | YES set paid < 1 | mean YES-set loss per set | NO set paid < n−1 | mean NO-set loss per set |",
         "|---|---|---|---|---|---|---|---|---|"]
    for name, b, c in (("plain (not augmented)", p, bt["plain"]), ("augmented (placeholders / Other)", a, bt["augmented"])):
        L.append(f"| {name} | {b['n']:,} | {c.get('exactly_one', 0):,} | {c.get('none', 0)} | {c.get('unclean', 0)} | {b['yes_lt1']} ({100 * b['yes_lt1'] / max(b['n'], 1):.3f} %) | "
                 f"{100 * b['yes_shortfall_per_set']:.4f} ¢ | {b['no_lt']} | {100 * b['no_shortfall_per_set']:.4f} ¢ |")
    L += ["",
          f"**Plain events.** A YES set paid less than 1 in {p['yes_lt1']} of {p['n']:,} events. Every one of them was an NFL *highest scoring "
          "quarter* market (a tie leaves no winner) or an ATP *exact score* market (a retirement leaves no score). Those two families are "
          f"excluded from YES sets (`CsaConfig.yes_set_exclude`). After the exclusion: **{p['yes_lt1_after_exclusion']} losses in "
          f"{p['n_after_exclusion']:,} events**. The exclusion was chosen on this same data, so only future events test it out of sample.",
          "",
          f"**Augmented events.** A YES set paid nothing in {a['yes_lt1']} of {a['n']:,} ({100 * a['yes_lt1'] / max(a['n'], 1):.1f} %): the winner "
          "was an unlisted outcome. The engine never builds a YES set on them. A NO set never paid less than n − 1 there.", "",
          "**What this does not cover.** It cannot cover a dispute that resolves against the rules, a market voided after entry, or a fee "
          "charged differently from the schedule. Settlement of the paper positions themselves (§4) is the direct test.", ""]
    return L


def fee_section(rows: Sequence[dict]) -> List[str]:
    """On-chain fee audit (``fee_audit.py``): fee charged in the exchange's fill events vs the per-market schedule."""
    by = defaultdict(lambda: {"markets": 0, "decoded": 0, "agree": 0, "fills": 0, "rates": []})
    for r in rows:
        k = (r["feeType"] or "fees disabled", float(r["schedule_rate"] or 0.0))
        b = by[k]
        b["markets"] += 1
        b["fills"] += len(r["fills"])
        if r["max_rate"] is not None:
            b["decoded"] += 1
            b["agree"] += abs(r["max_rate"] - k[1]) < 0.002
            b["rates"].append(r["max_rate"])
    L = ["## 1b. Fees: the schedule checked against the chain", "",
         "Gamma marks many fee-enabled markets `feeType: zero_fees` (rate 0) while the public docs list category taker rates of 0.03–0.07. "
         "`fee_audit.py` settles it: it reads recent public taker trades, fetches each transaction receipt from a public Polygon RPC, decodes "
         "the exchange's fill events and computes the rate actually charged, fee / (shares × p(1 − p)). The decoder reproduces the documented "
         "crypto rate (0.07) exactly.", "",
         "| schedule (Gamma) | rate | markets | with decoded trades | charged = schedule | fills read | highest rate charged |", "|---|---|---|---|---|---|---|"]
    for (ft, rate), b in sorted(by.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        L.append(f"| `{ft}` | {rate:.2f} | {b['markets']} | {b['decoded']} | {b['agree']} | {b['fills']} | {max(b['rates']) if b['rates'] else float('nan'):.4f} |")
    n = sum(b["decoded"] for b in by.values())
    a = sum(b["agree"] for b in by.values())
    zero = [f for r in rows if not float(r["schedule_rate"] or 0.0) for f in r["fills"]]
    dust = max((f["fee"] for f in zero), default=0.0)
    L += ["", f"**{a} of {n} markets were charged their schedule's rate** (within 0.002). The {len(zero)} fills read in zero-rate markets "
              f"(`zero_fees` or fees disabled) paid {sum(f['fee'] for f in zero):.5f} USD in total, at most {dust:.5f} USD on one fill: rounding "
              "(fees are rounded to 5 decimals), not a fee. The other exception is a sports market (schedule 0.05) where one 5-share fill paid "
              "0.128 while its other fills paid 0.05. It is unexplained, and it is not a zero-fee market. The engine prices every leg with "
              f"its own schedule. §3 also re-prices each fill at {STRESS_RATE:.2f} as a stress case.", ""]
    return L


def run_section(runs: Sequence[dict], cache) -> List[str]:
    L = ["## 3. Live paper sessions (100 USD account)", "",
         "Rules: ≤ 25 USD per event, ≤ 100 USD deployed, ≤ 8 events, ≤ 60 days to the end date + 2 days for resolution, the marginal set "
         "nets ≥ 0.5 ¢, the whole fill nets ≥ 0.4 % and ≥ 10 % a year. Execution: see it, wait 0.5 s, re-read every leg's book, buy only what is "
         "still profitable at the fresh asks (depth-walked, fees per level), subtract what was bought from every later book, re-read 3 s later.", "",
         "| session | duration | NegRisk events | exhaustive | tokens with asks | sweeps | sweep time | opportunities (sweep × event) | distinct events | fills | vanished at re-read |",
         "|---|---|---|---|---|---|---|---|---|---|---|"]
    fills: List[dict] = []
    rechecks: Dict[int, dict] = {}
    for k, r in enumerate(runs):
        rows = r["rows"]
        uni = [x for x in rows if x["event"] == "universe"]
        seen = [x for x in rows if x["event"] == "seen"]
        st = r["summary"].get("stats", {})
        dur = (rows[-1]["wall"] - rows[0]["wall"]) / 60 if rows else 0
        f = [dict(x, session=k) for x in rows if x["event"] == "fill"]
        fills += f
        for x in rows:
            if x["event"] == "recheck":
                rechecks[(k, x["pid"])] = x
        L.append(f"| {os.path.basename(r['dir'])} | {dur:.0f} min | {uni[-1]['events'] if uni else '–'} | {uni[-1]['exhaustive'] if uni else '–'} | "
                 f"{st.get('books', 0):,.0f} | {st.get('sweeps', 0):.0f} | {st.get('sweep_s', 0):.0f} s | {len(seen)} | {len({x['eid'] for x in seen})} | {len(f)} | "
                 f"{st.get('vanished', 0):.0f} |")
    L += ["", "### 3.1 Paper fills", "",
          f"*net (stressed)* re-prices the same fill as if every fee-enabled leg paid a {STRESS_RATE:.2f} taker rate (the docs' category rate) "
          "instead of the per-market schedule the venue reports (often `zero_fees`). *Legging*: could the same number of sets still be bought at "
          "a profit from the raw book 3 s later?", "",
          "| # | event | kind | legs | sets | capital | locked net | net / capital | days | annualised | net (stressed) | annualised (stressed) | legging: still fillable 3 s later |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    tot_cap = tot_net = tot_str = 0.0
    capdays = 0.0
    for i, f in enumerate(fills, 1):
        cap = f["cost"] + f["fees"]
        sn = stressed_net(f, cache)
        rc = rechecks.get((f["session"], f["pid"]), {})
        still = rc.get("still_fillable", rc.get("alive"))
        tot_cap += cap
        tot_net += f["net"]
        tot_str += sn if sn is not None else 0.0
        capdays += cap * f["days"]
        ann_s = "–" if sn is None else f"{100 * sn / cap * 365 / max(f['days'], 0.5):.1f} %"
        L.append(f"| {i} | {f['title'][:60]} | {f['kind']} | {f['n_legs']} | {f['sets']:.1f} | {usd(cap)} | {f['net']:+.3f} | {100 * f['ret']:.2f} % | {f['days']:.0f} | "
                 f"{100 * f['annualized']:.1f} % | {'–' if sn is None else f'{sn:+.3f}'} | {ann_s} | "
                 f"{'–' if still is None else ('yes' if still else 'no')} |")
    if fills:
        yr = tot_net / capdays * 365 if capdays else 0.0
        yr_s = tot_str / capdays * 365 if capdays else 0.0
        L += ["", f"**Total:** {usd(tot_cap)} USD deployed, **{tot_net:+.3f} USD locked** (schedule fees) / {tot_str:+.3f} USD (stressed fees), "
                  f"capital-weighted {100 * yr:.1f} % / {100 * yr_s:.1f} % a year. Locked means: paid if every leg resolves as the backtest says; "
                  "nothing is realised until resolution.", ""]
    else:
        L += ["", "No fill.", ""]
    return L, fills, tot_cap, tot_net, tot_str, capdays


def build(runs: Sequence[dict], bt: dict, notes: str = "", fees: Optional[Sequence[dict]] = None) -> str:
    cache: Dict[str, Dict[str, bool]] = {}
    L = ["# Phase 13 — complete-set arbitrage on Polymarket NegRisk events", ""]
    if notes:
        L += [notes.strip(), ""]
    rs, fills, cap, net, net_s, capdays = run_section(runs, cache)
    if fees:
        L += fee_section(fees)
    L += backtest_section(bt)
    L += rs
    return "\n".join(L), {"fills": len(fills), "capital": cap, "locked_net": net, "locked_net_stressed": net_s, "capital_days": capdays}


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--runs", nargs="+", required=True)
    p.add_argument("--backtest", default="docs/live_runs/phase13/resolution_backtest.json")
    p.add_argument("--fee-audit", default="docs/live_runs/phase13/fee_audit.json")
    p.add_argument("--head", default=None, help="markdown placed before the generated sections")
    p.add_argument("--tail", default=None, help="markdown placed after the generated sections")
    p.add_argument("--out", default="docs/PHASE13_COMPLETE_SET_ARB.md")
    a = p.parse_args(argv)
    runs = [load_run(d) for d in a.runs]
    fees = json.load(open(a.fee_audit)) if a.fee_audit and os.path.exists(a.fee_audit) else None
    md, tot = build(runs, json.load(open(a.backtest)), open(a.head).read() if a.head else "", fees)
    if a.tail:
        md += "\n" + open(a.tail).read()
    open(a.out, "w").write(md)
    print(json.dumps(tot), f"wrote {a.out}")


if __name__ == "__main__":
    main()
