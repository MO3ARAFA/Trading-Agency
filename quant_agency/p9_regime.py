"""Phase 9 — how did `fixed0.7` behave as a function of real-time BTC volatility, and how many floor-passed fills does a one-sided test need?

    python -m quant_agency.p9_regime tapes/p4_tape_1.npz … tapes/p8_tape_1.npz --out docs/live_runs/phase9_regime_power.md --json docs/live_runs/phase9_regime_power.json

No parameter of any engine is touched: this only *labels* the already-recorded floor-passed Polymarket `fixed0.7` entries with sigma60 at their signal time (causal, quant_agency.regime)
and does the arithmetic of the power calculation. Unit of observation, metric and clustering are those of Phase 8 (net bps of notional after fees, clusters = BTC impulse id).
"""
from __future__ import annotations

import argparse
import json
import math
import os
from multiprocessing import Pool
from typing import Dict, List, Optional, Tuple

import numpy as np
from scipy import stats

from . import p7_pool
from .p8_eval import cluster_stats
from .regime import ACTIVE_THR, sigma60_series
from .telemetry import md_table

ALPHA, POWER = 0.05, 0.80
BASELINE = "fixed0.7"


def _job(path):
    return p7_pool.replay(path)


def required_n(mu: float, sigma_eff: float, cluster_ratio: float, alpha: float = ALPHA, power: float = POWER, n_max: int = 20000) -> Optional[int]:
    """Smallest N such that a one-sided cluster-robust t-test of mean > 0 at ``alpha`` has ``power`` when the true mean is ``mu`` bps.

    sigma_eff = per-entry SD *already inflated for clustering* (= observed cluster-robust s.e. x sqrt(N_obs)); the number of clusters is taken as ``cluster_ratio`` x N and the t reference has
    (clusters - 1) degrees of freedom; power from the non-central t. mu <= 0 -> None."""
    if mu <= 0 or sigma_eff <= 0:
        return None
    for n in range(4, n_max):
        df = max(cluster_ratio * n - 1.0, 2.0)
        tcrit = stats.t.ppf(1.0 - alpha, df)
        ncp = mu * math.sqrt(n) / sigma_eff
        if 1.0 - stats.nct.cdf(tcrit, df, ncp) >= power:
            return n
    return None


def power_at(mu: float, sigma_eff: float, n: int, cluster_ratio: float, alpha: float = ALPHA) -> float:
    df = max(cluster_ratio * n - 1.0, 2.0)
    return float(1.0 - stats.nct.cdf(stats.t.ppf(1.0 - alpha, df), df, mu * math.sqrt(n) / sigma_eff))


def load_btc(path: str) -> Tuple[np.ndarray, np.ndarray, float]:
    z = np.load(path)
    m = z["i"] == 0
    return z["t"][m], 0.5 * (z["b"][m] + z["a"][m]), float(z["t"][-1] - z["t"][0])


