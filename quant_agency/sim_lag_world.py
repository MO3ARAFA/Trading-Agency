"""Controlled synthetic lag world — the stress test for the Phase 6 architectures.

Real tapes only show what the market happened to do. This generator builds a tape in the *same npz format* as a live recording
(BTC oracle quotes + Hyperliquid-like perps + Polymarket-like digitals + trade prints), so the full Agency (hunter, PM watcher, CFO,
CEO, engines) replays it unchanged, while the parameters that decide whether the architectures work are *controlled*:

  regime          quiet (small, frequent impulses) vs volatile (10-30 bp impulses)
  D_mm            how long the lagging venue's market makers take to reprice after Binance moves (HL 0.8 s, PM 1.5 s by default)
  D_inf           how long *informed takers* take to hit the stale quotes after Binance moves — the decisive race parameter:
                  our cancel-on-impulse needs  detection + 150 ms  <  D_inf  to protect a resting quote, and our taker needs
                  150 ms  <  D_inf  to get a price the informed flow hasn't already taken
  informed_prob   fraction of qualifying impulses that attract an informed taker at all
  uninformed flow Poisson market orders at the touch (prints emitted; they deplete the displayed size) — the *only* source of
                  benign passive fills, i.e. the spread income a quote maker lives on

The world is open-loop (our paper orders do not move it). Everything stochastic is seeded.
"""
from __future__ import annotations

import dataclasses
import json
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np

from .market_watchers import MarketMeta
from .polymarket_watcher import PmSpec, ncdf
from .venues import cross_venue_metas

SQRT_YEAR = math.sqrt(365.0 * 86400.0)


@dataclass
class WorldCfg:
    regime: str = "quiet"                # quiet | volatile
    duration_s: float = 900.0
    seed: int = 1
    D_mm_hl: float = 0.8
    D_mm_pm: float = 1.5
    D_inf: float = 0.5
    informed_prob: float = 0.8
    inf_min_hl_bps: float = 3.0          # informed takers only act when the stale quote is worth > ~their taker cost
    inf_min_pm_cents: float = 2.0
    hl_prices: tuple = (80_000.0, 3_000.0, 150.0)
    hl_ticks: tuple = (1.0, 0.1, 0.01)
    hl_spread_ticks: int = 1
    hl_touch_med: tuple = (2.0, 60.0, 1500.0)        # coins resting at the touch (median) — BTC/ETH/SOL
    hl_flow_hz: float = 1.5                          # uninformed prints per second per side-agnostic stream
    hl_flow_med: tuple = (0.15, 4.0, 100.0)          # coins per print (median)
    pm_strikes: tuple = (-0.0015, 0.0, 0.0015)       # relative to the opening BTC price
    pm_tau_s: float = 3600.0
    pm_short_tau_s: float = 0.0                      # >0 adds one short-dated market expiring that many s into the run
    pm_spread_ticks: int = 2
    pm_touch_med: float = 250.0                      # shares at the touch
    pm_flow_hz: float = 0.5
    pm_flow_med: float = 40.0
    diff_bps: float = -1.0                           # BTC diffusion bp/sqrt(s); <0 -> regime default
    jump_rate_hz: float = -1.0
    jump_bps_lo: float = -1.0
    jump_bps_hi: float = -1.0
    t0: float = 5000.0
    wall0: float = 1_800_000_000.0

    def resolved(self) -> "WorldCfg":
        c = dataclasses.replace(self)
        if c.regime == "volatile":
            d, r, lo, hi = 2.5, 1 / 9.0, 10.0, 30.0
        else:
            d, r, lo, hi = 0.8, 1 / 12.0, 1.5, 4.0
        c.diff_bps = d if c.diff_bps < 0 else c.diff_bps
        c.jump_rate_hz = r if c.jump_rate_hz < 0 else c.jump_rate_hz
        c.jump_bps_lo = lo if c.jump_bps_lo < 0 else c.jump_bps_lo
        c.jump_bps_hi = hi if c.jump_bps_hi < 0 else c.jump_bps_hi
        return c


def _lognorm(rng, med, sig=0.8):
    return float(med * math.exp(sig * rng.standard_normal()))


