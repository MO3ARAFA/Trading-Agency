"""Phase 12 report: slow-horizon structural strategies for a 100 USD account (Track 1 Polymarket, Track 2 Hyperliquid funding / basis).

    python -m quant_agency.phase12_report --pm runs/pm_structural/<stamp> --hist docs/live_runs/phase12 --notes docs/PHASE12_NOTES.md --out docs/PHASE12_SLOW_STRUCTURAL.md

Inputs: ``pm_result.json`` / ``pm_universe.json`` (poly_structural), and the Track 2 JSONs written by the history studies (funding_study, basis_study,
premium_test, dev_path, tape-level basis). Everything is descriptive except the single pre-declared hourly premium test (docs/PHASE12_PLAN.md).
"""
from __future__ import annotations

import argparse
import json
import math
import os
from typing import Dict, List

from .hl_funding_basis import Bankroll
from .sector_report import f, pct


def _j(path: str):
    return json.load(open(path)) if os.path.exists(path) else None


def usd(x: float, nd: int = 3) -> str:
    return "–" if x is None or x != x else f"{x:+.{nd}f}"


def pmv(m, se, nd=1) -> str:
    return "–" if m is None or m != m else (f"{m:+.{nd}f} ± {se:.{nd}f}" if se == se else f"{m:+.{nd}f}")


