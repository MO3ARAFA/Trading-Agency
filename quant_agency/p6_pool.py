"""Phase 6 Step 1 — replay recorded / synthetic tapes through Architecture A and B and pool the results.

    python -m quant_agency.p6_pool tapes/p4_tape_1.npz tapes/p5_tape_1.npz --out docs/live_runs/phase6_stepA_pooled.md
"""
from __future__ import annotations

import argparse
import os
import tempfile
import types
from typing import Dict, List, Optional

import numpy as np

from . import run_live as rl
from .maker_sniper import MakerSniper
from .pre_positioned_mm import PrePositionedMM
from .telemetry import md_table

BPS = 1e4


def replay(tape: str, hl_maker_bps: float = 1.5, hl_taker_bps: float = 4.5, calm_z: Optional[float] = None, impulse_z: Optional[float] = None,
           b_floor: Optional[float] = None, requote_hold: Optional[float] = None, cancel_latency: Optional[float] = None, quiet: bool = True) -> dict:
    """Run one tape through the full agency with both engines; return picklable rows + counters."""
    a = types.SimpleNamespace(replay=tape, phase6=True, phase5=True, phase4=True, hl_maker_bps=hl_maker_bps, hl_taker_bps=hl_taker_bps, snipe_model=None,
                              status_every=1e12, markets=60, duration=600, fee_bps=7.5, maker_fee_bps=None, no_cross_venue=True, review_interval=30.0,
                              ceo_window=600.0, z_thr=3.0, hurdle_bps=1.0, latency_ms=150.0, scalp_gate=0.5, no_polymarket=False, hold_frac=None,
                              hl_work_s=None, pm_work_s=None, calm_z=calm_z, impulse_z=impulse_z, b_floor=b_floor, no_mm=False, no_b=False)
    cfg = rl.make_cfg(a)
    if requote_hold is not None:
        cfg.mm.requote_hold_s = {"hyperliquid": requote_hold, "polymarket": requote_hold}
    if cancel_latency is not None:
        cfg.mm.cancel_latency_s = cancel_latency
        cfg.snipe.cancel_latency_s = cancel_latency
    out_dir = tempfile.mkdtemp(prefix="p6_")
    ag, _, t_end = rl.run_replay(a, cfg, out_dir)
    ag.mm.finalize(t_end)
    ag.hc.finalize(t_end)
    tag = os.path.basename(tape)
    mm_rows = [dict(r, tape=tag, imp=f"{tag}:{r['imp']}") for r in ag.mm.results]
    hc_rows = [dict(r, tape=tag, imp=f"{tag}:{r['imp']}") for r in ag.hc.results]
    mm_cnt = {}
    for venue in ("hyperliquid", "polymarket"):
        for v in ag.mm.variants:
            mm_cnt[(venue, v.name)] = ag.mm.counters(variant=v.name, venue=venue)
    return {"tape": tag, "dur": t_end - ag.t0, "mm": mm_rows, "hc": hc_rows, "mm_cnt": mm_cnt, "n_impulses": ag.mm.n_impulses,
            "calm": ag.mm.calm_frac[0] / max(ag.mm.calm_frac[1], 1e-9), "hc_signals": {v: len({r["sid"] for r in hc_rows if r["venue"] == v}) for v in ("hyperliquid", "polymarket")},
            "ceo": [iv.as_dict() for iv in ag.ceo.interventions if iv.kind.startswith(("MM_", "B_"))], "equity": ag.cfo.equity,
            "has_prints": bool(getattr(ag, "snipe_has_prints", False)), "mm_account": len(ag.mm.account_results), "hc_account": len(ag.hc.account_results)}


def sum_counters(res: List[dict], venue: str, variant: str) -> dict:
    tot: Dict[str, int] = {}
    for r in res:
        for k, v in r["mm_cnt"].get((venue, variant), {}).items():
            tot[k] = tot.get(k, 0) + v
    return tot


