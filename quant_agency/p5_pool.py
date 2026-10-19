"""Pool the maker-sniper shadow variants across several recorded tapes (independent sessions).

    python -m quant_agency.p5_pool tapes/p4_tape_1.npz tapes/p5_tape_1.npz [--hl-maker-bps 1.0]

BTC-impulse ids are offset per tape so cluster-robust standard errors treat sessions as independent.
"""
from __future__ import annotations

import argparse
import types

import numpy as np

from .cfo_agent import _cluster_se
from .config import AgencyConfig
from .maker_sniper import MakerSniper
from .run_live import run_replay
from .telemetry import VORDER, md_table


def run(tapes, hl_maker=None, hl_taker=4.5, out="/tmp/p5pool"):
    allrows = []
    for k, tp in enumerate(tapes):
        cfg = AgencyConfig()
        cfg.cfo.fee_taker_bps = cfg.cfo.fee_maker_bps = 7.5
        cfg.cfo.max_spread_bps = 0.5
        a = types.SimpleNamespace(replay=tp, status_every=1e12, phase5=True, snipe_model=None, hl_maker_bps=hl_maker, hl_taker_bps=hl_taker)
        ag, _, t_end = run_replay(a, cfg, f"{out}/{k}")
        ag.sniper.finalize(t_end)
        for r in ag.sniper.results:
            r = dict(r)
            r["imp"] = k * 10_000_000 + r["imp"]
            r["tape"] = k
            allrows.append(r)
        ag.close()
    return allrows


def table(rows, venue, model, pm):
    body = []
    for v in VORDER:
        rs = [r for r in rows if r["venue"] == venue and r["model"] == model and r["variant"] == v and not r["account"]]
        if not rs:
            continue
        f = [r for r in rs if r["outcome"] == "filled"]
        att = [{"imp": r["imp"], "net": (r["net_bps"] if r["outcome"] == "filled" else 0.0)} for r in rs]
        se_a = _cluster_se(att, "net")
        se_f = _cluster_se(f, "net_bps") if len(f) > 1 else 0.0
        mk = [r["markout5_bps"] for r in f if np.isfinite(r["markout5_bps"])]
        row = [v, len(rs), len(f), f"{len(f)/len(rs)*100:.0f}%", f"{np.mean([r['net_bps'] for r in f]):+.1f}±{se_f:.1f}" if f else "-",
               f"{np.mean(att and [a['net'] for a in att]):+.2f}±{se_a:.2f}", f"{np.mean(mk):+.1f}" if mk else "-"]
        if pm:
            row.insert(5, f"{np.mean([r['net_cents'] for r in f]):+.2f}" if f else "-")
        body.append(row)
    head = ["variant", "attempts", "filled", "fill rate", "net bps / fill ±s.e.", "net bps / attempt ±s.e.", "5s markout after fill (bps)"]
    if pm:
        head.insert(5, "net ¢/share / fill")
    return md_table(head, body)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("tapes", nargs="+")
    p.add_argument("--hl-maker-bps", type=float, default=None)
    p.add_argument("--hl-taker-bps", type=float, default=4.5)
    a = p.parse_args()
    rows = run(a.tapes, a.hl_maker_bps, a.hl_taker_bps)
    sigs = {v: len({(r["tape"], r["sid"]) for r in rows if r["venue"] == v}) for v in ("hyperliquid", "polymarket")}
    print(f"pooled over {len(a.tapes)} sessions; signals: {sigs}; HL maker fee {a.hl_maker_bps if a.hl_maker_bps is not None else 'tape default'} bps\n")
    for venue, pm in (("hyperliquid", False), ("polymarket", True)):
        for model in ("strict", "depletion"):
            print(f"### {venue} — fill model `{model}`\n")
            print(table(rows, venue, model, pm))


if __name__ == "__main__":
    main()
