"""Pre-registered primary test of the same-asset cross-venue tail lag (docs/PREREG_MIDCAP_XV.md).

    python -m quant_agency.midcap_eval --check-frozen
    python -m quant_agency.midcap_eval --runs runs/xvr_* [more …]

H1: among the 50 mid-cap pairs (BTC / ETH baseline excluded), signals whose same-asset gap clears the full cost hurdle
(|gap| >= HL spread + 2 x 4.5 bps taker fee + slippage) AND whose entry-side top of book is worth >= 1 000 USD have a mean net result > 0
(taker in, taker out, crossing the perp spread both ways, 4.5 bps per side), at 5 s after a 150 ms entry latency.
One-sided alpha = 0.05, cluster-robust t (clusters = 10-second time blocks per run), Student-t reference with clusters-1 df.
Decision requires >= 15 clusters; fewer is reported as "underpowered - no decision". Run directories named xvr* are confirmatory; xvv* (validation)
and xvp* (placebo) are refused. The Phase-6 sector capture that contained the motivating TAO event is not part of the test.
"""
from __future__ import annotations

import argparse
import glob
import gzip
import hashlib
import json
import os
from typing import Dict, List, Optional

import numpy as np

from .p8_eval import cluster_bootstrap_ci
from .p9_eval import primary_test

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FROZEN_FILE = os.path.join(ROOT, "docs", "PREREG_MIDCAP_XV.json")

PRIMARY = {"lat": 0.15, "h": 5.0, "tier": "full_cost", "min_top_usd": 1000.0, "fee_per_side_bps": 4.5, "min_clusters": 15, "alpha": 0.05}
FEE_TIERS = {"taker_taker_9": 9.0, "taker_in_maker_out_6": 6.0, "maker_maker_3": 3.0}


def check_frozen():
    spec = json.load(open(FROZEN_FILE))
    bad = [rel for rel, dg in spec["frozen_sha256"].items() if hashlib.sha256(open(os.path.join(ROOT, rel), "rb").read()).hexdigest() != dg]
    return (not bad), bad, spec


def _open(path: str):
    return open(path) if os.path.exists(path) else gzip.open(path + ".gz", "rt")


def load_rows(run_dir: str, tag: str = "") -> List[dict]:
    rows = []
    with _open(os.path.join(run_dir, "xv_markouts.jsonl")) as f:
        for line in f:
            line = line.strip()
            if line:
                r = json.loads(line)
                r["run"] = tag or os.path.basename(os.path.normpath(run_dir))
                r["cl"] = f"{r['run']}:{r['imp']}"
                rows.append(r)
    return rows


def is_full_cost(r: dict) -> bool:
    return r["gap"] >= r["x_hurdle"]


def tier_mask(r: dict, tier: str) -> bool:
    if tier == "full_cost":
        return is_full_cost(r)
    if tier == "all":
        return True
    return r["gap"] >= float(tier)                      # numeric tier: "8", "10", "15"


def net_variants(r: dict) -> Dict[str, float]:
    """Net result in bps for every fee tier, from the spread-crossing result ``net0`` (fees are subtracted afterwards), plus the optimistic maker-exit."""
    out = {k: r["net0"] - v for k, v in FEE_TIERS.items()}
    out["maker_exit_at_mid_opt_6"] = r["gross"] - r["hin"] - 6.0      # exit at the mid instead of crossing: no fill risk modelled
    return out


def select(rows: List[dict], lat: float, h: float, tier: str = "all", baseline: Optional[bool] = False, min_top_usd: float = 0.0) -> List[dict]:
    return [r for r in rows if abs(r["lat"] - lat) < 1e-9 and abs(r["h"] - h) < 1e-9 and (baseline is None or bool(r["x_baseline"]) == baseline)
            and tier_mask(r, tier) and r["x_top_usd"] >= min_top_usd]


def primary(rows: List[dict]) -> dict:
    P = PRIMARY
    sel = select(rows, P["lat"], P["h"], P["tier"], False, P["min_top_usd"])
    if not sel:
        return {"n": 0, "clusters": 0, "decision": "no signals in the primary subset"}
    x = np.array([r["net0"] - 2.0 * P["fee_per_side_bps"] for r in sel])
    cl = [r["cl"] for r in sel]
    res = primary_test(x, cl)
    lo, hi = cluster_bootstrap_ci(x, cl)
    res["boot_ci95"] = (lo, hi)
    res["gross_mean"] = float(np.mean([r["gross"] for r in sel]))
    res["gap_mean"] = float(np.mean([r["gap"] for r in sel]))
    res["hit_net"] = float(np.mean(x > 0))
    if res.get("clusters", 0) < P["min_clusters"]:
        res["decision"] = f"underpowered: {res.get('clusters', 0)} clusters < {P['min_clusters']} - no decision (estimate and CI reported only)"
    else:
        res["decision"] = "REJECT H0 (net > 0)" if res["reject"] else "do not reject H0"
    return res


def count_clusters(rows: List[dict]) -> dict:
    """The count-only stopping statistic: how many clusters the primary subset has so far. It never touches an outcome column."""
    sel = select(rows, PRIMARY["lat"], PRIMARY["h"], PRIMARY["tier"], False, PRIMARY["min_top_usd"])
    return {"signals": len(sel), "clusters": len({r["cl"] for r in sel})}


STOP_CLUSTERS = 20          # stop collecting once the primary subset has this many clusters ...
MAX_STAGES = 4              # ... or after this many 60-minute stages, whichever comes first


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--check-frozen", action="store_true")
    p.add_argument("--count", action="store_true", help="stopping rule: print only the primary-subset signal / cluster counts (no outcomes)")
    p.add_argument("--runs", nargs="*", default=[])
    a = p.parse_args(argv)
    ok, bad, spec = check_frozen()
    if a.check_frozen:
        print("frozen files intact" if ok else f"CHANGED since pre-registration: {bad}")
        return 0 if ok else 1
    if not ok:
        raise SystemExit(f"refusing to claim a confirmatory result: frozen files changed since pre-registration: {bad}")
    rows = []
    for d in a.runs:
        for dd in sorted(glob.glob(d)):
            b = os.path.basename(os.path.normpath(dd))
            if not b.startswith("xvr"):
                raise SystemExit(f"refusing {b}: confirmatory run directories are named xvr* (validation xvv*, placebo xvp*)")
            rows += load_rows(dd)
    if a.count:
        c = count_clusters(rows)
        c.update({"stop_clusters": STOP_CLUSTERS, "max_stages": MAX_STAGES, "stop": c["clusters"] >= STOP_CLUSTERS})
        print(json.dumps(c))
        return 0
    res = primary(rows)
    print(json.dumps(res, indent=1, default=float))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
