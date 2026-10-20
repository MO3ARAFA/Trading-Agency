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
from .telemetry import build_report, build_report_p4, build_report_p5, build_report_p6, build_report_p7, summary_json


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
    p.add_argument("--phase4", action="store_true", help="Venue & microstructure specialization: scalp universe, cross-venue, arb, Polymarket")
    p.add_argument("--scalp-gate", type=float, default=0.5, help="hard max live spread (bps) for directional trades (phase4)")
    p.add_argument("--no-polymarket", action="store_true")
    p.add_argument("--no-cross-venue-p4", action="store_true")
    p.add_argument("--phase5", action="store_true", help="Queue-aware maker sniper on Hyperliquid + Polymarket (Binance BTC oracle only)")
    p.add_argument("--hl-maker-bps", type=float, default=1.5, help="Hyperliquid maker fee per side (bps); public base tier 1.5")
    p.add_argument("--hl-taker-bps", type=float, default=4.5)
    p.add_argument("--hold-frac", type=float, default=None, help="shield: cancel when < this fraction of the impulse is intact")
    p.add_argument("--hl-work-s", type=float, default=None)
    p.add_argument("--pm-work-s", type=float, default=None)
    p.add_argument("--snipe-model", default=None, help="fill model of the CFO-accounted attempt: strict|depletion|trades")
    p.add_argument("--phase6", action="store_true", help="Architecture A (pre-positioned quote maker + oracle cancel-shield) and B (high-conviction taker sniper) side by side")
    p.add_argument("--phase7", action="store_true", help="Pure Architecture B on isolated per-venue risk sleeves (Architecture A shelved)")
    p.add_argument("--b-exit", default=None, help="exit policy of the ACCOUNT: fixed0.7|fixed1.0|wide1.5|wide2.0|adaptive|trail")
    p.add_argument("--sleeve-capital", type=float, default=None)
    p.add_argument("--stop-fills", type=int, default=0, help="Phase 8 stopping rule: stop when prior-fills + live floor-passed Polymarket fills >= this")
    p.add_argument("--prior-fills", type=int, default=0)
    p.add_argument("--stop-file", default=None, help="end the capture gracefully (tape saved, positions finalised) as soon as this file exists (used by regime_daemon)")
    p.add_argument("--count-file", default=None, help="write {floor_fills, elapsed_s} here every ~2 s (used by regime_daemon)")
    p.add_argument("--calm-z", type=float, default=None, help="A: quote only while every fast-horizon |BTC Z| is below this")
    p.add_argument("--impulse-z", type=float, default=None, help="A: cancel the vulnerable side at this Z")
    p.add_argument("--b-floor", type=float, default=None, help="B: absolute floor multiple of (spread + taker-in + maker-out fee)")
    p.add_argument("--no-mm", action="store_true")
    p.add_argument("--no-b", action="store_true")
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
    if getattr(a, "phase7", False):
        from .high_conviction_sniper import parse_exit
        a.phase5 = True                                   # same universe; Architecture A is not instantiated at all
        cfg.mm.enabled = False
        cfg.cfo.mm_enabled = False
        cfg.hc.enabled = True
        if a.b_exit:
            cfg.hc.account_exit = a.b_exit
        if a.b_floor is not None:
            cfg.cfo.b_floor_mult = a.b_floor
        if a.sleeve_capital:
            cfg.hc.sleeve_capital = a.sleeve_capital
        cfg.cfo.b_tp_mult = parse_exit(cfg.hc.account_exit)[1]
    if getattr(a, "phase6", False):
        a.phase5 = True                                   # same universe (BTC oracle + Hyperliquid + Polymarket), different engines
        cfg.mm.enabled = not a.no_mm
        cfg.hc.enabled = not a.no_b
        if a.calm_z is not None:
            cfg.mm.calm_z = a.calm_z
        if a.impulse_z is not None:
            cfg.mm.impulse_z = a.impulse_z
        if a.b_floor is not None:
            cfg.cfo.b_floor_mult = a.b_floor
        cfg.cfo.mm_enabled = cfg.mm.enabled
        cfg.cfo.b_enabled = cfg.hc.enabled
    if a.phase5:
        a.phase4 = True
        if a.hold_frac is not None:
            cfg.snipe.hold_frac = a.hold_frac
        if a.hl_work_s is not None:
            cfg.snipe.work_s["hyperliquid"] = a.hl_work_s
        if a.pm_work_s is not None:
            cfg.snipe.work_s["polymarket"] = a.pm_work_s
        cfg.snipe.enabled = True
        cfg.poly.enabled = not a.no_polymarket
        cfg.cfo.max_spread_bps = a.scalp_gate
    if a.phase4:
        cfg.cfo.max_spread_bps = a.scalp_gate            # hard microstructure gate (CFO); wider signals are shadow-tracked only
        cfg.poly.enabled = not a.no_polymarket
    return cfg


