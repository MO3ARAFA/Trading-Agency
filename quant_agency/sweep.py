"""Replay one recorded live tape under several cost / threshold settings and compare.

    python -m quant_agency.sweep tapes/live_tape_1.npz --fees 7.5 4.5 1 0 --z 3 2.5
"""
from __future__ import annotations

import argparse
import itertools
import json
import os
import time
from types import SimpleNamespace

from .config import AgencyConfig
from .run_live import run_replay
from .telemetry import md_table


def one(tape: str, fee: float, z: float, hurdle: float, out: str, ceo: bool = True, lat: float = 0.15):
    cfg = AgencyConfig()
    cfg.cfo.fee_taker_bps = cfg.cfo.fee_maker_bps = fee
    cfg.cfo.safety_hurdle_bps = hurdle
    cfg.hunter.z_thr = z
    cfg.cfo.latency_s = lat
    cfg.ceo.review_interval_s = 30.0 if ceo else 1e12
    ag, _, t_end = run_replay(SimpleNamespace(replay=tape, status_every=1e12), cfg, out)
    ag.engine.flatten_all(t_end)
    ag.housekeeping(t_end + 1.0)
    ag.close()
    return ag


def main():
    p = argparse.ArgumentParser()
    p.add_argument("tape")
    p.add_argument("--fees", type=float, nargs="+", default=[7.5, 4.5, 1.0, 0.0])
    p.add_argument("--z", type=float, nargs="+", default=[3.0])
    p.add_argument("--hurdle", type=float, default=1.0)
    p.add_argument("--latency", type=float, nargs="+", default=[0.15], help="assumed order latency (s)")
    p.add_argument("--out", default="runs/sweep")
    a = p.parse_args()
    rows = []
    for fee, z, lat in itertools.product(a.fees, a.z, a.latency):
        t0 = time.time()
        d = os.path.join(a.out, f"fee{fee:g}_z{z:g}_lat{lat*1000:.0f}")
        ag = one(a.tape, fee, z, a.hurdle, d, lat=lat)
        tb = ag.cfo.markouts.table(now=ag.last_t)
        ta = ag.cfo.markouts.table(cohort="approved", now=ag.last_t)
        cr = ag.cfo.report()
        cl = ag.engine.closed
        rows.append([f"{fee:g}", f"{z:g}", f"{lat*1000:.0f}", ag.hunter.n_signals, cr["approved"], len(cl),
                     f"{sum(t.net_pnl_usd for t in cl):+.2f}",
                     f"{tb[1.0]['gross']:+.2f}", f"{tb[5.0]['gross']:+.2f}", f"{tb[5.0]['net']:+.2f}", f"{tb[30.0]['gross']:+.2f}",
                     f"{ta[5.0]['net']:+.2f}" if ta[5.0]["n"] else "-", len(ag.ceo.interventions), ag.ceo.state.value,
                     f"{time.time()-t0:.0f}s"])
        print(md_table(["fee bps/side", "z", "lat ms", "signals", "approved", "closed", "paper PnL $", "gross@1s", "gross@5s", "net@5s (all, taker)",
                        "gross@30s", "net@5s approved", "CEO interventions", "CEO state", "wall"], rows[-1:]).splitlines()[-1], flush=True)
    head = ["fee bps/side", "z", "lat ms", "signals", "approved", "closed", "paper PnL $", "gross@1s", "gross@5s", "net@5s (all, taker)",
            "gross@30s", "net@5s approved", "CEO interventions", "CEO state", "wall"]
    table = md_table(head, rows)
    print("\n" + table)
    with open(os.path.join(a.out, "sweep.md"), "w") as f:
        f.write(table)


if __name__ == "__main__":
    main()