def csem(rows: List[dict], key: str = "net_bps", cluster: str = "imp") -> float:
    n = len(rows)
    if n < 2:
        return 0.0
    x = np.array([r[key] for r in rows], dtype=float)
    mu = x.mean()
    by: Dict[object, float] = {}
    for r, v in zip(rows, x):
        k = r.get(cluster, id(r))
        by[k] = by.get(k, 0.0) + (v - mu)
    cl = np.array(list(by.values()))
    return float(np.sqrt((cl ** 2).sum()) / n) if len(cl) > 1 else float(x.std(ddof=1) / np.sqrt(n))


def stat(rows: List[dict]) -> dict:
    if not rows:
        return {"n": 0}
    nb = np.array([r["net_bps"] for r in rows])
    return {"n": len(rows), "net_bps": float(nb.mean()), "se": csem(rows), "net_cents": float(np.mean([r["net_cents"] for r in rows])),
            "net_usd": float(sum(r["net_usd"] for r in rows)), "hit": float((nb > 0).mean()),
            "passive": float(np.mean([r["exit_kind"] == "passive" for r in rows])), "in_cancel": sum(1 for r in rows if r.get("entry_in_cancel") or r.get("exit_in_cancel")),
            "in_shield": sum(1 for r in rows if r.get("in_shield_cancel"))}


def fmt(s: dict, pm: bool) -> str:
    if not s.get("n"):
        return "-"
    return f"{s['net_cents']:+.2f}¢ ({s['net_bps']:+.0f}±{s['se']:.0f} bps)" if pm else f"{s['net_bps']:+.2f}±{s['se']:.2f} bps"


def a_rows(res: List[dict], variant: str, venue: str) -> List[dict]:
    return [r for x in res for r in x["mm"] if r["variant"] == variant and r["venue"] == venue]


def b_rows(res: List[dict], venue: str, variant: str, model: Optional[str] = None, floor: Optional[bool] = None) -> List[dict]:
    out = []
    for x in res:
        for r in x["hc"]:
            if r["venue"] != venue or r["variant"] != variant or r["outcome"] != "filled":
                continue
            if model is not None and r["model"] != model:
                continue
            if floor is not None and bool(r.get("floor_ok")) != floor:
                continue
            out.append(r)
    return out


def b_attempts(res: List[dict], venue: str, variant: str, model: Optional[str], floor: Optional[bool]) -> int:
    n = 0
    for x in res:
        for r in x["hc"]:
            if r["venue"] == venue and r["variant"] == variant and (model is None or r["model"] == model) and (floor is None or bool(r.get("floor_ok")) == floor):
                n += 1
    return n


