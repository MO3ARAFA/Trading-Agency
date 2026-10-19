"""Phase 8 — the single pre-registered comparison: `trail` vs `fixed0.7` on floor-passed Polymarket fills.

Everything here is fixed by docs/PREREG_PHASE8.md *before* any Phase 8 data exists. No parameter, no subset and no metric is chosen in this file after the fact.

    python -m quant_agency.p8_eval --check-frozen
    python -m quant_agency.p8_eval --prior tapes/p4_tape_1.npz tapes/p5_tape_1.npz tapes/p6_tape_1.npz tapes/p7_tape_1.npz \\
                                   --fresh tapes/p8_tape_1.npz [tapes/p8_tape_2.npz] --out docs/live_runs/phase8_eval.md
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from multiprocessing import Pool
from typing import Dict, List, Optional, Tuple

import numpy as np

from . import p7_pool
from .telemetry import md_table

CANDIDATE, BASELINE = "trail", "fixed0.7"
T_ONE_SIDED = 1.645          # one-sided 5 %  (fresh-only test; reported, small N)
T_RAW = 2.0                  # raw two-sided ~5 %
T_ADJ = 2.63                 # 6-way Bonferroni, two-sided 5 % (the six Phase 7 exits)
N_TARGET = 70
FROZEN_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "PREREG_PHASE8.json")


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


def check_frozen() -> Tuple[bool, List[str]]:
    with open(FROZEN_FILE) as f:
        spec = json.load(f)
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    bad = []
    for rel, digest in spec["frozen_sha256"].items():
        if sha256(os.path.join(root, rel)) != digest:
            bad.append(rel)
    return (not bad), bad


def phi(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def cluster_stats(x: np.ndarray, clusters: List[object]) -> Tuple[float, float, float]:
    """(mean, cluster-robust s.e., t). Clusters = BTC impulses (several markets react to the same impulse)."""
    n = len(x)
    if n == 0:
        return float("nan"), float("nan"), float("nan")
    mu = float(x.mean())
    if n < 2:
        return mu, float("nan"), float("nan")
    by: Dict[object, float] = {}
    for v, c in zip(x, clusters):
        by[c] = by.get(c, 0.0) + (v - mu)
    cl = np.array(list(by.values()))
    se = float(np.sqrt((cl ** 2).sum()) / n) if len(cl) > 1 else float(x.std(ddof=1) / np.sqrt(n))
    return mu, se, (mu / se if se > 0 else float("nan"))


def cluster_bootstrap_ci(x: np.ndarray, clusters: List[object], reps: int = 4000, seed: int = 7) -> Tuple[float, float]:
    if len(x) < 3:
        return float("nan"), float("nan")
    idx: Dict[object, List[int]] = {}
    for i, c in enumerate(clusters):
        idx.setdefault(c, []).append(i)
    keys = list(idx)
    rng = np.random.default_rng(seed)
    means = np.empty(reps)
    for b in range(reps):
        pick = rng.integers(0, len(keys), len(keys))
        ii = np.concatenate([idx[keys[k]] for k in pick])
        means[b] = x[ii].mean()
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def paired(res: List[dict], model: str) -> List[dict]:
    """One record per floor-passed, filled Polymarket entry that has both exits' rows under `model` (the entry is identical, so both exist)."""
    cand: Dict[Tuple[str, int], dict] = {}
    base: Dict[Tuple[str, int], dict] = {}
    for x in res:
        for r in x["rows"]:
            if r["venue"] != "polymarket" or r["variant"] == "ACCOUNT" or r["model"] != model or not r.get("floor_ok") or r["outcome"] != "filled":
                continue
            k = (x["tape"], r["sid"])
            if r.get("xvar") == CANDIDATE:
                cand[k] = r
            elif r.get("xvar") == BASELINE:
                base[k] = r
    out = []
    for k, c in cand.items():
        b = base.get(k)
        if b is None:
            continue
        out.append({"key": k, "tape": k[0], "imp": c["imp"], "c_bps": c["net_bps"], "b_bps": b["net_bps"], "c_cents": c["net_cents"], "b_cents": b["net_cents"],
                    "c_usd": c["net_usd"], "b_usd": b["net_usd"]})
    return out


