"""Sector lead-lag report: BTC vs SOL / PEPE / RENDER (+ DOGE / TAO) oracles against their ecosystems.

    python -m quant_agency.sector_report --capture --duration 1200          # live capture (+3 min warm-up) then the report
    python -m quant_agency.sector_report --run runs/<sector run dir>        # report on an existing run
    python -m quant_agency.sector_report --run <dir> --notes docs/SECTOR_NOTES.md --out docs/SECTOR_LEAD_LAG.md

Inputs are the artefacts ``run_live --sectors`` writes: ``sector_markouts.jsonl`` (one row per signal x horizon x assumed latency),
``sector_map.json`` and ``sector_models.json``. All statistics here are descriptive / exploratory - nothing in this report was
pre-registered - and every mean carries a cluster-robust s.e. (clusters = leader impulses, globally unique across oracles).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import time
from collections import defaultdict
from typing import Dict, List, Optional, Sequence

import numpy as np

from .cfo_agent import _cluster_se

HZ = (1.0, 3.0, 5.0, 10.0, 30.0)
GAP_BUCKETS = (5.0, 10.0, 20.0)
FEES = (0.0, 2.0, 4.5, 7.5)               # uniform per-side fee levels for the break-even sweep (bps)
BASE = "BTC"


# ---------------------------------------------------------------------------------------------- loading
def _open_text(path: str):
    """Plain or gzipped JSONL (archived runs under docs/live_runs are gzipped)."""
    import gzip
    return open(path) if os.path.exists(path) else gzip.open(path + ".gz", "rt")


def load_run(run_dir: str) -> dict:
    rows = []
    with _open_text(os.path.join(run_dir, "sector_markouts.jsonl")) as f:
        for ln in f:
            rows.append(json.loads(ln))
    with open(os.path.join(run_dir, "sector_map.json")) as f:
        info = json.load(f)
    models = {}
    pm = os.path.join(run_dir, "sector_models.json")
    if os.path.exists(pm):
        with open(pm) as f:
            models = json.load(f)
    uni = {}
    pu = os.path.join(run_dir, "sector_universe.json")
    if os.path.exists(pu):
        with open(pu) as f:
            uni = json.load(f)
    return {"rows": rows, "info": info, "models": models, "universe": uni, "dir": run_dir}


# ---------------------------------------------------------------------------------------------- statistics
def _mean_se(rows: List[dict], key: str):
    if not rows:
        return float("nan"), float("nan")
    x = np.array([r[key] for r in rows], dtype=float)
    return float(x.mean()), _cluster_se(rows, key) if len(rows) > 1 else float("nan")


def _tstat(m: float, se: float) -> float:
    return m / se if se and se == se and se > 0 else float("nan")


def block(rows: List[dict]) -> dict:
    """Everything the report prints for one (oracle, optional subset) cell. ``rows`` = all horizons of one latency."""
    by_h = {h: [r for r in rows if r["h"] == h] for h in HZ}
    first = by_h[HZ[0]] or next((v for v in by_h.values() if v), [])
    out: dict = {"n_sig": len(first), "n_imp": len({r["imp"] for r in first})}
    if not first:
        return out
    gap = np.array([r["gap"] for r in first])
    spr = np.array([r["spread"] for r in first])
    ng = np.array([r["net_gap"] for r in first])
    out.update({
        "gap_med": float(np.median(gap)), "gap_mean": float(gap.mean()), "gap_p90": float(np.percentile(gap, 90)),
        "gap_ge": {str(b): float((gap >= b).mean()) for b in GAP_BUCKETS},
        "spread_med": float(np.median(spr)), "s2g_med": float(np.median(spr / np.maximum(gap, 1e-9))),
        "gap_gt_spread": float((gap > spr).mean()), "net_gap_pos": float((ng > 0).mean()), "net_gap_med": float(np.median(ng)),
        "gap_over_lsig_med": float(np.median(gap / np.maximum([r["lsig"] for r in first], 1e-9))),
        "lag_med": float(np.median([r["lag_s"] for r in first])), "lag_pos": float(np.mean([r["lag_s"] >= 0.1 for r in first])),
        "fee_rt_med": float(np.median([r["fee_in"] + r["fee_out"] for r in first])),
        "lmove_med": float(np.median([abs(r["ldelta"]) for r in first])), "fair_med": float(np.median([r["fair"] for r in first])),
        "hurdle_med": float(np.median([r["hurdle"] for r in first])),
    })
    curves = {}
    for h, rs in by_h.items():
        if not rs:
            continue
        gm, gse = _mean_se(rs, "gross")
        n0m, n0se = _mean_se(rs, "net0")
        nm, nse = _mean_se(rs, "net")
        g = np.array([r["gross"] for r in rs])
        curves[str(h)] = {"n": len(rs), "gross": gm, "gross_se": gse, "gross_t": _tstat(gm, gse), "gross_med": float(np.median(g)),
                          "hit": float((g > 0).mean()), "flat": float((g == 0).mean()), "net0": n0m, "net0_se": n0se, "net": nm, "net_se": nse,
                          "net_hit": float(np.mean([r["net"] > 0 for r in rs])),
                          "capture": gm / out["gap_mean"] if out["gap_mean"] > 0 else float("nan"),
                          "breakeven_fee": n0m / 2.0,
                          "fee_sweep": {str(f): n0m - 2.0 * f for f in FEES}}
    out["curves"] = curves
    return out


def half_capture_horizon(curves: dict) -> Optional[float]:
    """Interpolated horizon at which the mean gross markout first reaches half of the mean predicted gap (None if never within 30 s)."""
    pts = [(float(h), c["capture"]) for h, c in sorted(curves.items(), key=lambda kv: float(kv[0])) if c["capture"] == c["capture"]]
    prev = (0.0, 0.0)
    for h, cap in pts:
        if cap >= 0.5:
            if cap == prev[1]:
                return h
            return prev[0] + (0.5 - prev[1]) / (cap - prev[1]) * (h - prev[0])
        prev = (h, cap)
    return None


def placebo_block(dirs: Sequence[str], warm_s: float) -> dict:
    """Pool the time-shifted replays: impulse and signal ids are remapped per run so clusters stay distinct."""
    rows_by: Dict[str, List[dict]] = defaultdict(list)
    shifts = []
    for k, d in enumerate(dirs):
        run = load_run(d)
        info = run["info"]
        lat = info.get("main_latency_s", 0.15)
        cut = info["t_start"] + warm_s
        shifts.append(info.get("placebo_shift", float("nan")))
        for r in run["rows"]:
            if abs(r["lat"] - lat) < 1e-9 and r["t0"] >= cut:
                r = dict(r)
                r["imp"] = k * 1_000_000_000 + r["imp"]
                r["sid"] = k * 1_000_000_000 + r["sid"]
                rows_by[r["oracle"]].append(r)
    return {"n_runs": len(dirs), "shifts": shifts, "oracles": {n: block(rs) for n, rs in rows_by.items()}}


TAIL_BPS = 10.0


def tail_events(rows: List[dict], t_start: float, thr: float = TAIL_BPS) -> dict:
    """Signals with |gap| >= thr (all oracles): one line per leader impulse, plus the venue split of the tail signals."""
    h5 = [r for r in rows if abs(r["h"] - 5.0) < 1e-9 and r["gap"] >= thr]
    by = defaultdict(list)
    for r in h5:
        by[(r["oracle"], r["imp"])].append(r)
    ev = []
    for (o, imp), rs in sorted(by.items(), key=lambda kv: kv[1][0]["t0"]):
        ev.append({"oracle": o, "t": rs[0]["t0"] - t_start, "n": len(rs), "ldelta": rs[0]["ldelta"], "gap": float(np.mean([r["gap"] for r in rs])),
                   "spread": float(np.mean([r["spread"] for r in rs])), "gross5": float(np.mean([r["gross"] for r in rs])), "net0": float(np.mean([r["net0"] for r in rs])),
                   "venues": sorted({r["venue"] for r in rs}), "best": max(rs, key=lambda r: r["gross"])["market"], "best_gross": max(r["gross"] for r in rs)})
    sids = {r["sid"] for r in h5}
    tail_rows = [r for r in rows if r["sid"] in sids]
    by_v = defaultdict(list)
    for r in tail_rows:
        by_v[r["venue"]].append(r)
    return {"thr": thr, "events": ev, "n_sig": len(sids), "n_imp": len({r["imp"] for r in h5}), "venues": {v: block(x) for v, x in sorted(by_v.items())}, "pooled": block(tail_rows)}


def analyse(run: dict, warm_s: float = 180.0, lat: Optional[float] = None, placebo_dirs: Sequence[str] = ()) -> dict:
    info = run["info"]
    lat = info.get("main_latency_s", 0.15) if lat is None else lat
    t_cut = info["t_start"] + warm_s
    meta = {m["id"]: m for m in info["markets"]}
    rows = [r for r in run["rows"] if abs(r["lat"] - lat) < 1e-9 and r["t0"] >= t_cut]
    sectors = info["sectors"]
    out: dict = {"warm_s": warm_s, "latency_s": lat, "span_s": info["t_end"] - t_cut, "oracles": {}, "venues": {}, "baseline": {}, "lag_split": {},
                 "latency_sens": {}, "assets": {}, "models": {}, "sectors": sectors, "summary": info.get("summary", {}), "config": info.get("config", {})}
    # pooled per oracle
    for name in [BASE] + [s["name"] for s in sectors]:
        rs = [r for r in rows if r["oracle"] == name]
        out["oracles"][name] = block(rs)
        by_v = defaultdict(list)
        for r in rs:
            by_v[r["venue"]].append(r)
        out["venues"][name] = {v: block(x) for v, x in sorted(by_v.items())}
        out["lag_split"][name] = {"lead": block([r for r in rs if r["lag_s"] >= 0.1]), "nolead": block([r for r in rs if r["lag_s"] < 0.1])}
    # same-assets baseline: BTC hunter restricted to the sector's group (leader's own Binance market excluded, as in the sector hunter)
    for s in sectors:
        grp = set(s["group"])
        lead_mkt = f"{s['leader']}USDT"
        btc_rows = [r for r in rows if r["oracle"] == BASE and r["asset"] in grp and r["market"] != lead_mkt]
        out["baseline"][s["name"]] = block(btc_rows)
    # latency sensitivity (mean gross / net0 at 5 s per oracle)
    lat_all = defaultdict(lambda: defaultdict(list))
    for r in run["rows"]:
        if r["t0"] >= t_cut and abs(r["h"] - 5.0) < 1e-9:
            lat_all[r["oracle"]][r["lat"]].append(r)
    for name, d in lat_all.items():
        out["latency_sens"][name] = {str(k): {"n": len(v), "gross": _mean_se(v, "gross")[0], "net0": _mean_se(v, "net0")[0]} for k, v in sorted(d.items())}
    # per-asset (sector oracles only): where the gaps are
    by_oa = defaultdict(list)
    for r in rows:
        if r["oracle"] != BASE:
            by_oa[(r["oracle"], r["asset"])].append(r)
    for (o, a), rs in by_oa.items():
        r5 = [r for r in rs if abs(r["h"] - 5.0) < 1e-9]
        if r5:
            out["assets"].setdefault(o, {})[a] = {"n": len(r5), "gap": float(np.mean([r["gap"] for r in r5])), "spread": float(np.mean([r["spread"] for r in r5])),
                                                  "gross5": float(np.mean([r["gross"] for r in r5])), "net5": float(np.mean([r["net"] for r in r5]))}
    out["own_asset"] = {}
    for s_ in sectors:
        rs = [r for r in rows if r["oracle"] == s_["name"]]
        out["own_asset"][s_["name"]] = {"own": block([r for r in rs if r["asset"] == s_["leader"]]), "eco": block([r for r in rs if r["asset"] != s_["leader"]])}
    out["tail"] = tail_events(rows, info["t_start"])
    out["models"] = model_comparison(run, sectors, meta)
    out["universe"] = run.get("universe", {})
    out["market_asset"] = {m["id"]: m["asset"] for m in info["markets"]}
    if placebo_dirs:
        out["placebo"] = placebo_block(placebo_dirs, warm_s)
    return out


def _paired(a: np.ndarray, b: np.ndarray, rng: np.random.Generator, n_boot: int = 4000) -> dict:
    d = a - b
    n = len(d)
    if n == 0:
        return {"n": 0}
    boots = np.array([np.median(rng.choice(d, n, replace=True)) for _ in range(n_boot)])
    wins = int((d > 0).sum())
    ties = int((d == 0).sum())
    from scipy.stats import binomtest
    k, m = wins, n - ties
    p = float(binomtest(k, m, 0.5).pvalue) if m > 0 else float("nan")
    return {"n": n, "median_diff": float(np.median(d)), "ci": (float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))), "sign_p": p, "wins": wins}


def model_comparison(run: dict, sectors: List[dict], meta: Dict[str, dict]) -> dict:
    """Calibrated lead-lag (HY lag, OLS rho, beta) per hunter, and the paired sector-vs-BTC comparison on the same markets."""
    models = run["models"]
    if not models or BASE not in models:
        return {}
    rng = np.random.default_rng(7)
    btc = {r["market"]: r for r in models[BASE] if r["calibrated"]}
    out: dict = {}
    for s in sectors:
        rows = [r for r in models.get(s["name"], []) if r["calibrated"]]
        if not rows:
            continue
        lag = np.array([r["lag_s"] for r in rows])
        rho = np.array([r["rho"] for r in rows])
        beta = np.array([r["beta"] for r in rows])
        dec = np.array([r["decay_s"] for r in rows])
        paired = [(r, btc[r["market"]]) for r in rows if r["market"] in btc]
        entry = {"n": len(rows), "lag_med": float(np.median(lag)), "lag_mean": float(lag.mean()), "lead_share": float((lag >= 0.1).mean()),
                 "rho_med": float(np.median(rho)), "beta_med": float(np.median(beta)), "decay_med": float(np.median(dec))}
        if paired:
            sl = np.array([p[0]["lag_s"] for p in paired]); bl = np.array([p[1]["lag_s"] for p in paired])
            sr = np.array([p[0]["rho"] for p in paired]); br = np.array([p[1]["rho"] for p in paired])
            sd = np.array([p[0]["decay_s"] for p in paired]); bd = np.array([p[1]["decay_s"] for p in paired])
            entry["btc_same_markets"] = {"lag_med": float(np.median(bl)), "rho_med": float(np.median(br)), "decay_med": float(np.median(bd)),
                                         "lead_share": float((bl >= 0.1).mean())}
            entry["paired_lag"] = _paired(sl, bl, rng)
            entry["paired_rho"] = _paired(sr, br, rng)
            entry["paired_decay"] = _paired(sd, bd, rng)
        out[s["name"]] = entry
    out["_btc_all"] = {"n": len(btc), "lag_med": float(np.median([r["lag_s"] for r in btc.values()])) if btc else float("nan"),
                       "rho_med": float(np.median([r["rho"] for r in btc.values()])) if btc else float("nan")}
    return out


# ---------------------------------------------------------------------------------------------- rendering
def f(x, nd=2, plus=False):
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return "–"
    return f"{x:+.{nd}f}" if plus else f"{x:.{nd}f}"


def pm(m, se, nd=2):
    if m is None or m != m:
        return "–"
    return f"{m:+.{nd}f} ± {se:.{nd}f}" if se == se else f"{m:+.{nd}f}"


def pct(x):
    return "–" if x is None or x != x else f"{100 * x:.0f}%"


def render_md(res: dict, notes: str = "", title: str = "Sector lead-lag: do altcoin ecosystems lag their own leaders by more than they lag BTC?") -> str:
    o = res["oracles"]
    sectors = res["sectors"]
    names = [BASE] + [s["name"] for s in sectors]
    lab = {BASE: "BTC → all sector alts"}
    for s in sectors:
        lab[s["name"]] = f"{s['leader']} → {s['label']}" + (" (variant)" if s["variant_of"] else "")
    L: List[str] = [f"# {title}", ""]
    L.append(f"*Measurement window:* {res['span_s'] / 60:.1f} min after a {res['warm_s'] / 60:.0f}-min warm-up (calibration window), markouts assume **{res['latency_s'] * 1000:.0f} ms** "
             f"order latency and a **{res['config'].get('observe_notional_usd', 1000):.0f} USD** clip for the slippage term. Paper only; every signal is *observed and marked out*, none is traded. "
             "Nothing here was pre-registered: all comparisons are exploratory.")
    L.append("")
    if notes:
        L += [notes.strip(), ""]
    # ---------------- universe
    uni = res.get("universe") or {}
    if uni:
        cnt = uni.get("counts", {})
        L += ["## 0. What was watched", "", f"{sum(cnt.values())} markets: " + ", ".join(f"{v} {k}" for k, v in cnt.items()) + ". Admission: Binance 24 h volume ≥ $250k and spread ≤ 40 bps (leaders always admitted); "
              "Gate 24 h volume ≥ $100k; Kraken `X/USD` pairs that are online; Hyperliquid perps (`k`-prefixed for the 1000× contracts). Quote-validation gate on every hunter: spread ≤ 40 bps, "
              "fast EW spread ≤ 3× slow EW spread, quote age ≤ 30 s, tick rate ≥ 0.05/s.", "",
              "| sector oracle | leader | ecosystem members (all venues) |", "|---|---|---|"]
        for sct in res["sectors"]:
            L.append(f"| {sct['name']}{' (variant)' if sct['variant_of'] else ''} | {sct['leader']} | {len(sct['members'])} markets over {len({res['market_asset'].get(m) for m in sct['members']})} assets: " + ", ".join(sorted({res['market_asset'].get(m, m) for m in sct['members']})) + " |")
        dr = uni.get("dropped", {})
        if dr:
            L += ["", "Left out (asset: venue → reason): " + "; ".join(f"**{a}** " + ", ".join(f"{v} → {why}" for v, why in d.items()) for a, d in dr.items()), ""]
        else:
            L.append("")
    # ---------------- headline
    L += ["## 1. Headline table (all venues pooled, markout horizon 5 s)", "",
          "| oracle → members | impulses | signals | median \\|gap\\| bps | median spread bps | spread÷gap | gap > spread | net gap > 0 | gross 5 s (bps) | hit | net0 5 s | net 5 s | capture 5 s |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for n in names:
        b = o[n]
        c = b.get("curves", {}).get("5.0")
        if not c:
            L.append(f"| {lab[n]} | {b.get('n_imp', 0)} | {b.get('n_sig', 0)} | – | – | – | – | – | – | – | – | – | – |")
            continue
        L.append(f"| {lab[n]} | {b['n_imp']} | {b['n_sig']} | {f(b['gap_med'])} | {f(b['spread_med'])} | {f(b['s2g_med'])} | {pct(b['gap_gt_spread'])} | {pct(b['net_gap_pos'])} | "
                 f"{pm(c['gross'], c['gross_se'])} | {pct(c['hit'])} | {pm(c['net0'], c['net0_se'])} | {pm(c['net'], c['net_se'])} | {pct(c['capture'])} |")
    L += ["", "`gap` = |β·Δleader(h) − Δmid(h)| at the signal; `spread` = full quoted spread; `net gap` = |gap| − (spread + 2·fee + slippage) (CFO cost model, fee tiers in §9); "
          "`gross` = side × mid-to-mid move from t+latency to t+latency+h; `net0` = crossing the spread both ways, zero fees; `net` = net0 − venue taker fees both sides; "
          "`capture` = mean gross ÷ mean gap. ± is a cluster-robust s.e. (clusters = leader impulses).", ""]
    # ---------------- gap magnitude
    L += ["## 2. Gap magnitude: is it 10–20 bps instead of 1–2 bps?", "",
          "| oracle | median \\|gap\\| | mean | p90 | ≥5 bps | ≥10 bps | ≥20 bps | median leader move \\|Δ\\| (bps) | median fair move β·Δ | median hurdle | median gap ÷ leader σ(h) | median lag (s) | share with lag ≥ 0.1 s |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for n in names:
        b = o[n]
        if "gap_med" not in b:
            continue
        L.append(f"| {lab[n]} | {f(b['gap_med'])} | {f(b['gap_mean'])} | {f(b['gap_p90'])} | {pct(b['gap_ge']['5.0'])} | {pct(b['gap_ge']['10.0'])} | {pct(b['gap_ge']['20.0'])} | "
                 f"{f(b['lmove_med'])} | {f(b['fair_med'])} | {f(b['hurdle_med'])} | {f(b['gap_over_lsig_med'])} | {f(b['lag_med'])} | {pct(b['lag_pos'])} |")
    L += ["", "`gap ÷ leader σ(h)` is the gap in units of the leader's own typical move over the impulse horizon: it separates *\"the leader simply moves more in bps\"* from *\"the followers are further behind\"*.", ""]
    # ---------------- markout curves
    L += ["## 3. Markout curves (mean ± cluster s.e., bps; hit = gross > 0)", ""]
    for n in names:
        b = o[n]
        if not b.get("curves"):
            continue
        L += [f"**{lab[n]}** — {b['n_sig']} signals / {b['n_imp']} impulses", "", "| h (s) | n | gross | hit | flat (=0) | gross t | net0 | net | net > 0 | capture of gap | break-even fee/side |", "|---|---|---|---|---|---|---|---|---|---|---|"]
        for h in HZ:
            c = b["curves"].get(str(h))
            if c:
                L.append(f"| {h:g} | {c['n']} | {pm(c['gross'], c['gross_se'])} | {pct(c['hit'])} | {pct(c['flat'])} | {f(c['gross_t'], 1)} | {pm(c['net0'], c['net0_se'])} | {pm(c['net'], c['net_se'])} | {pct(c['net_hit'])} | {pct(c['capture'])} | {f(c['breakeven_fee'], 2, True)} |")
        hc = half_capture_horizon(b["curves"])
        L.append("")
        L.append(f"Half of the mean gap is captured by ≈ {hc:.1f} s." if hc is not None else "The mean gross markout never reaches half of the mean gap within 30 s.")
        L.append("")
    # ---------------- same-asset baseline
    L += ["## 4. Same assets, two oracles: BTC baseline vs the sector leader (h = 5 s)", "",
          "BTC-hunter rows restricted to the sector's own assets (leader's Binance market excluded, as in the sector hunter), so both rows trade the same instruments.", "",
          "| sector | oracle | signals | median \\|gap\\| | median spread | gross 5 s | hit | net0 5 s | net 5 s | lag med (s) | Δ gross vs BTC (±, approx.) |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for s in sectors:
        for who, b in (("BTC", res["baseline"].get(s["name"], {})), (s["leader"], o[s["name"]])):
            c = b.get("curves", {}).get("5.0") if b else None
            if not c:
                L.append(f"| {s['name']} | {who} | {b.get('n_sig', 0) if b else 0} | – | – | – | – | – | – | – | – |")
                continue
            d = ""
            if who != "BTC":
                cb = res["baseline"].get(s["name"], {}).get("curves", {}).get("5.0")
                if cb:
                    dm, dse = c["gross"] - cb["gross"], math.hypot(c["gross_se"], cb["gross_se"])
                    d = f"{dm:+.2f} ± {dse:.2f}"
            L.append(f"| {s['name']} | {who} | {b['n_sig']} | {f(b['gap_med'])} | {f(b['spread_med'])} | {pm(c['gross'], c['gross_se'])} | {pct(c['hit'])} | {pm(c['net0'], c['net0_se'])} | {pm(c['net'], c['net_se'])} | {f(b['lag_med'])} | {d} |")
    L += ["", "Δ gross = sector-oracle gross − BTC-oracle gross on the same instruments; the s.e. combines the two cluster s.e.s as if independent, which they are not exactly (impulses of different leaders overlap in time), so read it as indicative.", ""]
    # ---------------- lag
    mc = res["models"]
    L += ["## 5. Reaction speed: calibrated lead-lag per oracle (Hayashi–Yoshida peak lag, 180 s windows)", ""]
    if mc:
        L += ["| oracle | markets | median lag (s) | share lag ≥ 0.1 s | median ρ (3 s OLS) | median decay (s) | median β | same markets vs BTC: lag / ρ / decay | paired Δlag (sector−BTC), 95 % CI, sign test (members of one leader are not independent) | paired Δρ |", "|---|---|---|---|---|---|---|---|---|---|"]
        for s in sectors:
            e = mc.get(s["name"])
            if not e:
                continue
            bs = e.get("btc_same_markets", {})
            pl, pr = e.get("paired_lag", {}), e.get("paired_rho", {})
            L.append(f"| {lab[s['name']]} | {e['n']} | {f(e['lag_med'])} | {pct(e['lead_share'])} | {f(e['rho_med'])} | {f(e['decay_med'])} | {f(e['beta_med'])} | "
                     f"{f(bs.get('lag_med'))} / {f(bs.get('rho_med'))} / {f(bs.get('decay_med'))} | "
                     + (f"{f(pl['median_diff'], 2, True)} [{f(pl['ci'][0], 2)}, {f(pl['ci'][1], 2)}], p{'<0.001' if pl['sign_p'] < 0.001 else '=' + f(pl['sign_p'], 3)} (n={pl['n']}) | {f(pr['median_diff'], 2, True)} [{f(pr['ci'][0], 2)}, {f(pr['ci'][1], 2)}] |" if pl.get("n") else "– | – |"))
        b0 = mc.get("_btc_all", {})
        L += ["", f"BTC hunter over all {b0.get('n', 0)} calibrated markets: median lag {f(b0.get('lag_med'))} s, median ρ {f(b0.get('rho_med'))}.", ""]
    L.append("A *positive* lag means the member moves after the oracle; a lag of 0 (or the −0.5 s grid edge) means the member is contemporaneous with – or leads – the supposed leader, "
             "in which case a 'gap' is a transient divergence rather than a lead-lag opportunity. Rows split by that condition:")
    L += ["", "| oracle | lag ≥ 0.1 s: signals | gross 5 s | net0 5 s | lag < 0.1 s: signals | gross 5 s | net0 5 s |", "|---|---|---|---|---|---|---|"]
    for n in names:
        a, b = res["lag_split"][n]["lead"], res["lag_split"][n]["nolead"]
        ca, cb = a.get("curves", {}).get("5.0"), b.get("curves", {}).get("5.0")
        L.append(f"| {lab[n]} | {a.get('n_sig', 0)} | {pm(ca['gross'], ca['gross_se']) if ca else '–'} | {pm(ca['net0'], ca['net0_se']) if ca else '–'} | "
                 f"{b.get('n_sig', 0)} | {pm(cb['gross'], cb['gross_se']) if cb else '–'} | {pm(cb['net0'], cb['net0_se']) if cb else '–'} |")
    L.append("")
    # ---------------- venues
    L += ["## 6. By venue (h = 5 s)", "", "| oracle | venue | signals | median gap | median spread | gross | hit | net0 | net (venue fees) | fee/side assumed |", "|---|---|---|---|---|---|---|---|---|---|"]
    fees = {"binance": 7.5, "gate": 20.0, "kraken": 40.0, "hyperliquid": 4.5}
    for n in names:
        for v, b in res["venues"][n].items():
            c = b.get("curves", {}).get("5.0")
            if c:
                L.append(f"| {n} | {v} | {b['n_sig']} | {f(b['gap_med'])} | {f(b['spread_med'])} | {pm(c['gross'], c['gross_se'])} | {pct(c['hit'])} | {pm(c['net0'], c['net0_se'])} | {pm(c['net'], c['net_se'])} | {fees.get(v, '?')} |")
    L.append("")
    # ---------------- own-asset vs ecosystem
    L += ["## 7. The leader's own asset on other venues vs the rest of the ecosystem (h = 5 s)", "",
          "Same-asset copies (e.g. SOL on Gate / Kraken / Hyperliquid) are the classic cross-venue lag; the other assets are the *ecosystem* lead-lag the brief is about.", "",
          "| oracle | group | signals | median gap | median spread | gross | hit | net0 | net |", "|---|---|---|---|---|---|---|---|---|"]
    for sct in sectors:
        for lbl, key in ((f"{sct['leader']} on other venues", "own"), ("other ecosystem assets", "eco")):
            b = res["own_asset"][sct["name"]][key]
            c = b.get("curves", {}).get("5.0")
            if c:
                L.append(f"| {sct['name']} | {lbl} | {b['n_sig']} | {f(b['gap_med'])} | {f(b['spread_med'])} | {pm(c['gross'], c['gross_se'])} | {pct(c['hit'])} | {pm(c['net0'], c['net0_se'])} | {pm(c['net'], c['net_se'])} |")
    L.append("")
    # ---------------- tail
    tl = res["tail"]
    L += [f"## 8. Tail events: signals with |gap| ≥ {tl['thr']:g} bps", "",
          f"{tl['n_sig']} signals from {tl['n_imp']} leader impulses (of {sum(b.get('n_imp', 0) for b in o.values())} impulses that produced any signal) reached the 10–20 bps range the brief asked about.", "",
          "| t (s into window) | oracle | leader move (bps) | signals ≥ thr | mean gap | mean spread | gross 5 s | net0 5 s | best market (gross) | venues |", "|---|---|---|---|---|---|---|---|---|---|"]
    for e in tl["events"]:
        L.append(f"| {e['t']:.0f} | {e['oracle']} | {e['ldelta']:+.1f} | {e['n']} | {e['gap']:.1f} | {e['spread']:.1f} | {e['gross5']:+.2f} | {e['net0']:+.2f} | {e['best']} ({e['best_gross']:+.1f}) | {', '.join(e['venues'])} |")
    pb = tl["pooled"].get("curves", {}).get("5.0")
    if pb:
        L += ["", f"Pooled tail signals: gross 5 s {pm(pb['gross'], pb['gross_se'])}, net0 {pm(pb['net0'], pb['net0_se'])}, net {pm(pb['net'], pb['net_se'])} (clusters = {tl['n_imp']}; treat as anecdote, not a rate).", ""]
    L += ["| venue (tail signals only) | signals | mean gap | mean spread | gross 5 s | net0 5 s | net 5 s |", "|---|---|---|---|---|---|---|"]
    for v, b in tl["venues"].items():
        c = b.get("curves", {}).get("5.0")
        if c:
            L.append(f"| {v} | {b['n_sig']} | {f(b['gap_mean'])} | {f(b['spread_med'])} | {pm(c['gross'], c['gross_se'])} | {pm(c['net0'], c['net0_se'])} | {pm(c['net'], c['net_se'])} |")
    L.append("")
    # ---------------- fees
    L += ["## 9. Fees: how much would have to change?", "",
          "Taker fee per side (public lowest-tier retail schedules; **assumptions**, not verified for any account): Binance 7.5 bps, Gate 20, Kraken 40, Hyperliquid 4.5. "
          "Mean net0 (spread-crossing, before fees) at 5 s and the same number after a *uniform* per-side fee:", "",
          "| oracle | net0 5 s | −2×0 | −2×2 | −2×4.5 | −2×7.5 | break-even fee per side |", "|---|---|---|---|---|---|---|"]
    for n in names:
        c = o[n].get("curves", {}).get("5.0")
        if c:
            sw = c["fee_sweep"]
            L.append(f"| {lab[n]} | {f(c['net0'], 2, True)} | {f(sw['0.0'], 2, True)} | {f(sw['2.0'], 2, True)} | {f(sw['4.5'], 2, True)} | {f(sw['7.5'], 2, True)} | {f(c['breakeven_fee'], 2, True)} |")
    L.append("")
    # ---------------- latency
    L += ["## 10. Latency sensitivity (mean gross / net0 at h = 5 s)", "", "| oracle | " + " | ".join(f"{k} s" for k in sorted({k for d in res['latency_sens'].values() for k in d}, key=float)) + " |"]
    ks = sorted({k for d in res["latency_sens"].values() for k in d}, key=float)
    L.append("|---|" + "---|" * len(ks))
    for n in names:
        d = res["latency_sens"].get(n, {})
        L.append(f"| {n} | " + " | ".join((f"{f(d[k]['gross'], 2, True)} / {f(d[k]['net0'], 2, True)}" if k in d else "–") for k in ks) + " |")
    L.append("")
    # ---------------- assets
    L += ["## 11. Where the gaps are (sector oracles, h = 5 s, assets with ≥ 3 signals)", ""]
    for s in sectors:
        a = res["assets"].get(s["name"], {})
        rows = [(k, v) for k, v in sorted(a.items(), key=lambda kv: -kv[1]["n"]) if v["n"] >= 3]
        if not rows:
            continue
        L += [f"**{s['name']}** ({s['leader']} oracle)", "", "| asset | signals | mean gap | mean spread | gross | net |", "|---|---|---|---|---|---|"]
        for k, v in rows:
            L.append(f"| {k} | {v['n']} | {f(v['gap'])} | {f(v['spread'])} | {f(v['gross5'], 2, True)} | {f(v['net5'], 2, True)} |")
        L.append("")
    pl = res.get("placebo")
    if pl:
        L += ["## 12. Control: leaders time-shifted against the members", "",
              f"The same tape was replayed {pl['n_runs']} times with every leader's quote stream (BTC included) circularly shifted by {', '.join(f'{x:g}' for x in pl['shifts'])} s while the members kept their clock, "
              "so the leader-to-member relationship is destroyed but each stream keeps its own statistics. Whatever signals survive are produced by noise and by whatever calibration the hunters could still find.", "",
              "| oracle | real signals | placebo signals (mean per replay) | ratio | real gross 5 s | placebo gross 5 s | real − placebo (±, approx.) | real hit | placebo hit | placebo net0 5 s |", "|---|---|---|---|---|---|---|---|---|---|"]
        for n in names:
            r, q = o[n], pl["oracles"].get(n, {})
            cq = q.get("curves", {}).get("5.0")
            per = q.get("n_sig", 0) / pl["n_runs"]
            ratio = (per / r["n_sig"]) if r.get("n_sig") else float("nan")
            cr = r.get("curves", {}).get("5.0")
            if cq and cr and cq["n"] >= 5:
                dm, dse = cr["gross"] - cq["gross"], math.hypot(cr["gross_se"], cq["gross_se"])
                L.append(f"| {lab[n]} | {r.get('n_sig', 0)} | {per:.1f} | {f(ratio, 3)} | {pm(cr['gross'], cr['gross_se'])} | {pm(cq['gross'], cq['gross_se'])} (n={cq['n']}) | {dm:+.2f} ± {dse:.2f} | {pct(cr['hit'])} | {pct(cq['hit'])} | {pm(cq['net0'], cq['net0_se'])} |")
            else:
                L.append(f"| {lab[n]} | {r.get('n_sig', 0)} | {per:.1f} | {f(ratio, 3)} | {pm(cr['gross'], cr['gross_se']) if cr else '–'} | n/a (n={cq['n'] if cq else 0}) | – | {pct(cr['hit']) if cr else '–'} | – | – |")
        L += ["", "A collapse of the signal count says the hunters' signals depend on a real leader→member relationship rather than on generic quote noise. It does **not** prove the surviving gross markout is lead-lag: "
              "selecting on `fair − actual` also picks up mid-price noise that mean-reverts, which inflates gross (never net) for every oracle alike.", ""]
    # ---------------- run quality
    L += ["## 13. Run diagnostics", "", "| hunter | members | calibrated | impulses | scans | signals | gap hurdle rule |", "|---|---|---|---|---|---|---|"]
    for n, sm in res["summary"].items():
        rule = "flat 1 bp" if sm.get("gap_vol_mult", 0) == 0 else f"max(1 bp, {sm['gap_vol_mult']:g}·β·σ_leader(h))"
        L.append(f"| {n} | {sm['members']} | {sm['calibrated']} | {sm['impulses']} | {sm['scans']} | {sm['signals']} | {rule} |")
    L.append("")
    return "\n".join(L)


# ---------------------------------------------------------------------------------------------- cli
def capture(duration: float, warm: float, out: str, tag: str, extra: Sequence[str] = ()) -> str:
    os.makedirs(out, exist_ok=True)
    tape = os.path.join(out, "tapes", f"{tag}.npz")
    os.makedirs(os.path.dirname(tape), exist_ok=True)
    before = set(os.listdir(out))
    cmd = [sys.executable, "-m", "quant_agency.run_live", "--sectors", "--duration", str(duration + warm), "--out", out, "--tag", tag, "--record", tape,
           "--status-every", "60", *extra]
    subprocess.run(cmd, check=True)
    new = sorted(d for d in os.listdir(out) if d.startswith(tag + "_") and d not in before)
    if not new:
        raise RuntimeError("capture produced no run directory")
    return os.path.join(out, new[-1])


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--run", default=None, help="existing run directory written by run_live --sectors")
    p.add_argument("--capture", action="store_true", help="first run a live capture (duration + warm-up)")
    p.add_argument("--duration", type=float, default=1200.0, help="measurement window (s) after the warm-up")
    p.add_argument("--warm", type=float, default=180.0)
    p.add_argument("--out", default="docs/SECTOR_LEAD_LAG.md")
    p.add_argument("--json", default="docs/live_runs/sector_lead_lag.json")
    p.add_argument("--placebo", nargs="*", default=(), help="run directories of time-shifted replays (run_live --replay <tape> --placebo-shift S)")
    p.add_argument("--notes", default=None, help="markdown file with the hand-written interpretation, spliced in after the preamble")
    p.add_argument("--runs-dir", default="runs")
    p.add_argument("--tag", default="sector")
    a = p.parse_args(argv)
    run_dir = a.run
    if a.capture:
        run_dir = capture(a.duration, a.warm, a.runs_dir, a.tag)
    if not run_dir:
        p.error("give --run <dir> or --capture")
    res = analyse(load_run(run_dir), warm_s=a.warm, placebo_dirs=a.placebo)
    notes = open(a.notes).read() if a.notes else ""
    md = render_md(res, notes)
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "w") as fh:
        fh.write(md)
    if a.json:
        os.makedirs(os.path.dirname(a.json) or ".", exist_ok=True)
        with open(a.json, "w") as fh:
            json.dump(res, fh, indent=1, default=float)
    print(f"wrote {a.out} ({len(md)} chars) from {run_dir}")


if __name__ == "__main__":
    main()
