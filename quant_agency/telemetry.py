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
