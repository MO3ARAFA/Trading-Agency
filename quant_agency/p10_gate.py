"""Phase 10 — does the volatility split survive a PRE-impulse definition, and what is the in-sample size of the gated specification?

    python -m quant_agency.p10_gate tapes/p4_tape_1.npz … tapes/p8_tape_1.npz --out docs/live_runs/phase10_gate.md --json docs/live_runs/phase10_gate.json

Phase 9 labelled each entry with sigma60 AT the signal time. That window contains the triggering impulse itself, so a large impulse can put an entry in the "active" bucket without any prior
turbulence. The gate in Architecture B therefore uses the sigma60 of the 60 s window ending `regime_lag_s` (15 s) BEFORE the signal. This script reports both definitions on the same entries.
The gated number is IN-SAMPLE and post hoc (the split was chosen after looking at these data): it is a planning input for the next pre-registered test, not evidence.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from multiprocessing import Pool
from typing import Dict, List

import numpy as np

from . import p7_pool
from .p8_eval import cluster_stats
from .p9_regime import ALPHA, POWER, power_at, required_n
from .telemetry import md_table

THR = 0.50


def _job(path):
    return p7_pool.replay(path, max_sigma60=THR)


def entries(res: List[dict]) -> List[dict]:
    out = []
    for r in res:
        for x in r["rows"]:
            if (x["venue"] == "polymarket" and x["variant"] != "ACCOUNT" and x.get("xvar") == "fixed0.7" and x["model"] == "strict" and x.get("floor_ok") and x["outcome"] == "filled"
                    and x.get("sigma_pre") is not None and x.get("sigma_now") is not None):
                out.append({"tape": r["tape"], "imp": x["imp"], "bps": x["net_bps"], "cents": x["net_cents"], "usd": x["net_usd"], "now": x["sigma_now"], "pre": x["sigma_pre"], "gate": x["gate_ok"],
                            "spread": x["spread_bps"]})
    return out


def stat(sub: List[dict]) -> dict:
    if len(sub) < 2:
        return {"n": len(sub)}
    x = np.array([e["bps"] for e in sub])
    mu, se, t = cluster_stats(x, [e["imp"] for e in sub])
    return {"n": len(sub), "mean": mu, "se": se, "t": t, "sd": float(x.std(ddof=1)), "hit": float((x > 0).mean()), "usd": float(sum(e["usd"] for e in sub)),
            "clusters": len(set(e["imp"] for e in sub)), "sigma_eff": se * math.sqrt(len(sub))}


def row(name, s):
    if s.get("n", 0) < 2:
        return [name, s.get("n", 0), "-", "-", "-", "-", "-"]
    return [name, s["n"], f"{s['mean']:+.0f}", f"{s['se']:.0f}", f"{s['t']:+.2f}", f"{s['hit']*100:.0f}%", f"{s['usd']:+.1f}"]


def analyse(tapes: List[str], procs: int = 4):
    with Pool(min(procs, len(tapes))) as pool:
        res = pool.map(_job, tapes)
    ent = entries(res)
    # all PM signals (one per sid) for the spread-by-regime check
    sigs = []
    for r in res:
        seen = set()
        for x in r["rows"]:
            if x["venue"] == "polymarket" and x.get("xvar") == "taker/taker" and x["sid"] not in seen and x.get("sigma_pre") is not None:
                seen.add(x["sid"])
                sigs.append({"now": x["sigma_now"], "pre": x["sigma_pre"], "spread": x["spread_bps"], "gap": abs(x["gap_bps"]), "floor": bool(x.get("floor_ok"))})
    L: List[str] = []
    P = L.append
    out: dict = {}
    P("# Phase 10 — the σ60 split under a pre-impulse definition, and the in-sample size of the gated specification\n")
    P(f"Entries: floor-passed Polymarket `fixed0.7` (strict), tapes {', '.join(os.path.basename(t) for t in tapes)}; N = {len(ent)}. `σ_now` = σ60 at the signal (includes the triggering impulse; the Phase 9 label); "
      f"`σ_pre` = σ60 on the 60 s window ending 15 s earlier (the baseline the impulse broke out of; the gate). Threshold {THR} for both. Same entries, same exits, same fees.\n")
    now_hi = [e for e in ent if e["now"] >= THR]
    now_lo = [e for e in ent if e["now"] < THR]
    pre_hi = [e for e in ent if e["pre"] >= THR]
    pre_lo = [e for e in ent if e["pre"] < THR]
    P("## 1. Same entries, two definitions of 'quiet' / 'active'\n")
    body = [row("σ_now < 0.50  (Phase 9 'quiet')", stat(now_lo)), row("σ_now ≥ 0.50  (Phase 9 'active')", stat(now_hi)),
            row("**σ_pre < 0.50  (the gate: quiet baseline)**", stat(pre_lo)), row("σ_pre ≥ 0.50  (turbulent baseline)", stat(pre_hi))]
    P(md_table(["bucket", "N", "mean net bps", "cluster s.e.", "t", "hit", "net $ ($50 clips)"], body))
    both = sum(1 for e in ent if e["now"] >= THR and e["pre"] < THR)
    P(f"Of the {len(now_hi)} entries labelled 'active' at signal time, **{both} had a quiet baseline (σ_pre < {THR})** — the label was reacting to the impulse itself, not to prior turbulence. "
      f"Entries with a turbulent baseline: {len(pre_hi)}. Correlation σ_now vs σ_pre across entries: {np.corrcoef([e['now'] for e in ent], [e['pre'] for e in ent])[0,1]:.2f}.\n")
    out.update({"now_lo": stat(now_lo), "now_hi": stat(now_hi), "pre_lo": stat(pre_lo), "pre_hi": stat(pre_hi), "active_with_quiet_baseline": both})
    P("## 2. Does a calm book get 'cleanly sniped', and do providers pull quotes when turbulent? (descriptive, all Polymarket signals)\n")
    body = []
    for name, f in (("σ_pre < 0.50", lambda s: s["pre"] < THR), ("σ_pre ≥ 0.50", lambda s: s["pre"] >= THR), ("σ_now < 0.50", lambda s: s["now"] < THR), ("σ_now ≥ 0.50", lambda s: s["now"] >= THR)):
        sub = [s for s in sigs if f(s)]
        if sub:
            body.append([name, len(sub), f"{np.median([s['spread'] for s in sub]):.0f}", f"{np.median([s['gap'] for s in sub]):.0f}", f"{np.mean([s['floor'] for s in sub])*100:.0f}%"])
    P(md_table(["bucket", "signals", "median spread bps", "median |gap| bps", "floor pass rate"], body))
    P("If providers pulled quotes in turbulence, spreads would be wider there; read the table, not the story.\n")
    # gated spec
    g = stat(pre_lo)
    P("## 3. The gated specification, in-sample (post hoc — a planning input, not evidence)\n")
    P(f"Pure Architecture B + `fixed0.7` + gate σ_pre < {THR}: N = {g['n']}, mean **{g['mean']:+.0f}** bps, cluster s.e. {g['se']:.0f}, t = {g['t']:+.2f} (one-sided p ≈ {1-0.5*(1+math.erf(g['t']/math.sqrt(2))):.2f}), "
      f"hit {g['hit']*100:.0f}%, σ_eff = {g['sigma_eff']:.0f} bps. The threshold was not searched: 0.50 was the only value evaluated, but the *split itself* was chosen after Phase 9 looked at these entries, "
      f"so its in-sample mean is optimistically biased and t is not a valid test statistic.\n")
    ratio = g["clusters"] / g["n"]
    out["gated"] = g
    out["cluster_ratio"] = ratio
    mu = g["mean"]
    P("## 4. Power for the gated specification (one-sided, α = 0.05, power 0.80, non-central t)\n")
    mus = [("in-sample gated mean", mu), ("half of it (selection / winner's-curse allowance)", mu / 2.0), ("+100 bps", 100.0), ("+250 bps", 250.0)]
    body, tab = [], {}
    for lab, m_ in mus:
        n_ = required_n(m_, g["sigma_eff"], ratio)
        tab[lab] = n_
        body.append([lab, f"{m_:+.0f}", n_ if n_ else "n/a"])
    P(md_table(["planning effect", "μ (bps)", "required N\\*"], body))
    n_star = required_n(mu, g["sigma_eff"], ratio)
    out["n_star"], out["n_star_table"] = n_star, tab
    if n_star:
        P(f"**N\\* (locked in PREREG_PHASE10) = {n_star}** gated entries at the in-sample mean; power at half that effect: {power_at(mu/2, g['sigma_eff'], n_star, ratio):.2f}.\n")
    # tercile on sigma_pre
    s_pre = np.array([e["pre"] for e in ent])
    qs = np.quantile(s_pre, [1 / 3, 2 / 3])
    body = []
    for nm, lo, hi in (("low", -1, qs[0]), ("mid", qs[0], qs[1]), ("high", qs[1], 1e9)):
        sub = [e for e in ent if lo < e["pre"] <= hi]
        st = stat(sub)
        body.append([f"{nm} (σ_pre {min(e['pre'] for e in sub):.2f}–{max(e['pre'] for e in sub):.2f})"] + row("", st)[1:])
    P("By σ_pre tercile (descriptive):\n")
    P(md_table(["tercile", "N", "mean net bps", "cluster s.e.", "t", "hit", "net $"], body))
    return "\n".join(L), out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tapes", nargs="+")
    ap.add_argument("--out", default=None)
    ap.add_argument("--json", default=None)
    a = ap.parse_args()
    md, out = analyse(a.tapes)
    print(md)
    if a.out:
        open(a.out, "w").write(md)
    if a.json:
        json.dump(out, open(a.json, "w"), indent=1, default=float)


if __name__ == "__main__":
    main()
