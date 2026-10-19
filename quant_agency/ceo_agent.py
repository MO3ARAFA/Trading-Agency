"""Tier 4 – CEO: autonomous meta-supervisor.

Every ``review_interval_s`` the CEO audits the whole agency (win rate, net expectancy in bps and R,
markout decay t+1…t+30 s, spread/slippage drag, per-market profitability, and the CFO's *predicted*
edge vs the *realised* markout) and intervenes directly with the CFO and the Hunter:

  1. quarantines toxic / losing markets (they keep producing shadow markouts, so they can earn their way back),
  2. recalibrates the CFO: safety hurdle, size multiplier, edge credit, slippage coefficients,
     and taker -> maker-only when fees eat the gross gap,
  3. retunes the Hunter impulse Z-threshold and lag window against the live volatility regime,
  4. escalates through an explicit state machine NORMAL -> TIGHTENED -> DEFENSIVE -> HALTED (and back, with hysteresis),
  5. writes every decision, with its KPI evidence and before/after parameters, to an audit trail.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Dict, List, Optional

import numpy as np

from .btc_oracle import BtcOracle
from .cfo_agent import CFOAgent, MarkoutTracker
from .config import CEOConfig
from .execution_engine import ExecutionEngine
from .inefficiency_hunter import InefficiencyHunter


class CEOState(str, Enum):
    NORMAL = "NORMAL"
    TIGHTENED = "TIGHTENED"
    DEFENSIVE = "DEFENSIVE"
    HALTED = "HALTED"


class Verdict(str, Enum):
    POOR = "POOR"
    OK = "OK"
    GOOD = "GOOD"


def next_state(state: CEOState, verdict: Verdict, good_streak: int, halt_elapsed: bool = False) -> CEOState:
    """Pure transition function (unit-tested). GOOD needs two consecutive reviews to de-escalate."""
    if state == CEOState.HALTED:
        return CEOState.DEFENSIVE if halt_elapsed else CEOState.HALTED
    if verdict == Verdict.POOR:
        return {CEOState.NORMAL: CEOState.TIGHTENED, CEOState.TIGHTENED: CEOState.DEFENSIVE,
                CEOState.DEFENSIVE: CEOState.HALTED}[state]
    if verdict == Verdict.GOOD and good_streak >= 2:
        return {CEOState.NORMAL: CEOState.NORMAL, CEOState.TIGHTENED: CEOState.NORMAL,
                CEOState.DEFENSIVE: CEOState.TIGHTENED}[state]
    return state


@dataclass
class Intervention:
    iid: int
    t: float
    wall: str
    kind: str
    target: str
    state_before: str
    state_after: str
    reason: str
    evidence: dict
    before: dict
    after: dict

    def as_dict(self):
        return asdict(self)

    def line(self) -> str:
        return (f"#{self.iid} [{self.wall}] {self.kind:<22} {self.target:<10} {self.state_before}->{self.state_after}"
                f" | {self.reason} | {self.before} -> {self.after}")


def _clip(x, lo, hi):
    return max(lo, min(hi, x))


class CEOAgent:
    def __init__(self, cfo: CFOAgent, hunter: InefficiencyHunter, engine: ExecutionEngine, oracle: BtcOracle,
                 cfg: Optional[CEOConfig] = None, audit_path: Optional[str] = None, wall0: float = 0.0, t0: float = 0.0):
        self.cfg = cfg or CEOConfig()
        self.cfo, self.hunter, self.engine, self.oracle = cfo, hunter, engine, oracle
        self.state = CEOState.NORMAL
        self.good_streak = 0
        self.last_review = None
        self.halt_since = 0.0
        self.interventions: List[Intervention] = []
        self.reviews: List[dict] = []
        self.audit_path = audit_path
        self.wall0, self.t0 = wall0, t0
        self._iid = 0
        self.z_base = hunter.cfg.z_thr
        self.wm_base = hunter.cfg.window_mult
        self.hurdle_base = cfo.cfg.safety_hurdle_bps
        self.z_quality_adj = 0.0
        self.offences: Dict[str, int] = {}
        self.calm_streak = 0
        self.epoch = -1e18                       # global KPIs only count evidence gathered after the last evidence-driven change
        self.market_epoch: Dict[str, float] = {}  # per-market evidence restarts when that market is quarantined
        self._bump = False
        self.last_probation: Dict[str, float] = {}
        self.arb = None                          # CrossVenueArb, attached by the Agency
        self.sniper = None                       # MakerSniper, attached by the Agency
        self.snipe_epoch = -1e18
        self.snipe_strikes: Dict[str, int] = {}

    # ----------------------------------------------------------------------------- KPIs
    def kpis(self, now: float) -> dict:
        c = self.cfg
        tr: MarkoutTracker = self.cfo.markouts
        H = c.primary_horizon_s
        since = max(now - c.window_s, self.epoch)
        win = max(now - since, 1e-6)
        full_p = tr.select(now, c.window_s, h=H)
        full_1 = tr.select(now, c.window_s, h=1.0)
        rows_p = [r for r in full_p if r["t0"] >= since]
        rows_1 = [r for r in full_1 if r["t0"] >= since]
        appr = [r for r in rows_p if r["approved"]]
        rej_edge = [r for r in rows_p if r["cohort"] == "rejected_edge"]
        agg = tr.agg
        a_all, a_app, a_rej = agg(rows_p), agg(appr), agg(rej_edge)
        false_gap = float(np.mean([r["gross"] <= 0 for r in rows_p])) if rows_p else 0.0
        trades = [x for x in self.engine.closed if x.t_exit >= since]
        nt = len(trades)
        tk = {"n": nt, "win_rate": 0.0, "exp_bps": 0.0, "exp_R": 0.0, "pnl_usd": 0.0, "fees_usd": 0.0, "exp_se": 0.0,
              "entry_slip_bps": 0.0, "pred_slip_bps": 0.0, "pred_net_bps": 0.0, "spread_bps": 0.0}
        if nt:
            tk.update({"win_rate": float(np.mean([x.net_pnl_usd > 0 for x in trades])),
                       "exp_bps": float(np.mean([x.net_bps for x in trades])),
                       "exp_R": float(np.mean([x.R for x in trades])),
                       "exp_se": float(np.std([x.net_bps for x in trades], ddof=1) / np.sqrt(nt)) if nt > 1 else 0.0,
                       "pnl_usd": float(sum(x.net_pnl_usd for x in trades)),
                       "fees_usd": float(sum(x.fees_usd for x in trades)),
                       "entry_slip_bps": float(np.mean([x.entry_slip_bps for x in trades])),
                       "pred_slip_bps": float(np.mean([x.predicted_slip_bps for x in trades])),
                       "pred_net_bps": float(np.mean([x.predicted_net_bps for x in trades])),
                       "spread_bps": float(np.mean([x.spread_bps_entry for x in trades]))})
        pred = [r["pred"] for r in appr]
        real = [r["net"] for r in appr]
        realization = (float(np.mean(real)) / float(np.mean(pred))) if appr and np.mean(pred) > 0 else None
        # optimistic bound (mean + 1 s.e.) so the CEO only convicts the CFO when the shortfall is statistically visible
        realization_hi = ((float(np.mean(real)) + a_app["net_se"]) / float(np.mean(pred))) if appr and np.mean(pred) > 0 else None
        mk: Dict[str, dict] = {}
        for r in full_p:                                    # per-market evidence: own epoch, not the global one
            if r["t0"] < self.market_epoch.get(r["market"], -1e18):
                continue
            m = mk.setdefault(r["market"], {"g": [], "n": [], "g1": []})
            m["g"].append(r["gross"])
            m["n"].append(r["net"])
        for r in full_1:
            if r["market"] in mk and r["t0"] >= self.market_epoch.get(r["market"], -1e18):
                mk[r["market"]]["g1"].append(r["gross"])
        markets = {k: {"n": len(v["g"]), "gross": float(np.mean(v["g"])), "net": float(np.mean(v["n"])),
                       "hit_net": float(np.mean([x > 0 for x in v["n"]])),
                       "gross1": float(np.mean(v["g1"])) if v["g1"] else 0.0} for k, v in mk.items()}
        curve_all = {h: tr.agg(tr.select(now, win, h=h)) for h in tr.horizons}
        curve_app = {h: tr.agg(tr.select(now, win, h=h, approved_only=True)) for h in tr.horizons}
        st = self.oracle.state(now)
        return {"t": now, "window_s": win, "n_signals": len(rows_p), "all": a_all, "approved": a_app,
                "rejected_edge": a_rej, "false_gap_rate": false_gap, "cost_drag_bps": a_all["gross"] - a_all["net"],
                "trades": tk, "realization": realization, "realization_hi": realization_hi, "markets": markets, "curve_all": curve_all,
                "curve_approved": curve_app, "vol_ratio": float(st.vol_ratio), "drawdown": self.cfo.drawdown_frac(),
                "equity": self.cfo.equity}

    # ----------------------------------------------------------------------------- verdict
    def classify(self, k: dict):
        """(Verdict, reasons) for the *financial* track; hunter-quality is handled separately."""
        c = self.cfg
        reasons = []
        poor = good = False
        t = k["trades"]
        if t["n"] >= max(c.n_min_market, 6):
            if t["exp_bps"] + t["exp_se"] < c.net_bad_bps:
                poor = True
                reasons.append(f"trade expectancy {t['exp_bps']:+.2f}bps over {t['n']} trades < {c.net_bad_bps}")
            elif t["exp_bps"] - t["exp_se"] > c.net_good_bps:
                good = True
        elif k["approved"]["n"] >= c.n_min_global:
            if k["approved"]["net"] + k["approved"]["net_se"] < c.net_bad_bps:
                poor = True
                reasons.append(f"approved net markout {k['approved']['net']:+.2f}bps over {k['approved']['n']} < {c.net_bad_bps}")
            elif k["approved"]["net"] - k["approved"]["net_se"] > c.net_good_bps:
                good = True
        if k["realization_hi"] is not None and k["approved"]["n"] >= c.n_min_global and k["realization_hi"] < c.realization_bad:
            poor = True
            reasons.append(f"CFO edge realization {k['realization']:.2f} < {c.realization_bad}")
        if k["drawdown"] > 0.5 * self.cfo.cfg.portfolio_dd_frac:
            poor = True
            reasons.append(f"drawdown {k['drawdown']*100:.2f}% past half of breaker")
        if poor:
            return Verdict.POOR, reasons
        return (Verdict.GOOD if good else Verdict.OK), reasons

    # ----------------------------------------------------------------------------- interventions
    def _log(self, now, kind, target, reason, evidence, before, after, state_before=None) -> Intervention:
        self._iid += 1
        wall = time.strftime("%H:%M:%S", time.gmtime(self.wall0 + (now - self.t0)))
        iv = Intervention(self._iid, now, wall, kind, target, (state_before or self.state).value, self.state.value,
                          reason, evidence, before, after)
        self.interventions.append(iv)
        if self.audit_path:
            with open(self.audit_path, "a") as f:
                f.write(json.dumps(iv.as_dict(), default=float) + "\n")
        return iv

    def _compact(self, k: dict) -> dict:
        return {"n_signals": k["n_signals"], "gross5": round(k["all"]["gross"], 3), "net5": round(k["all"]["net"], 3),
                "false_gap": round(k["false_gap_rate"], 3), "trades": k["trades"]["n"],
                "exp_bps": round(k["trades"]["exp_bps"], 3), "realization": None if k["realization"] is None else round(k["realization"], 3),
                "drawdown": round(k["drawdown"], 5), "vol_ratio": round(k["vol_ratio"], 3)}

    def _quarantine(self, now, k, out):
        c = self.cfg
        for m, v in k["markets"].items():
            if self.cfo.is_blacklisted(m, now) or v["n"] < c.n_min_market:
                continue
            toxic = v["gross1"] < c.toxic_gross1_bps and v["gross"] < 0.0
            losing = v["net"] < c.market_net_bad_bps and v["hit_net"] < c.market_hit_bad
            if not (toxic or losing):
                continue
            k_off = self.offences.get(m, 0)
            dur = min(c.quarantine_s * (2 ** k_off), c.quarantine_max_s)
            self.offences[m] = k_off + 1
            self.market_epoch[m] = now
            why = "toxic_flow" if toxic else "negative_markouts"
            self.cfo.apply_directive({"quarantine": (m, now + dur, why)}, now)
            out.append(self._log(now, "QUARANTINE_MARKET", m,
                                 f"{why}: n={v['n']} gross@1s={v['gross1']:+.2f} gross@5s={v['gross']:+.2f} "
                                 f"net@5s={v['net']:+.2f}bps hit={v['hit_net']:.0%}; blacklisted {dur:.0f}s",
                                 {k2: round(v2, 3) for k2, v2 in v.items()}, {}, {"until": round(float(now + dur), 1)}))

    def _quarantine_arbs(self, now, out):
        """Arb pairs whose *executed* trades realise a net loss (leg risk / vanishing gaps) are blacklisted like losing markets."""
        c = self.cfg
        if self.arb is None:
            return
        for name, st in self.arb.pair_stats.items():
            nb = st["net_bps"]
            if len(nb) < 4 or self.cfo.is_blacklisted(name, now):
                continue
            recent = nb[-8:]
            if float(np.mean(recent)) < c.market_net_bad_bps / 1.5:
                k_off = self.offences.get(name, 0)
                dur = min(c.quarantine_s * (2 ** k_off), c.quarantine_max_s)
                self.offences[name] = k_off + 1
                self.cfo.apply_directive({"quarantine": (name, now + dur, "arb_net_negative")}, now)
                st["net_bps"] = []
                out.append(self._log(now, "QUARANTINE_ARB", name,
                                     f"executed arb net {float(np.mean(recent)):+.2f}bps over last {len(recent)} (locked {st['locked']}, "
                                     f"leg-risk {st['leg_risk']}, missed {st['missed']}); blacklisted {dur:.0f}s",
                                     {"locked": st["locked"], "leg_risk": st["leg_risk"], "missed": st["missed"]}, {}, {"until": round(float(now + dur), 1)}))

    def _snipe_review(self, now, out):
        """Phase 5: audit the passive maker sniper — fill rate, cancel-latency adverse fills, net maker markout per venue."""
        sn = self.sniper
        if sn is None or not sn.account_results:
            return
        c, cc = self.cfg, self.cfo.cfg
        for venue in ("hyperliquid", "polymarket"):
            rows = [r for r in sn.account_results if r["venue"] == venue and r["t_end"] >= self.snipe_epoch]
            if venue in cc.snipe_blocked or len(rows) < 8:
                continue
            fills = [r for r in rows if r["outcome"] == "filled"]
            fr = len(fills) / len(rows)
            unit = 1.0 if venue == "hyperliquid" else 100.0          # bps tolerance scales with the venue's price units
            ev = {"venue": venue, "attempts": len(rows), "fills": len(fills), "fill_rate": round(fr, 3),
                  "shield_cancels": sum(1 for r in rows if r["shield_cancel"])}
            if len(fills) >= 4:
                nb = np.array([r["net_bps"] for r in fills])
                se = float(nb.std(ddof=1) / np.sqrt(len(nb))) if len(nb) > 1 else 0.0
                fdc = [r for r in fills if r["fill_during_cancel"]]
                ev.update({"net_bps_per_fill": round(float(nb.mean()), 3), "se": round(se, 3), "fill_during_cancel": len(fdc)})
                if len(fdc) >= 3 and len(fdc) / len(fills) >= 0.3 and float(np.mean([r["net_bps"] for r in fdc])) < 0 and sn.cfg.hold_frac < 0.8:
                    before = {"hold_frac": sn.cfg.hold_frac}
                    sn.cfg.hold_frac = round(min(sn.cfg.hold_frac + 0.1, 0.8), 2)
                    out.append(self._log(now, "SNIPE_SHIELD_TIGHTEN", venue,
                                         f"{len(fdc)}/{len(fills)} fills landed inside the cancel-latency window with net {np.mean([r['net_bps'] for r in fdc]):+.2f}bps: "
                                         f"pulling orders earlier", ev, before, {"hold_frac": sn.cfg.hold_frac}))
                    self.snipe_epoch = now
                    continue
                if float(nb.mean()) + se < -0.5 * unit * (1.0 if venue == "hyperliquid" else 1.5):
                    base = dict(cc.snipe_adverse_bps)
                    step = 0.3 if venue == "hyperliquid" else 50.0
                    at_cap = base[venue] >= 400.0 - 1e-9                      # buffer can't rise further: escalate instead of a no-op
                    if not at_cap:
                        self.cfo.set_snipe_base(venue, base[venue] + step)
                    self.snipe_strikes[venue] = self.snipe_strikes.get(venue, 0) + (3 if at_cap else 1)
                    if self.snipe_strikes[venue] >= 3:
                        cc.snipe_blocked = tuple(set(cc.snipe_blocked) | {venue})
                        out.append(self._log(now, "SNIPE_DISABLE_VENUE", venue,
                                             f"maker net {nb.mean():+.2f}±{se:.2f}bps per fill after {self.snipe_strikes[venue]} corrections; switching the sniper off for this venue",
                                             ev, {"enabled": True}, {"enabled": False}))
                    else:
                        out.append(self._log(now, "SNIPE_RAISE_ADVERSE_BUFFER", venue,
                                             f"maker net {nb.mean():+.2f}±{se:.2f}bps per fill < tolerance: CFO adverse-selection buffer {base[venue]:g}→{cc.snipe_adverse_bps[venue]:g}bps",
                                             ev, {"buffer": base[venue]}, {"buffer": cc.snipe_adverse_bps[venue]}))
                    self.snipe_epoch = now
                    continue
            if len(rows) >= 15 and fr < 0.08 and sum(1 for r in rows if r["shield_cancel"]) / len(rows) >= 0.6 and sn.cfg.hold_frac > 0.1:
                before = {"hold_frac": sn.cfg.hold_frac}
                sn.cfg.hold_frac = round(max(sn.cfg.hold_frac - 0.1, 0.1), 2)
                out.append(self._log(now, "SNIPE_RELAX_SHIELD", venue,
                                     f"fill rate {fr:.0%} with {sum(1 for r in rows if r['shield_cancel'])/len(rows):.0%} of orders pulled by the shield: shield too jumpy",
                                     ev, before, {"hold_frac": sn.cfg.hold_frac}))
                self.snipe_epoch = now

    def _tune_hunter(self, now, k, out):
        c, hc = self.cfg, self.hunter.cfg
        before = {"z_thr": hc.z_thr, "window_mult": hc.window_mult}
        adj0 = self.z_quality_adj
        if k["n_signals"] >= c.n_min_global:
            if k["false_gap_rate"] > c.false_gap_bad:
                self.z_quality_adj = _clip(self.z_quality_adj + c.z_step, 0.0, 2.0)
                self.calm_streak = 0
            elif k["false_gap_rate"] < 0.35:
                self.calm_streak += 1
                if self.calm_streak >= 2:
                    self.z_quality_adj = _clip(self.z_quality_adj - c.z_step, 0.0, 2.0)
                    self.calm_streak = 0
        if self.z_quality_adj != adj0:
            self._bump = True                                  # evidence-driven: demand fresh signals before the next move
        vr = k["vol_ratio"]
        regime_adj = c.z_step if vr > c.vol_ratio_hi else (-c.z_step if vr < c.vol_ratio_lo else 0.0)
        z = _clip(self.z_base + self.z_quality_adj + regime_adj, c.z_min, c.z_max)
        wm = round(_clip(self.wm_base / _clip(vr, 0.6, 1.6), 1.0, 3.0) * 4.0) / 4.0     # quarter steps: log regimes, not jitter
        if abs(z - hc.z_thr) > 1e-9 or abs(wm - hc.window_mult) > 1e-9:
            after = {"z_thr": round(z, 3), "window_mult": round(wm, 3)}
            self.hunter.apply_directive({"z_thr": z, "window_mult": wm})
            regime = "high-vol" if vr > c.vol_ratio_hi else ("low-vol" if vr < c.vol_ratio_lo else "normal-vol")
            out.append(self._log(now, "RETUNE_IMPULSE", "hunter",
                                 (f"false-gap {k['false_gap_rate']:.0%} over {k['n_signals']} fresh signals, " if k["n_signals"] >= c.n_min_global
                                  else f"only {k['n_signals']} fresh signals (quality unchanged), ")
                                 + f"regime {regime} (vol ratio {vr:.2f})", self._compact(k), before, after))

    def _audit_cfo(self, now, k, out):
        c = self.cfg
        cc = self.cfo.cfg
        if k["realization"] is not None and k["approved"]["n"] >= c.n_min_global:
            r = k["realization"]
            if (k["realization_hi"] if k["realization_hi"] is not None else r) < c.realization_bad and cc.edge_credit > 0.3:
                before = {"edge_credit": cc.edge_credit}
                self._bump = True
                self.cfo.apply_directive({"edge_credit": cc.edge_credit * 0.85}, now)
                out.append(self._log(now, "CFO_EDGE_RECALIBRATION", "cfo",
                                     f"CFO predicted net {k['approved']['pred']:+.2f}bps but realised {k['approved']['net']:+.2f}bps "
                                     f"(ratio {r:.2f}): haircutting gap credit", self._compact(k), before,
                                     {"edge_credit": round(cc.edge_credit, 3)}))
            elif r > 1.5 and cc.edge_credit < 1.0:
                before = {"edge_credit": cc.edge_credit}
                self._bump = True
                self.cfo.apply_directive({"edge_credit": cc.edge_credit + 0.05}, now)
                out.append(self._log(now, "CFO_EDGE_RECALIBRATION", "cfo",
                                     f"realisation {r:.2f}: CFO too conservative, restoring credit", self._compact(k), before,
                                     {"edge_credit": round(cc.edge_credit, 3)}))
        t = k["trades"]
        if t["n"] >= c.n_min_market:
            if t["entry_slip_bps"] > 1.5 * t["pred_slip_bps"] + 0.5 and cc.slip_depth_coeff < 3.0:
                before = {"slip_depth_coeff": cc.slip_depth_coeff, "slip_vol_coeff": cc.slip_vol_coeff}
                self._bump = True
                self.cfo.apply_directive({"slip_depth_coeff": cc.slip_depth_coeff * 1.25,
                                          "slip_vol_coeff": cc.slip_vol_coeff * 1.25}, now)
                out.append(self._log(now, "CFO_SLIPPAGE_RECALIBRATION", "cfo",
                                     f"realised entry slippage {t['entry_slip_bps']:+.2f}bps vs modelled {t['pred_slip_bps']:+.2f}bps; scaling slippage coeffs x1.25",
                                     self._compact(k), before,
                                     {"slip_depth_coeff": round(cc.slip_depth_coeff, 3), "slip_vol_coeff": round(cc.slip_vol_coeff, 3)}))

    def _escalate(self, now, k, verdict, reasons, out):
        c, cc = self.cfg, self.cfo.cfg
        prev = self.state
        halt_elapsed = prev == CEOState.HALTED and (now - self.halt_since) >= c.halt_pause_s
        self.good_streak = self.good_streak + 1 if verdict == Verdict.GOOD else 0
        if self.cfo.halted and prev != CEOState.HALTED:                  # CFO breaker tripped on its own
            self.state = CEOState.HALTED
            self.halt_since = now
            out.append(self._log(now, "BREAKER_ACK", "cfo", f"CFO circuit breaker '{self.cfo.halt_reason}' tripped; standing down",
                                 self._compact(k), {}, {"halted": True}, prev))
            return
        new = next_state(prev, verdict, self.good_streak, halt_elapsed)
        if new == prev and not halt_elapsed:
            if verdict == Verdict.OK and prev == CEOState.NORMAL:
                self._loosen_if_missed(now, k, out)
            return
        self.state = new
        before = {"hurdle": cc.safety_hurdle_bps, "size_mult": cc.size_mult, "mode": cc.mode_policy}
        t = k["trades"]
        bleed = (k["all"]["n"] >= c.n_min_global and k["all"]["gross"] > 0 and k["cost_drag_bps"] / max(k["all"]["gross"], 1e-9) > c.fee_bleed_ratio)
        if prev == CEOState.HALTED:                                    # pause elapsed: probation, whatever the stale verdict says
            self.cfo.apply_directive({"resume": True, "size_mult": max(c.size_floor, min(cc.size_mult, 0.25)),
                                      "mode_policy": "maker_only"}, now)
            self.good_streak = 0
            kind, why = "RESUME_PROBATION", "pause elapsed; resuming at reduced size, maker-only, with a fresh evidence window"
        elif verdict == Verdict.POOR and new == CEOState.TIGHTENED:
            self.cfo.apply_directive({"safety_hurdle_bps": min(cc.safety_hurdle_bps + c.hurdle_step_bps, c.hurdle_max_bps),
                                      "size_mult": max(cc.size_mult * 0.8, c.size_floor)}, now)
            kind, why = "TIGHTEN_CFO", "; ".join(reasons)
        elif verdict == Verdict.POOR and new == CEOState.DEFENSIVE:
            d = {"safety_hurdle_bps": min(cc.safety_hurdle_bps + 2 * c.hurdle_step_bps, c.hurdle_max_bps),
                 "size_mult": max(cc.size_mult * 0.5, c.size_floor)}
            if bleed or cc.mode_policy == "auto":
                d["mode_policy"] = "maker_only"
            self.cfo.apply_directive(d, now)
            kind = "DEFENSIVE_MAKER_ONLY" if d.get("mode_policy") == "maker_only" else "DEFENSIVE_CFO"
            why = "; ".join(reasons) + (f"; fee bleed: gross {k['all']['gross']:+.2f} vs net {k['all']['net']:+.2f}bps" if bleed else "")
        elif new == CEOState.HALTED:
            self.halt_since = now
            self.cfo.apply_directive({"halt": True}, now)
            kind, why = "HALT_TRADING", "; ".join(reasons) + f"; standing down {c.halt_pause_s:.0f}s then probation"
        else:                                                          # de-escalation after 2 GOOD reviews
            self.cfo.apply_directive({"safety_hurdle_bps": max(cc.safety_hurdle_bps - c.hurdle_step_bps, self.hurdle_base),
                                      "size_mult": min(cc.size_mult * 1.25, 1.0), "mode_policy": "auto" if new == CEOState.NORMAL else cc.mode_policy,
                                      "edge_credit": min(cc.edge_credit + 0.05, 1.0)}, now)
            kind, why = "RELAX_CFO", f"two consecutive good reviews: net expectancy {t['exp_bps']:+.2f}bps"
        self.epoch = now
        out.append(self._log(now, kind, "cfo", why, self._compact(k), before,
                             {"hurdle": cc.safety_hurdle_bps, "size_mult": round(cc.size_mult, 3), "mode": cc.mode_policy}, prev))

    def _loosen_if_missed(self, now, k, out):
        c, cc = self.cfg, self.cfo.cfg
        r = k["rejected_edge"]
        if r["n"] >= c.n_min_global and r["net"] >= c.missed_opportunity_bps and cc.safety_hurdle_bps > c.hurdle_min_bps:
            before = {"hurdle": cc.safety_hurdle_bps}
            self._bump = True
            self.cfo.apply_directive({"safety_hurdle_bps": max(cc.safety_hurdle_bps - c.hurdle_step_bps, c.hurdle_min_bps)}, now)
            out.append(self._log(now, "LOOSEN_HURDLE", "cfo",
                                 f"missed opportunity: {r['n']} CFO-rejected signals realised {r['net']:+.2f}bps net@{c.primary_horizon_s:g}s",
                                 self._compact(k), before, {"hurdle": cc.safety_hurdle_bps}))

    # ----------------------------------------------------------------------------- main
    def maybe_review(self, now: float) -> List[Intervention]:
        if self.last_review is None:
            self.last_review = now
            return []
        if now - self.last_review < self.cfg.review_interval_s:
            return []
        self.last_review = now
        return self.review(now)

    def review(self, now: float) -> List[Intervention]:
        out: List[Intervention] = []
        self._bump = False
        k = self.kpis(now)
        verdict, reasons = self.classify(k)
        self.reviews.append({"t": now, "state": self.state.value, "verdict": verdict.value, "reasons": reasons,
                             "kpi": self._compact(k)})
        self._quarantine(now, k, out)
        self._quarantine_arbs(now, out)
        self._snipe_review(now, out)
        self._audit_cfo(now, k, out)
        self._tune_hunter(now, k, out)
        self._escalate(now, k, verdict, reasons, out)
        if self._bump:
            self.epoch = max(self.epoch, now)
        if self.cfo.flatten_requested:
            self.engine.flatten_all(now, "breaker_flatten")
            self.cfo.flatten_requested = False
        return out
