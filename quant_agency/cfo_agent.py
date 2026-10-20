"""Tier 2 – CFO: capital preservation, fee math, trade gating, sizing, breakers, markout accounting.

No order is prepared without a CFO ``Decision(approved=True)``.

Net post-cost edge (bps), exactly the brief's formula with explicit components:

    NetEdge = credit * |Gap| - (Spread + Fees + Slippage + SafetyHurdle)

* Spread   – live full spread (taker round trip crosses half on entry, half on exit).
* Fees     – round-trip taker fees (or maker entry + taker exit).
* Slippage – depth term (size / top-of-book) + latency-drift term (order-entry latency x residual vol).
* ``credit`` – CEO/CFO-calibrated haircut on how much of the gap we actually capture (1.0 = brief's raw gap).
"""
from __future__ import annotations

import math
from collections import defaultdict, deque
from dataclasses import dataclass, field, asdict
from typing import Deque, Dict, List, Optional, Tuple

import numpy as np

from .config import CFOConfig
from .inefficiency_hunter import Signal
from .market_watchers import MarketBook, maker_fee_bps, taker_fee_bps

BPS = 1e4


@dataclass
class Decision:
    approved: bool
    reason: str
    mode: str = ""                       # taker | maker | ""
    net_edge_bps: float = 0.0            # of the chosen mode (or best mode if rejected)
    net_edge_taker_bps: float = 0.0
    net_edge_maker_bps: float = 0.0
    gap_credit_bps: float = 0.0
    spread_bps: float = 0.0
    fee_bps: float = 0.0
    slip_bps: float = 0.0
    hurdle_bps: float = 0.0
    notional: float = 0.0
    qty: float = 0.0
    tp_bps: float = 0.0
    stop_bps: float = 0.0
    time_stop_s: float = 0.0
    cohort: str = "rejected_other"       # approved | rejected_edge | rejected_gate | rejected_other
    entry_mode: str = ""                # snipe: join | penny

    def as_dict(self):
        return asdict(self)


def _cluster_se(rows: List[dict], key: str) -> float:
    """Standard error of the mean, clustered by BTC impulse.

    Every market that fires on the same BTC impulse shares that impulse's outcome, so rows are not
    independent. We average within an impulse and take the s.e. across impulses (conservative).
    """
    cl: Dict[int, List[float]] = defaultdict(list)
    for r in rows:
        cl[r["imp"]].append(r[key])
    if len(cl) < 2:
        return float(np.std([r[key] for r in rows], ddof=1)) if len(rows) > 1 else 0.0
    means = np.array([np.mean(v) for v in cl.values()])
    return float(means.std(ddof=1) / np.sqrt(len(means)))


