"""Live telemetry summary / final report (markdown) built from the agency's own state."""
from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
from typing import Dict, Optional

import numpy as np

from .agency import Agency


def md_table(headers, rows) -> str:
    if not rows:
        return "_(none)_\n"
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(x) for x in r) + " |")
    return "\n".join(out) + "\n"


def _f(x, nd=2, sign=False):
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "-"
    return f"{x:+.{nd}f}" if sign else f"{x:.{nd}f}"


def markout_rows(ag: Agency, cohort=None, approved_only=False):
    tb = ag.cfo.markouts.table(cohort=cohort, approved_only=approved_only, now=ag.last_t)
    rows = []
    for h, v in tb.items():
        rows.append([f"t+{h:g}s", v["n"], _f(v["gross"], 2, True), _f(v["net"], 2, True),
                     _f(v["net_se"], 2), f"{v['hit_gross']*100:.0f}%", f"{v['hit_net']*100:.0f}%", _f(v["closure"], 2)])
    return rows


MK_HEAD = ["horizon", "n", "gross bps", "net bps (taker, after spread+fees)", "net s.e.", "hit gross", "hit net", "gap closure"]


def build_report(ag: Agency, t_now: float, info: Optional[dict] = None) -> str:
    info = info or {}
    cfg = ag.cfg
    L = []
    P = L.append
    dur = t_now - ag.t0
    P(f"# Quant Agency — live telemetry report\n")
    P(f"* mode: **{info.get('mode', 'live')}**  | duration: **{dur:.0f}s**  | markets watched: **{ag.book.M}** "
      f"({sum(1 for m in ag.book.metas if m.venue == 'binance')} Binance + "
      f"{sum(1 for m in ag.book.metas if m.venue != 'binance')} cross-venue)")
    P(f"* fees: taker {cfg.cfo.fee_taker_bps} bps / maker {cfg.cfo.fee_maker_bps} bps per side | assumed order latency "
      f"{cfg.cfo.latency_s*1000:.0f} ms | capital ${cfg.cfo.capital_usd:,.0f} (paper)")
    P(f"* execution is **paper only** — no credentials, no live orders.\n")

    # ---- feeds
    P("## 1. Feed health & internal latency\n")
    rows = []
    for name, st in info.get("feeds", {}).items():
        rows.append([name, st.msgs, st.quotes, f"{st.msgs/max(dur,1e-9):.0f}/s", st.reconnects, st.errors,
                     "yes" if getattr(st, "up_at_end", st.connected) else "no", st.last_error or "-"])
    P(md_table(["feed", "msgs", "quotes", "rate", "reconnects", "errors", "up", "last error"], rows))
    sl, dl = ag.scan_lat.summary(), ag.decide_lat.summary()
    if sl.get("n"):
        P(f"* hunter scan (all {len(ag.book.metas)-1} markets, numba): n={sl['n']}  p50={sl['p50']:.0f}µs  p90={sl['p90']:.0f}µs  "
          f"p99={sl['p99']:.0f}µs  max={sl['max']/1000:.2f}ms")
    if dl.get("n"):
        P(f"* BTC tick received → CFO-approved executable payload ready: n={dl['n']}  p50={dl['p50']:.0f}µs  "
          f"p90={dl['p90']:.0f}µs  p99={dl['p99']:.0f}µs  max={dl['max']/1000:.2f}ms")
    P(f"* BTC quotes processed: {ag.n_btc}  | trades(agg): {ag.oracle.n_trades}  | book rejects: {ag.book.rejected}\n")

    # ---- oracle
    st = ag.oracle.state(t_now)
    P("## 2. BTC oracle (master reference)\n")
    d = st.as_dict()
    P(f"BTCUSDT bid/ask {d['bid']:.2f}/{d['ask']:.2f}, micro {d['micro']:.3f}, OBI {d['obi']:+.2f}, spread {d['spread_bps']:.3f} bps, "
      f"vol {d['vol_fast_bps_s']:.2f} bps/√s (slow {d['vol_slow_bps_s']:.2f}, ratio {d['vol_ratio']:.2f}), tick-vol {d['tick_vol_bps_s']:.2f}\n")
    P(f"BTC impulses detected (|Z|≥{ag.hunter.cfg.z_thr:.2f} at report time): **{ag.hunter.n_impulses}**; hunter scans: {ag.hunter.n_scans}\n")

    # ---- lead-lag table
    P("## 3. Lead-lag map (Hayashi-Yoshida peak lag, Kalman β) — top markets by ρ\n")
    tab = [r for r in ag.hunter.model.table() if r["calibrated"]]
    tab.sort(key=lambda r: -r["rho"])
    tr = ag.book.telemetry(t_now)
    meta = {r["market"]: r for r in tr}
    P(f"calibrated: {len(tab)}/{ag.book.M-1} markets\n")
    P(md_table(["market", "β (Kalman)", "t(β)", "ρ (3s, at lag)", "HY ρ peak", "HY ρ(0)", "lag s", "decay s", "σ_res 3s bps", "spread bps", "tick Hz", "regime"],
               [[r["market"], _f(r["beta"]), _f(r["tstat"], 1), _f(r["rho"]), _f(r["rho_hy"]), _f(r["rho0"]), _f(r["lag_s"], 1), _f(r["decay_s"], 1),
                 _f(r["sigma_res_3s_bps"]), _f(meta[r["market"]]["spread_bps"]), _f(meta[r["market"]]["rate_hz"], 1),
                 meta[r["market"]]["regime"]] for r in tab[:15]]))
    # ---- signals
    sigs = ag.signals
    P(f"## 4. Detected micro-gaps (hunter signals): **{ag.hunter.n_signals}**\n")
    by_m = Counter(s.market for s in sigs)
    P("per market (top 10): " + ", ".join(f"{k}:{v}" for k, v in by_m.most_common(10)) + "\n")
    outcome: Dict[int, dict] = defaultdict(dict)
    for r in ag.cfo.markouts.rows:
        outcome[r["sid"]][r["h"]] = r
    top = sorted(sigs, key=lambda s: -abs(s.gap_bps))[:14]
    rows = []
    for s in top:
        o = outcome.get(s.sid, {})
        g1 = o.get(1.0, {}).get("gross")
        g5 = o.get(5.0, {}).get("gross")
        n5 = o.get(5.0, {}).get("net")
        d = s.decision
        rows.append([f"{s.t-ag.t0:6.1f}s", s.market, "BUY" if s.side > 0 else "SELL", f"{s.btc_delta_bps:+.1f}@{s.horizon_s:g}s",
                     _f(s.btc_z, 1), _f(s.beta), _f(s.lag_s, 1), _f(s.gap_bps, 1, True), _f(s.gap_z, 1), _f(s.spread_bps, 1),
                     f"{d.reason}" + (f" ({d.mode})" if d.approved else ""), _f(d.net_edge_bps, 1, True),
                     _f(g1, 1, True), _f(g5, 1, True), _f(n5, 1, True)])
    P(md_table(["t", "market", "side", "BTC Δ", "Z", "β", "lag", "gap bps", "gap Z", "spread", "CFO", "pred net", "gross@1s", "gross@5s", "net@5s"], rows))

    # ---- CFO
    cr = ag.cfo.report()
    P("## 5. CFO gating & accounting\n")
    P(f"evaluated {cr['evaluated']}, approved {cr['approved']}; reasons: " + ", ".join(f"{k}={v}" for k, v in sorted(cr['reasons'].items(), key=lambda kv: -kv[1])) + "\n")
    P(f"equity ${cr['equity']:,.2f} (peak ${cr['peak']:,.2f}, drawdown {cr['drawdown_frac']*100:.3f}%), closed PnL ${cr['closed_pnl']:+.2f}, fees ${cr['fees_paid']:.2f}; "
      f"hurdle {cr['hurdle_bps']:.2f} bps, edge-credit {cr['edge_credit']:.2f}, mode {cr['mode_policy']}, size×{cr['size_mult']:.2f}, "
      f"halted={cr['halted']} ({cr['halt_reason'] or '-'}), quarantined={list(cr['blacklist']) or '-'}\n")

    # ---- markouts
    P("## 6. Realised markout curves (t+1s … t+30s)\n")
    P("**All detected gaps (incl. CFO-rejected shadow cohort)** — does the gap actually close?\n")
    P(md_table(MK_HEAD, markout_rows(ag)))
    P("**CFO-approved cohort**\n")
    P(md_table(MK_HEAD, markout_rows(ag, cohort="approved")))
    P("**CFO-rejected: net edge below hurdle**\n")
    P(md_table(MK_HEAD, markout_rows(ag, cohort="rejected_edge")))
    P("_gross = mid→mid after fill (latency-adjusted entry); net = cross the spread on entry and exit + round-trip taker fees; "
      "gap closure = share of the signalled gap that has closed._\n")

    # ---- per market
    rows5 = [r for r in ag.cfo.markouts.rows if r["h"] == 5.0]
    pm = defaultdict(list)
    for r in rows5:
        pm[r["market"]].append(r)
    prow = []
    for m, rs in pm.items():
        g = np.array([x["gross"] for x in rs]); n = np.array([x["net"] for x in rs])
        prow.append((float(n.mean()), [m, len(rs), _f(g.mean(), 2, True), _f(n.mean(), 2, True), f"{(n>0).mean()*100:.0f}%",
                                       "QUARANTINED" if m in cr["blacklist"] else ""]))
    prow.sort(key=lambda x: -x[0])
    P("## 7. Per-market profitability @ t+5s\n")
    P(md_table(["market", "n", "gross bps", "net bps", "hit net", "status"], [r for _, r in prow[:10]]))
    if len(prow) > 10:
        P("worst:\n")
        P(md_table(["market", "n", "gross bps", "net bps", "hit net", "status"], [r for _, r in prow[-5:]]))

    # ---- trades
    P("## 8. Paper execution\n")
    es = ag.engine.stats()
    P(f"orders submitted {es['submitted']}, filled {es['filled']} (partial {es['partial']}), closed {es['closed']}, open {es['open']}; dropped: {es['dropped']}\n")
    cl = ag.engine.closed
    if cl:
        pnl = sum(t.net_pnl_usd for t in cl)
        wins = np.mean([t.net_pnl_usd > 0 for t in cl])
        P(f"closed trades {len(cl)}: win rate {wins*100:.0f}%, net PnL ${pnl:+.2f}, fees ${sum(t.fees_usd for t in cl):.2f}, "
          f"expectancy {np.mean([t.net_bps for t in cl]):+.2f} bps / {np.mean([t.R for t in cl]):+.2f} R, "
          f"gross {np.mean([t.gross_bps for t in cl]):+.2f} bps, entry slippage {np.mean([t.entry_slip_bps for t in cl]):+.2f} bps, "
          f"mean spread at entry {np.mean([t.spread_bps_entry for t in cl]):.2f} bps\n")
        er = Counter(t.exit_reason for t in cl)
        P("exit reasons: " + ", ".join(f"{k}={v}" for k, v in er.items()) + "\n")
        P(md_table(["market", "side", "mode", "hold s", "entry", "exit", "gross bps", "net bps", "R", "exit"],
                   [[t.market, "L" if t.side > 0 else "S", t.mode, _f(t.hold_s, 1), f"{t.entry_px:.6g}", f"{t.exit_px:.6g}",
                     _f(t.gross_bps, 1, True), _f(t.net_bps, 1, True), _f(t.R, 2, True), t.exit_reason] for t in cl[-12:]]))
    if ag.engine.payload_log:
        P("sample prepared payload (never transmitted):\n")
        P("```json\n" + json.dumps(ag.engine.payload_log[-1], indent=1, default=float) + "\n```\n")

    # ---- CEO
    P("## 9. CEO → CFO/Hunter interventions\n")
    ceo = ag.ceo
    P(f"CEO state: **{ceo.state.value}**, reviews: {len(ceo.reviews)}, interventions: **{len(ceo.interventions)}**\n")
    if ceo.reviews:
        P(md_table(["t", "state", "verdict", "signals", "gross5", "net5", "false-gap", "trades", "exp bps", "realization", "reasons"],
                   [[f"{r['t']-ag.t0:.0f}s", r["state"], r["verdict"], r["kpi"]["n_signals"], r["kpi"]["gross5"], r["kpi"]["net5"],
                     f"{r['kpi']['false_gap']:.0%}", r["kpi"]["trades"], r["kpi"]["exp_bps"], r["kpi"]["realization"],
                     "; ".join(r["reasons"])[:80]] for r in ceo.reviews[-12:]]))
    P("audit trail:\n")
    P("```\n" + ("\n".join(iv.line() for iv in ceo.interventions) or "(no interventions yet)") + "\n```\n")
    P("## 10. Caveats\n")
    P("* Quotes are timestamped at *our* gateway (cloud container → proxy → venue). Lead-lag below ~100 ms here is measured through that path; a co-located engine would see different lags.\n"
      "* Paper fills use as-of quotes after an assumed order latency; maker fills require the market to trade *through* the resting price (no queue-position credit).\n"
      "* Short sales are simulated (perp-style); on spot they would be unavailable.\n")
    return "\n".join(L)


