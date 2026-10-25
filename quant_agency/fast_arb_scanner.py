"""Final sprint, kernel 3: complete-set arbitrage with an early-unwind check + date-ladder monotonicity scan (live, paper only).

Runs the Phase 13 paper engine (``complete_set_arb``) for ``--duration`` seconds and, alongside it:
  * every 60 s, for every paper set bought so far, the value of selling the same tokens back into the book now: sum over legs of the
    best-bid ladder walked for ``sets`` shares, minus a conservative taker fee 0.05 * p * (1 - p) per share, minus the capital paid.
    A set is "unwindable" the first time that net is > 0 (capital freed before resolution);
  * every 300 s, the ``bracket_arb`` monotonicity scan (earlier-date NO + later-date YES below 1.00 after fees).
Pre-registration: docs/PREREG_FINAL_K3.json. Outputs under --out: csa_* (engine), unwind.jsonl, brackets.jsonl, k3_summary.json.
"""
from __future__ import annotations

import glob
import json
import os
import subprocess
import sys
import time

from .bracket_arb import scan
from .reward_share import fetch_books


def bid_value(book: dict, shares: float) -> float:
    left, val = shares, 0.0
    for px, sz in sorted(((float(b["price"]), float(b["size"])) for b in (book or {}).get("bids", [])), reverse=True):
        q = min(left, sz)
        val += q * (px - 0.05 * px * (1 - px))
        left -= q
        if left <= 1e-9:
            return val
    return float("-inf")                                                    # not enough depth to unwind


def fills(run_dir: str):
    p = os.path.join(run_dir, "csa_log.jsonl")
    if not os.path.exists(p):
        return []
    return [r for r in map(json.loads, open(p)) if r.get("event") == "fill"]


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--duration", type=float, default=2700.0)
    ap.add_argument("--out", default="runs/final/k3")
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    eng = subprocess.Popen([sys.executable, "-m", "quant_agency.complete_set_arb", "--duration", str(a.duration), "--out", a.out],
                           stdout=open(os.path.join(a.out, "engine.log"), "w"), stderr=subprocess.STDOUT)
    t0, last_b, first_unwind = time.time(), 0.0, {}
    ul, bl = open(os.path.join(a.out, "unwind.jsonl"), "a", buffering=1), open(os.path.join(a.out, "brackets.jsonl"), "a", buffering=1)
    n_scans, bracket_opps = 0, 0
    while eng.poll() is None:
        runs = sorted(glob.glob(os.path.join(a.out, "paper_*")))
        fl = fills(runs[-1]) if runs else []
        if fl:
            books = fetch_books(sorted({t for f in fl for t in f["tokens"]}))
            for f in fl:
                sets, cap = float(f["sets"]), float(f["cost"]) + float(f["fees"])
                net = sum(bid_value(books.get(t), sets) for t in f["tokens"]) - cap
                ul.write(json.dumps({"t": time.time(), "pid": f["pid"], "net": net, "capital": cap}) + "\n")
                if net > 0 and f["pid"] not in first_unwind:
                    first_unwind[f["pid"]] = {"after_s": time.time() - f["wall"], "net": net, "capital": cap}
        if time.time() - last_b >= 300:
            last_b = time.time()
            r = scan()
            n_scans += 1
            bracket_opps += len(r["opportunities"])
            bl.write(json.dumps({"t": time.time(), "ladders": r["ladders"], "pairs": r["pairs"], "opportunities": r["opportunities"][:20]}) + "\n")
            print(f"[{time.strftime('%H:%M:%S')}] brackets: {r['ladders']} ladders {r['pairs']} pairs {len(r['opportunities'])} below 1.00; "
                  f"sets bought {len(fl)} unwindable {len(first_unwind)}", flush=True)
        time.sleep(60)
    runs = sorted(glob.glob(os.path.join(a.out, "paper_*")))
    summ = json.load(open(os.path.join(runs[-1], "csa_summary.json"))) if runs and os.path.exists(os.path.join(runs[-1], "csa_summary.json")) else {}
    res = {"duration_s": time.time() - t0, "sets_bought": len(fills(runs[-1])) if runs else 0, "unwindable": first_unwind,
           "locked_net": summ.get("locked_net"), "deployed": summ.get("deployed"), "bracket_scans": n_scans, "bracket_opportunities": bracket_opps}
    json.dump(res, open(os.path.join(a.out, "k3_summary.json"), "w"), indent=1, default=float)
    print(json.dumps(res, default=float))


if __name__ == "__main__":
    main()