class MarkoutTracker:
    """Realised markout curves t+1/3/5/10/30 s for every signal (approved and shadow)."""

    def __init__(self, book: MarketBook, horizons, latency_s: float, fee_taker_bps: float):
        self.book = book
        self.horizons = tuple(horizons)
        self.lat = latency_s
        self.fee = fee_taker_bps
        self.pending: List[dict] = []
        self.max_rows = 100_000                  # 24/7 safety: drop the oldest 20% beyond this (JSONL keeps the full record)
        # resolved rows: dict(market, cohort, side, h, t0, gap, pred_net, gross, net, closure)
        self.rows: List[dict] = []

    def register(self, sig: Signal, dec: Decision) -> None:
        self.pending.append({"sid": sig.sid, "idx": sig.idx, "market": sig.market, "side": sig.side, "t0": sig.t,
                             "mid0": sig.mid, "gap": abs(sig.gap_bps), "pred": dec.net_edge_taker_bps,
                             "pred_sel": dec.net_edge_bps, "imp": sig.impulse_id, "spread": sig.spread_bps, "px": sig.mid, "cohort": dec.cohort, "approved": dec.approved,
                             "reason": dec.reason, "todo": list(self.horizons),
                             "oracle": getattr(sig, "oracle", "BTC"), "net_gap": getattr(sig, "net_gap_bps", 0.0), "lag_s": sig.lag_s, "beta": sig.beta,
                             "fair": abs(sig.fair_bps), "ldelta": sig.btc_delta_bps, "lz": sig.btc_z, "hurdle": getattr(sig, "hurdle_bps", 0.0),
                             "lsig": getattr(sig, "lead_sigma_bps", 0.0), "hz": sig.horizon_s, "age": sig.age_s})

    def poll(self, now: float) -> int:
        n = 0
        keep = []
        for p in self.pending:
            todo = []
            for h in p["todo"]:
                tf = p["t0"] + self.lat
                if now < tf + h:
                    todo.append(h)
                    continue
                qe = self.book.quote_asof(p["idx"], tf)
                qx = self.book.quote_asof(p["idx"], tf + h)
                if qe is None or qx is None:
                    continue
                s = p["side"]
                mid_e, mid_x = 0.5 * (qe[0] + qe[1]), 0.5 * (qx[0] + qx[1])
                gross = s * (mid_x - mid_e) / mid_e * BPS
                ex_in = qe[1] if s > 0 else qe[0]
                ex_out = qx[0] if s > 0 else qx[1]
                meta = self.book.metas[p["idx"]]
                net0 = s * (ex_out - ex_in) / ex_in * BPS                  # spread-crossing, zero fees
                net = net0 - taker_fee_bps(meta, ex_in, self.fee) - taker_fee_bps(meta, ex_out, self.fee)
                closure = s * (mid_x - p["mid0"]) / p["mid0"] * BPS / p["gap"] if p["gap"] > 0 else 0.0
                self.rows.append({"market": p["market"], "cohort": p["cohort"], "side": s, "h": h, "t0": p["t0"],
                                  "gap": p["gap"], "pred": p["pred"], "gross": gross, "net": net, "net0": net0,
                                  "spread": p["spread"], "px": p["px"], "lat": self.lat, "venue": meta.venue, "kind": meta.kind,
                                  "closure": closure, "approved": p["approved"], "sid": p["sid"], "imp": p["imp"],
                                  "oracle": p["oracle"], "asset": meta.asset or meta.base, "net_gap": p["net_gap"], "lag_s": p["lag_s"], "beta": p["beta"],
                                  "fair": p["fair"], "ldelta": p["ldelta"], "lz": p["lz"], "hurdle": p["hurdle"], "lsig": p["lsig"], "hz": p["hz"],
                                  "age": p["age"], "fee_in": taker_fee_bps(meta, ex_in, self.fee), "fee_out": taker_fee_bps(meta, ex_out, self.fee)})
                n += 1
            p["todo"] = todo
            if todo:
                keep.append(p)
        self.pending = keep
        if len(self.rows) > self.max_rows:
            del self.rows[: self.max_rows // 5]
        return n

    def select(self, now: float, window_s: float, h: Optional[float] = None, cohort: Optional[str] = None,
               market: Optional[str] = None, approved_only: bool = False) -> List[dict]:
        t_lo = now - window_s
        out = []
        for r in reversed(self.rows):
            if r["t0"] < t_lo:
                break
            if h is not None and r["h"] != h:
                continue
            if cohort is not None and r["cohort"] != cohort:
                continue
            if market is not None and r["market"] != market:
                continue
            if approved_only and not r["approved"]:
                continue
            out.append(r)
        return out

    @staticmethod
    def agg(rows: List[dict]) -> dict:
        n = len(rows)
        if n == 0:
            return {"n": 0, "gross": 0.0, "net": 0.0, "hit_gross": 0.0, "hit_net": 0.0, "closure": 0.0, "pred": 0.0,
                    "net_se": 0.0, "gross_se": 0.0}
        g = np.array([r["gross"] for r in rows])
        nt = np.array([r["net"] for r in rows])
        return {"n": n, "gross": float(g.mean()), "net": float(nt.mean()), "hit_gross": float((g > 0).mean()),
                "hit_net": float((nt > 0).mean()),
                "net_se": _cluster_se(rows, "net"), "gross_se": _cluster_se(rows, "gross"),
                "n_imp": len({r["imp"] for r in rows}), "closure": float(np.mean([r["closure"] for r in rows])),
                "pred": float(np.mean([r["pred"] for r in rows]))}

    def table(self, cohort: Optional[str] = None, approved_only: bool = False, window_s: float = 1e12,
              now: float = 0.0) -> Dict[float, dict]:
        return {h: self.agg(self.select(now if now else (self.rows[-1]["t0"] + 1e6 if self.rows else 0.0), window_s, h=h,
                                        cohort=cohort, approved_only=approved_only)) for h in self.horizons}


class CFOAgent:
    DIRECTIVE_KEYS = {"safety_hurdle_bps": (0.0, 25.0), "edge_credit": (0.05, 1.0), "size_mult": (0.0, 1.5),
                      "slip_depth_coeff": (0.1, 3.0), "slip_vol_coeff": (0.05, 1.5)}

    def __init__(self, book: MarketBook, cfg: Optional[CFOConfig] = None):
        self.cfg = cfg or CFOConfig()
        self.book = book
        c = self.cfg
        self.equity = c.capital_usd
        self.peak = c.capital_usd
        self.day_start = c.capital_usd
        self.day_t0: Optional[float] = None
        self.exposure: Dict[str, float] = {}           # signed notional per market
        self.beta_expo: Dict[str, float] = {}
        self.blacklist: Dict[str, Tuple[float, str]] = {}
        self.market_pnl: Dict[str, Deque[Tuple[float, float]]] = defaultdict(deque)
        self.halted = False
        self.halt_reason = ""
        self.halted_at = 0.0
        self.flatten_requested = False
        self.reasons: Dict[str, int] = defaultdict(int)
        self.cohorts: Dict[str, int] = defaultdict(int)
        self.n_eval = 0
        self.n_approved = 0
        self.closed_pnl = 0.0
        self.fees_paid = 0.0
        self.directive_log: List[dict] = []
        self.maker_attempts = 0
        self.maker_fills = 0
        self.poly_min_ttl = 60.0                       # pre-expiry entry guard (the Agency sets it from PolyConfig)
        self.markouts = MarkoutTracker(book, c.markout_horizons_s, c.latency_s, c.fee_taker_bps)

    # ------------------------------------------------------------------ directives (CEO -> CFO)
    def apply_directive(self, d: dict, now: float = 0.0) -> dict:
        before: Dict[str, object] = {}
        c = self.cfg
        for k, v in d.items():
            if k in self.DIRECTIVE_KEYS:
                lo, hi = self.DIRECTIVE_KEYS[k]
                v = min(max(float(v), lo), hi)
                before[k] = getattr(c, k)
                setattr(c, k, v)
            elif k == "mode_policy" and v in ("auto", "maker_only", "taker_only"):
                before[k] = c.mode_policy
                c.mode_policy = v
            elif k == "halt" and v:
                before["halted"] = self.halted
                self.trip("ceo_halt", now)
            elif k == "resume" and v:
                before["halted"] = self.halted
                self.halted = False
                self.halt_reason = ""
                self.peak = self.equity            # restart the drawdown clock from here
            elif k == "quarantine":
                market, until, why = v
                before[f"quarantine:{market}"] = self.blacklist.get(market)
                self.blacklist[market] = (until, why)
            elif k == "release":
                before[f"release:{v}"] = self.blacklist.pop(v, None)
        if before:
            self.directive_log.append({"t": now, "directive": d, "before": before})
        return before

    def is_blacklisted(self, market: str, now: float) -> bool:
        b = self.blacklist.get(market)
        if b is None:
            return False
        if now >= b[0]:
            del self.blacklist[market]
            return False
        return True

    def trip(self, reason: str, now: float) -> None:
        if not self.halted:
            self.halted = True
            self.halt_reason = reason
            self.halted_at = now
            self.flatten_requested = True

    # ------------------------------------------------------------------ cost model
    def costs(self, sig: Signal, qty: float, mode: str) -> Tuple[float, float, float]:
        """(spread_bps, fee_bps, slip_bps) for the given mode."""
        c = self.cfg
        spread = sig.spread_bps
        meta = self.book.metas[sig.idx]
        px = sig.ask if sig.side > 0 else sig.bid
        fee_t = taker_fee_bps(meta, px, c.fee_taker_bps)
        top = sig.aq if sig.side > 0 else sig.bq
        depth_ratio = min(qty / top, 4.0) if top > 0 else 4.0
        sigma_s = sig.sigma_res_bps / math.sqrt(max(sig.horizon_s, 1e-6))
        drift = c.slip_vol_coeff * sigma_s * math.sqrt(c.latency_s)
        if mode == "taker":
            slip = c.slip_depth_coeff * spread * depth_ratio + drift
            return spread, 2.0 * fee_t, slip
        # maker entry (earn half spread, exit taker): spread cost nets ~0, pay adverse-selection penalty
        slip = 0.25 * spread + drift
        return 0.0, maker_fee_bps(meta, c.fee_maker_bps) + fee_t, slip

    def _risk_stop_idx(self, idx: int, side: int, price: float, stop_bps: float) -> float:
        if self.book.metas[idx].kind != "prediction":
            return stop_bps
        p = min(max(price, 1e-3), 1.0 - 1e-3)
        worst = p if side > 0 else (1.0 - p)
        return max(stop_bps, 0.5 * worst / p * BPS)

    def _risk_stop_bps(self, sig: Signal, price: float, stop_bps: float) -> float:
        """Effective stop distance used for the risk budget.

        Spot/perp: the configured stop. Binary contracts can gap ~50 % of the *worst-case* loss inside one order latency, and the
        worst case per share is p for a long but (1-p) for a short (a short at 0.33 can lose 0.67/share = 2x its notional).
        """
        if self.book.metas[sig.idx].kind != "prediction":
            return stop_bps
        p = min(max(price, 1e-3), 1.0 - 1e-3)
        worst = p if sig.side > 0 else (1.0 - p)
        return max(stop_bps, 0.5 * worst / p * BPS)

    # ------------------------------------------------------------------ gating & sizing
    def evaluate(self, sig: Signal, now: float, has_position: bool = False, tradable: bool = True) -> Decision:
        c = self.cfg
        self.n_eval += 1
        credit_bps = c.edge_credit * abs(sig.gap_bps)
        price = sig.ask if sig.side > 0 else sig.bid
        top = sig.aq if sig.side > 0 else sig.bq
        # pass 1: worst-case slippage at the liquidity cap
        qty_cap = c.liquidity_frac * top
        net = {}
        parts = {}
        for mode in ("taker", "maker"):
            sp, fee, slip = self.costs(sig, qty_cap, mode)
            net[mode] = credit_bps - (sp + fee + slip + c.safety_hurdle_bps)
            parts[mode] = (sp, fee, slip)
        # mode choice: urgency + CEO policy; maker EV discounted by the realised fill probability
        pf = c.p_fill_maker
        ev_maker = pf * net["maker"] if net["maker"] > 0 else net["maker"]
        if c.mode_policy == "maker_only":
            mode = "maker"
        elif c.mode_policy == "taker_only":
            mode = "taker"
        else:
            urgent = sig.window_s <= c.urgent_window_s
            mode = "taker" if (urgent or net["taker"] >= ev_maker) else "maker"
        dec = Decision(approved=False, reason="", mode=mode, net_edge_bps=net[mode], net_edge_taker_bps=net["taker"],
                       net_edge_maker_bps=net["maker"], gap_credit_bps=credit_bps, spread_bps=parts[mode][0],
                       fee_bps=parts[mode][1], slip_bps=parts[mode][2], hurdle_bps=c.safety_hurdle_bps)

        def reject(reason: str, cohort: str = "rejected_other") -> Decision:
            dec.reason, dec.cohort = reason, cohort
            self.reasons[reason] += 1
            self.cohorts[cohort] += 1
            return dec

        if not tradable:
            return reject("watch_only")
        if self.halted:
            return reject("halted")
        if self.is_blacklisted(sig.market, now):
            return reject("quarantined")
        gate = self.book.metas[sig.idx].spread_gate_bps
        if sig.spread_bps > (c.max_spread_bps if gate is None else gate):
            return reject("spread_too_wide", "rejected_gate")   # hard microstructure gate (scalp mode: 0.5 bps); shadow-tracked
        if sig.side < 0 and not c.allow_short:
            return reject("short_disabled")
        if has_position:
            return reject("in_position")
        if net[mode] <= 0.0:
            return reject("net_edge_below_hurdle", "rejected_edge")

        # ---- sizing: fractional Kelly ∧ stop-risk budget ∧ per-trade/market/gross/beta/liquidity caps
        eq = self.equity
        stop_bps = max(c.stop_mult * sig.sigma_res_bps, c.min_stop_bps)
        risk_stop_bps = self._risk_stop_bps(sig, price, stop_bps)
        hold = min(max(3.0 * sig.window_s, c.time_stop_min_s), c.time_stop_max_s)
        sigma_trade = max(sig.sigma_res_bps * math.sqrt(max(hold, sig.horizon_s) / max(sig.horizon_s, 1e-6)) * 0.5, 1.0)
        mu = net[mode] / BPS
        kelly = c.kelly_fraction * mu / (sigma_trade / BPS) ** 2 * eq
        risk_cap = c.risk_per_trade_frac * eq / (risk_stop_bps / BPS)
        caps = {"kelly": kelly, "risk": risk_cap, "trade": c.max_notional_frac * eq,
                "liq": qty_cap * price,
                "market": c.max_market_frac * eq - abs(self.exposure.get(sig.market, 0.0)),
                "gross": c.max_gross_frac * eq - sum(abs(v) for v in self.exposure.values())}
        beta_now = sum(self.beta_expo.values())
        room_beta = c.max_beta_net_frac * eq - sig.side * beta_now if sig.side * beta_now >= 0 else c.max_beta_net_frac * eq
        caps["beta"] = room_beta / max(sig.beta, 0.1)
        notional = max(min(caps.values()), 0.0) * c.size_mult
        if notional <= 0.0:
            return reject("exposure_cap")
        qty = notional / price
        # pass 2: recompute slippage at the actual size; edge can only improve vs worst-case, re-check anyway
        sp, fee, slip = self.costs(sig, qty, mode)
        net_final = credit_bps - (sp + fee + slip + c.safety_hurdle_bps)
        if net_final <= 0.0:
            dec.net_edge_bps = net_final
            return reject("net_edge_below_hurdle", "rejected_edge")
        dec.net_edge_bps, dec.spread_bps, dec.fee_bps, dec.slip_bps = net_final, sp, fee, slip
        dec.net_edge_taker_bps = net_final if mode == "taker" else dec.net_edge_taker_bps
        meta_min = c.min_notional
        if notional < meta_min:
            return reject("size_below_min")
        tp = max(c.tp_capture * credit_bps, sp + fee + slip + 0.25 * c.safety_hurdle_bps)
        dec.approved, dec.reason, dec.cohort = True, "ok", "approved"
        dec.notional, dec.qty = notional, qty
        dec.tp_bps, dec.stop_bps, dec.time_stop_s = tp, stop_bps, hold
        self.n_approved += 1
        self.reasons["ok"] += 1
        self.cohorts["approved"] += 1
        return dec

    def revoke(self, dec: Decision, reason: str) -> None:
        """Downgrade an approval that execution could not honour (e.g. rounded below min notional)."""
        if dec.approved:
            dec.approved, dec.reason, dec.cohort = False, reason, "rejected_other"
            self.n_approved -= 1
            self.reasons["ok"] -= 1
            self.cohorts["approved"] -= 1
            self.reasons[reason] += 1
            self.cohorts["rejected_other"] += 1

    # ------------------------------------------------------------------ Phase 5: queue-aware maker sniper
    def evaluate_snipe(self, sig: Signal, now: float, has_position: bool = False, n_open: int = 0) -> Decision:
        """Net edge for a *passive* entry (join / penny-jump) with a passive-then-taker exit.

            NetFilled = tp + entry_advantage - exit_spread - fees - adverse_buffer - hurdle
              entry_advantage = half-spread (join) or half-spread - 1 tick (penny)       [we buy at the bid instead of the mid]
              fees            = maker_in + p_xm*maker_out + (1-p_xm)*taker_out            [Polymarket maker = 0; HL maker ~1-1.5 bps]
              exit_spread     = (1-p_xm) * half-spread                                    [only the taker-fallback exits cross]
              adverse_buffer  = max(venue base learned from realised-vs-predicted shortfall, 0.75 x half-spread):
                                a passive fill is *conditionally* adverse, and on a 10 %-wide book that dwarfs everything else
            EV = P(fill) * NetFilled (an unfilled order costs nothing but the missed move).
        """
        c = self.cfg
        meta = self.book.metas[sig.idx]
        self.n_eval += 1
        hs = sig.spread_bps / 2.0
        tick_bps = (meta.tick / sig.mid * BPS) if meta.tick > 0 else 0.0
        two_ticks = meta.tick > 0 and (sig.ask - sig.bid) >= 2 * meta.tick - 1e-12
        credit_bps = c.edge_credit * abs(sig.gap_bps)
        tp_bps = c.tp_capture * credit_bps
        px = sig.bid if sig.side > 0 else sig.ask
        fee_in = maker_fee_bps(meta, c.fee_maker_bps)
        fee_ot = taker_fee_bps(meta, px, c.fee_taker_bps)
        p_xm = c.snipe_p_exit_maker
        fees = fee_in + p_xm * fee_in + (1.0 - p_xm) * fee_ot
        exit_spread = (1.0 - p_xm) * hs
        buf = max(c.snipe_adverse_bps.get(meta.venue, 0.0), c.snipe_adverse_hs_frac * hs)

        def net(mode):
            adv = hs - (tick_bps if mode == "penny" else 0.0)
            return tp_bps + adv - exit_spread - fees - buf - c.safety_hurdle_bps

        options = {"join": (net("join"), c.snipe_p_fill)}
        if c.snipe_penny and two_ticks:
            options["penny"] = (net("penny"), min(0.95, 1.5 * c.snipe_p_fill))
        mode = max(options, key=lambda m: options[m][0] * options[m][1])
        nf, pf = options[mode]
        dec = Decision(approved=False, reason="", mode="snipe", entry_mode=mode, net_edge_bps=nf, net_edge_taker_bps=nf, net_edge_maker_bps=nf,
                       gap_credit_bps=credit_bps, spread_bps=exit_spread, fee_bps=fees, slip_bps=buf, hurdle_bps=c.safety_hurdle_bps)

        def reject(reason: str, cohort: str = "rejected_other") -> Decision:
            dec.reason, dec.cohort = reason, cohort
            self.reasons[reason] += 1
            self.cohorts[cohort] += 1
            return dec

        if meta.venue in c.snipe_blocked:
            return reject("venue_disabled")
        if self.halted:
            return reject("halted")
        if self.is_blacklisted(sig.market, now):
            return reject("quarantined")
        if sig.spread_bps > c.snipe_gate_bps and meta.kind != "prediction":
            return reject("spread_too_wide", "rejected_gate")
        if sig.side < 0 and not c.allow_short:
            return reject("short_disabled")
        if has_position or n_open >= c.max_snipe_open:
            return reject("in_position")
        if nf <= 0.0:
            return reject("net_edge_below_hurdle", "rejected_edge")
        if pf * nf < c.snipe_min_ev_bps:
            return reject("low_ev", "rejected_edge")
        eq = self.equity
        stop_bps = max(c.stop_mult * sig.sigma_res_bps, c.min_stop_bps)
        risk_stop_bps = self._risk_stop_bps(sig, px, stop_bps)
        hold = min(max(3.0 * max(sig.window_s, 3.0), c.time_stop_min_s), c.time_stop_max_s)
        sigma_trade = max(sig.sigma_res_bps * 0.5, 1.0)
        kelly = c.kelly_fraction * (pf * nf / BPS) / (sigma_trade / BPS) ** 2 * eq
        caps = {"kelly": kelly, "risk": c.risk_per_trade_frac * eq / (risk_stop_bps / BPS), "trade": c.max_notional_frac * eq,
                "market": c.max_market_frac * eq - abs(self.exposure.get(sig.market, 0.0)),
                "gross": c.max_gross_frac * eq - sum(abs(v) for v in self.exposure.values())}
        notional = max(min(caps.values()), 0.0) * c.size_mult
        if notional <= 0.0:
            return reject("exposure_cap")
        if notional < max(c.min_notional, meta.min_notional):
            return reject("size_below_min")
        dec.approved, dec.reason, dec.cohort = True, "ok", "approved"
        dec.notional, dec.qty = notional, notional / max(px, 1e-12)
        dec.tp_bps, dec.stop_bps, dec.time_stop_s = tp_bps, stop_bps, hold
        self.n_approved += 1
        self.reasons["ok"] += 1
        self.cohorts["approved"] += 1
        return dec

    # ------------------------------------------------------------------ Phase 6 — Architecture A (quote maker)
    def quote_econ(self, idx: int, spread_bps: float) -> Tuple[float, float, float]:
        """(round-trip net bps, per-side maker fee bps, adverse buffer bps) for a quote at the touch."""
        c = self.cfg
        meta = self.book.metas[idx]
        fee = maker_fee_bps(meta, c.fee_maker_bps)
        buf = max(c.mm_adverse_bps.get(meta.venue, 0.0), c.snipe_adverse_hs_frac * spread_bps / 2.0)
        return spread_bps - 2.0 * fee - buf - c.safety_hurdle_bps, fee, buf

    def evaluate_quote(self, idx: int, now: float, mid: float, spread_bps: float, n_open: int = 0, ttl_s: float = 1e18) -> Decision:
        """Gate + size a *two-sided resting quote* on market ``idx`` (called while flat, before (re)posting).

            round-trip net = spread - 2 x maker fee - adverse buffer - hurdle      [both legs maker-filled, spread captured]
            adverse buffer = max(venue base (CEO/learned), 0.75 x half-spread)      [a resting quote is hit when it is *wrong*]

        Sizing uses the binary worst-case loss per share (long p, short 1-p) with a 50 % gap inside one latency, so the quote can
        never be sized by notional alone (the Phase 5 live drawdown). Inventory is capped at one clip per market.
        """
        c = self.cfg
        meta = self.book.metas[idx]
        net, fee, buf = self.quote_econ(idx, spread_bps)
        dec = Decision(approved=False, reason="", mode="quote", net_edge_bps=net, net_edge_maker_bps=net, spread_bps=spread_bps, fee_bps=2.0 * fee,
                       slip_bps=buf, hurdle_bps=c.safety_hurdle_bps)

        def reject(reason: str, cohort: str = "rejected_other") -> Decision:
            dec.reason, dec.cohort = reason, cohort
            self.reasons["mm_" + reason] += 1
            return dec

        if not c.mm_enabled or meta.venue in c.mm_blocked:
            return reject("venue_disabled")
        if self.halted:
            return reject("halted")
        if self.is_blacklisted(meta.id, now):
            return reject("quarantined")
        if meta.kind == "prediction" and ttl_s < self.poly_min_ttl:
            return reject("near_expiry")
        if net < c.mm_min_ev_bps:
            return reject("spread_too_thin_for_fees", "rejected_edge")
        if n_open >= c.max_mm_open:
            return reject("in_position")
        eq = self.equity
        stop_bps = c.mm_stop_bps.get(meta.venue, 6.0)
        risk_stop = max(self._risk_stop_idx(idx, 1, mid, stop_bps), self._risk_stop_idx(idx, -1, mid, stop_bps))
        caps = {"risk": c.risk_per_trade_frac * eq / (risk_stop / BPS), "trade": c.max_notional_frac * eq,
                "market": c.max_market_frac * eq - abs(self.exposure.get(meta.id, 0.0)),
                "gross": c.max_gross_frac * eq - sum(abs(v) for v in self.exposure.values())}
        notional = max(min(caps.values()), 0.0) * c.size_mult
        if notional <= 0.0:
            return reject("exposure_cap")
        if notional < max(c.min_notional, meta.min_notional):
            return reject("size_below_min")
        dec.approved, dec.reason, dec.cohort = True, "ok", "approved"
        dec.notional, dec.qty, dec.stop_bps = notional, notional / max(mid, 1e-12), stop_bps
        self.reasons["mm_ok"] += 1
        return dec

    def on_mm_result(self, r: dict) -> None:
        """Learn the adverse buffer from account round-trips (realised shortfall vs the spread the model expected)."""
        if r["outcome"] != "filled":
            return
        ew = getattr(self, "_mm_ew", {})
        short = max(r.get("pred_net_bps", 0.0) - r["net_bps"], 0.0)
        ew[r["venue"]] = 0.8 * ew.get(r["venue"], 0.0) + 0.2 * short
        self._mm_ew = ew
        base = getattr(self, "_mm_base", None)
        if base is None:
            base = self._mm_base = dict(self.cfg.mm_adverse_bps)
        self.cfg.mm_adverse_bps[r["venue"]] = min(max(base.get(r["venue"], 0.0), ew[r["venue"]]), 400.0)

    def set_mm_base(self, venue: str, val: float) -> None:
        base = getattr(self, "_mm_base", None)
        if base is None:
            base = self._mm_base = dict(self.cfg.mm_adverse_bps)
        base[venue] = max(val, 0.0)
        ew = getattr(self, "_mm_ew", {}).get(venue, 0.0)
        self.cfg.mm_adverse_bps[venue] = min(max(base[venue], ew), 400.0)
        self.directive_log.append({"directive": {"mm_adverse_base": (venue, val)}})

    # ------------------------------------------------------------------ Phase 6 — Architecture B (high-conviction taker sniper)
    def b_floor(self, sig: Signal, mult: Optional[float] = None) -> Tuple[float, float, float]:
        """(predicted move bps, floor bps, ratio). Hard rule: never fire a taker unless the predicted absolute move clears
        ``b_floor_mult`` x (spread + taker entry fee + maker exit fee) — all in bps of the entry price."""
        c = self.cfg
        meta = self.book.metas[sig.idx]
        px = sig.ask if sig.side > 0 else sig.bid
        cost = sig.spread_bps + taker_fee_bps(meta, px, c.fee_taker_bps) + maker_fee_bps(meta, c.fee_maker_bps)
        pred = c.edge_credit * abs(sig.gap_bps)
        floor = (c.b_floor_mult if mult is None else mult) * cost
        return pred, floor, (pred / floor if floor > 0 else 0.0)

    def evaluate_sniper_b(self, sig: Signal, now: float, has_position: bool = False, n_open: int = 0, regime_ok: bool = True) -> Decision:
        """Taker-in / maker-out. Absolute floor first (the rule), then the usual net-edge / risk sizing on top."""
        c = self.cfg
        meta = self.book.metas[sig.idx]
        self.n_eval += 1
        pred, floor, ratio = self.b_floor(sig)
        px = sig.ask if sig.side > 0 else sig.bid
        fee_in = taker_fee_bps(meta, px, c.fee_taker_bps)
        fee_mk = maker_fee_bps(meta, c.fee_maker_bps)
        p_xm = c.snipe_p_exit_maker
        hs = sig.spread_bps / 2.0
        tp_bps = c.b_tp_mult * pred
        # entry at the touch (pay the half-spread vs mid); passive exit at the converged touch pays none, a taker fallback pays the half-spread
        net = tp_bps - hs - fee_in - p_xm * fee_mk - (1.0 - p_xm) * (hs + taker_fee_bps(meta, px, c.fee_taker_bps)) - c.safety_hurdle_bps
        dec = Decision(approved=False, reason="", mode="b_snipe", net_edge_bps=net, net_edge_taker_bps=net, gap_credit_bps=pred, spread_bps=sig.spread_bps,
                       fee_bps=fee_in + fee_mk, slip_bps=floor, hurdle_bps=c.safety_hurdle_bps, entry_mode="taker")

        def reject(reason: str, cohort: str = "rejected_other") -> Decision:
            dec.reason, dec.cohort = reason, cohort
            self.reasons["b_" + reason] += 1
            return dec

        if meta.venue in c.b_blocked or not c.b_enabled:
            return reject("venue_disabled")
        if self.halted:
            return reject("halted")
        if self.is_blacklisted(sig.market, now):
            return reject("quarantined")
        if sig.side < 0 and not c.allow_short:
            return reject("short_disabled")
        if pred < floor:
            return reject("below_absolute_floor", "rejected_edge")
        if not regime_ok:
            return reject("regime_gate", "rejected_gate")                     # Phase 10: pre-impulse sigma60 too high (or unknown)
        if has_position or n_open >= c.max_b_open:
            return reject("in_position")
        if net <= 0.0 or net < c.b_min_ev_bps:
            return reject("net_edge_below_hurdle", "rejected_edge")
        eq = self.equity
        stop_bps = max(c.stop_mult * sig.sigma_res_bps, c.min_stop_bps)
        risk_stop = self._risk_stop_bps(sig, px, stop_bps)
        hold = min(max(3.0 * max(sig.window_s, 3.0), c.time_stop_min_s), c.time_stop_max_s)
        sigma_trade = max(sig.sigma_res_bps * 0.5, 1.0)
        kelly = c.kelly_fraction * (net / BPS) / (sigma_trade / BPS) ** 2 * eq
        caps = {"kelly": kelly, "risk": c.risk_per_trade_frac * eq / (risk_stop / BPS), "trade": c.max_notional_frac * eq,
                "market": c.max_market_frac * eq - abs(self.exposure.get(sig.market, 0.0)),
                "gross": c.max_gross_frac * eq - sum(abs(v) for v in self.exposure.values())}
        notional = max(min(caps.values()), 0.0) * c.size_mult
        if notional <= 0.0:
            return reject("exposure_cap")
        if notional < max(c.min_notional, meta.min_notional):
            return reject("size_below_min")
        dec.approved, dec.reason, dec.cohort = True, "ok", "approved"
        dec.notional, dec.qty = notional, notional / max(px, 1e-12)
        dec.tp_bps, dec.stop_bps, dec.time_stop_s = tp_bps, stop_bps, hold
        self.n_approved += 1
        self.reasons["b_ok"] += 1
        return dec

    def on_b_result(self, r: dict) -> None:
        if r["outcome"] != "filled":
            return
        a = 0.15
        c = self.cfg
        c.snipe_p_exit_maker = min(max((1 - a) * c.snipe_p_exit_maker + a * float(r.get("exit_kind") == "passive"), 0.05), 0.95)

    def set_snipe_base(self, venue: str, val: float) -> None:
        """CEO directive: raise/lower the venue's base adverse-selection buffer (survives the CFO's online learning)."""
        base = getattr(self, "_adv_base", None)
        if base is None:
            base = self._adv_base = dict(self.cfg.snipe_adverse_bps)
        base[venue] = max(val, 0.0)
        ew = getattr(self, "_adv_ew", {}).get(venue, 0.0)
        self.cfg.snipe_adverse_bps[venue] = min(max(base[venue], ew), 400.0)
        self.directive_log.append({"directive": {"snipe_adverse_base": (venue, val)}})

    def on_snipe_result(self, r: dict) -> None:
        """Learn fill probability, passive-exit probability and the adverse-selection buffer from account attempts."""
        c = self.cfg
        self._snipe_n = getattr(self, "_snipe_n", 0) + 1
        a = 0.15
        if self._snipe_n >= 5:
            c.snipe_p_fill = min(max((1 - a) * c.snipe_p_fill + a * float(r["outcome"] == "filled"), 0.03), 0.95)
        if r["outcome"] == "filled":
            c.snipe_p_exit_maker = min(max((1 - a) * c.snipe_p_exit_maker + a * float(r.get("exit_kind") == "passive"), 0.05), 0.95)
            short = max(r.get("pred_net_bps", 0.0) - r["net_bps"], 0.0)
            ew = getattr(self, "_adv_ew", {})
            ew[r["venue"]] = 0.8 * ew.get(r["venue"], short) + 0.2 * short
            self._adv_ew = ew
            base = getattr(self, "_adv_base", None)
            if base is None:
                base = self._adv_base = dict(c.snipe_adverse_bps)
            c.snipe_adverse_bps[r["venue"]] = min(max(base.get(r["venue"], 0.0), ew[r["venue"]]), 400.0)

    # ------------------------------------------------------------------ position / PnL accounting
    def on_open(self, market: str, side: int, notional: float, beta: float) -> None:
        self.exposure[market] = self.exposure.get(market, 0.0) + side * notional
        self.beta_expo[market] = self.beta_expo.get(market, 0.0) + side * notional * beta

    def on_close(self, market: str, side: int, notional: float, beta: float) -> None:
        self.exposure[market] = self.exposure.get(market, 0.0) - side * notional
        self.beta_expo[market] = self.beta_expo.get(market, 0.0) - side * notional * beta
        if abs(self.exposure[market]) < 1e-9:
            self.exposure.pop(market, None)
            self.beta_expo.pop(market, None)

    def on_maker_result(self, filled: bool) -> None:
        self.maker_attempts += 1
        self.maker_fills += int(filled)
        if self.maker_attempts >= 5:                       # EW realised fill probability
            self.cfg.p_fill_maker = min(max(0.8 * self.cfg.p_fill_maker + 0.2 * float(filled), 0.05), 0.95)

    def on_trade_closed(self, tr, now: float) -> None:
        c = self.cfg
        self.equity += tr.net_pnl_usd
        self.closed_pnl += tr.net_pnl_usd
        self.fees_paid += tr.fees_usd
        self.peak = max(self.peak, self.equity)
        dq = self.market_pnl[tr.market]
        dq.append((now, tr.net_pnl_usd))
        while dq and now - dq[0][0] > 1800.0:
            dq.popleft()
        if sum(p for _, p in dq) < -c.market_loss_frac * self.equity:
            self.blacklist[tr.market] = (now + c.breaker_cooldown_s, "market_loss_breaker")
            self.reasons["breaker_market"] += 1
        if self.day_t0 is None:
            self.day_t0 = now
        if now - self.day_t0 > 86400.0:
            self.day_t0, self.day_start = now, self.equity
        if self.equity < self.peak * (1.0 - c.portfolio_dd_frac):
            self.trip("portfolio_drawdown", now)
        elif self.equity < self.day_start * (1.0 - c.daily_loss_frac):
            self.trip("daily_loss", now)

    # ------------------------------------------------------------------ reporting
    def drawdown_frac(self) -> float:
        return 1.0 - self.equity / self.peak if self.peak > 0 else 0.0

    def report(self) -> dict:
        return {"equity": self.equity, "peak": self.peak, "drawdown_frac": self.drawdown_frac(),
                "closed_pnl": self.closed_pnl, "fees_paid": self.fees_paid, "evaluated": self.n_eval,
                "approved": self.n_approved, "reasons": dict(self.reasons), "halted": self.halted,
                "halt_reason": self.halt_reason, "gross_exposure": sum(abs(v) for v in self.exposure.values()),
                "blacklist": {k: v[1] for k, v in self.blacklist.items()},
                "hurdle_bps": self.cfg.safety_hurdle_bps, "edge_credit": self.cfg.edge_credit,
                "mode_policy": self.cfg.mode_policy, "size_mult": self.cfg.size_mult,
                "p_fill_maker": self.cfg.p_fill_maker}
