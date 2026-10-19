"""Operator tool: summarise a finished (or running) run directory — sleeve states, governor events, last account fills, CEO audit.

    python -m quant_agency.inspect_run runs/phase8_live_1_<timestamp>
    python -m quant_agency.inspect_run runs/phase8_live_1_<timestamp> --follow      # re-print every 30 s while a run is writing
"""
from __future__ import annotations

import argparse
import json
import os
import time
from typing import List


def _jsonl(path: str) -> List[dict]:
    if not os.path.exists(path):
        return []
    out = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    pass                                   # a line being written right now
    return out


def render(run_dir: str) -> str:
    L: List[str] = []
    P = L.append
    P(f"run: {run_dir}")
    summ = os.path.join(run_dir, "summary.json")
    if os.path.exists(summ):
        s = json.load(open(summ))
        P("\n== sleeves (final) ==")
        for sl in s.get("sleeves", []):
            P(f"  {sl['sleeve']:<16} {sl['state']:<10} equity ${sl['equity']:>10,.2f}  round trips {sl['round_trips']:>3}  floor {sl['b_floor_mult']}x  size x{sl['size_mult']}  halts {sl['n_halts']}")
    else:
        P("\n(no summary.json yet — the run is still going; sleeve state below is reconstructed from the event/trade logs)")
    ev = _jsonl(os.path.join(run_dir, "sleeve_events.jsonl"))
    P(f"\n== sleeve governor events ({len(ev)}) ==")
    for e in ev[-15:]:
        P(f"  {e['sleeve']:<16} {e['kind']:<24} {e['from_state']}→{e['to_state']}  {e['reason']}")
    tr = _jsonl(os.path.join(run_dir, "trades.jsonl"))
    by: dict = {}
    for t in tr:
        by.setdefault(t.get("sleeve", "main"), []).append(t)
    P("\n== account fills per sleeve (from trades.jsonl) ==")
    for k, v in by.items():
        pnl = sum(x["net_pnl_usd"] for x in v)
        P(f"  {k:<16} {len(v):>3} fills, net ${pnl:+.2f}")
    for t in tr[-8:]:
        P(f"    {t.get('sleeve', 'main'):<14} {t['market'][-34:]:<34} {'L' if t['side'] > 0 else 'S'} {t['entry_px']:.3f}→{t['exit_px']:.3f} {t['exit_reason']:<14} net ${t['net_pnl_usd']:+.3f}")
    ca = _jsonl(os.path.join(run_dir, "ceo_audit.jsonl"))
    P(f"\n== global CEO audit ({len(ca)} interventions; B is governed by the sleeves, not by this) ==")
    for e in ca[-6:]:
        P(f"  {e['wall']} {e['kind']:<22} {e['target']:<12} {e['reason'][:110]}")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--follow", action="store_true")
    a = ap.parse_args()
    while True:
        print(render(a.run_dir), flush=True)
        if not a.follow:
            break
        time.sleep(30)
        print("\n" + "=" * 100 + "\n")


if __name__ == "__main__":
    main()