def pooled_markdown(res: List[dict], title: str, hl_fee: float) -> str:
    L: List[str] = []
    P = L.append
    models = [m for m in ("strict", "depletion", "trades") if any(r["model"] == m for x in res for r in x["mm"])] or ["strict"]
    dur = sum(x["dur"] for x in res)
    P(f"# {title}\n")
    P(f"Tapes: {', '.join(x['tape'] for x in res)} — total **{dur:.0f} s**; BTC impulses {sum(x['n_impulses'] for x in res)}; calm fraction "
      f"{', '.join(f'{x['calm']*100:.0f}%' for x in res)}. HL maker fee assumed **{hl_fee} bps** (taker 4.5). Cluster s.e. is by BTC impulse across tapes. "
      f"Trade prints on tape: {', '.join(str(x['has_prints']) for x in res)}.\n")
    P("## Architecture A — pre-positioned quote maker\n")
    for venue, pm in (("hyperliquid", False), ("polymarket", True)):
        posted = sum(sum_counters(res, venue, v)["posted"] for v in ("shield/" + models[0],) if sum_counters(res, venue, v))
        gated = sum_counters(res, venue, "shield/" + models[0]).get("gated_out", 0)
        P(f"### {venue}\n")
        if posted == 0:
            P(f"No quote posted ({gated} gate rejections): round-trip economics (spread − 2·maker fee − adverse buffer − hurdle) never positive at maker fee {hl_fee} bps.\n" if not pm else "")
            continue
        body = []
        for m in models:
            for v in (f"shield/{m}", f"noshield/{m}"):
                s = stat(a_rows(res, v, venue))
                c = sum_counters(res, venue, v)
                body.append([v, s["n"], fmt(s, pm), f"{s.get('hit',0)*100:.0f}%" if s["n"] else "-", f"{s.get('net_usd',0):+.2f}" if s["n"] else "-",
                             f"{s.get('passive',0)*100:.0f}%" if s["n"] else "-", f"{s.get('in_shield', 0)} / {s.get('in_cancel', 0)}" if s["n"] else "-", c.get("posted", 0), c.get("shield_cancels", 0),
                             c.get("shield_flatten", 0)])
        P(md_table(["variant", "round trips", "net / trip", "hit", "net $", "passive exit", "fills in shield-cancel window / any cancel window", "quotes", "shield cancels", "shield flattens"], body))
        sa = stat(a_rows(res, "ACCOUNT", venue))
        if sa["n"]:
            P(f"ACCOUNT (CFO-gated, adaptive buffer): {sa['n']} trips, {fmt(sa, pm)}, net ${sa['net_usd']:+.2f}.\n")
    P("## Architecture B — high-conviction taker sniper\n")
    for venue, pm in (("hyperliquid", False), ("polymarket", True)):
        n_all = b_attempts(res, venue, "taker/taker", None, None)
        n_ok = b_attempts(res, venue, "taker/taker", None, True)
        P(f"### {venue}\n")
        P(f"{n_all} signals, **{n_ok} pass the absolute floor ({n_ok/max(n_all,1)*100:.0f}%)**, {n_all-n_ok} abstained.\n")
        body = []
        for m in models:
            for name, fl in (("B all signals (no floor)", None), ("B floor-passed", True), ("B floor-failed", False)):
                rows = b_rows(res, venue, "B/taker→maker+scratch", m, fl)
                s = stat(rows)
                if s["n"]:
                    sc = sum(1 for r in rows if r.get("scratched"))
                    rs = sum(1 for r in rows if r["exit_reason"] in ("reversal_stop", "adverse_stop"))
                    body.append([m, name, b_attempts(res, venue, "B/taker→maker+scratch", m, fl), s["n"], fmt(s, pm), f"{s['hit']*100:.0f}%", f"{s['net_usd']:+.2f}", f"{s['passive']*100:.0f}%", sc, rs])
        for name, fl in (("taker/taker (all)", None), ("taker/taker (floor-passed)", True)):
            s = stat(b_rows(res, venue, "taker/taker", None, fl))
            if s["n"]:
                body.append(["-", name, b_attempts(res, venue, "taker/taker", None, fl), s["n"], fmt(s, pm), f"{s['hit']*100:.0f}%", f"{s['net_usd']:+.2f}", "0%", 0, 0])
        P(md_table(["fill model", "variant", "attempts", "filled", "net / fill", "hit", "net $", "passive exit", "scratched", "stopped"], body))
        sacc = stat([r for x in res for r in x["hc"] if r["venue"] == venue and r["variant"] == "ACCOUNT" and r["outcome"] == "filled"])
        if sacc["n"]:
            P(f"ACCOUNT: {sacc['n']} fills, {fmt(sacc, pm)}, net ${sacc['net_usd']:+.2f}.\n")
    ivs = [iv for x in res for iv in x["ceo"]]
    if ivs:
        P("## CEO Phase 6 interventions in these replays\n")
        P("```\n" + "\n".join(f"{iv['wall']} {iv['kind']:<24} {iv['target']:<12} {iv['reason']}" for iv in ivs) + "\n```\n")
    return "\n".join(L)


def _sweep_job(a):
    tape, kw = a
    return kw, replay(tape, **kw)


