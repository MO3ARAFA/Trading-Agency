"""Phase 6 Step 1b — controlled synthetic stress test: quiet vs volatile regimes x informed-taker delay (the cancel-vs-taker race).

    python -m quant_agency.p6_stress --out docs/live_runs/phase6_stepA_stress.md --json docs/live_runs/phase6_stepA_stress.json
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from multiprocessing import Pool
from typing import Dict, List

import numpy as np

from . import p6_pool as pp
from .sim_lag_world import WorldCfg, make_world, save_world
from .telemetry import md_table


def _job(args):
    name, wcfg, kw = args
    d = tempfile.mkdtemp(prefix="w_")
    path = os.path.join(d, name + ".npz")
    save_world(make_world(wcfg), path)
    res = pp.replay(path, **kw)
    os.remove(path)
    return name, res


def run(configs: Dict[str, tuple], procs: int = 3) -> Dict[str, List[dict]]:
    jobs = []
    for cell, (wcfgs, kw) in configs.items():
        for k, w in enumerate(wcfgs):
            jobs.append((f"{cell}#{k}", w, kw))
    out: Dict[str, List[dict]] = {c: [] for c in configs}
    with Pool(procs) as pool:
        for name, res in pool.imap_unordered(_job, jobs):
            out[name.rsplit("#", 1)[0]].append(res)
    return out


def cell_summary(res: List[dict]) -> dict:
    d: dict = {}
    for venue, pm in (("polymarket", True), ("hyperliquid", False)):
        for model in ("strict", "trades"):
            sh, ns = pp.stat(pp.a_rows(res, f"shield/{model}", venue)), pp.stat(pp.a_rows(res, f"noshield/{model}", venue))
            d[f"A|{venue}|{model}"] = {"shield": sh, "noshield": ns}
        n_all = pp.b_attempts(res, venue, "taker/taker", None, None)
        n_ok = pp.b_attempts(res, venue, "taker/taker", None, True)
        d[f"B|{venue}"] = {"signals": n_all, "pass": n_ok,
                           "all": pp.stat(pp.b_rows(res, venue, "B/taker→maker+scratch", "trades", None)),
                           "gated": pp.stat(pp.b_rows(res, venue, "B/taker→maker+scratch", "trades", True)),
                           "failed": pp.stat(pp.b_rows(res, venue, "B/taker→maker+scratch", "trades", False)),
                           "tt_all": pp.stat(pp.b_rows(res, venue, "taker/taker", None, None)),
                           "tt_gated": pp.stat(pp.b_rows(res, venue, "taker/taker", None, True))}
        d[f"ACCOUNT|{venue}"] = {"A": pp.stat(pp.a_rows(res, "ACCOUNT", venue)),
                                 "B": pp.stat([r for x in res for r in x["hc"] if r["venue"] == venue and r["variant"] == "ACCOUNT" and r["outcome"] == "filled"])}
    d["n_impulses"] = sum(x["n_impulses"] for x in res)
    d["calm"] = float(np.mean([x["calm"] for x in res]))
    d["dur"] = sum(x["dur"] for x in res)
    return d


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--seeds", type=int, default=3)
    p.add_argument("--duration", type=float, default=600.0)
    p.add_argument("--procs", type=int, default=3)
    p.add_argument("--out", default=None)
    p.add_argument("--json", default=None)
    a = p.parse_args()
    D_INF = (0.05, 0.15, 0.5, 1.0)
    configs: Dict[str, tuple] = {}
    for reg in ("quiet", "volatile"):
        for d in D_INF:
            configs[f"{reg}|D_inf={d}"] = ([WorldCfg(regime=reg, duration_s=a.duration, D_inf=d, seed=100 * s + int(d * 100)) for s in range(1, a.seeds + 1)], {})
    # HL economics need a book wider than HL's real 1-tick: 4 ticks, and a maker fee of 0 / 1 bp (the brief's "~1 bp")
    for reg in ("quiet", "volatile"):
        for fee in (0.0, 1.0):
            configs[f"{reg}|HLwide|fee={fee}"] = ([WorldCfg(regime=reg, duration_s=a.duration, D_inf=0.5, hl_spread_ticks=4, seed=900 + s) for s in range(1, a.seeds + 1)],
                                                  {"hl_maker_bps": fee})
    out = run(configs, a.procs)
    summ = {k: cell_summary(v) for k, v in out.items()}
    if a.json:
        with open(a.json, "w") as f:
            json.dump(summ, f, indent=1, default=float)
    md = stress_markdown(summ, a)
    print(md)
    if a.out:
        with open(a.out, "w") as f:
            f.write(md)


def _c(s: dict, pm: bool) -> str:
    if not s.get("n"):
        return "-"
    return f"{s['net_cents']:+.2f}¢" if pm else f"{s['net_bps']:+.1f}bp"


def stress_markdown(summ: dict, a) -> str:
    L: List[str] = []
    P = L.append
    P("# Phase 6 Step 1b — synthetic lag-world stress test\n")
    P(f"Open-loop synthetic worlds in the live-tape format (Binance BTC oracle + Hyperliquid-like perps + Polymarket-like digitals + trade prints), {a.seeds} seeds x {a.duration:.0f} s per cell, "
      "replayed through the *unchanged* agency (hunter, PM watcher, CFO, CEO, both engines). `quiet` = 1.5–4 bp impulses every ~12 s; `volatile` = 10–30 bp impulses every ~9 s and 3x the diffusion. "
      "The lagging venue's makers reprice 0.8 s (HL) / 1.5 s (PM) after Binance; **informed takers** hit the stale quotes `D_inf` seconds after the Binance move completes (80 % of qualifying impulses) — "
      "the cancel-vs-taker race. Our order and cancel latencies are fixed at 150 ms each, so the shield can only protect a quote when (detection + 150 ms) < D_inf. "
      "Uninformed flow is Poisson at the touch. Fill model shown: `trades` (queue-aware, prints) unless stated.\n")
    P("## Architecture A on Polymarket-like digitals (net ¢ per round trip, shield vs the identical policy without the shield)\n")
    body = []
    for reg in ("quiet", "volatile"):
        for d in (0.05, 0.15, 0.5, 1.0):
            c = summ[f"{reg}|D_inf={d}"]
            r = c["A|polymarket|trades"]
            rs = c["A|polymarket|strict"]
            sh, ns = r["shield"], r["noshield"]
            body.append([reg, d, c["n_impulses"], f"{c['calm']*100:.0f}%", f"{sh.get('n',0)} / {ns.get('n',0)}", f"{_c(sh,True)} / {_c(ns,True)}",
                         f"{(sh.get('net_cents',0)-ns.get('net_cents',0)):+.2f}¢" if sh.get("n") and ns.get("n") else "-", f"{sh.get('net_usd',0):+.1f} / {ns.get('net_usd',0):+.1f}",
                         f"{_c(rs['shield'],True)} / {_c(rs['noshield'],True)}", f"{sh.get('in_shield',0)} of {sh.get('n',0)}"])
    P(md_table(["regime", "D_inf (s)", "BTC impulses", "calm", "trips (shield / none)", "net/trip (shield / none)", "shield value", "net $ (shield / none)", "strict-model net/trip (shield / none)", "shield trips filled inside the shield's cancel window"], body))
    P("## Architecture A on Hyperliquid-like perps (4-tick-wide book, D_inf 0.5 s; the real HL book is 1 tick = 0.04–1.7 bp and is gated out)\n")
    body = []
    for reg in ("quiet", "volatile"):
        for fee in (0.0, 1.0):
            c = summ[f"{reg}|HLwide|fee={fee}"]
            r = c["A|hyperliquid|trades"]
            sh, ns = r["shield"], r["noshield"]
            body.append([reg, fee, f"{sh.get('n',0)} / {ns.get('n',0)}", f"{_c(sh,False)} / {_c(ns,False)}", f"{sh.get('net_usd',0):+.2f} / {ns.get('net_usd',0):+.2f}",
                         f"{sh.get('passive',0)*100:.0f}% / {ns.get('passive',0)*100:.0f}%" if sh.get("n") and ns.get("n") else "-"])
    P(md_table(["regime", "HL maker fee (bp)", "trips (shield / none)", "net/trip (shield / none)", "net $", "passive exit"], body))
    P("## Architecture B on Polymarket-like digitals (net per fill; `trades` model)\n")
    body = []
    for reg in ("quiet", "volatile"):
        for d in (0.05, 0.15, 0.5, 1.0):
            c = summ[f"{reg}|D_inf={d}"]
            b = c["B|polymarket"]
            body.append([reg, d, b["signals"], f"{b['pass']} ({b['pass']/max(b['signals'],1)*100:.0f}%)", _c(b["gated"], True) + f" (n={b['gated'].get('n',0)}, hit {b['gated'].get('hit',0)*100:.0f}%)" if b["gated"].get("n") else "abstains",
                         _c(b["all"], True) + f" (n={b['all'].get('n',0)})" if b["all"].get("n") else "-", _c(b["tt_all"], True) if b["tt_all"].get("n") else "-",
                         f"{b['gated'].get('net_usd',0):+.1f} / {b['all'].get('net_usd',0):+.1f}"])
    P(md_table(["regime", "D_inf (s)", "signals", "pass floor", "B floor-passed", "B no floor", "taker/taker (all)", "net $ (floor-passed / no floor)"], body))
    P("## Architecture B on Hyperliquid-like perps (1-tick book; net bps per fill)\n")
    body = []
    for reg in ("quiet", "volatile"):
        for d in (0.05, 0.15, 0.5, 1.0):
            c = summ[f"{reg}|D_inf={d}"]
            b = c["B|hyperliquid"]
            body.append([reg, d, b["signals"], f"{b['pass']} ({b['pass']/max(b['signals'],1)*100:.0f}%)", _c(b["gated"], False) + f" (n={b['gated'].get('n',0)}, hit {b['gated'].get('hit',0)*100:.0f}%)" if b["gated"].get("n") else "abstains",
                         _c(b["all"], False) + f" (n={b['all'].get('n',0)})" if b["all"].get("n") else "-", _c(b["tt_all"], False) if b["tt_all"].get("n") else "-"])
    P(md_table(["regime", "D_inf (s)", "signals", "pass floor", "B floor-passed", "B no floor", "taker/taker (all)"], body))
    P("## CFO-governed ACCOUNT engines in the same worlds\n")
    body = []
    for key in sorted(summ):
        c = summ[key]
        a_pm, b_pm, a_hl, b_hl = c["ACCOUNT|polymarket"]["A"], c["ACCOUNT|polymarket"]["B"], c["ACCOUNT|hyperliquid"]["A"], c["ACCOUNT|hyperliquid"]["B"]
        body.append([key, a_pm.get("n", 0), f"{a_pm.get('net_usd',0):+.1f}", b_pm.get("n", 0), f"{b_pm.get('net_usd',0):+.1f}", a_hl.get("n", 0), f"{a_hl.get('net_usd',0):+.1f}", b_hl.get("n", 0), f"{b_hl.get('net_usd',0):+.1f}"])
    P(md_table(["world", "A-PM trips", "A-PM $", "B-PM fills", "B-PM $", "A-HL trips", "A-HL $", "B-HL fills", "B-HL $"], body))
    return "\n".join(L)


if __name__ == "__main__":
    main()