def summary_json(ag: Agency, t_now: float) -> dict:
    cr = ag.cfo.report()
    return {"duration_s": t_now - ag.t0, "markets": ag.book.M, "signals": ag.hunter.n_signals, "impulses": ag.hunter.n_impulses,
            "cfo": cr, "engine": ag.engine.stats(), "interventions": [iv.as_dict() for iv in ag.ceo.interventions],
            "ceo_state": ag.ceo.state.value, "scan_latency_us": ag.scan_lat.summary(), "decide_latency_us": ag.decide_lat.summary(),
            "markout_all": {str(h): v for h, v in ag.cfo.markouts.table(now=ag.last_t).items()},
            "markout_approved": {str(h): v for h, v in ag.cfo.markouts.table(cohort="approved", now=ag.last_t).items()}}


# =====================================================================================================================
# Phase 4 report: venue & microstructure specialization
# =====================================================================================================================
RUN1 = {   # Run A (live, 15 min, 60 same-venue USDT alts, 7.5 bps/side) — docs/live_runs/runA_live_fee7.5_900s
    "signals": 197, "approved": 0, "gross5": -0.09, "hit_gross5": 0.34, "net5": -17.31, "net0_5": -2.31, "closed": 0, "pnl": 0.0,
    "tight_net0_5": 0.98, "tight_hit": 0.77, "tight_n": 35, "gross1": 0.25, "gross30": 0.45,
}


def _csem(rows, key):
    from .cfo_agent import _cluster_se
    return _cluster_se(rows, key) if len(rows) > 1 else 0.0


def _agg(rows, h_rows=None):
    n = len(rows)
    if not n:
        return None
    g = np.array([r["gross"] for r in rows]); n0 = np.array([r["net0"] for r in rows]); nt = np.array([r["net"] for r in rows])
    return {"n": n, "imp": len({r["imp"] for r in rows}), "gross": float(g.mean()), "gross_se": _csem(rows, "gross"), "net0": float(n0.mean()),
            "net0_se": _csem(rows, "net0"), "net": float(nt.mean()), "hit_g": float((g > 0).mean()), "hit_n0": float((n0 > 0).mean())}


def _fee_class(ag, market: str) -> str:
    m = ag.book.metas[ag.book.index[market]]
    if m.venue == "binance":
        return "Binance, assumed zero-fee" if m.fee_taker_bps == 0.0 else "Binance, 7.5 bps"
    return f"{m.venue} ({m.kind})"


def _fmt_stats(a, nd=2):
    if a is None:
        return ["0", "-", "-", "-", "-", "-"]
    return [a["n"], f"{a['gross']:+.{nd}f}", f"{a['net0']:+.{nd}f}±{a['net0_se']:.{nd}f}", f"{a['net']:+.{nd}f}", f"{a['hit_g']*100:.0f}%", f"{a['hit_n0']*100:.0f}%"]