def status_line(ag: Agency, t: float, feeds) -> str:
    st = ag.oracle.state(t)
    cr = ag.cfo.report()
    fs = " ".join(f"{k}:{'up' if v.connected else 'DOWN'}/{v.msgs}" for k, v in feeds.items())
    return (f"[{t-ag.t0:6.0f}s] BTC {st.micro:,.2f} z1={st.z[0]:+.1f} z3={st.z[1]:+.1f} vol={st.vol_fast_bps:.2f}bps/√s | "
            f"signals={ag.hunter.n_signals} approved={cr['approved']} trades={len(ag.engine.closed)} "
            f"eq=${cr['equity']:,.2f} | CEO={ag.ceo.state.value} iv={len(ag.ceo.interventions)} | {fs}")


def attach_phase6(ag: Agency, cfg: AgencyConfig, a, has_prints: bool) -> None:
    from .high_conviction_sniper import HighConvictionSniper
    from .pre_positioned_mm import PrePositionedMM
    models = ("strict", "depletion", "trades") if has_prints else ("strict", "depletion")
    acct = getattr(a, "snipe_model", None) or ("trades" if has_prints else "strict")
    cfg.mm.shadow_models, cfg.mm.account_model = models, acct
    cfg.hc.shadow_models, cfg.hc.account_model = models, acct
    cfg.hc.exit_variants = ("fixed0.7",)                        # Phase 6 = the reference exit only
    if cfg.mm.enabled:
        ag.attach_mm(PrePositionedMM(ag, cfg.mm))
    if cfg.hc.enabled:
        ag.attach_hc(HighConvictionSniper(ag, cfg.hc))


def attach_phase7(ag: Agency, cfg: AgencyConfig, a, has_prints: bool) -> None:
    from .high_conviction_sniper import HighConvictionSniper
    from .sleeves import SleeveSet
    models = ("strict", "depletion", "trades") if has_prints else ("strict", "depletion")
    cfg.hc.shadow_models = models
    cfg.hc.account_model = getattr(a, "snipe_model", None) or ("trades" if has_prints else "strict")
    sleeves = SleeveSet(ag.book, cfg.cfo, capital=cfg.hc.sleeve_capital, poly_min_ttl=cfg.poly.min_ttl_s)
    ag.attach_sleeves(sleeves)
    ag.attach_hc(HighConvictionSniper(ag, cfg.hc, sleeves), govern=False)


def finish(ag: Agency, t_end: float, info: dict, run_dir: str) -> str:
    ag.engine.flatten_all(t_end, "end_of_run")
    if ag.sniper is not None:
        ag.sniper.finalize(t_end)
    if ag.mm is not None:
        ag.mm.finalize(t_end)
    if ag.hc is not None:
        ag.hc.finalize(t_end)
    t_rep = t_end + ag.cfg.cfo.latency_s + 0.01
    ag.housekeeping(t_rep)
    ag.ceo.review(t_rep)
    ag.close()
    rep = (build_report_p7 if info.get("phase7") else build_report_p6 if info.get("phase6") else build_report_p5 if info.get("phase5") else (build_report_p4 if info.get("phase4") else build_report))(ag, t_rep, info)
    with open(os.path.join(run_dir, "report.md"), "w") as f:
        f.write(rep)
    with open(os.path.join(run_dir, "summary.json"), "w") as f:
        json.dump(summary_json(ag, t_rep), f, indent=1, default=float)
    return rep