def analyse(tapes: List[str], procs: int = 4) -> dict:
    with Pool(min(procs, len(tapes))) as pool:
        res = pool.map(_job, tapes)
    ent: List[dict] = []
    hours = {"quiet": 0.0, "active": 0.0}
    sig_cnt = {"quiet": 0, "active": 0}
    sig_floor = {"quiet": 0, "active": 0}
    hl_sig = {"quiet": 0, "active": 0}
    hl_pass = {"quiet": 0, "active": 0}
    per_tape = []
    for path, r in zip(tapes, res):
        t, mid, dur = load_btc(path)
        t0 = float(np.load(path)["t"][0])
        grid = t0 + np.arange(70.0, dur, 10.0)
        v = sigma60_series(t, mid, grid)
        ok = ~np.isnan(v)
        hq = float(((v < ACTIVE_THR) & ok).sum()) * 10.0 / 3600.0
        ha = float(((v >= ACTIVE_THR) & ok).sum()) * 10.0 / 3600.0
        hours["quiet"] += hq
        hours["active"] += ha
        tape = os.path.basename(path)
        # signals (one per sid): label by sigma60 at the signal time — one batched pass over the tick stream
        seen: Dict[Tuple[str, int], float] = {}
        for row in r["rows"]:
            if row["venue"] in ("polymarket", "hyperliquid") and row.get("xvar") == "taker/taker" and (row["venue"], row["sid"]) not in seen:
                seen[(row["venue"], row["sid"])] = row["t0"]
        keys = list(seen)
        sv_all = sigma60_series(t, mid, [seen[k] for k in keys]) if keys else []
        sig_floor_flag = {(row["venue"], row["sid"]): bool(row.get("floor_ok")) for row in r["rows"] if row.get("xvar") == "taker/taker"}
        for k, sv in zip(keys, sv_all):
            if sv != sv:
                continue
            reg = "active" if sv >= ACTIVE_THR else "quiet"
            if k[0] == "polymarket":
                sig_cnt[reg] += 1
                sig_floor[reg] += int(sig_floor_flag[k])
            else:
                hl_sig[reg] += 1
                hl_pass[reg] += int(sig_floor_flag[k])
        base = [row for row in r["rows"] if row["venue"] == "polymarket" and row["variant"] != "ACCOUNT" and row.get("xvar") == BASELINE and row["model"] == "strict"
                and row.get("floor_ok") and row["outcome"] == "filled"]
        sv = sigma60_series(t, mid, [row["t0"] for row in base]) if base else []
        n_nan = 0
        for row, s_ in zip(base, sv):
            if s_ != s_:
                n_nan += 1
                continue
            ent.append({"tape": tape, "imp": f"{tape}:{row['imp']}", "bps": row["net_bps"], "cents": row["net_cents"], "usd": row["net_usd"], "sigma": float(s_),
                        "reg": "active" if s_ >= ACTIVE_THR else "quiet", "exit": row["exit_reason"]})
        per_tape.append({"tape": tape, "dur_h": dur / 3600.0, "hours_quiet": hq, "hours_active": ha, "entries": len(base) - n_nan, "no_vol_estimate": n_nan})
    return {"entries": ent, "hours": hours, "signals": sig_cnt, "signals_floor": sig_floor, "per_tape": per_tape, "hl_signals": hl_sig, "hl_pass": hl_pass}