def build_report_p4(ag: Agency, t_now: float, info: Optional[dict] = None) -> str:
    info = info or {}
    cfg = ag.cfg
    L = []
    P = L.append
    dur = t_now - ag.t0
    metas = ag.book.metas
    byv = Counter((m.venue, m.kind) for m in metas)
    P("# Quant Agency — Phase 4 report: venue & microstructure specialization\n")
    P(f"* mode **{info.get('mode','live')}**, duration **{dur:.0f}s**, **{ag.book.M}** markets: " + ", ".join(f"{v}/{k}: {n}" for (v, k), n in sorted(byv.items())))
    P(f"* hard microstructure gate: directional trades require live spread ≤ **{cfg.cfo.max_spread_bps} bps** (CFO rule; wider signals are shadow-tracked, `rejected_gate` cohort). "
      f"Prediction markets use their own cost model (spread + price-dependent taker fee).")
    P(f"* order latency assumed **{cfg.cfo.latency_s*1000:.0f} ms**; shadow trackers re-score every signal at {', '.join(f'{l*1000:.0f} ms' for l in ag.alt_trackers)}.")
    P("\n> **FEE ASSUMPTIONS (not verifiable from public data):** zero fee on Binance `*FDUSD`, `BTCUSDC`, `ETHUSDC` (per the operator brief; promotions change), "
      "7.5 bps elsewhere on Binance; public retail taker fees Gate 20 / Kraken 40 / Coinbase 60 / Hyperliquid 4.5 / Deribit 5 bps; Polymarket taker `0.07·p·(1−p)` per share "
      "(≈ 350 bps at p = 0.5), makers free. Every table below also shows **zero-fee net** (`net0`) so conclusions do not depend on them.\n")

    # ---- feeds
    P("## 1. Feed health & internal latency\n")
    rows = []
    for name, st in info.get("feeds", {}).items():
        rows.append([name, st.msgs, st.quotes, f"{st.msgs/max(dur,1e-9):.0f}/s", st.reconnects, st.errors, "yes" if getattr(st, 'up_at_end', st.connected) else "no", st.last_error or "-"])
    P(md_table(["feed", "msgs", "quotes", "rate", "reconnects", "errors", "up", "last error"], rows))
    sl, dl = ag.scan_lat.summary(), ag.decide_lat.summary()
    if sl.get("n"):
        P(f"* scan→gate (all {ag.book.M-1} markets + arb + prediction): n={sl['n']} p50={sl['p50']:.0f}µs p90={sl['p90']:.0f}µs p99={sl['p99']:.0f}µs max={sl['max']/1000:.1f}ms")
    if dl.get("n"):
        P(f"* BTC tick → approved executable payload: n={dl['n']} p50={dl['p50']:.0f}µs p99={dl['p99']:.0f}µs")
    quiet = [m.id for i, m in enumerate(metas) if ag.book.state[i, 9] == 0]
    P(f"* markets that never ticked: {len(quiet)}" + (f" ({', '.join(quiet[:12])}{'…' if len(quiet) > 12 else ''})" if quiet else "") + "\n")

    allrows = ag.cfo.markouts.rows
    dir_rows = [r for r in allrows if r["kind"] != "prediction" and r["h"] == 5.0]
    # ---- gate analysis
    P("## 2. Battleground 1 — the `< 0.5 bps` hypothesis, tested out-of-sample\n")
    P("*Pre-registered claim (from Run 1, n = 35, **zero latency, zero fee**): signals in markets with live spread < 0.5 bps have net@5s > 0 and hit-rate > 60 %. "
      "Here it is re-tested on a fresh live session at **realistic latency**. `net0` = spread-crossing net with zero fees; cluster-robust s.e. over BTC impulses.*\n")
    buckets = [(0, 0.5), (0.5, 1.0), (1.0, 3.0), (3.0, 1e9)]
    body = []
    for lo, hi in buckets:
        rr = [r for r in dir_rows if lo <= r["spread"] < hi]
        body.append([f"{lo:g}–{hi:g} bps" if hi < 1e8 else f"≥{lo:g} bps"] + _fmt_stats(_agg(rr)))
    P(md_table(["spread bucket (all directional signals, all venues, t+5s)", "n", "gross bps", "net0 bps ±s.e. (zero fee)", "net (mixed venue fees)", "hit gross", "hit net0"], body))
    P("*The `net (mixed venue fees)` column blends 0 bps (assumed Binance promo pairs) with 60 bps (Coinbase); read `net0` for the microstructure question and the per-fee-class tables below for the economics.*\n")
    tight = [r for r in dir_rows if r["spread"] < 0.5]
    a_t = _agg(tight)
    P("**Latency sensitivity of the tight-spread cohort (same signals re-scored at different order latencies; t+5s):**\n")
    lat_rows = []
    trackers = {ag.cfg.cfo.latency_s: ag.cfo.markouts, **ag.alt_trackers}
    for lat in sorted(trackers):
        rr = [r for r in trackers[lat].rows if r["kind"] != "prediction" and r["h"] == 5.0 and r["spread"] < 0.5]
        lat_rows.append([f"{lat*1000:.0f} ms"] + _fmt_stats(_agg(rr)))
    P(md_table(["order latency", "n", "gross bps", "net0 bps ±s.e.", "net (assumed fees)", "hit gross", "hit net0"], lat_rows))
    trk0 = ag.alt_trackers.get(0.0)
    for lab, tk in (("150 ms", ag.cfo.markouts), ("0 ms", trk0)):
        if tk is None:
            continue
        rr = [r for r in tk.rows if r["kind"] != "prediction" and r["h"] == 5.0 and r["spread"] < 0.5]
        by = {}
        for r in rr:
            by.setdefault(_fee_class(ag, r["market"]), []).append(r)
        P(f"**Tight cohort (<0.5 bps) by venue / fee class — order latency {lab}, t+5s:**\n")
        P(md_table(["class", "n", "gross bps", "net0 bps ±s.e.", "net (assumed fees)", "hit gross", "hit net0"],
                   [[k] + _fmt_stats(_agg(v)) for k, v in sorted(by.items(), key=lambda kv: -len(kv[1]))]))
    if a_t:
        verdict = ("SUPPORTED" if (a_t["net0"] - 2 * a_t["net0_se"] > 0 and a_t["hit_n0"] > 0.6) else
                   "NOT SUPPORTED at 2σ" if a_t["net0"] - 2 * a_t["net0_se"] <= 0 else "mixed")
        P(f"\n**Claim check (150 ms): n={a_t['n']} over {a_t['imp']} BTC impulses, net0 {a_t['net0']:+.2f}±{a_t['net0_se']:.2f} bps, hit {a_t['hit_n0']*100:.0f}% → {verdict}.** "
          f"(Run 1: n=35, +0.98 bps, 77 % at zero latency.)\n")
    P("**Fee sensitivity (tight cohort, t+5s): net = net0 − 2·fee** → " + ", ".join(f"fee {f:g} bps: {(a_t['net0'] - 2*f):+.2f}" if a_t else "-" for f in (0, 1, 4.5, 7.5)) + "\n")

    cr = ag.cfo.report()
    P("## 3. CFO gating (this run) vs Run 1\n")
    nsig = ag.hunter.n_signals + (ag.pm.n_signals if ag.pm else 0)
    reasons = ", ".join(f"{k}={v}" for k, v in sorted(cr["reasons"].items(), key=lambda kv: -kv[1]))
    P(f"evaluated {cr['evaluated']}, approved **{cr['approved']}** ({cr['approved']/max(cr['evaluated'],1)*100:.1f}%); reasons: {reasons}\n")

    # ---- cross venue lead-lag
    P("## 4. Cross-venue lead-lag (BTC oracle → other venues' books, same assets)\n")
    cv = [r for r in allrows if r["h"] == 5.0 and r["venue"] not in ("binance", "polymarket")]
    rows4 = []
    for v in ("gate", "kraken", "coinbase", "hyperliquid", "deribit"):
        rr = [r for r in cv if r["venue"] == v]
        rows4.append([v] + _fmt_stats(_agg(rr)))
    P(md_table(["venue (t+5s)", "n", "gross bps", "net0 bps ±s.e.", "net (assumed fees)", "hit gross", "hit net0"], rows4))
    tbl = [r for r in ag.hunter.model.table() if r["calibrated"] and ":" in r["market"]]
    tbl.sort(key=lambda r: -r["rho"])
    P("lead-lag map, cross-venue books (HY lag vs the Binance BTC oracle):\n")
    P(md_table(["market", "β", "t(β)", "ρ", "lag s"], [[r["market"], _f(r["beta"]), _f(r["tstat"], 1), _f(r["rho"]), _f(r["lag_s"], 1)] for r in tbl[:12]]))

    # ---- arb
    ar = ag.arb.summary()
    P("## 5. Direct cross-venue & triangular arbitrage (locked gaps, basis-adjusted)\n")
    P(f"{ar['pairs']} same-asset pairs + {ar['triangles']} triangles scanned ({ar['scans']} scans). **Episodes with a positive basis-adjusted gross gap: {ar['episodes']}** "
      f"(gap p50 {ar['gap_p50']:.2f}, p90 {ar['gap_p90']:.2f}, max {ar['gap_max']:.2f} bps; lifetime p50 {ar['life_p50']:.2f}s, p90 {ar['life_p90']:.2f}s).\n")
    P(md_table(["metric", "count"], [["gross gap ≥ record threshold", ar["gross_gt_0"]], ["net of fees+slippage+hurdle > 0 at detection", ar["net_gt_0_at_detect"]],
                                      ["net > 0 still true after order latency (persistence)", ar["net_gt_0_at_fill"]], ["executed (both/any legs)", ar["executed"]],
                                      ["paper PnL $", f"{ar['pnl_usd']:+.2f}"], ["mean gap at fill time (bps)", f"{ar['gap_fill_mean']:+.2f}"]]))
    P("reasons: " + ", ".join(f"{k}={v}" for k, v in ar["reasons"].items()) + "\n")
    ex = sorted(ag.arb.pair_stats.items(), key=lambda kv: -kv[1]["n"])
    ex = [(k, v) for k, v in ex if v["locked"] or v["leg_risk"]][:10]
    if ex:
        P("**Executed arb by pair** (`locked` = both legs filled at the detected prices; `leg_risk` = one leg missed and the other was unwound):\n")
        P(md_table(["pair", "opps", "locked", "leg-risk", "missed", "paper PnL $"], [[k, v["n"], v["locked"], v["leg_risk"], v["missed"], f"{v['pnl']:+.3f}"] for k, v in ex]))
    nz = sum(1 for o in ag.arb.opps if o.status in ("locked", "leg_risk") and o.fee_bps == 0.0)
    nex = sum(1 for o in ag.arb.opps if o.status in ("locked", "leg_risk"))
    P(f"*{nz} of {nex} executed arb trades had a total modelled fee of 0 bps (the assumed zero-fee Binance pairs). 'Locked' profit is **basis-adjusted**: it assumes the "
      "stable-coin / quote-currency basis reverts to its EW mean; it is not risk-free.*\n")
    top = sorted([o for o in ag.arb.opps], key=lambda o: -o.gap_bps)[:10]
    P(md_table(["name", "kind", "gap bps", "fees", "slip", "net@detect", "gap@fill", "status", "approved/reason"],
               [[o.name, o.kind, _f(o.gap_bps), _f(o.fee_bps), _f(o.slip_bps), _f(o.net_bps, 2, True), _f(o.gap_fill_bps), o.status, f"{o.approved}/{o.reason}"] for o in top]))

    # ---- polymarket
    P("## 6. Battleground 2 — Polymarket CLOB (50+ BTC markets) driven by the Binance oracle\n")
    if ag.pm is None:
        P("_(not enabled in this run)_\n")
    else:
        pm = ag.pm
        P(f"{len(pm.specs)} BTC markets watched ({Counter(s.kind for s in pm.specs.values())}), book updates: {int(sum(ag.book.state[i, 9] for i in pm.pm_idx))}, scans {pm.n_scans}, **signals {pm.n_signals}**.\n")
        pmrows = [r for r in allrows if r["kind"] == "prediction"]
        mk = []
        for h in (1.0, 3.0, 5.0, 10.0, 30.0):
            rr = [r for r in pmrows if r["h"] == h]
            a = _agg(rr)
            mk.append([f"t+{h:g}s"] + _fmt_stats(a))
        P(md_table(["Polymarket markouts", "n", "gross bps", "net0 bps ±s.e.", "net (taker fee schedule)", "hit gross", "hit net0"], mk))
        P("**Economics in cents per share (bps of notional is distorted by contracts priced near 0 or 1, where one tick is a 100 % move)** — t+5s, taker both ways:\n")
        cents = []
        for lab, lo, hi in (("p < 0.10 or > 0.90 (near-decided)", None, None), ("0.10 ≤ p ≤ 0.90 (live)", 0.10, 0.90)):
            rr = [r for r in pmrows if r["h"] == 5.0 and ((r["px"] < 0.10 or r["px"] > 0.90) if lo is None else (lo <= r["px"] <= hi))]
            if not rr:
                continue
            gc = np.array([r["gross"] * r["px"] / 1e4 * 100 for r in rr]); n0c = np.array([r["net0"] * r["px"] / 1e4 * 100 for r in rr])
            nc = np.array([r["net"] * r["px"] / 1e4 * 100 for r in rr]); spc = np.array([r["spread"] * r["px"] / 1e4 * 100 for r in rr])
            feec = np.array([(r["net0"] - r["net"]) * r["px"] / 1e4 * 100 for r in rr])
            se = _csem([{"imp": r["imp"], "net": x} for r, x in zip(rr, n0c)], "net")
            cents.append([lab, len(rr), len({r['imp'] for r in rr}), f"{gc.mean():+.2f}", f"{spc.mean():.2f}", f"{n0c.mean():+.2f}±{se:.2f}", f"{feec.mean():.2f}", f"{nc.mean():+.2f}"])
        P(md_table(["price bucket", "n", "impulses", "gross ¢/share", "spread ¢", "net0 ¢ ±s.e.", "taker fee ¢ (2 sides)", "net ¢ (after fees)"], cents))
        g5 = [r for r in pmrows if r["h"] == 5.0]
        if g5:
            P(f"mean signalled gap {np.mean([abs(r['gap']) for r in g5]):.0f} bps vs mean spread {np.mean([r['spread'] for r in g5]):.0f} bps; "
              f"mean taker fee drag {np.mean([r['net0']-r['net'] for r in g5]):.0f} bps round-trip.\n")
        cr_rows = pm.ctrl_rows
        if cr_rows:
            P("**Momentum control — did the CLOB converge to fair value, or did BTC just keep moving?** "
              "`gap` = fair-value move minus CLOB move at signal time (prob. points, signed to the trade). After h seconds: `fair drift` = how far the model fair value moved "
              "(pure BTC drift), `CLOB move` = how far the CLOB mid moved. If the CLOB merely tracks fair value, CLOB move ≈ fair drift and **closure ≈ 0**.\n")
            ctl = []
            for h in (5.0, 30.0):
                for fam, pred in (("all", lambda r: True), ("updown_twap", lambda r: r["kind"] == "updown_twap"),
                                  ("updown_terminal", lambda r: r["kind"] == "updown_terminal"),
                                  ("above/below/range", lambda r: r["kind"] in ("above", "below", "range"))):
                    rr = [r for r in cr_rows if r["h"] == h and pred(r)]
                    if not rr:
                        continue
                    g = np.array([r["gap_p"] for r in rr]); f = np.array([r["fair_move"] for r in rr]); m = np.array([r["mkt_move"] for r in rr])
                    resid = [{"imp": r["imp"], "x": r["mkt_move"] - r["fair_move"]} for r in rr]
                    se = _csem([{"imp": x["imp"], "net": x["x"]} for x in resid], "net")
                    ctl.append([f"t+{h:g}s", fam, len(rr), len({r['imp'] for r in rr}), f"{g.mean()*100:+.2f}", f"{f.mean()*100:+.2f}", f"{m.mean()*100:+.2f}",
                                f"{(m.mean()-f.mean())*100:+.2f}±{se*100:.2f}", f"{(m.mean()-f.mean())/g.mean():+.2f}" if abs(g.mean()) > 1e-9 else "-"])
            P(md_table(["horizon", "family", "n", "impulses", "gap ¢", "fair drift ¢", "CLOB move ¢", "CLOB − fair ¢ ±s.e.", "closure of gap"], ctl))
        tb = sorted(pm.table(t_now), key=lambda r: -r["signals"])[:12]
        P(md_table(["market", "kind", "ttl min", "ticks", "mid", "spread ¢", "signals"], [[r["market"], r["kind"], _f(r["ttl_min"], 0), r["ticks"], _f(r["mid"], 3), _f(r["spread_c"], 1), r["signals"]] for r in tb]))
        pr = {k: v for k, v in ag.cfo.reasons.items()}
        P(f"coverage rejects: {pm.coverage_rejects}\n")

    # ---- before / after
    P("## 7. Before / after vs Run 1\n")
    all5 = [r for r in allrows if r["h"] == 5.0 and r["kind"] != "prediction"]
    a_all = _agg(all5)
    all1 = _agg([r for r in allrows if r["h"] == 1.0 and r["kind"] != "prediction"])
    all30 = _agg([r for r in allrows if r["h"] == 30.0 and r["kind"] != "prediction"])
    tr = ag.engine.closed
    ra = lambda x: "-" if x is None else x
    rowsba = [
        ["directional signals detected", RUN1["signals"], ag.hunter.n_signals],
        ["CFO-approved (all signal types)", RUN1["approved"], f"{cr['approved']} ({cr['approved']/max(cr['evaluated'],1)*100:.1f}%)"],
        ["gross markout @1s (directional)", f"{RUN1['gross1']:+.2f}", "-" if not all1 else f"{all1['gross']:+.2f}"],
        ["gross markout @5s (directional)", f"{RUN1['gross5']:+.2f}", "-" if not a_all else f"{a_all['gross']:+.2f}"],
        ["gross markout @30s (directional)", f"{RUN1['gross30']:+.2f}", "-" if not all30 else f"{all30['gross']:+.2f}"],
        ["hit rate gross @5s", f"{RUN1['hit_gross5']*100:.0f}%", "-" if not a_all else f"{a_all['hit_g']*100:.0f}%"],
        ["net0 (zero-fee, crosses spread) @5s", f"{RUN1['net0_5']:+.2f}", "-" if not a_all else f"{a_all['net0']:+.2f}"],
        ["tight-spread (<0.5 bps) net0 @5s [n, hit]", f"{RUN1['tight_net0_5']:+.2f} [{RUN1['tight_n']}, {RUN1['tight_hit']*100:.0f}%; zero latency]",
         "-" if not a_t else f"{a_t['net0']:+.2f}±{a_t['net0_se']:.2f} [{a_t['n']}, {a_t['hit_n0']*100:.0f}%; 150 ms]"],
        ["closed paper trades / PnL", f"{RUN1['closed']} / ${RUN1['pnl']:.2f}", f"{len(tr)} / ${sum(t.net_pnl_usd for t in tr):+.2f}"],
        ["arb episodes net>0 after fees", "n/a", ar["net_gt_0_at_detect"]],
        ["Polymarket signals", "n/a", ag.pm.n_signals if ag.pm else 0],
    ]
    P(md_table(["metric", "Run 1 (60 USDT alts, live)", "Phase 4 (this run)"], rowsba))

    # ---- trades & CEO via generic report
    P("\n---\n# Appendix: generic agency telemetry (CFO, markouts, execution, CEO)\n")
    gen = build_report(ag, t_now, info)
    gen = gen.split("## 1. Feed health & internal latency", 1)[-1]
    P("## (generic) Feed health" + gen)
    return "\n".join(L)


