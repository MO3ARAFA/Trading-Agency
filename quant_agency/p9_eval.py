"""Phase 9 — the single pre-registered confirmatory test: floor-passed Polymarket `fixed0.7` net expectancy > 0 on FRESH daemon-collected data.

    python -m quant_agency.p9_eval --check-frozen
    python -m quant_agency.p9_eval --tapes tapes/p9_seg_*.npz --out docs/live_runs/phase9_eval.md

Everything is fixed by docs/PREREG_PHASE9.md. Only tapes named p9_seg*.npz (the daemon's confirmatory prefix) are accepted; validation tapes (p9v_seg*) are refused. The Phase 4–8
tapes are NOT part of this test (they generated the hypothesis).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from multiprocessing import Pool
from typing import Dict, List, Optional

import numpy as np
from scipy import stats

from . import p7_pool
from .p8_eval import cluster_stats
from .p9_regime import ALPHA, POWER, required_n, power_at
from .regime import ACTIVE_THR, sigma60_series
from .telemetry import md_table

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FROZEN_FILE = os.path.join(ROOT, "docs", "PREREG_PHASE9.json")
BASELINE = "fixed0.7"
HL_MIN_N = 30


def check_frozen():
    spec = json.load(open(FROZEN_FILE))
    bad = [rel for rel, dg in spec["frozen_sha256"].items() if hashlib.sha256(open(os.path.join(ROOT, rel), "rb").read()).hexdigest() != dg]
    return (not bad), bad, spec


def primary_test(bps: np.ndarray, clusters: List[object]) -> dict:
    """One-sided cluster-robust t-test of mean > 0. Reference distribution: Student t with (clusters - 1) df — the same one the power calculation used."""
    n = len(bps)
    if n < 3:
        return {"n": n}
    mu, se, t = cluster_stats(bps, clusters)
    k = len(set(clusters))
    df = max(k - 1, 1)
    return {"n": n, "clusters": k, "mean": mu, "se": se, "t": t, "df": df, "t_crit": float(stats.t.ppf(1 - ALPHA, df)), "p1": float(1 - stats.t.cdf(t, df)), "reject": bool(t > stats.t.ppf(1 - ALPHA, df))}


def entries(res: List[dict], tapes: List[str], venue: str, model: str) -> List[dict]:
    out = []
    for path, r in zip(tapes, res):
        z = np.load(path)
        m = z["i"] == 0
        t, mid = z["t"][m], 0.5 * (z["b"][m] + z["a"][m])
        rows = [x for x in r["rows"] if x["venue"] == venue and x["variant"] != "ACCOUNT" and x.get("xvar") == BASELINE and x["model"] == model and x.get("floor_ok") and x["outcome"] == "filled"]
        sig = sigma60_series(t, mid, [x["t0"] for x in rows]) if rows else []
        for x, s in zip(rows, sig):
            out.append({"tape": r["tape"], "imp": x["imp"], "bps": x["net_bps"], "cents": x["net_cents"], "usd": x["net_usd"], "sigma": float(s), "exit": x["exit_reason"]})
    return out


def _job(p):
    return p7_pool.replay(p)


def evaluate(tapes: List[str], procs: int = 4) -> str:
    for p in tapes:
        b = os.path.basename(p)
        if not b.startswith("p9_seg") or b.startswith("p9v"):
            raise SystemExit(f"refusing {b}: confirmatory tapes must be named p9_seg*.npz (validation tapes are p9v_seg*)")
    spec_ok, bad, spec = check_frozen()
    n_star, mu_plan, sig_plan, ratio = spec["n_star"], spec["planning_mean_bps"], spec["sigma_eff_bps"], spec["cluster_ratio"]
    with Pool(min(procs, len(tapes))) as pool:
        res = pool.map(_job, tapes)
    L: List[str] = []
    P = L.append
    P("# Phase 9 — evaluation of the pre-registered confirmatory test\n")
    P(f"**Frozen-code check:** {'PASS' if spec_ok else 'FAIL — changed since pre-registration: ' + ', '.join(bad)}. Tapes ({len(tapes)}): {', '.join(os.path.basename(t) for t in tapes)}.\n")
    P(f"Hypothesis: floor-passed (1.5×) Polymarket `{BASELINE}` net expectancy > 0 (bps of notional, after fees); one-sided α = {ALPHA}; cluster-robust t (clusters = BTC impulse id), Student t with clusters−1 df. "
      f"Planned N\\* = {n_star} (power {POWER} for a true mean of {mu_plan:+.0f} bps with σ_eff = {sig_plan:.0f} bps).\n")
    out_models = {}
    for model in ("strict", "trades"):
        ent = entries(res, tapes, "polymarket", model)
        x = np.array([e["bps"] for e in ent])
        a = primary_test(x, [e["imp"] for e in ent]) if len(ent) else {"n": 0}
        out_models[model] = a
        P(f"## Polymarket, fill model `{model}`" + (" (primary)" if model == "strict" else " (secondary)") + "\n")
        if not a.get("n"):
            P("No floor-passed fills.\n")
            continue
        verdict = ("**REJECT H0** (mean > 0)" if a["reject"] else "**do not reject H0**")
        short = "" if a["n"] >= n_star else f" N = {a['n']} < N\\* = {n_star}: the test is underpowered; a non-rejection is inconclusive, not evidence of no effect."
        P(md_table(["N", "clusters", "mean net bps", "cluster s.e.", "t", f"t crit (df {a['df']})", "one-sided p"],
                   [[a["n"], a["clusters"], f"{a['mean']:+.0f}", f"{a['se']:.0f}", f"{a['t']:+.2f}", f"{a['t_crit']:.3f}", f"{a['p1']:.4f}"]]))
        P(f"Decision (pre-registered): {verdict}.{short} Achieved power for the planning effect at this N: {power_at(mu_plan, sig_plan, a['n'], ratio):.2f}; "
          f"¢/share cross-check {np.mean([e['cents'] for e in ent]):+.2f}¢; net $ on fixed $50 clips {sum(e['usd'] for e in ent):+.1f}.\n")
        if model == "strict":
            body = []
            for reg, lo, hi in (("quiet (σ60 < 0.50)", -1, ACTIVE_THR), ("active (σ60 ≥ 0.50)", ACTIVE_THR, 1e9)):
                sub = [e for e in ent if lo <= e["sigma"] < hi] if reg.startswith("active") else [e for e in ent if e["sigma"] < ACTIVE_THR or e["sigma"] != e["sigma"]]
                if len(sub) >= 2:
                    m, s, tt = cluster_stats(np.array([e["bps"] for e in sub]), [e["imp"] for e in sub])
                    body.append([reg, len(sub), f"{m:+.0f}", f"{s:.0f}", f"{tt:+.2f}"])
                else:
                    body.append([reg, len(sub), "-", "-", "-"])
            P("Pre-registered secondary (descriptive, no decision): by regime at the signal\n")
            P(md_table(["regime", "N", "mean net bps", "cluster s.e.", "t"], body))
    hl = entries(res, tapes, "hyperliquid", "strict")
    P("## Hyperliquid (secondary, conditional arm)\n")
    if len(hl) >= HL_MIN_N:
        a = primary_test(np.array([e["bps"] for e in hl]), [e["imp"] for e in hl])
        P(f"{len(hl)} floor-passed Hyperliquid entries (≥ {HL_MIN_N}): mean {a['mean']:+.2f} bps, t = {a['t']:+.2f}, one-sided p = {a['p1']:.4f}. Exploratory only: no power calculation exists for this arm.\n")
    else:
        P(f"Only {len(hl)} floor-passed Hyperliquid entries (< {HL_MIN_N}): not analysed. (Phase 4–8: 0 of 317 signals ever cleared the floor.)\n")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check-frozen", action="store_true")
    ap.add_argument("--tapes", nargs="*", default=[])
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    if a.check_frozen:
        ok, bad, _ = check_frozen()
        print("FROZEN OK" if ok else f"FROZEN FILES CHANGED: {bad}")
        raise SystemExit(0 if ok else 1)
    md = evaluate(a.tapes)
    print(md)
    if a.out:
        open(a.out, "w").write(md)


if __name__ == "__main__":
    main()