def summarise(d: dict) -> Tuple[str, dict]:
    ent = d["entries"]
    x = np.array([e["bps"] for e in ent])
    cl = [e["imp"] for e in ent]
    n = len(x)
    mu, se, t = cluster_stats(x, cl)
    n_cl = len(set(cl))
    ratio = n_cl / n
    sigma_eff = se * math.sqrt(n)
    sd_raw = float(x.std(ddof=1))
    out: dict = {"n": n, "n_clusters": n_cl, "mean": mu, "se": se, "t": t, "sigma_eff": sigma_eff, "sd_raw": sd_raw, "cluster_ratio": ratio, "deff": (sigma_eff / sd_raw) ** 2}
    L: List[str] = []
    P = L.append
    P("# Phase 9 — `fixed0.7` by BTC volatility regime, and the power calculation\n")
    P(f"Entries: floor-passed (1.5×) Polymarket entries on tapes {', '.join(p['tape'] for p in d['per_tape'])}, `strict` fills, exit `fixed0.7` (the Phase 6/7 reference, parameters untouched), "
      f"metric net bps of notional, clusters = BTC impulse id. Each entry is labelled with **sigma60 at its signal time** (RMS of the last 60 one-second Binance BTCUSDT mid log-returns, bps/√s; causal; "
      f"`quant_agency/regime.py`, the same estimator the daemon triggers on). Active = sigma60 ≥ {ACTIVE_THR}. Entries with < 60 s of BTC history are excluded from this table (none expected).\n")
    P(f"All entries: N = {n} ({n_cl} clusters), mean **{mu:+.1f}** bps, cluster-robust s.e. **{se:.1f}**, t = {t:+.2f}; raw per-entry SD {sd_raw:.0f} bps; design effect (cluster) {out['deff']:.2f}; "
      f"effective per-entry SD σ_eff = s.e.·√N = **{sigma_eff:.0f}** bps.\n")
    P("## 1. Time spent in each regime and signal/fill supply\n")
    body = []
    for reg in ("quiet", "active"):
        h = d["hours"][reg]
        k = sum(1 for e in ent if e["reg"] == reg)
        body.append([reg, f"{h:.2f}", d["signals"][reg], f"{d['signals'][reg]/h:.0f}" if h > 0 else "-", d["signals_floor"][reg],
                     f"{d['signals_floor'][reg]/max(d['signals'][reg],1)*100:.0f}%", k, f"{k/h:.1f}" if h > 0 else "-"])
    P(md_table(["regime", "tape-hours", "PM signals", "signals / h", "pass floor", "floor pass rate", "floor-passed `fixed0.7` fills", "fills / h"], body))
    P(f"Hyperliquid (the secondary arm): signals by regime quiet {d['hl_signals']['quiet']} / active {d['hl_signals']['active']}; clearing the 1.5× floor: quiet {d['hl_pass']['quiet']} / active {d['hl_pass']['active']}. "
      f"With zero floor-passed Hyperliquid entries in any regime there is no variance to plan from, so the Hyperliquid arm cannot be powered (see PREREG_PHASE9).\n")
    out["hl"] = {"signals": d["hl_signals"], "pass": d["hl_pass"]}
    P("## 2. `fixed0.7` net expectancy by regime (descriptive; no regime was ever used to choose or drop anything)\n")
    body = []
    reg_stats: Dict[str, dict] = {}
    for reg in ("quiet", "active"):
        sub = [e for e in ent if e["reg"] == reg]
        if len(sub) >= 1:
            xs = np.array([e["bps"] for e in sub])
            m, s, tt = cluster_stats(xs, [e["imp"] for e in sub])
            reg_stats[reg] = {"n": len(sub), "mean": m, "se": s, "t": tt, "sd": float(xs.std(ddof=1)) if len(sub) > 1 else float("nan"), "hit": float((xs > 0).mean()),
                              "usd": float(sum(e["usd"] for e in sub)), "sigma_eff": (s * math.sqrt(len(sub))) if s == s else float("nan")}
            r = reg_stats[reg]
            body.append([reg, r["n"], f"{r['mean']:+.0f}", f"{r['se']:.0f}" if r["se"] == r["se"] else "-", f"{r['t']:+.2f}" if r["t"] == r["t"] else "-",
                         f"{r['sd']:.0f}" if r["sd"] == r["sd"] else "-", f"{r['hit']*100:.0f}%", f"{r['usd']:+.1f}"])
    P(md_table(["regime", "N", "mean net bps", "cluster s.e.", "t", "per-entry SD", "hit", "net $ (fixed $50 clips)"], body))
    out["regimes"] = reg_stats
    if len(reg_stats) == 2 and min(r["n"] for r in reg_stats.values()) >= 2:
        q, a = reg_stats["quiet"], reg_stats["active"]
        dm = a["mean"] - q["mean"]
        dse = math.sqrt(q["se"] ** 2 + a["se"] ** 2)
        P(f"Active − quiet difference: {dm:+.0f} bps, s.e. {dse:.0f}, t = {dm/dse:+.2f} (descriptive; N_active = {a['n']}).\n")
        out["active_minus_quiet"] = {"diff": dm, "se": dse, "t": dm / dse}
    # variance decomposition
    grand = x.mean()
    ss_tot = float(((x - grand) ** 2).sum())
    ss_b = sum(r["n"] * (r["mean"] - grand) ** 2 for r in reg_stats.values())
    ss_w = ss_tot - ss_b
    P(f"**Variance decomposition (entries, bps²):** total {ss_tot/(n-1):.0f}; between-regime share η² = {ss_b/ss_tot*100:.1f}% , within-regime share {ss_w/ss_tot*100:.1f}%. "
      f"Per-entry SD: quiet {reg_stats.get('quiet', {}).get('sd', float('nan')):.0f}, active {reg_stats.get('active', {}).get('sd', float('nan')):.0f} bps.\n")
    out["eta2"] = ss_b / ss_tot
    # terciles / slope on sigma
    sig = np.array([e["sigma"] for e in ent])
    qs = np.quantile(sig, [1 / 3, 2 / 3])
    body = []
    for name, lo, hi in (("low", -1, qs[0]), ("mid", qs[0], qs[1]), ("high", qs[1], 1e9)):
        sub = [e for e in ent if lo < e["sigma"] <= hi]
        if sub:
            xs = np.array([e["bps"] for e in sub])
            m, s, tt = cluster_stats(xs, [e["imp"] for e in sub])
            body.append([f"{name} (σ60 {min(e['sigma'] for e in sub):.2f}–{max(e['sigma'] for e in sub):.2f})", len(sub), f"{m:+.0f}", f"{s:.0f}", f"{tt:+.2f}"])
    P("**By σ60 tercile (descriptive):**\n")
    P(md_table(["tercile", "N", "mean net bps", "cluster s.e.", "t"], body))
    # OLS slope with cluster-robust se
    X = np.column_stack([np.ones(n), sig - sig.mean()])
    beta = np.linalg.lstsq(X, x, rcond=None)[0]
    res_ = x - X @ beta
    bread = np.linalg.inv(X.T @ X)
    meat = np.zeros((2, 2))
    by: Dict[str, np.ndarray] = {}
    for i, c in enumerate(cl):
        by[c] = by.get(c, np.zeros(2)) + X[i] * res_[i]
    for g in by.values():
        meat += np.outer(g, g)
    cov = bread @ meat @ bread
    slope, slope_se = float(beta[1]), float(math.sqrt(cov[1, 1]))
    P(f"Regression of net bps on σ60 (cluster-robust): slope {slope:+.0f} bps per 1 bps/√s (s.e. {slope_se:.0f}, t = {slope/slope_se:+.2f}). Descriptive: it is estimated from {n} entries of which "
      f"{reg_stats.get('active', {}).get('n', 0)} are in the active regime.\n")
    out["slope"] = {"slope": slope, "se": slope_se}
    # per-tape table
    body = [[p["tape"], f"{p['dur_h']:.2f}", f"{p['hours_quiet']:.2f}", f"{p['hours_active']:.2f}", p["entries"], p["no_vol_estimate"]] for p in d["per_tape"]]
    P("**Per tape:**\n")
    P(md_table(["tape", "hours", "quiet h", "active h", "entries", "excluded (no 60 s history)"], body))
    # power
    P("## 3. Power calculation: smallest N for a one-sided test of mean > 0\n")
    P(f"One-sided cluster-robust t-test, α = {ALPHA}, power {POWER}; non-central t with df = (clusters − 1), clusters = {ratio:.2f}·N (observed ratio {n_cl}/{n}); "
      f"σ_eff = {sigma_eff:.0f} bps (observed, cluster-inflated). N depends only on μ/σ_eff:\n")
    mus = [("observed mean", mu), ("observed lower 80 % one-sided bound", mu - stats.norm.ppf(0.8) * se), ("half the observed mean (shrinkage / winner's-curse allowance)", mu / 2.0),
           ("+100 bps (≈ 1 % of notional per entry)", 100.0), ("+250 bps", 250.0), ("upper 95 % bound of the observed mean", mu + 1.645 * se)]
    body = []
    pn = {}
    for label, m_ in mus:
        nn = required_n(m_, sigma_eff, ratio)
        pn[label] = nn
        body.append([label, f"{m_:+.0f}", f"{nn}" if nn else "n/a (μ ≤ 0)", f"{(nn or 0)/max(d['hours']['quiet']+d['hours']['active'],1e-9)*0:.0f}" if False else ""])
    body = [b[:3] for b in body]
    P(md_table(["planning effect μ", "μ (bps)", "required N*"], body))
    n_star = required_n(mu, sigma_eff, ratio)
    out["n_star_observed"] = n_star
    out["n_star_table"] = pn
    out["sigma_eff"] = sigma_eff
    if n_star:
        P(f"**Locked planning value (Phase 9 pre-registration): μ = observed mean {mu:+.0f} bps ⇒ N\\* = {n_star} floor-passed Polymarket entries.** "
          f"Achieved power at N\\*: {power_at(mu, sigma_eff, n_star, ratio):.2f}. If the true mean is only half the observed one, the power of a test with N = N\\* is "
          f"{power_at(mu/2, sigma_eff, n_star, ratio):.2f}; the minimum detectable true mean at N\\* with power 0.8 is {mu:+.0f} bps by construction. "
          f"A non-significant result at N\\* therefore means 'no evidence of an effect as large as the one observed', not 'no effect'.\n")
    rate_q = reg_stats.get("quiet", {}).get("n", 0) / max(d["hours"]["quiet"], 1e-9)
    rate_a = reg_stats.get("active", {}).get("n", 0) / max(d["hours"]["active"], 1e-9) if d["hours"]["active"] > 0 else float("nan")
    out["rate_quiet"], out["rate_active"] = rate_q, rate_a
    P("**Capture time implied** (floor-passed fills per hour from §1; the active rate rests on very few entries):\n")
    body = []
    if n_star:
        body.append(["all-quiet capture", f"{rate_q:.1f}", f"{n_star/rate_q:.1f}" if rate_q > 0 else "-"])
        if rate_a == rate_a and rate_a > 0:
            body.append(["all-active capture", f"{rate_a:.1f}", f"{n_star/rate_a:.1f}"])
    P(md_table(["scenario", "floor-passed fills / h", f"hours to N* = {n_star}"], body))
    return "\n".join(L), out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tapes", nargs="+")
    ap.add_argument("--out", default=None)
    ap.add_argument("--json", default=None)
    a = ap.parse_args()
    md, out = summarise(analyse(a.tapes))
    print(md)
    if a.out:
        open(a.out, "w").write(md)
    if a.json:
        json.dump(out, open(a.json, "w"), indent=1, default=float)


if __name__ == "__main__":
    main()