# =====================================================================================================================
# Phase 5 report: queue-aware passive maker sniper
# =====================================================================================================================
P4_REF = {   # Phase 4 (taker) reference numbers, same venues, 150 ms: docs/PHASE4.md
    "hl": {"n": 92, "gross": 2.45, "net0": 1.65, "net": -7.35, "hit": 0.84},
    "pm": {"gross_c": 2.33, "spread_c": 2.17, "net0_c": 0.48, "fee_c": 2.87, "net_c": -2.39, "n": 105},
}
VORDER = ["taker/taker", "taker/passive", "join/taker-exit+shield", "join/passive noshield", "join/passive+shield", "penny/passive+shield"]


def _sn_rows(sn, venue, model, variant):
    return sn.rows(variant=variant, model=model, venue=venue, account=False)


def _sn_table(sn, venue, model, pm: bool):
    from .cfo_agent import _cluster_se
    body = []
    for v in VORDER:
        rs = _sn_rows(sn, venue, model, v)
        if not rs:
            continue
        s = sn.summarize(rs)
        f = [r for r in rs if r["outcome"] == "filled"]
        se = _cluster_se(f, "net_bps") if len(f) > 1 else 0.0
        att = [{"imp": r["imp"], "net": (r["net_bps"] if r["outcome"] == "filled" else 0.0)} for r in rs]
        se_a = _cluster_se(att, "net") if len(att) > 1 else 0.0
        row = [v, s["n"], s["filled"], f"{s['fill_rate']*100:.0f}%", f"{s['net_bps_per_fill']:+.2f}±{se:.2f}", f"{s['hit']*100:.0f}%",
               f"{s['net_bps_per_attempt']:+.2f}±{se_a:.2f}", f"{s['markout5_per_fill']:+.2f}", s["fill_during_cancel"], s["shield"]]
        if pm:
            row.insert(5, f"{s['net_cents_per_fill']:+.2f}")
        body.append(row)
    head = ["variant", "attempts", "filled", "fill rate", "net bps / fill ±s.e.", "hit", "net bps / attempt ±s.e.", "5s markout after fill (bps)", "fills in cancel window", "shield cancels"]
    if pm:
        head.insert(5, "net ¢/share / fill")
    return md_table(head, body)


