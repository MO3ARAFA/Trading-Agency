"""Phase 7 — pooled replay of the recorded tapes (and synthetic worlds) through *Pure Architecture B* on isolated risk sleeves.

    python -m quant_agency.p7_pool tapes/p4_tape_1.npz tapes/p5_tape_1.npz tapes/p6_tape_1.npz --out docs/live_runs/phase7_pooled_3tapes.md
    python -m quant_agency.p7_pool --synthetic --out docs/live_runs/phase7_synthetic_exits.md
"""
from __future__ import annotations

import argparse
import os
import tempfile
import types
from multiprocessing import Pool
from typing import Dict, List, Optional, Tuple

import numpy as np

from . import run_live as rl
from .sleeves import cluster_se
from .telemetry import md_table

BPS = 1e4
EXITS = ("fixed0.7", "fixed1.0", "wide1.5", "wide2.0", "adaptive", "trail")


def replay(tape: str, hl_maker_bps: float = 1.5, hl_taker_bps: float = 4.5, b_exit: Optional[str] = None, b_floor: Optional[float] = None) -> dict:
    a = types.SimpleNamespace(replay=tape, phase7=True, phase6=False, phase5=True, phase4=True, hl_maker_bps=hl_maker_bps, hl_taker_bps=hl_taker_bps,
                              snipe_model=None, status_every=1e12, markets=60, duration=600, fee_bps=7.5, maker_fee_bps=None, no_cross_venue=True,
                              review_interval=30.0, ceo_window=600.0, z_thr=3.0, hurdle_bps=1.0, latency_ms=150.0, scalp_gate=0.5, no_polymarket=False,
                              hold_frac=None, hl_work_s=None, pm_work_s=None, calm_z=None, impulse_z=None, b_floor=b_floor, no_mm=True, no_b=False,
                              b_exit=b_exit, sleeve_capital=None)
    cfg = rl.make_cfg(a)
    ag, _, t_end = rl.run_replay(a, cfg, tempfile.mkdtemp(prefix="p7_"))
    assert ag.mm is None, "Architecture A must not be instantiated in Phase 7"
    ag.hc.finalize(t_end)
    tag = os.path.basename(tape)
    rows = [dict(r, tape=tag, imp=f"{tag}:{r['imp']}") for r in ag.hc.results]
    return {"tape": tag, "dur": t_end - ag.t0, "rows": rows, "sleeves": [s.summary() for s in ag.sleeves.sleeves.values()],
            "events": [e.as_dict() for e in ag.sleeves.events()], "has_prints": bool(getattr(ag, "snipe_has_prints", False)),
            "main_cfo_trades": len(ag.engine.closed), "n_impulses": ag.hunter.n_impulses, "account_exit": cfg.hc.account_exit}


def _job(args):
    path, kw = args
    return replay(path, **kw)


def stat(rows: List[dict]) -> dict:
    f = [r for r in rows if r["outcome"] == "filled"]
    if not f:
        return {"n": 0}
    nb = np.array([r["net_bps"] for r in f])
    se = cluster_se(f)
    ex: Dict[str, int] = {}
    for r in f:
        k = r.get("trail_reason") or r["exit_reason"]
        ex[k] = ex.get(k, 0) + 1
    return {"n": len(f), "net_bps": float(nb.mean()), "se": se, "t": float(nb.mean() / se) if se > 0 else 0.0, "net_cents": float(np.mean([r["net_cents"] for r in f])),
            "net_usd": float(sum(r["net_usd"] for r in f)), "hit": float((nb > 0).mean()), "gross_bps": float(np.mean([r["gross_bps"] for r in f])),
            "passive": float(np.mean([r["exit_kind"] == "passive" for r in f])), "hold": float(np.mean([r["hold_s"] for r in f])), "exits": ex,
            "need_n": int(np.ceil(len(f) * (2.0 * se / abs(nb.mean())) ** 2)) if (se > 0 and nb.mean() > 0) else None}


def sel(res: List[dict], venue: str, xvar: str, model: Optional[str], floor: Optional[bool]) -> List[dict]:
    out = []
    for x in res:
        for r in x["rows"]:
            if r["venue"] != venue or r.get("xvar") != xvar or r["variant"] == "ACCOUNT":
                continue
            if model is not None and r["model"] != model:
                continue
            if floor is not None and bool(r.get("floor_ok")) != floor:
                continue
            out.append(r)
    return out


