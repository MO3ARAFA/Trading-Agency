"""Phase 10 — the single pre-registered confirmatory test on the continuous collector's LIVE shadow rows.

    python -m quant_agency.p10_eval --check-frozen
    python -m quant_agency.p10_eval --runs runs/p10r1_* [runs/p10r2_* …] --out docs/live_runs/phase10_eval.md

H1 (docs/PREREG_PHASE10.md): among Polymarket entries that clear the 1.5× floor AND whose pre-impulse sigma60 is below 0.50 bps/√s, the `fixed0.7` exit has net expectancy > 0 (bps of notional,
after fees), one-sided α = 0.05, cluster-robust t (clusters = BTC impulse, per run directory), Student-t reference with clusters−1 df, fill model `strict` (primary).
Run directories named p10v* (validation) are refused. Phase 4–8 data are not part of the test.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
from typing import Dict, List

import numpy as np

from .p8_eval import cluster_stats
from .p9_eval import primary_test
from .p9_regime import ALPHA, POWER, power_at
from .telemetry import md_table

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FROZEN_FILE = os.path.join(ROOT, "docs", "PREREG_PHASE10.json")
HL_MIN_N = 30


def check_frozen():
    spec = json.load(open(FROZEN_FILE))
    bad = [rel for rel, dg in spec["frozen_sha256"].items() if hashlib.sha256(open(os.path.join(ROOT, rel), "rb").read()).hexdigest() != dg]
    return (not bad), bad, spec


def load_rows(run_dirs: List[str]) -> List[dict]:
    rows = []
    for d in run_dirs:
        b = os.path.basename(os.path.normpath(d))
        if not b.startswith("p10r"):
            raise SystemExit(f"refusing {b}: confirmatory run directories are named p10r* (validation runs are p10v*)")
        path = os.path.join(d, "b_shadow.jsonl")
        if not os.path.exists(path):
            raise SystemExit(f"{path} missing — was the run started with --shadow-log?")
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue                                          # a line being written while the run is live
                r["run"], r["cl"] = b, f"{b}:{r.get('imp')}"
                rows.append(r)
    return rows


def sel(rows: List[dict], model: str, venue: str = "polymarket", gated: bool = True, sigma_known: bool = True) -> List[dict]:
    out = []
    for r in rows:
        if r.get("variant") != "B/fixed0.7" or r.get("model") != model or r.get("venue") != venue or not r.get("floor_ok") or r.get("outcome") != "filled":
            continue
        if sigma_known and r.get("sigma_pre") is None:
            continue
        if gated and not r.get("gate_ok"):
            continue
        out.append(r)
    return out


def test(sub: List[dict]) -> dict:
    if len(sub) < 3:
        return {"n": len(sub)}
    return primary_test(np.array([r["net_bps"] for r in sub]), [r["cl"] for r in sub])


def evaluate(run_dirs: List[str]) -> str:
    ok, bad, spec = check_frozen()
    rows = load_rows(run_dirs)
    n_star, mu, sg, ratio = spec["n_star"], spec["planning_mean_bps"], spec["sigma_eff_bps"], spec["cluster_ratio"]
    L: List[str] = []
    P = L.append
    P("# Phase 10 — evaluation of the pre-registered confirmatory test (live shadow rows)\n")
    P(f"**Frozen-code check:** {'PASS' if ok else 'FAIL — changed since pre-registration: ' + ', '.join(bad)}. Runs ({len(run_dirs)}): {', '.join(os.path.basename(os.path.normpath(d)) for d in run_dirs)}; {len(rows)} shadow rows.\n")
    P(f"H1: floor-passed (1.5×) Polymarket entries with pre-impulse σ60 < {spec['max_sigma60']} bps/√s: `fixed0.7` net expectancy > 0 (bps of notional after fees). One-sided α = {ALPHA}, cluster-robust t, "
      f"planned N\\* = {n_star} (power {POWER} for μ = {mu:+.0f} bps, σ_eff = {sg:.0f} bps).\n")
    for model in ("strict", "trades"):
        a = test(sel(rows, model))
        P(f"## Gated population, fill model `{model}`" + (" (primary)" if model == "strict" else " (secondary)") + "\n")
        if not a.get("clusters"):
            P(f"N = {a.get('n', 0)}: too few entries to test.\n")
            continue
        verdict = "**REJECT H0** (mean > 0)" if a["reject"] else "**do not reject H0**"
        short = "" if a["n"] >= n_star else f" N = {a['n']} < N\\* = {n_star}: underpowered — a non-rejection is inconclusive, not evidence of no effect."
        P(md_table(["N", "clusters", "mean net bps", "cluster s.e.", "t", f"t crit (df {a['df']})", "one-sided p"],
                   [[a["n"], a["clusters"], f"{a['mean']:+.0f}", f"{a['se']:.0f}", f"{a['t']:+.2f}", f"{a['t_crit']:.3f}", f"{a['p1']:.4f}"]]))
        P(f"Decision (pre-registered): {verdict}.{short} Achieved power for the planning effect at this N: {power_at(mu, sg, a['n'], ratio):.2f}.\n")
    P("## Secondary, descriptive (no decision rule): the same entries with and without the gate\n")
    body = []
    for name, sub in (("gated: σ_pre < 0.50", sel(rows, "strict")), ("turbulent baseline: σ_pre ≥ 0.50", [r for r in sel(rows, "strict", gated=False) if not r.get("gate_ok")]),
                      ("all floor-passed (gate ignored)", sel(rows, "strict", gated=False))):
        if len(sub) >= 2:
            m, s, t = cluster_stats(np.array([r["net_bps"] for r in sub]), [r["cl"] for r in sub])
            body.append([name, len(sub), f"{m:+.0f}", f"{s:.0f}", f"{t:+.2f}"])
        else:
            body.append([name, len(sub), "-", "-", "-"])
    P(md_table(["population (strict)", "N", "mean net bps", "cluster s.e.", "t"], body))
    hl = sel(rows, "strict", venue="hyperliquid", gated=False)
    P("## Hyperliquid (conditional arm)\n")
    if len(hl) >= HL_MIN_N:
        a = test(hl)
        P(f"{len(hl)} floor-passed Hyperliquid entries: mean {a['mean']:+.2f} bps, t = {a['t']:+.2f} (exploratory; no power calculation exists).\n")
    else:
        P(f"Only {len(hl)} floor-passed Hyperliquid entries (< {HL_MIN_N}): not analysed.\n")
    P("## Caveat\n")
    P("The gated split was chosen after looking at Phases 4–8, whose pooled gated mean was +128 bps (t = 0.80) — see docs/PHASE10_FINAL.md. This test uses only fresh data. A rejection would not be a trading recommendation (OPERATOR_GUIDE §6).\n")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check-frozen", action="store_true")
    ap.add_argument("--runs", nargs="*", default=[])
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    if a.check_frozen:
        ok, bad, _ = check_frozen()
        print("FROZEN OK" if ok else f"FROZEN FILES CHANGED: {bad}")
        raise SystemExit(0 if ok else 1)
    runs = []
    for pat in a.runs:
        runs += sorted(glob.glob(pat)) or [pat]
    md = evaluate(runs)
    print(md)
    if a.out:
        open(a.out, "w").write(md)


if __name__ == "__main__":
    main()