def build_report_p5(ag: Agency, t_now: float, info: Optional[dict] = None) -> str:
    from .cfo_agent import _cluster_se
    info = info or {}
    cfg = ag.cfg
    sn = ag.sniper
    L = []
    P = L.append
    dur = t_now - ag.t0
    metas = ag.book.metas
    nhl = sum(1 for m in metas if m.venue == "hyperliquid")
    npm = sum(1 for m in metas if m.venue == "polymarket")
    prints = bool(getattr(ag, "snipe_has_prints", ag.n_mkt_trades > 0))
    P("# Quant Agency — Phase 5 report: queue-aware passive maker sniper\n")
    P(f"* mode **{info.get('mode','live')}**, duration **{dur:.0f}s**; markets: Binance BTC oracle, **{nhl} Hyperliquid perps**, **{npm} Polymarket BTC markets**; "
      f"trade prints recorded: **{ag.n_mkt_trades}** ({'real fills are modelled from prints' if prints else 'NO trade tape → fills are bounded, not observed'}).")
    P(f"* order latency **{cfg.snipe.order_latency_s*1000:.0f} ms**, cancel latency **{cfg.snipe.cancel_latency_s*1000:.0f} ms**; shield: cancel when < {cfg.snipe.hold_frac:.0%} of the impulse is intact, on a "
      f"{cfg.snipe.rev_bps} bps reversal, or when the venue already did {cfg.snipe.converge_frac:.0%} of the gap; TTL {cfg.snipe.ttl_s}; passive-exit work window {cfg.snipe.work_s} then taker fallback.")
    hl = [m for m in metas if m.venue == "hyperliquid"]
    P(f"* **fees (assumptions):** Hyperliquid maker {hl[0].fee_maker_bps if hl else '-'} bps / taker {hl[0].fee_taker_bps if hl else '-'} bps per side (public base tier; the brief says ~1 bp maker — "
      f"every table is linear in that: Δnet = −2·Δfee); Polymarket maker 0, taker `0.07·p·(1−p)` per share.")
    P("""
**Fill models** (an order sits behind the visible size at its price, or at the front if it penny-jumps inside the spread):
`strict` — fill only when the opposite touch crosses our price (certain, lower bound) ·
`depletion` — displayed-size depletion at our level counts as trades (optimistic upper bound; the only other option when no trade tape exists) ·
`trades` — real trade prints consume the queue ahead of us and sweep through on prints beyond our price (live only).
Cancels take effect after the cancel latency; fills inside that window are real and counted.
""")
    models = [m for m in ("strict", "depletion", "trades") if any(r["model"] == m for r in sn.results)]
    for venue, label, pm in (("hyperliquid", "Hyperliquid perps (ALO maker, 1 tick spread)", False), ("polymarket", "Polymarket CLOB (post-only, 0 maker fee)", True)):
        P(f"## {label}\n")
        sigs = len({r["sid"] for r in sn.results if r["venue"] == venue})
        P(f"{sigs} signals; every variant below runs on **exactly these signals** with identical paper size "
          f"({'$%.0f' % cfg.snipe.hl_notional if not pm else '$%.0f' % cfg.snipe.pm_notional}).\n")
        for m in models:
            P(f"**fill model: `{m}`**\n")
            P(_sn_table(sn, venue, m, pm))
    # ---- mechanics
    P("## Mechanics: why orders do or don't fill, and where the edge goes\n")
    body = []
    for venue in ("hyperliquid", "polymarket"):
        sigs_ = [r for r in sn.results if r["venue"] == venue and r["variant"] == "taker/taker" and r["model"] == models[0]]
        if sigs_:
            ratios = []
            for r in sigs_:
                meta = ag.book.metas[ag.book.index[r["market"]]]
                tick = meta.tick if meta.tick > 0 else sn.tick_est.get(ag.book.index[r["market"]], 0.0)
                tick_bps = tick / r["mid0"] * 1e4 if r["mid0"] else 0.0
                if tick_bps > 0:
                    ratios.append(abs(r["gap_bps"]) / tick_bps)
            body.append([venue, len(sigs_), f"{np.median([abs(r['gap_bps']) for r in sigs_]):.1f}", f"{np.median([r['spread_bps'] for r in sigs_]):.2f}",
                         f"{np.median(ratios):.2f}" if ratios else "-", f"{np.mean([x < 1.0 for x in ratios])*100:.0f}%" if ratios else "-"])
    P("**Signalled gap vs the price grid** — if the whole gap is smaller than one tick, a resting order cannot capture it: it only fills after the book has already moved a tick.\n")
    P(md_table(["venue", "signals", "median |gap| bps", "median spread bps", "median gap / tick", "signals with gap < 1 tick"], body))
    body = []
    for venue in ("hyperliquid", "polymarket"):
        for m in models:
            rs = _sn_rows(sn, venue, m, "join/passive+shield")
            if not rs:
                continue
            f = [r for r in rs if r["outcome"] == "filled"]
            why = {}
            for r in rs:
                if r["outcome"] != "filled":
                    why[r["reason"] or "?"] = why.get(r["reason"] or "?", 0) + 1
            ex = {}
            for r in f:
                ex[r["exit_kind"]] = ex.get(r["exit_kind"], 0) + 1
            body.append([venue, m, len(rs), ", ".join(f"{k}={v}" for k, v in sorted(why.items(), key=lambda kv: -kv[1])) or "-",
                         ", ".join(f"{k}={v}" for k, v in ex.items()) or "-",
                         f"{np.mean([r['gross_bps'] for r in f]):+.2f}" if f else "-", f"{np.mean([r['fees_usd']/r['notional']*1e4 for r in f]):.2f}" if f else "-"])
    P("**`join/passive+shield`: no-fill reasons, exit mix, gross and fees per fill (bps of notional):**\n")
    P(md_table(["venue", "model", "attempts", "not filled because", "exit mix of fills", "gross bps / fill", "fees bps / fill"], body))
    # ---- shield value
    P("## Does the oracle cancel shield earn its keep?\n")
    body = []
    for venue in ("hyperliquid", "polymarket"):
        for m in models:
            a = _sn_rows(sn, venue, m, "join/passive+shield")
            b = _sn_rows(sn, venue, m, "join/passive noshield")
            if not a or not b:
                continue
            sa, sb = sn.summarize(a), sn.summarize(b)
            body.append([venue, m, f"{sa['fill_rate']*100:.0f}% vs {sb['fill_rate']*100:.0f}%", f"{sa['net_bps_per_fill']:+.2f} vs {sb['net_bps_per_fill']:+.2f}",
                         f"{sa['net_bps_per_attempt']:+.2f} vs {sb['net_bps_per_attempt']:+.2f}", f"{sa['markout5_per_fill']:+.2f} vs {sb['markout5_per_fill']:+.2f}", sa["shield"]])
    P(md_table(["venue", "fill model", "fill rate (shield vs none)", "net bps/fill", "net bps/attempt", "5s markout after fill", "orders pulled"], body))
    # ---- adverse selection
    P("## Adverse selection: filled orders vs the same signals' unconditional markout\n")
    P("`unconditional` = mid-to-mid gross markout at t+5s of *all* signals on that venue (what a taker captures before costs); `conditional` = markout after a passive fill. "
      "A negative gap is the adverse-selection tax on maker fills.\n")
    body = []
    for venue in ("hyperliquid", "polymarket"):
        un = [r["gross"] for r in ag.cfo.markouts.rows if r["venue"] == venue and r["h"] == 5.0]
        for m in models:
            rs = [r for r in _sn_rows(sn, venue, m, "join/passive+shield") if r["outcome"] == "filled" and np.isfinite(r["markout5_bps"])]
            if not rs or not un:
                continue
            c = float(np.mean([r["markout5_bps"] for r in rs]))
            body.append([venue, m, len(un), f"{np.mean(un):+.2f}", len(rs), f"{c:+.2f}", f"{c-np.mean(un):+.2f}"])
    P(md_table(["venue", "fill model", "n signals", "unconditional gross bps", "n fills", "conditional markout bps", "adverse-selection gap"], body))
    # ---- cancel latency
    P("## Cancel-latency adverse fills\n")
    body = []
    for venue in ("hyperliquid", "polymarket"):
        for m in models:
            rs = [r for r in sn.rows(model=m, venue=venue, account=False) if r["outcome"] == "filled" and r["variant"] in ("join/passive+shield", "penny/passive+shield", "join/taker-exit+shield")]
            f_in = [r for r in rs if r["fill_during_cancel"]]
            f_out = [r for r in rs if not r["fill_during_cancel"]]
            if not rs:
                continue
            body.append([venue, m, len(rs), len(f_in), f"{np.mean([r['net_bps'] for r in f_in]):+.2f}" if f_in else "-", f"{np.mean([r['net_bps'] for r in f_out]):+.2f}" if f_out else "-"])
    P(md_table(["venue", "fill model", "shield-variant fills", "of which inside the cancel window", "mean net bps (inside)", "mean net bps (other fills)"], body))
    # ---- before / after
    P("## Before / after: Phase 4 taker vs Phase 5 maker (same venues, same assumptions)\n")
    ref = P4_REF
    for venue in ("hyperliquid",):
        m0 = "strict" if "strict" in models else models[0]
        t = sn.summarize(_sn_rows(sn, venue, m0, "taker/taker"))
        mj = sn.summarize(_sn_rows(sn, venue, m0, "join/passive+shield"))
        mjd = sn.summarize(_sn_rows(sn, "hyperliquid", "depletion", "join/passive+shield")) if "depletion" in models else None
        mjt = sn.summarize(_sn_rows(sn, "hyperliquid", "trades", "join/passive+shield")) if "trades" in models else None
        body = [["Phase 4 report (taker, 150 ms, all HL signals)", ref["hl"]["n"], "100%", f"{ref['hl']['net']:+.2f}", "-"],
                ["Phase 5 `taker/taker` (same engine, same signals as below)", t.get("n", 0), "100%" if t.get("n") else "-", f"{t.get('net_bps_per_fill', 0):+.2f}", f"{t.get('net_bps_per_attempt', 0):+.2f}"]]
        for lab, s_ in (("join/passive+shield, strict (lower bound)", mj), ("join/passive+shield, depletion (upper bound)", mjd), ("join/passive+shield, trades (observed prints)", mjt)):
            if s_ and s_.get("n"):
                body.append([f"Phase 5 {lab}", s_["n"], f"{s_['fill_rate']*100:.0f}%", f"{s_['net_bps_per_fill']:+.2f}", f"{s_['net_bps_per_attempt']:+.2f}"])
        P("**Hyperliquid, net bps (after fees):**\n")
        P(md_table(["configuration", "signals/attempts", "fill rate", "net bps / fill", "net bps / attempt (unfilled = 0)"], body))
    body = []
    t = sn.summarize(_sn_rows(sn, "polymarket", models[0], "taker/taker"))
    body.append(["Phase 4 report (taker, live-priced contracts)", ref["pm"]["n"], "100%", f"{ref['pm']['net_c']:+.2f}", "-"])
    body.append(["Phase 5 `taker/taker` baseline", t.get("n", 0), "100%" if t.get("n") else "-", f"{t.get('net_cents_per_fill', 0):+.2f}", "-"])
    for m in models:
        for v in ("join/passive+shield", "penny/passive+shield"):
            s_ = sn.summarize(_sn_rows(sn, "polymarket", m, v))
            if s_.get("n"):
                rs = _sn_rows(sn, "polymarket", m, v)
                per_att = sum(r["net_cents"] for r in rs if r["outcome"] == "filled") / len(rs)
                body.append([f"Phase 5 {v}, {m}", s_["n"], f"{s_['fill_rate']*100:.0f}%", f"{s_['net_cents_per_fill']:+.2f}", f"{per_att:+.2f}"])
    P("**Polymarket, net ¢ per share (after fees):**\n")
    P(md_table(["configuration", "signals/attempts", "fill rate", "net ¢ / fill", "net ¢ / attempt (unfilled = 0)"], body))
    # ---- account
    P("## CFO-accounted maker attempts and CEO monitoring\n")
    ar = sn.account_results
    fl = [r for r in ar if r["outcome"] == "filled"]
    cr = ag.cfo.report()
    P(f"account attempts {len(ar)}, filled {len(fl)} ({len(fl)/max(len(ar),1)*100:.0f}%), net PnL ${sum(r['net_usd'] for r in fl):+.2f}, equity ${cr['equity']:,.2f}; "
      f"learned P(fill) {ag.cfo.cfg.snipe_p_fill:.2f}, P(passive exit) {ag.cfo.cfg.snipe_p_exit_maker:.2f}, adverse buffers {ag.cfo.cfg.snipe_adverse_bps}, CFO reasons: "
      + ", ".join(f"{k}={v}" for k, v in sorted(cr['reasons'].items(), key=lambda kv: -kv[1])) + "\n")
    if fl:
        P(md_table(["market", "side", "entry", "mode", "wait s", "entry px", "exit px", "exit", "net bps", "net $", "in cancel window"],
                   [[r["market"][:40], "L" if r["side"] > 0 else "S", r["entry_mode"], r["model"], f"{r['wait_s']:.1f}", f"{r['entry_px']:.5g}", f"{r['exit_px']:.5g}", r["exit_kind"],
                     f"{r['net_bps']:+.1f}", f"{r['net_usd']:+.3f}", r["fill_during_cancel"]] for r in fl[-12:]]))
    ivs = [iv for iv in ag.ceo.interventions if iv.kind.startswith("SNIPE")]
    P("**CEO sniper interventions:**\n")
    P("```\n" + ("\n".join(iv.line() for iv in ivs) or "(none triggered)") + "\n```\n")
    P(f"CEO state {ag.ceo.state.value}; all interventions {len(ag.ceo.interventions)}.\n")
    P("## Caveats\n")
    P("* " + ("Real trade prints were recorded for Hyperliquid and Polymarket in this session; Polymarket aggressor side is inferred from price vs mid. " if prints else
              "**This tape has no trade prints**, so queue consumption is unobservable: `strict`/`depletion` bracket the truth. ") +
      "A real queue also has cancellations ahead of us, hidden/iceberg size and other makers' adverse-selection management, none of which can be observed here.\n"
      "* Shadow variants use a fixed small paper size and do not move the book; the account attempt is CFO-sized. Hyperliquid is 1 tick wide so penny-jumping applies to Polymarket only.\n"
      "* One quiet-regime session; cluster-robust s.e. over BTC impulses are shown and power is low.\n")
    return "\n".join(L)