def analyse(recs: List[dict]) -> dict:
    if not recs:
        return {"n": 0}
    cl = [r["imp"] for r in recs]
    c = np.array([r["c_bps"] for r in recs])
    b = np.array([r["b_bps"] for r in recs])
    out = {"n": len(recs), "n_clusters": len(set(cl))}
    for name, x in (("trail", c), ("fixed", b), ("diff", c - b)):
        mu, se, t = cluster_stats(x, cl)
        lo, hi = cluster_bootstrap_ci(x, cl)
        out[name] = {"mean": mu, "se": se, "t": t, "p1": (1.0 - phi(t)) if t == t else float("nan"), "lo": lo, "hi": hi}
    cc = np.array([r["c_cents"] for r in recs])
    bc = np.array([r["b_cents"] for r in recs])
    out["trail_cents"] = float(cc.mean())
    out["fixed_cents"] = float(bc.mean())
    out["t_cents_trail"] = cluster_stats(cc, cl)[2]
    out["t_cents_diff"] = cluster_stats(cc - bc, cl)[2]
    out["usd_trail"] = float(sum(r["c_usd"] for r in recs))
    out["usd_fixed"] = float(sum(r["b_usd"] for r in recs))
    return out


def row_cells(a: dict) -> List[list]:
    if not a.get("n"):
        return [["-"] * 8]
    body = []
    for label, key in (("trail (candidate)", "trail"), ("fixed0.7 (baseline)", "fixed"), ("paired diff  trail − fixed0.7", "diff")):
        s = a[key]
        body.append([label, a["n"], a["n_clusters"], f"{s['mean']:+.0f}", f"{s['se']:.0f}", f"{s['t']:+.2f}", f"{s['p1']:.3f}", f"[{s['lo']:+.0f}, {s['hi']:+.0f}]"])
    return body


HEAD = ["quantity", "paired entries N", "BTC-impulse clusters", "mean net bps/fill", "cluster s.e.", "t", "one-sided p", "cluster-bootstrap 95 % CI (report only)"]


def _job(a):
    return p7_pool.replay(a)