def n_signals(res: List[dict], venue: str, floor: Optional[bool] = None) -> int:
    ids = set()
    for x in res:
        for r in x["rows"]:
            if r["venue"] == venue and r["variant"] == "taker/taker" and (floor is None or bool(r.get("floor_ok")) == floor):
                ids.add((x["tape"], r["sid"]))
    return len(ids)


def fmt(s: dict, pm: bool) -> str:
    if not s.get("n"):
        return "-"
    return f"{s['net_cents']:+.2f}¢ ({s['net_bps']:+.0f} bps)" if pm else f"{s['net_bps']:+.2f} bps"


def table_for(res: List[dict], venue: str, pm: bool, model: str, subsets=(("floor-passed", True), ("all signals", None))) -> str:
    body = []
    for sub, fl in subsets:
        for x in EXITS + ("taker/taker",):
            rows = sel(res, venue, x, model if x != "taker/taker" else "strict", fl)
            s = stat(rows)
            if not s["n"]:
                continue
            top = ", ".join(f"{k}={v}" for k, v in sorted(s["exits"].items(), key=lambda kv: -kv[1])[:3])
            body.append([sub, x, s["n"], fmt(s, pm), f"±{s['se']:.0f}" if pm else f"±{s['se']:.2f}", f"{s['t']:+.2f}", f"{s['hit']*100:.0f}%", f"{s['net_usd']:+.2f}",
                         f"{s['gross_bps']:+.0f}" if pm else f"{s['gross_bps']:+.1f}", f"{s['passive']*100:.0f}%", f"{s['hold']:.1f}", top])
    return md_table(["subset", "exit", "fills", "net / fill", "cluster s.e. (bps)", "t", "hit", "net $", "gross bps", "passive exit", "hold s", "top exits"], body)


def preregister(res: List[dict]) -> Tuple[Optional[str], List[list]]:
    """Pre-registered rule: pooled Polymarket floor-passed `strict` net bps per fill (the one model every tape supports), n >= 30."""
    ranks = []
    for x in EXITS:
        s = stat(sel(res, "polymarket", x, "strict", True))
        ranks.append([x, s.get("n", 0), s.get("net_bps", float("nan")), s.get("se", float("nan")), s.get("t", float("nan"))])
    ok = [r for r in ranks if r[1] >= 30]
    best = max(ok, key=lambda r: r[2])[0] if ok else None
    return best, ranks


def sleeves_markdown(res: List[dict]) -> str:
    L: List[str] = []
    P = L.append
    P("## Isolated risk sleeves\n")
    body = []
    for x in res:
        for s in x["sleeves"]:
            body.append([x["tape"], s["sleeve"], s["state"], f"${s['equity']:,.2f}", s["round_trips"], s["closed_pnl"], s["n_halts"], s["events"]])
    P(md_table(["tape", "sleeve", "final state", "equity", "account round trips", "closed P&L $", "halts", "governor events"], body))
    ev = [e for x in res for e in x["events"]]
    if ev:
        P("```\n" + "\n".join(f"{e['sleeve']:<16} {e['kind']:<24} {e['from_state']}→{e['to_state']}  {e['reason']}" for e in ev) + "\n```\n")
    return "\n".join(L)