def _p6_cell(s: dict, pm: bool) -> list:
    if not s.get("n"):
        return ["0", "-", "-", "-", "-"]
    net = f"{s['net_cents']:+.2f}¢ ({s['net_bps']:+.0f} bps)" if pm else f"{s['net_bps']:+.2f} bps"
    return [str(s["n"]), net, f"±{s['se_bps']:.0f}" if pm else f"±{s['se_bps']:.2f}", f"{s['hit']*100:.0f}%", f"{s['net_usd']:+.2f}"]


def _b_rows(hc, venue, model=None, variant=None, floor=None):
    out = []
    for r in hc.results:
        if r["venue"] != venue or (variant is not None and r["variant"] != variant) or (model is not None and r["model"] != model):
            continue
        if floor is not None and bool(r.get("floor_ok")) != floor:
            continue
        out.append(r)
    return out


def _b_stats(rows: list) -> dict:
    n = len(rows)
    f = [r for r in rows if r["outcome"] == "filled"]
    if not f:
        return {"n": n, "filled": 0}
    nb = np.array([r["net_bps"] for r in f])
    se = _csem(f, "net_bps")
    ex = {}
    for r in f:
        k = r["exit_reason"]
        ex[k] = ex.get(k, 0) + 1
    return {"n": n, "filled": len(f), "net_bps": float(nb.mean()), "se": se, "net_cents": float(np.mean([r["net_cents"] for r in f])),
            "net_usd": float(sum(r["net_usd"] for r in f)), "hit": float((nb > 0).mean()), "gross_bps": float(np.mean([r["gross_bps"] for r in f])),
            "exits": ex, "scratched": sum(1 for r in f if r.get("scratched")), "passive": float(np.mean([r["exit_kind"] == "passive" for r in f]))}