# ---------------------------------------------------------------------------------------------- Track 2
def track2(h: str, bank: Bankroll) -> List[str]:
    L: List[str] = ["## 3. Track 2 — Hyperliquid funding and spot-perp basis", ""]
    fs, bs, pt, dp = _j(f"{h}/funding_study.json"), _j(f"{h}/basis_study.json"), _j(f"{h}/premium_test.json"), _j(f"{h}/dev_path.json")
    tb = [_j(f"{h}/xvr_s1_basis.json"), _j(f"{h}/xvr_s2_basis.json")]
    if fs:
        L += ["### 3.1 Funding (90 days of `fundingHistory`, liquid coins = Hyperliquid 24 h volume ≥ 1M USD, BTC/ETH excluded)", "",
              f"{fs['coins']} coins, {fs['coin_hours']:,} coin-hours. Median funding **{fs['median_bps_h']:.3f} bps/h** (the interest-rate floor, ≈ 11 % a year); percentiles 1 / 5 / 50 / 95 / 99: "
              + " / ".join(f"{fs['pct'][k]:+.2f}" for k in ('1', '5', '50', '95', '99')) + " bps/h.", "",
              "| |funding| level | share of coin-hours, positive | negative |", "|---|---|---|"]
        for lv, v in fs["share_ge"].items():
            L.append(f"| ≥ {float(lv):g} bps/h | {100 * v['pos']:.2f} % | {100 * v['neg']:.2f} % |")
        L += ["", "After an hour at or above the level (positive side — the only side a long-spot hedge can carry), the funding actually collected over the next k hours, and how long such episodes last:", "",
              "| level | episodes (starts) | carry next 4 h | next 8 h | next 24 h | median run (h) | share of runs ≥ 3 h / ≥ 6 h |", "|---|---|---|---|---|---|---|"]
        for lv, v in fs["persistence_pos"].items():
            r = fs["runs_pos"].get(lv, {})
            L.append(f"| ≥ {float(lv):g} bps/h | {v['starts']} | {f(v['carry_4h_bps'], 1)} bps | {f(v['carry_8h_bps'], 1)} bps | {f(v['carry_24h_bps'], 1)} bps | {f(r.get('median_h'), 0)} | "
                     f"{pct(r.get('share_ge_3h'))} / {pct(r.get('share_ge_6h'))} |")
        be = fs["breakeven_hours"]
        L += ["", "Hours of carry needed to pay the round-trip cost (public base-tier fees: Hyperliquid maker 1.5 / taker 4.5 bps per side, Binance spot 7.5 bps per side):", "",
              "| structure | cost (bps) | at the 0.125 floor | at 1 bps/h | at 3 bps/h | at 5 bps/h |", "|---|---|---|---|---|---|"]
        for k, c in (("perp_only_maker", 3), ("perp_only_taker", 9), ("hedged_perp_maker+spot", 18)):
            b = be[k]
            L.append(f"| {k.replace('_', ' ')} | {c} | {b['0.125']:.0f} h | {b['1.0']:.0f} h | {b['3.0']:.0f} h | {b['5.0']:.1f} h |")
        L += ["", f"**Reading.** The \"3–5 bps/h extremes\" do not exist among liquid coins: positive ≥ 3 bps/h is {100 * fs['share_ge']['3.0']['pos']:.2f} % of coin-hours "
              f"({fs['persistence_pos']['3.0']['starts']} episodes in 90 days across {fs['coins']} coins), ≥ 5 bps/h never. A delta-neutral carry needs ≈ 18 bps, i.e. 144 hours at the floor; even a ≥ 3 bps/h episode "
              f"collects ≈ {f(fs['persistence_pos']['3.0']['carry_24h_bps'], 0)} bps over 24 h, which is the cost, before any basis move. On a {bank.notional_usd:.0f} USD position 20 bps is "
              f"{usd(20 / 1e4 * bank.notional_usd, 3)} USD.", ""]
    if bs:
        L += ["### 3.2 Basis reversion at 5 / 15 / 30 minutes (3.4 days of 1-minute bars, 60 mid-caps)", "",
              "Basis = ln(HL / Binance), 3-minute smoothed, deviation from the trailing 6 h median (excluding the last 10 min), one event per coin per 30 min, **entry one minute after the trigger**; position = short the rich leg / long the cheap leg. "
              f"Threshold × horizon chosen on the first {bs['cut_min']} minutes (train), evaluated once on the rest (test). Mean ± cluster s.e. (30-min blocks), bps:", "",
              "| part | threshold | h | events | clusters | mean \\|dev\\| | perp leg | spot leg | **hedged spread** | net: perp-only maker (3) | hedged (18) |", "|---|---|---|---|---|---|---|---|---|---|---|"]
        for part in ("train", "test"):
            for thr, d in bs[part].items():
                for H, s in d["by_h"].items():
                    n = s["net"]
                    L.append(f"| {part} | {float(thr):g} | {H} min | {s['n']} | {s['clusters']} | {s['mean_abs_dev']:.1f} | {pmv(s['perp']['mean'], s['perp']['se'])} | {pmv(s['spot']['mean'], s['spot']['se'])} | "
                             f"**{pmv(s['hedged']['mean'], s['hedged']['se'])}** | {n['perp_only_maker']['mean']:+.1f} | {n['hedged_perp_maker+spot']['mean']:+.1f} |")
        sel = bs.get("selected")
        L += ["", (f"Selected on train: threshold {float(sel['thr']):g} bps, {sel['h']} min (train net {sel['train_net_perp_maker']:+.1f} bps). On test that cell is **+11.7 ± 18.0 bps (n = 25, t = 0.65, one-sided p = 0.26): not significant**." if sel else ""),
              "The perp and spot legs are mirror images (+15 / −15): the unhedged perp P&L is the coin's direction, not the basis. The hedged spread — the only part that is basis — earns −5 to +2 bps against ≈ 18 bps of cost.", ""]
        if dp:
            p = dp["path"]
            L += ["Where does the deviation go? Mean signed deviation (bps) k minutes after a ≥ 15 bps trigger: " + ", ".join(f"{k} min: {v:.1f}" for k, v in p.items()) +
                  ". About 40 % comes back within 3–5 minutes (mostly before the earliest possible fill) and ≈ 60 % is still there after 30 minutes — the same \"persistent\" share Phase 11 saw at tick level.", ""]
    ev = [t for t in tb if t]
    if ev:
        L += ["### 3.3 The same question at quote level (Phase 11 tapes: real bid/ask on both legs, 1-second grid, entry at the touch)", "",
              "Equilibrium here is a 20-minute trailing median (each tape is 1 h long), 60-second smoothed basis, entry 1 s after the trigger, exit at the touch; **2 tapes, 60 coins, 2 hours**.", ""]
        tot = sum(t["events"] for t in ev)
        L += [f"**{tot} events ≥ 8 bps in two hours across 60 coins** (the 1-minute candles of 3.2 above gave ≈ 950 in 1.5 days). Per event, hedged spread mid-to-mid / after crossing both spreads: " +
              "; ".join(f"{k}: {pmv(c['hedged_mid']['mean'], c['hedged_mid']['se'])} / {pmv(c['hedged_cross']['mean'], c['hedged_cross']['se'])} (n = {c['n']})" for t in ev for k, c in t["cells"].items()) + ".", "",
              "Most of the \"persistent basis\" in 1-minute candle data is **last-trade-close mismatch between the two venues**, not a quoted divergence: at quote level a ≥ 8 bps deviation from a 20-minute equilibrium is rare, and the few that occur are worth about nothing after the spreads.", ""]
    if pt:
        sp = pt["spec"]
        c = pt["primary"]
        L += ["### 3.4 The one pre-declared test: a rich perp underperforms the market over the next hours (hourly bars, ~100 days, discovery window excluded)", "",
              "Found by searching a 3.4-day window (the unhedged perp leg of \"short the rich / long the cheap perp\", market-neutral, +160 ± 48 bps at 4 h for ≥ 30 bps), so it was **frozen as a hypothesis and tested out of sample** "
              f"(`docs/PHASE12_PLAN.md`, hashes in `PHASE12_PLAN.json`): hourly bars, {pt['coins']} coins, {pt['bars_used']} bars (the last 84 never used), trigger |dev| ≥ {sp['thr_bps']:g} bps, hold {sp['h_bars']} h, outcome = perp leg minus the equal-weight market move, minus {sp['cost_bps']:g} bps, "
              f"one-sided cluster t, ≥ {sp['min_clusters']} clusters.", "",
              f"**Primary: {c['n']} events, {c['clusters']} clusters, market-neutral net {c['net_neutral']['mean']:+.1f} ± {c['net_neutral']['se']:.1f} bps, t = {c['net_neutral']['t']:.2f}, one-sided p = {c['net_neutral']['p1']:.3f} → {pt['decision']}.** "
              "The in-sample +160 bps is not reproduced (+21.5 ± 17.8). Secondary cells (descriptive):", "",
              "| threshold | hold | events | clusters | market-neutral perp | raw perp | hedged spread | net (neutral − 6) | t |", "|---|---|---|---|---|---|---|---|---|"]
        for k, v in pt["cells"].items():
            thr, H = k.split("|")
            nn = v["net_neutral"]
            L.append(f"| {thr} | {H.replace('h-bars','')} h | {v['n']} | {v['clusters']} | {pmv(v['neutral']['mean'], v['neutral']['se'])} | {pmv(v['raw_perp']['mean'], v['raw_perp']['se'])} | {pmv(v['hedged']['mean'], v['hedged']['se'])} | {nn['mean']:+.1f} | {nn['t']:.2f} |")
        L += ["", "**Caution on the hedged column.** At hourly resolution it shows +15 to +35 bps with tiny standard errors. That is a measurement artefact: it enters at stale last-trade closes of two venues, so the observed basis at the trigger bar is partly noise that is gone one bar later "
              "(the 1-minute study with a one-minute entry delay and the quote-level study both show ≈ 0). It is not tradable and is not used anywhere in the verdict. The 15 bps cells (t ≈ 3.1 at 1 h, market-neutral net +5 bps) are exploratory, one of 8 secondary cells, share the same artefact "
              "(entry at the stale close) and are not claimed.", ""]
    return L