async def live(a, cfg: AgencyConfig, run_dir: str):
    import uvloop  # noqa: F401  (policy installed in main)
    from .feeds import FeedManager

    pm_specs, pm_tokens, pm_metas = {}, {}, []
    if a.phase5:
        import aiohttp
        from . import polymarket_watcher as pmw
        from .venues import cross_venue_metas as p4_cross
        print("discovering phase-5 universe (BTC oracle, Hyperliquid perps, Polymarket) …", flush=True)
        sess = aiohttp.ClientSession(trust_env=True, timeout=aiohttp.ClientTimeout(total=40), headers={"User-Agent": "Mozilla/5.0"})
        try:
            if cfg.poly.enabled:
                pm_metas, pm_specs, pm_tokens = await pmw.discover(time.time(), a.duration + 600.0, cfg.poly, sess)
                await pmw.binance_ref_prices(sess, pm_specs, time.time())
        finally:
            await sess.close()
        hl = [m for m in p4_cross(venues=("hyperliquid",), deribit_assets=())]
        for m in hl:
            m.fee_maker_bps, m.fee_taker_bps = a.hl_maker_bps, a.hl_taker_bps
        bm = [MarketMeta("BTCUSDT", "binance", "BTCUSDT", "BTC", tick=0.01, step=1e-5, min_notional=5.0, asset="BTC")]
        metas = bm + hl + pm_metas
        xm = hl
        print(f"oracle: 1 | hyperliquid: {len(hl)} | polymarket: {len(pm_metas)}", flush=True)
    elif a.phase4:
        import aiohttp
        from .venues import cross_venue_metas as p4_cross, discover_scalp_universe
        from . import polymarket_watcher as pmw
        print("discovering phase-4 universe (Binance scalp set, cross-venue, Polymarket) …", flush=True)
        sess = aiohttp.ClientSession(trust_env=True, timeout=aiohttp.ClientTimeout(total=40), headers={"User-Agent": "Mozilla/5.0"})
        try:
            bm = await discover_scalp_universe(sess)
            xm = [] if a.no_cross_venue_p4 else p4_cross()
            if cfg.poly.enabled:
                pm_metas, pm_specs, pm_tokens = await pmw.discover(time.time(), a.duration + 600.0, cfg.poly, sess)
                await pmw.binance_ref_prices(sess, pm_specs, time.time())
        finally:
            await sess.close()
        metas = list(bm) + xm + pm_metas
        print(f"binance scalp/tri markets: {len(bm)} | cross-venue: {len(xm)} | polymarket: {len(pm_metas)}", flush=True)
    else:
        print("discovering Binance universe …", flush=True)
        bm = await discover_binance_universe(cfg.watchers.n_markets, cfg.watchers.exclude_bases,
                                             exclude_regex=cfg.watchers.exclude_regex)
        metas = list(bm)
        if cfg.watchers.cross_venue:
            metas += cross_venue_metas()
    perf = time.perf_counter
    ag = Agency(metas, cfg, out_dir=run_dir, t0=perf(), wall0=time.time())
    tape_extra = {}
    if (a.phase4 or a.phase5) and pm_metas:
        import dataclasses
        tape_extra = {"wall0": time.time(), "t0": ag.t0, "specs": {k: dataclasses.asdict(v) for k, v in pm_specs.items()}, "tokens": pm_tokens,
                      "pm_ids": [m.id for m in pm_metas]}
        w = pmw.PolymarketWatcher(ag, pm_metas, pm_specs, pm_tokens, cfg.poly, wall0=tape_extra["wall0"], t0=ag.t0)
        ag.attach_polymarket(w)
    ag.hunter.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="calib")
    if a.phase5 and getattr(a, "phase7", False):
        attach_phase7(ag, cfg, a, has_prints=True)
    elif a.phase5 and getattr(a, "phase6", False):
        attach_phase6(ag, cfg, a, has_prints=True)
    elif a.phase5:
        from .maker_sniper import MakerSniper
        cfg.snipe.shadow_models = ("strict", "depletion", "trades")
        cfg.snipe.account_model = a.snipe_model or "trades"
        ag.attach_sniper(MakerSniper(ag, cfg.snipe))
    if a.record:
        ag.start_recording()
    nb = sum(1 for m in metas if m.venue == "binance")
    print(f"watching {len(metas)} markets: {nb} Binance (incl. BTCUSDT oracle) + {len(metas)-nb-len(pm_metas)} cross-venue + {len(pm_metas)} Polymarket", flush=True)
    fm = FeedManager(ag, trade_prints=bool(a.phase5))
    tasks = fm.tasks()
    t_end = ag.t0 + a.duration
    try:
        next_status = ag.t0 + a.status_every
        next_chk = ag.t0 + 60.0
        next_aux = ag.t0
        while True:
            await asyncio.sleep(0.05)
            t = perf()
            ag.housekeeping(t)
            if t >= next_status:
                next_status += a.status_every
                print(status_line(ag, t, fm.stats), flush=True)
                if ag.hc is not None:
                    print(f"          floor-passed Polymarket fills this session: {ag.hc.n_floor_fills} (stop at {a.stop_fills - a.prior_fills} more)" if a.stop_fills else
                          f"          floor-passed Polymarket fills this session: {ag.hc.n_floor_fills}", flush=True)
            if t >= t_end:
                break
            if (a.stop_file or a.count_file) and t >= next_aux:
                next_aux = t + 2.0
                if a.count_file and ag.hc is not None:
                    tmp = a.count_file + ".tmp"
                    with open(tmp, "w") as cf:
                        json.dump({"floor_fills": ag.hc.n_floor_fills, "elapsed_s": t - ag.t0, "wall": time.time()}, cf)
                    os.replace(tmp, a.count_file)
                if a.stop_file and os.path.exists(a.stop_file):
                    print(f"[{t-ag.t0:6.0f}s] STOP: stop-file present", flush=True)
                    t_end = t
                    break
            if a.stop_fills and ag.hc is not None and t >= next_chk:
                next_chk = t + 5.0
                if a.prior_fills + ag.hc.n_floor_fills >= a.stop_fills:       # a count-only rule: it never looks at P&L
                    print(f"[{t-ag.t0:6.0f}s] STOP: {a.prior_fills} prior + {ag.hc.n_floor_fills} live floor-passed fills >= {a.stop_fills}", flush=True)
                    t_end = t
                    break
        for st in fm.stats.values():
            st.up_at_end = st.connected
    finally:
        fm.stop.set()
        for tk in tasks:
            tk.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    if a.record:
        ag.save_tape(a.record, extra=tape_extra)
        print(f"tape saved: {a.record} ({len(ag.tape[0])} events)", flush=True)
    return ag, fm, t_end


