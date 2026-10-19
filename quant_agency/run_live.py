"""Live (or offline-sim) runner.

    python -m quant_agency.run_live --markets 60 --duration 600
    python -m quant_agency.run_live --sim --duration 300        # deterministic offline dry-run
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from .agency import Agency
from .config import AgencyConfig
from .market_watchers import MarketMeta, cross_venue_metas, discover_binance_universe
from .telemetry import build_report, summary_json


def parse():
    p = argparse.ArgumentParser()
    p.add_argument("--markets", type=int, default=60, help="Binance USDT alt markets to watch (BTC is extra)")
    p.add_argument("--duration", type=float, default=600.0)
    p.add_argument("--fee-bps", type=float, default=7.5, help="per-side taker/maker fee (bps)")
    p.add_argument("--maker-fee-bps", type=float, default=None)
    p.add_argument("--no-cross-venue", action="store_true")
    p.add_argument("--review-interval", type=float, default=30.0)
    p.add_argument("--ceo-window", type=float, default=600.0)
    p.add_argument("--z-thr", type=float, default=3.0)
    p.add_argument("--hurdle-bps", type=float, default=1.0)
    p.add_argument("--latency-ms", type=float, default=150.0)
    p.add_argument("--out", default="runs")
    p.add_argument("--tag", default="live")
    p.add_argument("--sim", action="store_true")
    p.add_argument("--record", default=None, help="save the live tape (npz) for deterministic replay")
    p.add_argument("--replay", default=None, help="replay a recorded tape through the full agency")
    p.add_argument("--status-every", type=float, default=15.0)
    return p.parse_args()


def make_cfg(a) -> AgencyConfig:
    cfg = AgencyConfig()
    cfg.cfo.fee_taker_bps = a.fee_bps
    cfg.cfo.fee_maker_bps = a.fee_bps if a.maker_fee_bps is None else a.maker_fee_bps
    cfg.cfo.safety_hurdle_bps = a.hurdle_bps
    cfg.cfo.latency_s = a.latency_ms / 1000.0
    cfg.hunter.z_thr = a.z_thr
    cfg.ceo.review_interval_s = a.review_interval
    cfg.ceo.window_s = a.ceo_window
    cfg.watchers.n_markets = a.markets
    cfg.watchers.cross_venue = not a.no_cross_venue
    return cfg


def status_line(ag: Agency, t: float, feeds) -> str:
    st = ag.oracle.state(t)
    cr = ag.cfo.report()
    fs = " ".join(f"{k}:{'up' if v.connected else 'DOWN'}/{v.msgs}" for k, v in feeds.items())
    return (f"[{t-ag.t0:6.0f}s] BTC {st.micro:,.2f} z1={st.z[0]:+.1f} z3={st.z[1]:+.1f} vol={st.vol_fast_bps:.2f}bps/√s | "
            f"signals={ag.hunter.n_signals} approved={cr['approved']} trades={len(ag.engine.closed)} "
            f"eq=${cr['equity']:,.2f} | CEO={ag.ceo.state.value} iv={len(ag.ceo.interventions)} | {fs}")


def finish(ag: Agency, t_end: float, info: dict, run_dir: str) -> str:
    ag.engine.flatten_all(t_end, "end_of_run")
    t_rep = t_end + ag.cfg.cfo.latency_s + 0.01
    ag.housekeeping(t_rep)
    ag.ceo.review(t_rep)
    ag.close()
    rep = build_report(ag, t_rep, info)
    with open(os.path.join(run_dir, "report.md"), "w") as f:
        f.write(rep)
    with open(os.path.join(run_dir, "summary.json"), "w") as f:
        json.dump(summary_json(ag, t_rep), f, indent=1, default=float)
    return rep


async def live(a, cfg: AgencyConfig, run_dir: str):
    import uvloop  # noqa: F401  (policy installed in main)
    from .feeds import FeedManager

    print("discovering Binance universe …", flush=True)
    bm = await discover_binance_universe(cfg.watchers.n_markets, cfg.watchers.exclude_bases,
                                         exclude_regex=cfg.watchers.exclude_regex)
    metas = list(bm)
    if cfg.watchers.cross_venue:
        metas += cross_venue_metas()
    perf = time.perf_counter
    ag = Agency(metas, cfg, out_dir=run_dir, t0=perf(), wall0=time.time())
    ag.hunter.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="calib")
    if a.record:
        ag.start_recording()
    print(f"watching {len(metas)} markets: {len(bm)-1} Binance alts + BTCUSDT oracle + {len(metas)-len(bm)} cross-venue", flush=True)
    fm = FeedManager(ag)
    tasks = fm.tasks()
    t_end = ag.t0 + a.duration
    try:
        next_status = ag.t0 + a.status_every
        while True:
            await asyncio.sleep(0.05)
            t = perf()
            ag.housekeeping(t)
            if t >= next_status:
                next_status += a.status_every
                print(status_line(ag, t, fm.stats), flush=True)
            if t >= t_end:
                break
        for st in fm.stats.values():
            st.up_at_end = st.connected
    finally:
        fm.stop.set()
        for tk in tasks:
            tk.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    if a.record:
        ag.save_tape(a.record)
        print(f"tape saved: {a.record} ({len(ag.tape[0])} events)", flush=True)
    return ag, fm, t_end


def run_replay(a, cfg: AgencyConfig, run_dir: str):
    import dataclasses
    import numpy as np
    z = np.load(a.replay, allow_pickle=False)
    metas = [MarketMeta(**m) for m in json.loads(str(z["metas"]))]
    t, idx, b, aa, bq, aq = z["t"], z["i"], z["b"], z["a"], z["bq"], z["aq"]
    ag = Agency(metas, cfg, out_dir=run_dir, t0=float(t[0]), wall0=time.time())
    last_hk = last_st = float(t[0])
    for k in range(t.shape[0]):
        tk, i = float(t[k]), int(idx[k])
        if i < 0:
            ag.on_trade(tk, float(b[k]), float(aa[k]), bool(bq[k]))
            continue
        ag.on_quote(i, tk, float(b[k]), float(aa[k]), float(bq[k]), float(aq[k]))
        if i == 0:
            ag.scan(tk)
        if tk - last_hk >= 0.05:
            ag.housekeeping(tk)
            last_hk = tk
        if tk - last_st >= a.status_every:
            last_st = tk
            print(status_line(ag, tk, {}), flush=True)
    return ag, {}, float(t[-1])


def run_sim(a, cfg: AgencyConfig, run_dir: str):
    from .sim import make_sim
    metas, ev, truth = make_sim(n_alts=min(a.markets, 60), duration_s=a.duration, seed=11)
    ag = Agency(metas, cfg, out_dir=run_dir, t0=ev[0][0], wall0=time.time())
    last = ev[0][0]
    for (t, i, b, aa, bq, aq) in ev:
        ag.on_quote(i, t, b, aa, bq, aq)
        ag.step(t)
        if t - last >= a.status_every:
            last = t
            print(status_line(ag, t, {}), flush=True)
    return ag, {}, ev[-1][0]


def main():
    a = parse()
    cfg = make_cfg(a)
    run_dir = os.path.join(a.out, f"{a.tag}_{time.strftime('%Y%m%d_%H%M%S')}")
    os.makedirs(run_dir, exist_ok=True)
    with open(os.path.join(run_dir, "config.json"), "w") as f:
        json.dump(cfg.to_dict(), f, indent=1, default=list)
    if a.replay:
        ag, feeds, t_end = run_replay(a, cfg, run_dir)
        mode = f"replay of {os.path.basename(a.replay)}"
    elif a.sim:
        ag, feeds, t_end = run_sim(a, cfg, run_dir)
        mode = "offline-sim"
    else:
        import uvloop
        uvloop.install()
        ag, fm, t_end = asyncio.run(live(a, cfg, run_dir))
        feeds, mode = fm.stats, "live"
    rep = finish(ag, t_end, {"mode": mode, "feeds": feeds}, run_dir)
    print(rep)
    print(f"\nartifacts: {run_dir}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