# ---------------------------------------------------------------------------------------------- Track 1
def track1(pm: str, bank: Bankroll) -> List[str]:
    r, u = _j(f"{pm}/pm_result.json"), _j(f"{pm}/pm_universe.json")
    L: List[str] = ["## 2. Track 1 — Polymarket slow event markets", ""]
    if not r or not u:
        return L + ["*(no Polymarket run found)*", ""]
    c = r["universe_counts"]
    L += [f"**Live capture:** {r['hours']:.2f} h, {r['msgs']:,} CLOB messages, {r['feed'].get('reconnects', 0)} reconnects. Universe from {c['events']:,} Gamma events / {c['markets']:,} markets ({c['live']:,} live): "
          f"**{c['slow_candidates']} slow markets** pass the filter (> 24 h to expiry, 24 h volume ≥ 500 USD, cached spread 3–8 ¢, mid 5–95 ¢); the {r['n_slow']} most active are quoted; "
          f"{r['n_control']} BTC up/down markets are the control; {c['groups']} NegRisk groups exist, {r['scan']['groups']} are scanned live.", ""]
    # structural
    L += ["### 2.1 Structural scan (live CLOB books, net of the fee schedule, ≥ 5 shares on the thinnest leg)", "",
          f"{r['scan']['evals']:,} group evaluations ({r['scan']['incomplete']:,} skipped while a leg had no book). Binary YES/NO mirror check: {r['mirror']['checks']:,} comparisons, "
          f"min ask(YES)+ask(NO) = {r['mirror']['min_ask_sum']:.3f}, max bid(YES)+bid(NO) = {r['mirror']['max_bid_sum']:.3f}, **{r['mirror']['crossed']} crossed** — the two books are mirrors, there is no binary free lunch.", ""]
    opps = r["opps"]
    if opps:
        L += ["Locked-margin opportunities seen (a *set* is one share of every leg; margin is per set after fees; capital is what is tied up until the event resolves):", "",
              "| group | kind | legs | exhaustive-like | peak net / set | peak gross | thinnest leg (shares) | lasted | days to resolution | net on capital | annualised |", "|---|---|---|---|---|---|---|---|---|---|---|"]
        for o in sorted(opps, key=lambda o: -o["max_net"])[:15]:
            n = o["n_legs"]
            cap = (1.0 - o["max_gross"]) if o["kind"] == "buy_set" else (n - 1.0 - o["max_gross"])
            ret = o["max_net"] / cap if cap > 0 else float("nan")
            d = o.get("days_to_end")
            ann = ret * 365.0 / d if d and d == d and d > 0 else float("nan")
            title = (u["group_info"].get(o["gid"], {}).get("title") or o["gid"])[:46]
            L.append(f"| {title} | {o['kind']} | {n} | {'yes' if o['exhaustive_like'] else 'no'} | {o['max_net']:.4f} USD | {o['max_gross']:.4f} | {o['min_shares']:.0f} | {o['duration']:.0f} s | {f(d, 1)} | {pct(ret)} | {pct(ann)} |")
        top = max(opps, key=lambda o: o["max_net"] * o["min_shares"])
        L += ["", f"The largest dollar opportunity of the hour: {top['max_net']:.4f} USD per set × {top['min_shares']:.0f} shares on the thinnest leg ≈ **{top['max_net'] * top['min_shares']:.2f} USD**. "
              f"With a {bank.capital_usd:.0f} USD account the binding limits are depth (the thinnest leg) and capital locked until resolution, not the margin.", ""]
    else:
        L += ["No net-positive locked margin with ≥ 5 shares of depth appeared in this session.", ""]
    w = sorted(r["worst"].values(), key=lambda x: -x["best_net"])[:8]
    if w:
        L += ["Best net margin seen per group and kind (including ones that never reached 5 shares):", "", "| group | kind | legs | exhaustive-like | best net / set | best gross | shares at that moment |", "|---|---|---|---|---|---|---|"]
        for x in w:
            L.append(f"| {(u['group_info'].get(x['gid'], {}).get('title') or x['gid'])[:46]} | {x['kind']} | {x['n']} | {'yes' if x['exh'] else 'no'} | {x['best_net']:+.4f} | {x['best_gross']:+.4f} | {x['shares']:.1f} |")
        L.append("")
    # maker
    m = r["maker"]
    L += ["### 2.2 Passive quoting (virtual post-only orders, 5 shares = the Polymarket minimum, TTL 300 s)", "",
          "*trades* is the primary fill model (real trade prints consume the queue ahead of us); *strict* is a lower bound; *depletion* counts any displayed-size drop as a trade and is an **upper bound shown for completeness**. "
          "Markout = (later mid − fill price) × side, in cents per share; dollars are at 5 shares.", "",
          "| universe | policy | model | attempts | fills | fill rate | fills / market-hour | spread capture (¢) | markout 60 s (¢) | markout 300 s (¢) | USD per fill (300 s) |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for kind in ("slow", "control"):
        for pol in ("join", "penny"):
            for mod in ("strict", "trades", "depletion"):
                d = m.get(f"{kind}|{pol}|{mod}")
                if not d:
                    continue
                L.append(f"| {kind} | {pol} | {mod} | {d['attempts']} | {d['fills']} | {pct(d['fill_rate'])} | {f(d['fills_per_market_hour'], 2)} | {f(d.get('spread_capture_c'), 2)} | "
                         f"{pmv(d.get('markout_60s_c'), d.get('markout_60s_se', float('nan')), 2)} | {pmv(d.get('markout_300s_c'), d.get('markout_300s_se', float('nan')), 2)} | {usd(d.get('usd_per_fill_300s'))} |")
    b = r["burst"]
    L += ["", "Trade-print arrival (per-minute counts, Fano factor: 1 = Poisson, ≫ 1 = bursty sweeps):", "",
          "| universe | markets with ≥ 5 prints | median trades / min | Fano median | Fano p90 |", "|---|---|---|---|---|"]
    for k in ("slow", "control"):
        x = b[k]
        L.append(f"| {k} | {x['markets_with_trades']} | {x['trades_per_min_median']:.2f} | {f(x['fano_median'], 2)} | {f(x['fano_p90'], 2)} |")
    L.append("")
    sets = r.get("sets", [])
    if sets:
        comp = [s for s in sets if s["complete"]]
        L += ["### 2.3 Maker lock across a whole exhaustive group (join-bids on every leg; legging risk)", "",
              f"{len(sets)} sets attempted, **{len(comp)} completed** ({100 * len(comp) / len(sets):.0f} %). Complete sets locked "
              + (f"{sum(s['locked_usd'] for s in comp) / len(comp):.3f} USD each on average (5 shares)" if comp else "nothing")
              + f"; incomplete sets left {sum(s['legs_filled'] for s in sets if not s['complete'])} filled legs marked at mid for a mean P&L of "
              + usd(sum(s['pnl_mark_usd'] for s in sets if not s['complete']) / max(sum(1 for s in sets if not s['complete']), 1)) + " USD each (no resolution, no spread).", ""]
    return L


def comparison() -> List[str]:
    return ["## 4. How this compares with Phases 1–11", "",
            "| phase | strategy | horizon | execution | best honest result |", "|---|---|---|---|---|",
            "| 1–3 | BTC → 60 Binance alts lead-lag | seconds | taker | gaps ≲ 1 bp gross vs ≈ 2 bp spread and 15 bp fees: detected, refused |",
            "| 4–6 | BTC → Hyperliquid / Polymarket (taker, passive maker, pre-positioned maker) | seconds | taker / maker | Hyperliquid +2.5 bps gross vs 4.5 bps taker; Polymarket maker fills adversely, taker loses ≈ 2.4 ¢ per share |",
            "| 7–10 | Architecture B on Polymarket, exits, regime gates | 10 s – minutes | taker in / maker out | never significant; in-sample +128 bps, t = 0.80, pre-registered N\\* = 608 not collected |",
            "| 11 | Sector oracles; same-asset Binance → Hyperliquid tail lag | sub-second | taker | pre-registered: net −8.46 ± 1.63 bps (t = −5.2); lag real (+3.9 bps) but sub-second and ≈ ⅓ of the gap |",
            "| **12** | **Funding carry, basis reversion, premium drift (Hyperliquid); structural sets and passive quoting (Polymarket)** | minutes – days | maker / hold | see §1 |", ""]


def build(pm: str, hist: str, notes: str, bank: Bankroll) -> str:
    L: List[str] = ["# Phase 12 — slow-horizon structural strategies for a 100 USD account", ""]
    if notes:
        L += [notes.strip(), ""]
    L += [f"## 1. The 100 USD account in numbers", "",
          f"Hyperliquid minimum order ≈ {bank.min_notional_usd:.0f} USD; positions of {bank.notional_usd:.0f} USD, ≤ {bank.max_open} at once, ≤ {bank.max_leverage:g}× leverage, stop at −{100 * bank.max_loss_frac:.0f} %. "
          f"Polymarket minimum order {bank.pm_min_shares:.0f} shares (≈ 0.5–4.5 USD). Fees are public base-tier assumptions: Hyperliquid maker 1.5 / taker 4.5 bps, Binance spot 7.5 bps, Polymarket maker 0 and taker per the market's fee schedule. "
          f"**One basis point of {bank.notional_usd:.0f} USD is {bank.notional_usd / 1e4:.4f} USD**: a 30 bps edge is {30 * bank.notional_usd / 1e4:.2f} USD per trade; the per-trade noise of an unhedged perp position (≈ 90 bps s.d. over 15–30 minutes) is ≈ {90 * bank.notional_usd / 1e4:.2f} USD. "
          "This repository contains no code that sends an order and reads no credentials; everything here is measurement or paper simulation.", ""]
    L += track1(pm, bank)
    L += track2(hist, bank)
    L += comparison()
    return "\n".join(L)


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--pm", required=True)
    p.add_argument("--hist", default="docs/live_runs/phase12")
    p.add_argument("--notes", default=None)
    p.add_argument("--out", default="docs/PHASE12_SLOW_STRUCTURAL.md")
    a = p.parse_args(argv)
    md = build(a.pm, a.hist, open(a.notes).read() if a.notes else "", Bankroll())
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    open(a.out, "w").write(md)
    print(f"wrote {a.out} ({len(md)} chars)")


if __name__ == "__main__":
    main()