def run_replay(a, cfg: AgencyConfig, run_dir: str):
    import dataclasses
    import numpy as np
    z = np.load(a.replay, allow_pickle=False)
    metas = []
    for m in json.loads(str(z["metas"])):
        if m.get("fee_schedule") is not None:
            m["fee_schedule"] = tuple(m["fee_schedule"])
        metas.append(MarketMeta(**m))
    extra = json.loads(str(z["extra"])) if "extra" in z.files else {}
    t, idx, b, aa, bq, aq = z["t"], z["i"], z["b"], z["a"], z["bq"], z["aq"]
    ag = Agency(metas, cfg, out_dir=run_dir, t0=float(t[0]), wall0=time.time())
    if extra.get("specs"):
        from .polymarket_watcher import PmSpec, PolymarketWatcher
        specs = {k: PmSpec(**v) for k, v in extra["specs"].items()}
        pm_metas = [m for m in metas if m.id in specs]
        w = PolymarketWatcher(ag, pm_metas, specs, extra["tokens"], cfg.poly, wall0=extra["wall0"] + (float(t[0]) - extra["t0"]), t0=float(t[0]))
        ag.attach_polymarket(w)
    if getattr(a, "phase7", False):
        has_prints = bool((idx < -1).any())
        for m in metas:
            if m.venue == "hyperliquid" and getattr(a, "hl_maker_bps", None) is not None:
                m.fee_maker_bps, m.fee_taker_bps = a.hl_maker_bps, a.hl_taker_bps
        attach_phase7(ag, cfg, a, has_prints)
        ag.snipe_has_prints = has_prints
    elif getattr(a, "phase6", False):
        has_prints = bool((idx < -1).any())
        for m in metas:
            if m.venue == "hyperliquid" and getattr(a, "hl_maker_bps", None) is not None:
                m.fee_maker_bps, m.fee_taker_bps = a.hl_maker_bps, a.hl_taker_bps
        attach_phase6(ag, cfg, a, has_prints)
        ag.snipe_has_prints = has_prints
    elif getattr(a, "phase5", False):
        from .maker_sniper import MakerSniper
        has_prints = bool((idx < -1).any())
        cfg.snipe.shadow_models = ("strict", "depletion", "trades") if has_prints else ("strict", "depletion")
        cfg.snipe.account_model = getattr(a, "snipe_model", None) or ("trades" if has_prints else "strict")
        for m in metas:                                               # fee sensitivity override for the replayed tape
            if m.venue == "hyperliquid" and getattr(a, "hl_maker_bps", None) is not None:
                m.fee_maker_bps, m.fee_taker_bps = a.hl_maker_bps, a.hl_taker_bps
        ag.attach_sniper(MakerSniper(ag, cfg.snipe))
        ag.snipe_has_prints = has_prints
    last_hk = last_st = float(t[0])
    for k in range(t.shape[0]):
        tk, i = float(t[k]), int(idx[k])
        if i == -1:
            ag.on_trade(tk, float(b[k]), float(aa[k]), bool(bq[k]))
            continue
        if i < -1:                                           # market trade print: idx = -(market+2)
            ag.on_market_trade(-i - 2, tk, float(b[k]), float(aa[k]), int(bq[k]))
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
    rep = finish(ag, t_end, {"mode": mode, "feeds": feeds, "phase4": a.phase4 or ag.pm is not None, "phase5": bool(getattr(a, "phase5", False)), "phase6": bool(getattr(a, "phase6", False)), "phase7": bool(getattr(a, "phase7", False)), "fee_assumption": True}, run_dir)
    print(rep)
    print(f"\nartifacts: {run_dir}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
