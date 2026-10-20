"""Report for the 1-to-1 same-asset cross-venue (Binance Vision spot -> Hyperliquid perp) tail-lag capture.

    python -m quant_agency.midcap_report --runs runs/xvr_* --placebo runs/xvp* --out docs/MIDCAP_CROSSVENUE.md --notes docs/MIDCAP_NOTES.md

Reads the artefacts ``run_live --midcap-xv`` writes (``xv_markouts.jsonl``, ``xv_map.json``, ``xv_universe.json``). The pre-registered primary test is
computed by ``midcap_eval`` (frozen); everything else here is descriptive.
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import os
from collections import defaultdict
from typing import Dict, List, Optional, Sequence

import numpy as np

from .midcap_eval import FEE_TIERS, PRIMARY, check_frozen, load_rows, net_variants, primary, select
from .p8_eval import cluster_stats
from .sector_report import f, pct

LATS = (0.0, 0.15, 0.5, 1.0)
HZ = (1.0, 3.0, 5.0, 10.0, 30.0)
TIERS = ("4", "8", "10", "15", "full_cost")
TIER_LABEL = {"4": "≥ 4 bps (shadow floor)", "8": "≥ 8 bps", "10": "≥ 10 bps", "15": "≥ 15 bps", "full_cost": "≥ full cost (spread + 9 bps fee + slip)", "all": "all"}


def _open_json(path):
    import gzip
    return json.load(open(path) if os.path.exists(path) else gzip.open(path + ".gz", "rt"))


LEAN_KEYS = ("x_asset", "lat", "h", "gap", "x_hurdle", "gross", "net0", "x_top_usd", "cl", "imp", "x_baseline", "side", "hin", "x_spread_h", "x_hl_age", "x_spread_b", "t0")


def load_set(dirs: Sequence[str], lean: bool = False) -> dict:
    """``lean`` keeps only the main-latency, h = 5 s rows and the columns the control tables need (the 24 control replays would not fit in memory otherwise)."""
    rows, infos, unis, rows_all = [], [], [], []
    for d in dirs:
        tag = os.path.basename(os.path.normpath(d))
        info = _open_json(os.path.join(d, "xv_map.json"))
        cut = info["t_start"] + info.get("warm_s", 60.0)
        if lean:
            r = []
            for x in load_rows(d, tag):
                if x["t0"] >= cut and abs(x["lat"] - 0.15) < 1e-9 and abs(x["h"] - 5.0) < 1e-9:
                    r.append({k: x[k] for k in LEAN_KEYS})
        else:
            allr = load_rows(d, tag)
            rows_all += [x for x in allr if abs(x["lat"] - PRIMARY["lat"]) < 1e-9 and abs(x["h"] - PRIMARY["h"]) < 1e-9]     # the frozen evaluator does not trim the warm-up
            r = [x for x in allr if x["t0"] >= cut]
        rows += r
        infos.append(info)
        up = os.path.join(d, "xv_universe.json")
        if os.path.exists(up) or os.path.exists(up + ".gz"):
            unis.append(_open_json(up))
    hours = sum((i["t_end"] - i["t_start"] - 60.0) / 3600.0 for i in infos)
    return {"rows": rows, "rows_all": rows_all, "infos": infos, "unis": unis, "hours": hours, "dirs": list(dirs)}


def stat(rows: List[dict], key=lambda r: r["gross"]) -> dict:
    if not rows:
        return {"n": 0, "k": 0, "mean": float("nan"), "se": float("nan"), "hit": float("nan")}
    x = np.array([key(r) for r in rows], dtype=float)
    mu, se, t = cluster_stats(x, [r["cl"] for r in rows])
    return {"n": len(rows), "k": len({r["cl"] for r in rows}), "mean": mu, "se": se, "t": t, "hit": float((x > 0).mean())}


def pm(s: dict, nd=2) -> str:
    if not s["n"]:
        return "–"
    return f"{s['mean']:+.{nd}f} ± {s['se']:.{nd}f}" if s["se"] == s["se"] else f"{s['mean']:+.{nd}f}"


def occurrence(rows: List[dict], hours: float, n_pairs: int) -> List[dict]:
    """Counts per tier at the main latency / h = 5 s view (one row per signal)."""
    out = []
    for base in (False, True):
        sel0 = select(rows, PRIMARY["lat"], PRIMARY["h"], "all", base)
        for tier in TIERS:
            s = [r for r in sel0 if (r["gap"] >= float(tier) if tier != "full_cost" else r["gap"] >= r["x_hurdle"])]
            ev = {(r["x_asset"], r["cl"]) for r in s}
            out.append({"baseline": base, "tier": tier, "signals": len(s), "events": len(ev), "assets": len({r["x_asset"] for r in s}), "blocks": len({r["cl"] for r in s}),
                        "per_hour": len(ev) / hours if hours else float("nan"), "per_coin_hour": len(ev) / hours / n_pairs if hours and n_pairs else float("nan"),
                        "top_ok": sum(r["x_top_usd"] >= PRIMARY["min_top_usd"] for r in s)})
    return out


def analyse(real: dict, placebo: Optional[dict] = None) -> dict:
    rows = real["rows"]
    n_mid = sum(1 for p in (real["infos"][0]["pairs"] if real["infos"] else []) if not p["baseline"])
    n_base = sum(1 for p in (real["infos"][0]["pairs"] if real["infos"] else []) if p["baseline"])
    out: dict = {"hours": real["hours"], "n_mid": n_mid, "n_base": n_base, "runs": [os.path.basename(d) for d in real["dirs"]]}
    out["primary"] = primary(real["rows_all"] or rows)               # exactly the frozen evaluator's population (no warm-up trim)
    out["occurrence"] = occurrence(rows, real["hours"], n_mid)
    # tier x latency (h = 5)
    tl = {}
    for tier in TIERS:
        for lat in LATS:
            s = select(rows, lat, 5.0, tier, False)
            tl[f"{tier}|{lat}"] = {"gross": stat(s), "net0": stat(s, lambda r: r["net0"]),
                                   "fee": {k: stat(s, lambda r, v=v: r["net0"] - v) for k, v in FEE_TIERS.items()},
                                   "maker_exit_opt": stat(s, lambda r: net_variants(r)["maker_exit_at_mid_opt_6"])}
    out["tier_lat"] = tl
    # horizon curves
    hc = {}
    for tier in ("8", "10", "full_cost"):
        for lat in (0.0, 0.15):
            hc[f"{tier}|{lat}"] = {str(h): {"gross": stat(select(rows, lat, h, tier, False)), "net9": stat(select(rows, lat, h, tier, False), lambda r: r["net0"] - 9.0)} for h in HZ}
    out["curves"] = hc
    # baseline vs midcap at equal gap tiers
    bl = {}
    for tier in ("4", "8"):
        for base in (False, True):
            s = select(rows, 0.15, 5.0, tier, base)
            bl[f"{tier}|{base}"] = {"gross": stat(s), "net0": stat(s, lambda r: r["net0"]), "gap": float(np.mean([r["gap"] for r in s])) if s else float("nan"),
                                    "spread": float(np.median([r["x_spread_h"] for r in s])) if s else float("nan")}
    out["baseline"] = bl
    # tradability / composition (tier >= 10, main latency)
    t10 = select(rows, 0.15, 5.0, "10", False)
    tr = {}
    if t10:
        top = np.array([r["x_top_usd"] for r in t10])
        tr = {"n": len(t10), "top_med": float(np.median(top)), "top_ge_1k": float((top >= 1000).mean()), "top_ge_5k": float((top >= 5000).mean()),
              "spread_h_med": float(np.median([r["x_spread_h"] for r in t10])), "hl_age_med": float(np.median([r["x_hl_age"] for r in t10])),
              "hl_age_gt1": float(np.mean([r["x_hl_age"] > 1.0 for r in t10])), "up": int(sum(r["side"] > 0 for r in t10)), "down": int(sum(r["side"] < 0 for r in t10)),
              "gross_up": stat([r for r in t10 if r["side"] > 0]), "gross_down": stat([r for r in t10 if r["side"] < 0]),
              "binance_spread_med": float(np.median([r["x_spread_b"] for r in t10]))}
    out["trade"] = tr
    sens = {}
    for tier in ("10", "full_cost"):
        for mt in (0.0, 250.0, 500.0, 1000.0, 5000.0):
            sel = select(rows, 0.15, 5.0, tier, False, mt)
            sens[f"{tier}|{mt:g}"] = {"gross": stat(sel), "net9": stat(sel, lambda r: r["net0"] - 9.0)}
    out["touch_sens"] = sens
    strat = {}
    for lat in (0.0, 0.15):
        for lo, hi in ((0.0, 2.0), (2.0, 5.0), (5.0, 1e9)):
            sel = [r for r in select(rows, lat, 5.0, "8", False) if lo < r["x_spread_b"] <= hi]
            gap = float(np.mean([r["gap"] for r in sel])) if sel else float("nan")
            g = stat(sel)
            strat[f"{lat}|{lo:g}|{hi:g}"] = {"gross": g, "net9": stat(sel, lambda r: r["net0"] - 9.0), "gap": gap, "closure": g["mean"] / gap if sel else float("nan"),
                                             "touch": float(np.median([r["x_top_usd"] for r in sel])) if sel else float("nan"), "spread_h": float(np.median([r["x_spread_h"] for r in sel])) if sel else float("nan")}
    out["leader_quality"] = strat
    cl_curve = {}
    for h in HZ:
        sel = select(rows, 0.15, h, "8", False)
        gap = float(np.mean([r["gap"] for r in sel])) if sel else float("nan")
        cl_curve[str(h)] = {"gross": stat(sel)["mean"], "gap": gap, "closure": stat(sel)["mean"] / gap if sel else float("nan")}
    out["closure_curve"] = cl_curve
    # per asset
    pa = defaultdict(list)
    for r in select(rows, 0.15, 5.0, "8", False):
        pa[r["x_asset"]].append(r)
    prim = select(rows, PRIMARY["lat"], PRIMARY["h"], PRIMARY["tier"], False, PRIMARY["min_top_usd"])
    pa_rows = []
    for a, rs in sorted(pa.items(), key=lambda kv: -len(kv[1])):
        r10 = [r for r in rs if r["gap"] >= 10]
        pa_rows.append({"asset": a, "n8": len(rs), "n10": len(r10), "events": len({r["cl"] for r in rs}), "gap": float(np.mean([r["gap"] for r in rs])), "gross": stat(rs),
                        "net9": stat(rs, lambda r: r["net0"] - 9.0), "spread_h": float(np.median([r["x_spread_h"] for r in rs])), "top_med": float(np.median([r["x_top_usd"] for r in rs]))})
    out["assets"] = pa_rows
    # robustness of the primary estimate
    rob = {}
    if prim:
        x = np.array([r["net0"] - 9.0 for r in prim])
        cl = np.array([r["cl"] for r in prim])
        by_cl = {c: x[cl == c].sum() for c in set(cl)}
        worst = max(by_cl, key=lambda c: by_cl[c])
        keep = cl != worst
        rob["drop_best_cluster"] = {"cluster": str(worst), "mean": float(x[keep].mean()) if keep.any() else float("nan"), "n": int(keep.sum())}
        asset = np.array([r["x_asset"] for r in prim])
        top_asset = max(set(asset), key=lambda a: (asset == a).sum())
        k2 = asset != top_asset
        rob["drop_top_asset"] = {"asset": str(top_asset), "share": float((asset == top_asset).mean()), "mean": float(x[k2].mean()) if k2.any() else float("nan"), "n": int(k2.sum())}
        rob["max_cluster_share"] = float(max(by_cl.values()) / x.sum()) if x.sum() > 0 else float("nan")
    out["robust"] = rob
    out["placebo"] = None
    if placebo and placebo["rows"]:
        k = len(placebo["dirs"])
        pb = {"n_runs": k, "shifts": [i.get("placebo_shift") for i in placebo["infos"]], "tiers": {}}
        for tier in ("4", "8", "10", "15", "full_cost"):
            s = select(placebo["rows"], 0.15, 5.0, tier, False)
            pb["tiers"][tier] = {"per_run": len(s) / k, "gross": stat(s), "net9": stat(s, lambda r: r["net0"] - 9.0)}
        out["placebo"] = pb
    out["frozen_ok"], out["frozen_bad"] = check_frozen()[:2] if os.path.exists(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "PREREG_MIDCAP_XV.json")) else (None, [])
    return out


def render_md(res: dict, real: dict, notes: str = "") -> str:
    L: List[str] = ["# Same-asset cross-venue tail lag: Binance Vision spot → Hyperliquid perp (1-to-1, mid-caps)", ""]
    L.append(f"*Capture:* {res['hours']:.2f} h of measurement after a 60 s warm-up per run, {res['n_mid']} matched mid-cap pairs + {res['n_base']} baseline pairs (BTC, ETH); "
             f"runs {', '.join(res['runs'])}. Paper only; every signal is observed and marked out, none is traded. Entry = taker on the perp at the touch `latency` after the Binance tick, exit = taker at the touch.")
    L.append("")
    if notes:
        L += [notes.strip(), ""]
    # ---- primary
    p = res["primary"]
    L += ["## 1. Pre-registered primary test (`docs/PREREG_MIDCAP_XV.md`)", "",
          "H1: mean **net** > 0 for mid-cap signals with |gap| ≥ full cost hurdle and ≥ 1 000 USD at the entry-side touch; taker in / taker out at 4.5 bps per side, crossing the perp spread both ways, "
          "5 s exit, 150 ms entry latency; one-sided α = 0.05, cluster-robust t over 10-second blocks, Student-t with clusters − 1 df, ≥ 15 clusters required.", ""]
    if p.get("n"):
        L += ["| signals | clusters | mean net (bps) | s.e. | t | df | t crit | p (1-sided) | bootstrap 95 % CI | mean gross | mean gap | hit (net>0) |", "|---|---|---|---|---|---|---|---|---|---|---|---|",
              f"| {p['n']} | {p['clusters']} | {p['mean']:+.2f} | {f(p['se'])} | {f(p['t'])} | {p['df']} | {f(p['t_crit'])} | {f(p['p1'], 3)} | [{p['boot_ci95'][0]:+.2f}, {p['boot_ci95'][1]:+.2f}] | {p['gross_mean']:+.2f} | {p['gap_mean']:.1f} | {pct(p['hit_net'])} |", "",
              f"**Decision: {p['decision']}.**", ""]
    else:
        L += [f"**Decision: {p['decision']}.**", ""]
    if res.get("frozen_ok") is not None:
        L += [f"Frozen-file check at report time: {'intact' if res['frozen_ok'] else 'CHANGED since pre-registration: ' + ', '.join(res['frozen_bad'])}.", ""]
    rb = res["robust"]
    if rb:
        L += [f"Robustness of the primary estimate: dropping the single best cluster leaves a mean net of {rb['drop_best_cluster']['mean']:+.2f} bps (n = {rb['drop_best_cluster']['n']}); "
              f"dropping the most frequent asset ({rb['drop_top_asset']['asset']}, {pct(rb['drop_top_asset']['share'])} of the subset) leaves {rb['drop_top_asset']['mean']:+.2f} bps (n = {rb['drop_top_asset']['n']}). "
              + (f"The best cluster carries {pct(rb['max_cluster_share'])} of the summed net." if rb["max_cluster_share"] == rb["max_cluster_share"] else "")]
        L.append("")
    # ---- occurrence
    L += ["## 2. How often do same-asset dislocations occur?", "",
          "A signal is a Binance tick on which the coin moved ≥ 4 bps over 1 or 3 s and the perp has not followed by ≥ 4 bps (cooldown 3 s per pair). An *event* is a distinct (coin, 10-second block). "
          f"Rates are per hour of measurement ({res['hours']:.2f} h) and per coin-hour ({res['n_mid']} mid-caps, {res['n_base']} baseline).", "",
          "| group | gap tier | signals | events | coins | 10-s blocks | events / h | events / coin-h | signals with ≥ 1 000 USD at the touch |", "|---|---|---|---|---|---|---|---|---|"]
    for o in res["occurrence"]:
        L.append(f"| {'BTC+ETH baseline' if o['baseline'] else 'mid-caps'} | {TIER_LABEL[o['tier']]} | {o['signals']} | {o['events']} | {o['assets']} | {o['blocks']} | {f(o['per_hour'])} | {f(o['per_coin_hour'], 3)} | {o['top_ok']} |")
    L.append("")
    # ---- tier x latency
    L += ["## 3. Markouts by tier and latency (mid-caps, h = 5 s; mean ± cluster s.e., bps)", "",
          "`gross` = mid-to-mid; `net0` = crossing the perp spread both ways, no fees; fee tiers are subtracted from `net0` (taker/taker 9 bps; taker-in/maker-out 6; maker/maker 3 — the maker tiers keep the "
          "spread-crossing price and assume no fill risk, so they are optimistic). *maker exit at mid* = cross on entry, exit at the mid, 6 bps.", "",
          "| tier | latency | signals | clusters | gross | hit | net0 | net 9 bps | net 6 | net 3 | maker exit at mid (opt.) |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for tier in TIERS:
        for lat in LATS:
            c = res["tier_lat"][f"{tier}|{lat}"]
            g = c["gross"]
            if not g["n"]:
                L.append(f"| {TIER_LABEL[tier]} | {lat * 1000:.0f} ms | 0 | 0 | – | – | – | – | – | – | – |")
                continue
            L.append(f"| {TIER_LABEL[tier]} | {lat * 1000:.0f} ms | {g['n']} | {g['k']} | {pm(g)} | {pct(g['hit'])} | {pm(c['net0'])} | {pm(c['fee']['taker_taker_9'])} | "
                     f"{pm(c['fee']['taker_in_maker_out_6'])} | {pm(c['fee']['maker_maker_3'])} | {pm(c['maker_exit_opt'])} |")
    L.append("")
    # ---- curves
    L += ["## 4. Markout curves (mid-caps)", ""]
    for key, cur in res["curves"].items():
        tier, lat = key.split("|")
        L += [f"**{TIER_LABEL[tier]}, {float(lat) * 1000:.0f} ms**", "", "| h (s) | signals | clusters | gross | hit | net 9 bps |", "|---|---|---|---|---|---|"]
        for h in HZ:
            c = cur[str(h)]
            if c["gross"]["n"]:
                L.append(f"| {h:g} | {c['gross']['n']} | {c['gross']['k']} | {pm(c['gross'])} | {pct(c['gross']['hit'])} | {pm(c['net9'])} |")
        L.append("")
    # ---- baseline
    L += ["## 5. Mid-caps vs the BTC / ETH baseline at equal gap tiers (150 ms, h = 5 s)", "",
          "| gap tier | group | signals | clusters | mean gap | median perp spread | gross | hit | net0 |", "|---|---|---|---|---|---|---|---|---|"]
    for tier in ("4", "8"):
        for base in (False, True):
            c = res["baseline"][f"{tier}|{base}"]
            g = c["gross"]
            L.append(f"| {TIER_LABEL[tier]} | {'BTC+ETH' if base else 'mid-caps'} | {g['n']} | {g['k']} | {f(c['gap'], 1)} | {f(c['spread'])} | {pm(g)} | {pct(g['hit']) if g['n'] else '–'} | {pm(c['net0'])} |")
    L.append("")
    # ---- placebo
    pb = res.get("placebo")
    if pb:
        L += ["## 6. Control: Binance legs time-shifted against the perps", "",
              f"The same tape(s) were replayed {pb['n_runs']} times with every Binance leg circularly shifted by {', '.join(f'{x:g}' for x in sorted({x for x in pb['shifts'] if x is not None}))} s (each on every stage's tape) while the perps kept their clock, "
              "so the same-asset relationship is destroyed. Compare with §3 (150 ms, h = 5 s).", "",
              "| gap tier | real signals | placebo signals per replay | placebo gross | placebo hit | placebo net 9 bps | real gross | real − placebo gross (±, approx.) |", "|---|---|---|---|---|---|---|---|"]
        for tier in ("4", "8", "10", "15", "full_cost"):
            q = pb["tiers"][tier]
            r = res["tier_lat"][f"{tier}|0.15"]["gross"] if tier in TIERS else None
            diff = "–"
            if q["gross"]["n"] >= 5 and r and r["n"] >= 5:
                diff = f"{r['mean'] - q['gross']['mean']:+.2f} ± {math.hypot(r['se'], q['gross']['se']):.2f}"
            L.append(f"| {TIER_LABEL[tier]} | {r['n'] if r else '–'} | {q['per_run']:.1f} | {pm(q['gross']) if q['gross']['n'] else '–'} | {pct(q['gross']['hit']) if q['gross']['n'] else '–'} | "
                     f"{pm(q['net9']) if q['net9']['n'] else '–'} | {pm(r) if r and r['n'] else '–'} | {diff} |")
        L.append("")
    # ---- tradability
    tr = res["trade"]
    if tr:
        L += ["## 7. Could it have been traded? (signals ≥ 10 bps, 150 ms, h = 5 s)", "",
              f"* Entry-side touch size: median {tr['top_med']:,.0f} USD; {pct(tr['top_ge_1k'])} of signals show ≥ 1 000 USD, {pct(tr['top_ge_5k'])} ≥ 5 000 USD (the clip assumed for slippage is 1 000 USD).",
              f"* Perp spread at the signal: median {tr['spread_h_med']:.2f} bps; Binance spread: median {tr['binance_spread_med']:.2f} bps.",
              f"* Age of the perp quote at the signal: median {tr['hl_age_med']:.2f} s; {pct(tr['hl_age_gt1'])} older than 1 s (a quote that old is a resting order nobody has repriced – or a dead book).",
              f"* Direction: {tr['up']} up-moves (gross {pm(tr['gross_up'])}) and {tr['down']} down-moves (gross {pm(tr['gross_down'])}); the perp short leg additionally pays/receives funding, ignored here (seconds).", ""]
    L += ["Sensitivity to the touch-size filter (150 ms, h = 5 s; descriptive — the primary test uses ≥ 1 000 USD):", "",
          "| gap tier | min touch (USD) | signals | clusters | gross | net 9 bps |", "|---|---|---|---|---|---|"]
    for key, c in res["touch_sens"].items():
        tier, mt = key.split("|")
        if c["gross"]["n"]:
            L.append(f"| {TIER_LABEL[tier]} | {float(mt):,.0f} | {c['gross']['n']} | {c['gross']['k']} | {pm(c['gross'])} | {pm(c['net9'])} |")
    L.append("")
    lq = res["leader_quality"]
    L += ["**Exploratory (post hoc, not pre-registered): is the incomplete gap closure a leader-book-quality artefact?** The Binance leg's mid can jump on a wide, thin book without any price change; "
          "if that explained why the perp closes only part of the gap, closure would be much higher on tight Binance books. Gap ≥ 8 bps, h = 5 s, by the Binance spread at the signal:", "",
          "| latency | Binance spread (bps) | signals | clusters | mean gap | gross | closure (gross ÷ gap) | net 9 bps | median touch (USD) | median perp spread |", "|---|---|---|---|---|---|---|---|---|---|"]
    for key, c in lq.items():
        lat, lo, hi = key.split("|")
        if c["gross"]["n"]:
            rng = f"≤ {float(hi):g}" if float(lo) == 0 else (f"{float(lo):g}–{float(hi):g}" if float(hi) < 1e8 else f"> {float(lo):g}")
            L.append(f"| {float(lat) * 1000:.0f} ms | {rng} | {c['gross']['n']} | {c['gross']['k']} | {c['gap']:.1f} | {pm(c['gross'])} | {pct(c['closure'])} | {pm(c['net9'])} | {c['touch']:,.0f} | {c['spread_h']:.2f} |")
    cc = res["closure_curve"]
    L += ["", "Gap closure over the horizon (gap ≥ 8 bps, 150 ms): " + ", ".join(f"{h} s: {pct(c['closure'])}" for h, c in cc.items()) + ". A lagging perp would keep closing with the horizon; this one stops.", ""]
    L += ["## 8. By coin (gap ≥ 8 bps, 150 ms, h = 5 s; coins with ≥ 1 signal)", "", "| coin | signals ≥ 8 | signals ≥ 10 | events | mean gap | median perp spread | median touch (USD) | gross | net 9 bps |", "|---|---|---|---|---|---|---|---|---|"]
    for a in res["assets"][:25]:
        L.append(f"| {a['asset']} | {a['n8']} | {a['n10']} | {a['events']} | {a['gap']:.1f} | {a['spread_h']:.2f} | {a['top_med']:,.0f} | {pm(a['gross'])} | {pm(a['net9'])} |")
    L.append("")
    # ---- universe
    if real["unis"]:
        u = real["unis"][0]
        L += ["## 9. Universe", "", f"{len(u['pairs'])} pairs (BTC, ETH baseline + {sum(not p['baseline'] for p in u['pairs'])} mid-caps ranked by Hyperliquid 24 h volume): "
              + ", ".join(p["asset"] for p in u["pairs"] if not p["baseline"]) + ".", "",
              "Admission: Binance 24 h volume ≥ $1M, Hyperliquid 24 h volume ≥ $0.5M, Binance spread ≤ 15 bps, one Binance tick ≤ 10 bps of price; gold/stable tokens excluded. "
              "Left out: " + "; ".join(f"**{a}** {why}" for a, why in list(u["dropped"].items())[:40]) + ("; …" if len(u["dropped"]) > 40 else "") + ".", ""]
    return "\n".join(L)


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--runs", nargs="+", required=True)
    p.add_argument("--placebo", nargs="*", default=())
    p.add_argument("--out", default="docs/MIDCAP_CROSSVENUE.md")
    p.add_argument("--json", default="docs/live_runs/midcap_crossvenue.json")
    p.add_argument("--notes", default=None)
    a = p.parse_args(argv)
    runs = sorted({d for g in a.runs for d in glob.glob(g)})
    pls = sorted({d for g in a.placebo for d in glob.glob(g)})
    real = load_set(runs)
    pl = load_set(pls, lean=True) if pls else None
    res = analyse(real, pl)
    md = render_md(res, real, open(a.notes).read() if a.notes else "")
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    open(a.out, "w").write(md)
    if a.json:
        os.makedirs(os.path.dirname(a.json) or ".", exist_ok=True)
        json.dump(res, open(a.json, "w"), indent=1, default=float)
    print(f"wrote {a.out} ({len(md)} chars) from {len(runs)} run(s), {len(pls)} placebo run(s)")


if __name__ == "__main__":
    main()