def pooled_markdown(res: List[dict], title: str, synthetic: bool = False) -> str:
    L: List[str] = []
    P = L.append
    models = [m for m in ("strict", "depletion", "trades") if any(r["model"] == m for x in res for r in x["rows"])]
    P(f"# {title}\n")
    P(f"Tapes: {', '.join(x['tape'] for x in res)} — total **{sum(x['dur'] for x in res):.0f} s**. Pure Architecture B (Architecture A is not instantiated), "
      f"floor 1.5× (spread + taker-in + maker-out fee) tagged on every shadow row with a *fixed* reference; HL fees 1.5 / 4.5 bps assumed. Every exit policy below ran on "
      f"**identical entries** (same signals, same IOC taker fill), so differences are the exit alone. t = mean / cluster-robust s.e. (clusters = BTC impulses).\n")
    P("Exit policies: `fixed0.7` = Phase 6 reference (maker TP at 0.7× the credited gap, 8–10 s window) · `fixed1.0` = maker TP at 1.0× · `wide1.5`/`wide2.0` = maker TP at 1.5×/2.0× with a "
      "20–25 s horizon · `adaptive` = start 1.0×, widen to 1.5× then 2.0× each time Binance extends the impulse by another 20 % beyond the signal level (cancel latency charged, "
      "re-post only after the cancel lands) · `trail` = no resting TP, stay while Binance velocity is supportive, exit passively at the touch when the venue has done the credited gap "
      "and Binance 1 s velocity has faded (or on a 40 % give-back of peak progress / a stall); reversal, adverse and time stops apply to all.\n")
    for venue, pm in (("polymarket", True), ("hyperliquid", False)):
        ns, nok = n_signals(res, venue), n_signals(res, venue, True)
        P(f"## {venue}\n")
        P(f"{ns} signals; **{nok} ({nok/max(ns,1)*100:.0f}%) clear the 1.5× floor**.\n")
        if nok == 0:
            P("No signal clears the floor: B abstains here. The 'all signals' rows show what the refused signals would have done.\n")
        for m in models:
            P(f"**fill model `{m}`**\n")
            P(table_for(res, venue, pm, m))
    best, ranks = preregister(res)
    P("## Pre-registered exit selection (made *before* the Phase 7 live session)\n")
    P("Rule: among the six exits, take the one with the highest pooled **Polymarket floor-passed net bps per fill under `strict`** (the one fill model all tapes support) with n ≥ 30. "
      "Ties/near-ties are not adjudicated: a difference smaller than its standard error is noise.\n")
    P(md_table(["exit", "floor-passed fills", "net bps / fill", "cluster s.e.", "t"], [[r[0], r[1], f"{r[2]:+.0f}", f"{r[3]:.0f}", f"{r[4]:+.2f}"] for r in ranks]))
    P(f"**Selected for the ACCOUNT: `{best}`**\n")
    if best:
        s = stat(sel(res, "polymarket", best, "strict", True))
        P(f"Sample-size check for `{best}` (Polymarket, floor-passed, strict): n = {s['n']}, mean {s['net_bps']:+.0f} bps, s.e. {s['se']:.0f}, t = {s['t']:+.2f}. "
          + (f"At the same mean and variance, |t| > 2 needs n ≈ **{s['need_n']}** floor-passed fills." if s.get("need_n") else "Mean is not positive: no sample size reaches t > 2.") + "\n")
    if any(x["rows"] and any(r["variant"] == "ACCOUNT" for r in x["rows"]) for x in res):
        P(sleeves_markdown(res))
    return "\n".join(L)


def synthetic_jobs(seeds: int, duration: float):
    from .sim_lag_world import WorldCfg, make_world, save_world
    out = {}
    for reg in ("quiet", "volatile"):
        paths = []
        for s in range(1, seeds + 1):
            d = tempfile.mkdtemp(prefix="w7_")
            p = os.path.join(d, f"{reg}_s{s}.npz")
            save_world(make_world(WorldCfg(regime=reg, duration_s=duration, D_inf=0.5, seed=700 + s)), p)
            paths.append(p)
        out[reg] = paths
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tapes", nargs="*")
    ap.add_argument("--synthetic", action="store_true")
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--duration", type=float, default=600.0)
    ap.add_argument("--procs", type=int, default=3)
    ap.add_argument("--hl-maker-bps", type=float, default=1.5)
    ap.add_argument("--title", default=None)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    md = ""
    if a.synthetic:
        worlds = synthetic_jobs(a.seeds, a.duration)
        with Pool(a.procs) as pool:
            for reg, paths in worlds.items():
                res = pool.map(_job, [(p, {}) for p in paths])
                md += pooled_markdown(res, f"Phase 7 — synthetic {reg} world, exit policies ({a.seeds} seeds x {a.duration:.0f} s; MECHANISM CHECK, not market evidence)", True) + "\n\n"
    else:
        with Pool(min(a.procs, len(a.tapes))) as pool:
            res = pool.map(_job, [(t, {"hl_maker_bps": a.hl_maker_bps}) for t in a.tapes])
        md = pooled_markdown(res, a.title or "Phase 7 — exit policies of Pure Architecture B, pooled replay of the recorded tapes")
    print(md)
    if a.out:
        with open(a.out, "w") as f:
            f.write(md)


if __name__ == "__main__":
    main()