def build_report_p6(ag, t_end: float, info: dict) -> str:
    cfg = ag.cfg
    mm, hc = ag.mm, ag.hc
    L = []
    P = L.append
    dur = t_end - ag.t0
    metas = ag.book.metas
    nhl = sum(1 for m in metas if m.venue == "hyperliquid")
    npm = sum(1 for m in metas if m.venue == "polymarket")
    hl = [m for m in metas if m.venue == "hyperliquid"]
    P("# Quant Agency — Phase 6 report: Architecture A (pre-positioned quote maker) vs Architecture B (high-conviction taker sniper)\n")
    P(f"* mode **{info.get('mode','live')}**, duration **{dur:.0f}s**; Binance BTC oracle, **{nhl} Hyperliquid perps**, **{npm} Polymarket markets**; "
      f"trade prints: **{ag.n_mkt_trades}** ({'`trades` fill model is observed' if ag.n_mkt_trades else 'no trade tape: fills bounded by strict/depletion only'}).")
    P(f"* latencies: order **{cfg.mm.order_latency_s*1000:.0f} ms**, cancel **{cfg.mm.cancel_latency_s*1000:.0f} ms** (fills inside the window are real and counted). "
      f"A: quote only while every fast-horizon (0.25/1/3 s) |BTC Z| < **{cfg.mm.calm_z}**, cancel the vulnerable side at Z ≥ **{cfg.mm.impulse_z}**, stay off it {cfg.mm.requote_hold_s} s; "
      f"no quotes inside {cfg.mm.expiry_pull_s:.0f} s of expiry, flat by {cfg.mm.expiry_flat_s:.0f} s (CFO entry guard {cfg.poly.min_ttl_s:.0f} s). "
      f"B: floor **{cfg.cfo.b_floor_mult}x (spread + taker-in + maker-out fee)**.")
    P(f"* **fees (assumptions):** Hyperliquid maker {hl[0].fee_maker_bps if hl else '-'} bps / taker {hl[0].fee_taker_bps if hl else '-'} bps per side; Polymarket maker 0, taker `0.07·p·(1−p)`/share. "
      f"A's HL economics are linear in the maker fee (round trip = 2 x fee vs the spread).")
    if mm is not None:
        cz = mm.calm_frac[0] / max(mm.calm_frac[1], 1e-9)
        P(f"* oracle regime: **{mm.n_impulses} BTC impulses** (Z ≥ {cfg.mm.impulse_z} on a fast horizon, ≥ {cfg.mm.min_abs_bps} bps), calm {cz*100:.0f}% of the time (the window in which A is allowed to quote).")
    models = [m for m in ("strict", "depletion", "trades") if mm is not None and any(r["model"] == m for r in mm.results)] or ["strict"]
    P("")
    # ------------------------------------------------------------- Architecture A
    if mm is not None:
        P("## Architecture A — pre-positioned quote maker with oracle cancel-shield\n")
        P("One clip per market, both sides at the touch while calm; a round trip = maker entry fill + exit (passive at the touch, else taker stop / time stop / shield-flatten). "
          "Net includes both legs' fees and the taker exit when it happens. `noshield` runs the identical quote policy but never cancels on an impulse.\n")
        for venue, pm in (("hyperliquid", False), ("polymarket", True)):
            P(f"### {venue}\n")
            cnt = mm.counters(variant=None, venue=venue)
            if cnt.get("posted", 0) == 0:
                gated = cnt.get("gated_out", 0)
                P(f"**No quote was ever posted** ({gated} gating decisions): the CFO's round-trip economics (spread − 2 x maker fee − adverse buffer − hurdle) were never positive. "
                  f"This is the result, not a bug: with maker fee {hl[0].fee_maker_bps if hl else '-'} bps the two legs cost more than the whole spread.\n" if not pm else "")
                continue
            body = []
            for m in models:
                for v in (f"shield/{m}", f"noshield/{m}"):
                    s = mm.summarize(mm.rows(variant=v, venue=venue))
                    c = mm.counters(variant=v, venue=venue)
                    body.append([v] + _p6_cell(s, pm) + [f"{s.get('passive_exit', 0)*100:.0f}%" if s.get("n") else "-", f"{s.get('in_shield_cancel', 0)} / {s.get('in_cancel', 0)}" if s.get("n") else "-",
                                                         c.get("posted", 0), c.get("shield_cancels", 0), c.get("shield_flatten", 0), c.get("rejected_cross", 0)])
            P(md_table(["variant", "round trips", "net / trip", "cluster s.e.", "hit", "net $", "passive exit", "trips filled in shield-cancel window / any cancel window", "quotes posted", "shield cancels", "shield flattens", "post-only rejects"], body))
            sa = mm.summarize(mm.rows(variant="ACCOUNT", venue=venue))
            if sa.get("n"):
                P(f"**ACCOUNT quoter (CFO-sized, `{cfg.mm.account_model}` fills):** " + ", ".join(f"{x}" for x in _p6_cell(sa, pm)) + f"; exit reasons {sa['reasons']}.\n")
        # shield value
        P("### Does the shield earn its keep? (same quote policy, same ticks)\n")
        body = []
        for venue, pm in (("hyperliquid", False), ("polymarket", True)):
            for m in models:
                a, b = mm.summarize(mm.rows(variant=f"shield/{m}", venue=venue)), mm.summarize(mm.rows(variant=f"noshield/{m}", venue=venue))
                if not a.get("n") and not b.get("n"):
                    continue
                u = (lambda s: f"{s['net_cents']:+.2f}¢" if pm else f"{s['net_bps']:+.2f}bps") if True else None
                body.append([venue, m, f"{a.get('n',0)} vs {b.get('n',0)}", (u(a) if a.get("n") else "-") + " vs " + (u(b) if b.get("n") else "-"),
                             f"{a.get('net_usd',0):+.2f} vs {b.get('net_usd',0):+.2f}", f"{a.get('in_shield_cancel',0)} vs {b.get('in_shield_cancel',0)}"])
        P(md_table(["venue", "fill model", "round trips (shield vs none)", "net / trip", "net $ total", "trips filled in a shield-cancel window"], body))
        # adverse selection
        P("### Adverse selection: when do the entry fills happen?\n")
        body = []
        for venue in ("hyperliquid", "polymarket"):
            for v in [f"noshield/{models[0]}", f"shield/{models[0]}"]:
                rs = mm.rows(variant=v, venue=venue)
                if not rs:
                    continue
                ai = [r for r in rs if r["after_impulse_s"] is not None]
                body.append([venue, v, len(rs), f"{len(ai)/len(rs)*100:.0f}%", f"{np.mean([r['net_bps'] for r in ai]):+.1f}" if ai else "-",
                             f"{np.mean([r['net_bps'] for r in rs if r['after_impulse_s'] is None]):+.1f}" if len(ai) < len(rs) else "-",
                             f"{np.mean([r['markout5_bps'] for r in rs if np.isfinite(r['markout5_bps'])]):+.1f}"])
        P("A fill within 10 s after a BTC impulse is, by construction, the quote that was on the wrong side of it.\n")
        P(md_table(["venue", "variant", "round trips", "entered ≤10 s after an impulse", "net bps (those)", "net bps (calm fills)", "mean 5s markout after fill (bps)"], body))
    # ------------------------------------------------------------- Architecture B
    if hc is not None:
        P("## Architecture B — high-conviction taker sniper + passive maker exit\n")
        P(f"Fire only if the CFO-credited predicted move |Δ̂| = edge_credit·|gap| ≥ **{cfg.cfo.b_floor_mult}x (spread + taker entry fee + maker exit fee)**. Shadow rows are spawned for *every* signal and "
          f"tagged `floor_ok`, so the floor's effect is read off the same ticks. Exit: maker take-profit at the converged touch → scratch (passive at the touch) if the impulse stalls → taker only on a genuine reversal / time stop.\n")
        for venue, pm in (("hyperliquid", False), ("polymarket", True)):
            sigs = len({r["sid"] for r in hc.results if r["venue"] == venue})
            if not sigs:
                P(f"### {venue}\n\nno signals.\n")
                continue
            base = [r for r in _b_rows(hc, venue, variant="taker/taker")]
            ok = [r for r in base if r.get("floor_ok")]
            ratios = [r.get("ratio", 0.0) for r in base]
            P(f"### {venue}\n")
            P(f"{sigs} signals; **{len(ok)} ({len(ok)/max(len(base),1)*100:.0f}%) pass the floor** ({len(base)-len(ok)} abstained); median predicted-move/floor ratio {np.median(ratios):.2f}; "
              f"median |Δ̂| {np.median([r.get('pred_bps',0) for r in base]):.1f} bps vs median floor {np.median([r.get('floor_bps',0) for r in base]):.1f} bps.\n")
            body = []
            for m in models:
                for name, rows in ((f"B (all signals, no floor)", _b_rows(hc, venue, m, "B/taker→maker+scratch")),
                                   (f"B (floor passed) ← the architecture", _b_rows(hc, venue, m, "B/taker→maker+scratch", floor=True)),
                                   (f"B (floor failed) ← abstained", _b_rows(hc, venue, m, "B/taker→maker+scratch", floor=False))):
                    st = _b_stats(rows)
                    if not st["n"]:
                        continue
                    body.append([m, name, st["n"], st["filled"]] + ([f"{st['net_cents']:+.2f}¢ ({st['net_bps']:+.0f} bps)" if pm else f"{st['net_bps']:+.2f} bps", f"±{st['se']:.1f}", f"{st['hit']*100:.0f}%",
                                                                   f"{st['net_usd']:+.2f}", f"{st['passive']*100:.0f}%", st["scratched"], ", ".join(f"{k}={v}" for k, v in st['exits'].items())] if st["filled"] else ["-"] * 7))
            for name, rows in (("taker/taker baseline (all signals)", base), ("taker/taker baseline (floor passed)", ok)):
                st = _b_stats(rows)
                if st["n"]:
                    body.append(["-", name, st["n"], st["filled"]] + ([f"{st['net_cents']:+.2f}¢ ({st['net_bps']:+.0f} bps)" if pm else f"{st['net_bps']:+.2f} bps", f"±{st['se']:.1f}", f"{st['hit']*100:.0f}%", f"{st['net_usd']:+.2f}",
                                                                      "0%", 0, ", ".join(f"{k}={v}" for k, v in st['exits'].items())] if st["filled"] else ["-"] * 7))
            P(md_table(["fill model", "variant", "attempts", "filled", "net / fill", "cluster s.e.", "hit", "net $", "passive exit", "scratched", "exit reasons"], body))
            acc = [r for r in hc.account_results if r["venue"] == venue]
            if acc:
                st = _b_stats(acc)
                if st["filled"]:
                    P(f"**ACCOUNT (CFO-sized, floor + net-edge + binary risk + expiry guard):** {st['filled']} fills, net {st['net_usd']:+.2f} $ ({st['net_bps']:+.1f} bps/fill), hit {st['hit']*100:.0f}%, exits {st['exits']}.\n")
    # ------------------------------------------------------------- side by side
    P("## A vs B side by side (same session, same oracle, same CFO/CEO)\n")
    body = []
    hrs = max(dur / 3600.0, 1e-9)
    for venue, pm in (("hyperliquid", False), ("polymarket", True)):
        for name, rows, kind in (("A ACCOUNT", mm.rows(variant="ACCOUNT", venue=venue) if mm else [], "mm"),
                                 (f"A shield/{models[0]}", mm.rows(variant=f"shield/{models[0]}", venue=venue) if mm else [], "mm"),
                                 ("B ACCOUNT", [r for r in (hc.account_results if hc else []) if r["venue"] == venue and r["outcome"] == "filled"], "b"),
                                 (f"B floor-passed/{models[0]}", [r for r in _b_rows(hc, venue, models[0], "B/taker→maker+scratch", floor=True) if r["outcome"] == "filled"] if hc else [], "b")):
            if not rows:
                body.append([venue, name, 0, "-", "-", "-", "-"])
                continue
            nb = np.array([r["net_bps"] for r in rows])
            nc = np.mean([r["net_cents"] for r in rows])
            body.append([venue, name, len(rows), f"{len(rows)/hrs:.0f}", (f"{nc:+.2f}¢" if pm else f"{nb.mean():+.2f} bps"), f"{(nb > 0).mean()*100:.0f}%", f"{sum(r['net_usd'] for r in rows):+.2f}"])
    P(md_table(["venue", "engine", "round trips / fills", "per hour", "net per trade", "hit", "net $"], body))
    # ------------------------------------------------------------- governance
    P("## CFO / CEO governance\n")
    cr = ag.cfo.report()
    P(f"* equity ${cr['equity']:,.2f} (start ${cfg.cfo.capital_usd:,.0f}); account round trips: A {len(mm.account_results) if mm else 0}, B {len(hc.account_results) if hc else 0}; "
      f"CFO state {'HALTED: ' + ag.cfo.halt_reason if ag.cfo.halted else 'trading'}; CEO state {ag.ceo.state.value}.")
    reasons = {k: v for k, v in ag.cfo.reasons.items() if k.startswith("mm_") or k.startswith("b_")}
    P(f"* CFO gate decisions (A `mm_*`, B `b_*`): {dict(sorted(reasons.items(), key=lambda kv: -kv[1]))}")
    P(f"* learned A adverse buffers {cfg.cfo.mm_adverse_bps}; B floor multiple {cfg.cfo.b_floor_mult}; blocked A {cfg.cfo.mm_blocked} / B {cfg.cfo.b_blocked}; shield holds {cfg.mm.requote_hold_s}.")
    ivs = [iv for iv in ag.ceo.interventions if iv.kind.startswith(("MM_", "B_", "SNIPE_"))]
    P("\n**CEO Phase 6 interventions:**\n")
    P("```\n" + ("\n".join(f"{iv.wall} {iv.kind:<26} {iv.target:<12} {iv.reason}" for iv in ivs) if ivs else "(none triggered)") + "\n```")
    P(f"\nAll CEO interventions: {len(ag.ceo.interventions)} (final state {ag.ceo.state.value}).\n")
    P("## Caveats\n")
    P("* Paper only. A real queue also has cancellations ahead of us, hidden size and other makers' adverse-selection logic; prints give a lower-bound `trades` model, `depletion` an upper bound.\n"
      "* The cancel-vs-informed-taker race is the decisive unknown: A is only protected when (BTC detection + cancel latency) < the delay of the informed flow hitting the stale quote. "
      "This report measures the outcome on the data it saw; it cannot measure other participants' latency. The synthetic stress test sweeps that delay explicitly.\n"
      "* Fee assumptions above are inputs, not measurements. Small samples: read the cluster s.e.\n")
    return "\n".join(L)