def sweeps_markdown(tapes: List[str], procs: int = 3) -> str:
    """Counterfactuals on the real tapes: (1) how fast would the cancel have to be for the shield to matter, (2) the B floor multiple."""
    from multiprocessing import Pool
    L: List[str] = []
    P = L.append
    jobs = [(tapes[-1], {"cancel_latency": c}) for c in (0.0, 0.05, 0.15, 0.30)]
    jobs += [(t, {}) for t in tapes[:-1]] if False else []
    with Pool(procs) as pool:
        out = pool.map(_sweep_job, jobs)
    P("## Sweep 1 — cancel latency (Polymarket, the last tape; shield vs identical policy without shield)\n")
    P("The order latency stays 150 ms; only the cancel latency changes. This answers whether the shield fails because the *cancel is too slow* (a latency problem we could engineer away) or because quoting on a lagging venue is adverse even when cancels are instant.\n")
    body = []
    for kw, res in out:
        for model in ("strict", "trades"):
            sh, ns = stat(a_rows([res], f"shield/{model}", "polymarket")), stat(a_rows([res], f"noshield/{model}", "polymarket"))
            if not sh["n"] and not ns["n"]:
                continue
            body.append([f"{kw['cancel_latency']*1000:.0f} ms", model, f"{sh['n']} / {ns['n']}", f"{fmt(sh, True)} / {fmt(ns, True)}",
                         f"{sh.get('net_usd', 0):+.1f} / {ns.get('net_usd', 0):+.1f}", f"{sh.get('in_shield', 0)}"])
    P(md_table(["cancel latency", "fill model", "trips (shield / none)", "net/trip (shield / none)", "net $ (shield / none)", "shield trips filled inside the cancel window"], body))
    return "\n".join(L)


def floor_sweep_markdown(res: List[dict]) -> str:
    L: List[str] = []
    P = L.append
    P("## Sweep 2 — B's absolute floor multiple (post-hoc on the same shadow rows; the predicted move / floor ratio is stored at 1.5x)\n")
    body = []
    for venue, pm in (("hyperliquid", False), ("polymarket", True)):
        base = [r for x in res for r in x["hc"] if r["venue"] == venue and r["variant"] == "B/taker→maker+scratch" and r["outcome"] == "filled" and r["model"] == ("trades" if any(
            q["model"] == "trades" for q in x["hc"]) else "strict")]
        allsig = [r for x in res for r in x["hc"] if r["venue"] == venue and r["variant"] == "taker/taker"]
        for mult in (0.0, 1.0, 1.5, 2.0, 3.0):
            rows = [r for r in base if r.get("ratio", 0) * 1.5 >= mult]
            n_sig = sum(1 for r in allsig if r.get("ratio", 0) * 1.5 >= mult)
            s = stat(rows)
            body.append([venue, f"{mult:g}x" if mult else "none", n_sig, s["n"], fmt(s, pm), f"{s.get('hit', 0)*100:.0f}%" if s["n"] else "-", f"{s.get('net_usd', 0):+.2f}" if s["n"] else "-"])
    P(md_table(["venue", "floor", "signals passing", "fills", "net / fill", "hit", "net $"], body))
    return "\n".join(L)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("tapes", nargs="+")
    p.add_argument("--hl-maker-bps", type=float, default=1.5)
    p.add_argument("--out", default=None)
    p.add_argument("--title", default="Phase 6 Step 1 — pooled tape replay")
    p.add_argument("--sweeps", action="store_true")
    a = p.parse_args()
    res = [replay(t, hl_maker_bps=a.hl_maker_bps) for t in a.tapes]
    md = pooled_markdown(res, a.title, a.hl_maker_bps)
    md += "\n" + floor_sweep_markdown(res)
    if a.sweeps:
        md += "\n" + sweeps_markdown(a.tapes)
    print(md)
    if a.out:
        with open(a.out, "w") as f:
            f.write(md)


if __name__ == "__main__":
    main()