def make_world(cfg: WorldCfg):
    """Returns dict(t, i, b, a, bq, aq, metas, extra, jumps)."""
    c = cfg.resolved()
    rng = np.random.default_rng(c.seed)
    dt = 0.01
    n = int(c.duration_s / dt) + 1
    grid = np.arange(n) * dt
    inc = rng.normal(0.0, c.diff_bps * 1e-4 * math.sqrt(dt), n)
    jumps: List[dict] = []
    tj = 8.0                                     # first jump after the oracle has warmed a little
    ramp = 10
    while True:
        tj += rng.exponential(1.0 / c.jump_rate_hz)
        if tj >= c.duration_s - 8.0:
            break
        mag = rng.uniform(c.jump_bps_lo, c.jump_bps_hi) * (1 if rng.random() < 0.5 else -1)
        k0 = int(tj / dt)
        inc[k0:k0 + ramp] += mag * 1e-4 / ramp
        jumps.append({"t": c.t0 + tj, "bps": float(mag), "t_done": c.t0 + tj + ramp * dt})
    btc0 = 80_000.0
    lb = math.log(btc0) + np.cumsum(inc)         # log price on the 10 ms grid

    def lb_at(tt):
        return np.interp(tt, grid, lb)

    ev: List[tuple] = []                         # (t, idx, a, b, c, d) quote or print rows
    # ---- BTC oracle quotes (100 Hz)
    tb = np.sort(rng.uniform(0.0, c.duration_s, int(100 * c.duration_s)))
    pb = np.exp(lb_at(tb))
    bqb, aqb = rng.uniform(1, 6, tb.size), rng.uniform(1, 6, tb.size)
    for k in range(tb.size):
        ev.append((c.t0 + tb[k], 0, pb[k] - 0.005, pb[k] + 0.005, float(bqb[k]), float(aqb[k])))

    hl = [m for m in cross_venue_metas(venues=("hyperliquid",), deribit_assets=()) if m.base in ("BTC", "ETH", "SOL")]
    metas: List[MarketMeta] = [MarketMeta("BTCUSDT", "binance", "BTCUSDT", "BTC", tick=0.01, step=1e-5, min_notional=5.0, asset="BTC")] + hl
    idx_hl = {m.base: 1 + k for k, m in enumerate(hl)}

    specs: Dict[str, PmSpec] = {}
    tokens: Dict[str, str] = {}
    pm_defs = []
    for si, rel in enumerate(c.pm_strikes):
        pm_defs.append((f"pm:synth-above-{si}:above", btc0 * (1.0 + rel), c.pm_tau_s + c.duration_s))
    if c.pm_short_tau_s > 0:
        pm_defs.append(("pm:synth-above-short:above", btc0, c.pm_short_tau_s))
    pm_ids = []
    pm_models = []
    sig_s = 0.8e-4                                # the pricing makers' vol per sqrt(s) (quiet baseline)
    for (mid_id, K, t_exp) in pm_defs:
        metas.append(MarketMeta(id=mid_id, venue="polymarket", symbol="tok-" + mid_id, base="BTC", tick=0.01, step=0.01, min_notional=1.0,
                                asset="BTC-PM", kind="prediction", quote="USD", fee_schedule=(0.07, 1.0, True), spread_gate_bps=5000.0, hunt=False,
                                tradable=True, extra={"slug": mid_id, "family": "above", "t_end": c.wall0 + t_exp, "question": "synthetic", "min_size": 5.0}))
        specs[mid_id] = PmSpec(kind="above", t_end=c.wall0 + t_exp, K=K)
        tokens[mid_id] = "tok-" + mid_id
        pm_ids.append(mid_id)
        pm_models.append((len(metas) - 1, K, t_exp))

    def venue_stream(i: int, fair_fn, tick: float, spread_ticks: int, touch_med: float, flow_hz: float, flow_med: float, D_mm: float,
                     inf_min_fn, lo: float, hi: float):
        """Simulate one lagging venue: reprice events + uninformed prints + informed sweeps -> quote/print rows."""
        # reprice grid: quantised venue fair at 20 ms resolution, emit on change
        tg = np.arange(0.0, c.duration_s, 0.02)
        fair = np.array([fair_fn(x - D_mm) for x in tg])
        tgt_bid = np.floor((fair - spread_ticks * tick / 2.0) / tick + 1e-9) * tick
        tgt_bid = np.clip(tgt_bid, lo, hi - spread_ticks * tick)
        chg = np.flatnonzero(np.diff(tgt_bid) != 0.0) + 1
        evs: List[tuple] = [(float(tg[0]), "reprice", float(tgt_bid[0]))] + [(float(tg[k]), "reprice", float(tgt_bid[k])) for k in chg]
        for _ in range(rng.poisson(flow_hz * c.duration_s)):
            evs.append((float(rng.uniform(2.0, c.duration_s)), "flow", 1 if rng.random() < 0.5 else -1))
        for _ in range(int(c.duration_s / 0.4)):
            evs.append((float(rng.uniform(0, c.duration_s)), "refill", 0))
        for j in jumps:
            tt = j["t_done"] - c.t0 + c.D_inf
            f_new, f_old = fair_fn(j["t_done"] - c.t0), fair_fn(j["t"] - c.t0 - 1e-3)
            if abs(f_new - f_old) >= inf_min_fn(f_old) and rng.random() < c.informed_prob:
                evs.append((tt, "informed", 1 if f_new > f_old else -1, f_new))
        evs.sort(key=lambda e: e[0])
        bid = ask = 0.0
        bq = aq = 0.0
        out: List[tuple] = []

        def q(t):
            out.append((c.t0 + t, i, bid, ask, bq, aq))

        for e in evs:
            t, kind = e[0], e[1]
            if kind == "reprice":
                nb = e[2]
                if nb != bid or bid == 0.0:
                    bid, ask = nb, nb + spread_ticks * tick
                    bq, aq = _lognorm(rng, touch_med), _lognorm(rng, touch_med)
                    q(t)
            elif bid == 0.0:
                continue
            elif kind == "flow":
                sz = _lognorm(rng, flow_med, 1.0)
                side = e[2]
                if side > 0:
                    got = min(sz, aq)
                    out.append((c.t0 + t, -(i + 2), ask, got, 1.0, 0.0))
                    aq -= got
                    if aq <= 1e-9:
                        aq = _lognorm(rng, touch_med)
                else:
                    got = min(sz, bq)
                    out.append((c.t0 + t, -(i + 2), bid, got, -1.0, 0.0))
                    bq -= got
                    if bq <= 1e-9:
                        bq = _lognorm(rng, touch_med)
                q(t)
            elif kind == "refill":
                if rng.random() < 0.5:
                    bq += _lognorm(rng, touch_med * 0.15)
                else:
                    aq += _lognorm(rng, touch_med * 0.15)
                q(t)
            elif kind == "informed":
                side, f_new = e[2], e[3]
                if side > 0 and f_new > ask:                     # lift the stale ask through to ~60 % of the new fair
                    out.append((c.t0 + t, -(i + 2), ask, aq + touch_med * 3.0, 1.0, 0.0))
                    steps = max(1, int(round(0.6 * (f_new - ask) / tick)))
                    ask = ask + steps * tick
                    aq = _lognorm(rng, touch_med)
                    q(t)
                elif side < 0 and f_new < bid:
                    out.append((c.t0 + t, -(i + 2), bid, bq + touch_med * 3.0, -1.0, 0.0))
                    steps = max(1, int(round(0.6 * (bid - f_new) / tick)))
                    bid = bid - steps * tick
                    bq = _lognorm(rng, touch_med)
                    q(t)
        return out

    # ---- Hyperliquid-like perps (ETH/SOL track BTC with beta 1)
    for k, a in enumerate(("BTC", "ETH", "SOL")):
        if a not in idx_hl:
            continue
        p0 = c.hl_prices[k]
        i = idx_hl[a]

        def fair_hl(x, p0=p0):
            return p0 * math.exp(float(lb_at(max(x, 0.0))) - math.log(btc0))

        ev += venue_stream(i, fair_hl, c.hl_ticks[k], c.hl_spread_ticks, c.hl_touch_med[k], c.hl_flow_hz, c.hl_flow_med[k], c.D_mm_hl,
                           lambda f, p0=p0: c.inf_min_hl_bps * 1e-4 * f, c.hl_ticks[k], p0 * 5.0)
    # ---- Polymarket-like digitals on BTC
    for (i, K, t_exp) in pm_models:
        def fair_pm(x, K=K, t_exp=t_exp):
            tau = max(t_exp - max(x, 0.0), 1.0)
            return ncdf((float(lb_at(max(x, 0.0))) - math.log(K)) / (sig_s * math.sqrt(tau)))

        ev += venue_stream(i, fair_pm, 0.01, c.pm_spread_ticks, c.pm_touch_med, c.pm_flow_hz, c.pm_flow_med, c.D_mm_pm,
                           lambda f: c.inf_min_pm_cents * 0.01, 0.01, 0.99)
    ev.sort(key=lambda e: e[0])
    arr = np.array(ev, dtype=np.float64)
    extra = {"wall0": c.wall0, "t0": c.t0, "specs": {k: dataclasses.asdict(v) for k, v in specs.items()}, "tokens": tokens, "pm_ids": pm_ids,
             "world": dataclasses.asdict(c), "jumps": jumps}
    return {"t": arr[:, 0], "i": arr[:, 1].astype(np.int32), "b": arr[:, 2], "a": arr[:, 3], "bq": arr[:, 4], "aq": arr[:, 5],
            "metas": metas, "extra": extra, "jumps": jumps}


def save_world(w: dict, path: str) -> None:
    metas = json.dumps([dataclasses.asdict(m) for m in w["metas"]])
    np.savez_compressed(path, t=w["t"], i=w["i"], b=w["b"], a=w["a"], bq=w["bq"], aq=w["aq"], metas=np.array(metas),
                        extra=np.array(json.dumps(w["extra"], default=float)))


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--regime", default="quiet")
    p.add_argument("--duration", type=float, default=900.0)
    p.add_argument("--d-inf", type=float, default=0.5)
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--out", required=True)
    a = p.parse_args()
    w = make_world(WorldCfg(regime=a.regime, duration_s=a.duration, D_inf=a.d_inf, seed=a.seed))
    save_world(w, a.out)
    print(f"{a.out}: {w['t'].size} events, {len(w['jumps'])} jumps")