def evaluate(prior: List[str], fresh: List[str], procs: int = 4) -> Tuple[str, dict]:
    tapes = prior + fresh
    with Pool(min(procs, len(tapes))) as pool:
        res = pool.map(_job, tapes)
    by_tape = {x["tape"]: x for x in res}
    fresh_res = [by_tape[os.path.basename(t)] for t in fresh]
    L: List[str] = []
    P = L.append
    ok, bad = check_frozen()
    P("# Phase 8 — evaluation of the single pre-registered comparison\n")
    P(f"**Frozen-code check:** {'PASS — every strategy/analysis file matches the SHA-256 recorded in docs/PREREG_PHASE8.json' if ok else 'FAIL — changed since pre-registration: ' + ', '.join(bad)}.\n")
    P(f"Tapes — prior: {', '.join(os.path.basename(t) for t in prior)}; fresh (Phase 8): {', '.join(os.path.basename(t) for t in fresh)}. "
      f"Unit: one floor-passed (1.5×) Polymarket entry; its `trail` and `fixed0.7` exits ran on the identical IOC taker fill. Metric: net bps of notional after fees (fixed-notional shadows). "
      f"Clusters: BTC impulse id. One-sided p from the normal approximation of t.\n")
    out: dict = {"frozen_ok": ok}
    for model in ("strict", "trades"):
        P(f"## Fill model `{model}`" + (" (primary)" if model == "strict" else " (secondary: only tapes with trade prints)") + "\n")
        P("### Test 1 — fresh out-of-sample only (Phase 8 tapes)\n")
        a1 = analyse(paired(fresh_res, model))
        P(md_table(HEAD, row_cells(a1)))
        if a1.get("n"):
            sup = a1["trail"]["t"] > T_ONE_SIDED and a1["diff"]["t"] > T_ONE_SIDED
            P(f"Rule: supported iff **both** one-sided t > {T_ONE_SIDED}. Result: **{'SUPPORTED' if sup else 'NOT supported'}** at N = {a1['n']} "
              f"(trail t = {a1['trail']['t']:+.2f}, paired difference t = {a1['diff']['t']:+.2f}).\n")
            P(f"¢/share cross-check: trail {a1['trail_cents']:+.2f}¢ (t {a1['t_cents_trail']:+.2f}), fixed0.7 {a1['fixed_cents']:+.2f}¢, difference t {a1['t_cents_diff']:+.2f}.\n")
            out[f"oos_{model}"] = a1
        P("### Test 2 — cumulative pooled (all tapes)\n")
        a2 = analyse(paired(res, model))
        P(md_table(HEAD, row_cells(a2)))
        if a2.get("n"):
            t = a2["trail"]["t"]
            n_ok = a2["n"] >= N_TARGET
            verdict = ("CLEARS the 6-way adjusted bar" if (n_ok and t > T_ADJ) else ("clears the raw bar only" if (n_ok and t > T_RAW) else "does NOT clear the raw bar" if n_ok else "N below the pre-registered target — inconclusive"))
            P(f"Rule: N ≥ {N_TARGET} **and** trail t > {T_RAW} (raw) / > {T_ADJ} (adjusted for the six Phase 7 exits). N = {a2['n']} ({'met' if n_ok else 'NOT met'}); trail t = {t:+.2f}. "
              f"Verdict: **{verdict}**. Paired difference vs fixed0.7: t = {a2['diff']['t']:+.2f}.\n")
            P(f"¢/share cross-check: trail {a2['trail_cents']:+.2f}¢ (t {a2['t_cents_trail']:+.2f}), fixed0.7 {a2['fixed_cents']:+.2f}¢, difference t {a2['t_cents_diff']:+.2f}.\n")
            out[f"pooled_{model}"] = a2
        body = []
        for x in res:
            a = analyse(paired([x], model))
            if a.get("n"):
                body.append([x["tape"], "fresh" if x in fresh_res else "prior", a["n"], f"{a['trail']['mean']:+.0f}", f"{a['fixed']['mean']:+.0f}", f"{a['diff']['mean']:+.0f}"])
        P("Per-tape breakdown (descriptive only, no test):\n")
        P(md_table(["tape", "role", "paired entries", "trail mean bps", "fixed0.7 mean bps", "diff mean bps"], body))
    P("## Caveat that no statistic here removes\n")
    P("The four prior tapes are the data on which `trail` looked best of six, so the pooled test is biased upward by selection (the 2.63 bar corrects for choosing among six exits, not for every other analysis choice); "
      "the fresh-only test is the only clean one and it is small. Sessions are in whatever BTC regime the clock delivered — see the per-session volatility in docs/PHASE8.md.\n")
    return "\n".join(L), out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check-frozen", action="store_true")
    ap.add_argument("--prior", nargs="*", default=[])
    ap.add_argument("--fresh", nargs="*", default=[])
    ap.add_argument("--out", default=None)
    ap.add_argument("--json", default=None)
    a = ap.parse_args()
    if a.check_frozen:
        ok, bad = check_frozen()
        print("FROZEN OK" if ok else f"FROZEN FILES CHANGED: {bad}")
        raise SystemExit(0 if ok else 1)
    md, out = evaluate(a.prior, a.fresh)
    print(md)
    if a.out:
        with open(a.out, "w") as f:
            f.write(md)
    if a.json:
        with open(a.json, "w") as f:
            json.dump(out, f, indent=1, default=float)


if __name__ == "__main__":
    main()
