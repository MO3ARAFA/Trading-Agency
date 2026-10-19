"""Battleground 1 — direct (locked) cross-venue arbitrage and triangular/synthetic crosses.

*Cross-venue*: for every same-asset pair of markets (e.g. ETH on Binance-USDT, Binance-USDC, Gate, Kraken, Coinbase,
Hyperliquid perp) the locked gap is   sell at Bid_A,  buy at Ask_B :

    gap_bps = [ ln Bid_A - ln Ask_B - basis_AB ] * 1e4,     basis_AB = EW mean of ln mid_A - ln mid_B

The EW basis removes the stable-coin / quote-currency spread (USDT vs USD vs USDC vs FDUSD) and perp funding basis, so only
*dislocations around the long-run basis* are candidates. This is NOT risk-free: basis can move, and two-venue inventory must
exist on both sides (ignored in paper mode; reported as an assumption).

*Triangular*: Binance X/Y, X/Z, Y/Z (ETHBTC vs ETHUSDT & BTCUSDT; BTCUSDC vs BTCUSDT & USDCUSDT; ...), both cycles, 3 legs.

An opportunity trades only if  gap > fee_A + fee_B (+ slippage + safety hurdle)  — the brief's "direct arbitrage gap exceeds
total execution cost" — and CFO limits allow. Paper execution is two/three-leg IOC at the *detected* prices after the assumed order
latency using as-of quotes, so leg risk (one leg fills, the other misses) is simulated, not assumed away. Every opportunity,
traded or not, is shadow-tracked for whether it still exists at fill time (persistence), which is the real test of "arb".
"""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
from numba import njit

from .cfo_agent import CFOAgent
from .config import ArbConfig
from .execution_engine import TradeResult
from .market_watchers import AQ, ASK, BID, BQ, LAST_T, MID, NTICK, MarketBook, taker_fee_bps

BPS = 1e4


@njit(cache=True)
def _pair_gaps(state, pi, pj, basis, ok, out):
    for k in range(pi.shape[0]):
        if not ok[k]:
            out[k, 0] = -1e9
            out[k, 1] = -1e9
            continue
        i, j = pi[k], pj[k]
        out[k, 0] = (np.log(state[i, BID]) - np.log(state[j, ASK]) - basis[k]) * 1e4      # sell i, buy j
        out[k, 1] = (np.log(state[j, BID]) - np.log(state[i, ASK]) + basis[k]) * 1e4      # sell j, buy i


@dataclass
class Leg:
    idx: int
    side: int                    # +1 buy at ask, -1 sell at bid
    limit: float = 0.0


@dataclass
class ArbOpp:
    aid: int
    kind: str                    # xvenue | triangle
    name: str
    t0: float
    legs: List[Leg]
    gap_bps: float
    fee_bps: float
    slip_bps: float
    net_bps: float
    notional: float
    approved: bool
    reason: str
    basis_adj: List[float] = field(default_factory=list)
    t_end: float = 0.0
    # resolution
    resolved: bool = False
    gap_fill_bps: float = float("nan")
    net_fill_bps: float = float("nan")
    status: str = "pending"      # locked | leg_risk | missed | shadow
    pnl_usd: float = 0.0

    def row(self) -> dict:
        return {"aid": self.aid, "kind": self.kind, "name": self.name, "t0": self.t0, "gap_bps": self.gap_bps, "fee_bps": self.fee_bps,
                "slip_bps": self.slip_bps, "net_bps": self.net_bps, "notional": self.notional, "approved": self.approved,
                "reason": self.reason, "gap_fill_bps": self.gap_fill_bps, "net_fill_bps": self.net_fill_bps, "status": self.status,
                "pnl_usd": self.pnl_usd, "life_s": self.t_end - self.t0 if self.t_end else None}


class CrossVenueArb:
    def __init__(self, book: MarketBook, cfo: CFOAgent, cfg: Optional[ArbConfig] = None):
        self.book, self.cfo = book, cfo
        self.cfg = cfg or ArbConfig()
        c = self.cfg
        self.n_scans = 0
        # ---- same-asset pairs (cross-venue and cross-quote)
        groups: Dict[str, List[int]] = {}
        for i, m in enumerate(book.metas):
            if m.kind in ("spot", "perp") and m.asset and m.venue != "polymarket" and m.hunt:
                groups.setdefault(m.asset, []).append(i)
        pairs = []
        for a, ids in groups.items():
            for i, j in itertools.combinations(ids, 2):
                mi, mj = book.metas[i], book.metas[j]
                if mi.venue == mj.venue and mi.quote == mj.quote:
                    continue
                pairs.append((i, j))
        self.pi = np.array([p[0] for p in pairs], dtype=np.int64)
        self.pj = np.array([p[1] for p in pairs], dtype=np.int64)
        P = len(pairs)
        self.basis = np.zeros(P)
        self.basis_n = np.zeros(P, dtype=np.int64)
        self._gaps = np.zeros((P, 2))
        self._ok = np.zeros(P, dtype=np.bool_)
        self.pair_names = [f"{book.ids[i]}|{book.ids[j]}" for i, j in pairs]
        self.alpha_b = 1.0 - 0.5 ** (c.basis_update_s / c.basis_halflife_s)
        self.last_basis = -1e18
        # ---- triangles on Binance: X/Y, X/Z, Y/Z
        idx = {m.symbol: i for i, m in enumerate(book.metas) if m.venue == "binance"}
        self.tris: List[Tuple[str, int, int, int]] = []
        for ysym, zq in (("BTC", "USDT"), ("USDC", "USDT"), ("FDUSD", "USDT")):
            yz = idx.get(f"{ysym}{zq}")
            if yz is None:
                continue
            for xs in sorted({m.base for m in book.metas if m.venue == "binance"}):
                if xs == ysym:
                    continue
                xy, xz = idx.get(f"{xs}{ysym}"), idx.get(f"{xs}{zq}")
                if xy is not None and xz is not None:
                    self.tris.append((f"{xs}/{ysym}~{xs}/{zq}~{ysym}/{zq}", xy, xz, yz))
        # ---- state
        self.active: Dict[Tuple[str, int], ArbOpp] = {}      # live episodes keyed by (name, direction)
        self.pending: List[ArbOpp] = []
        self.opps: List[ArbOpp] = []
        self._aid = 0
        self.last_scan = -1e18
        self.pair_stats: Dict[str, dict] = {}
        self.closed_trades: List[TradeResult] = []
        self.episode_lifetimes: List[float] = []
        self.resolved_buffer: List[dict] = []     # drained by the Agency into arb_opps.jsonl

    # -------------------------------------------------------------------- basis
    def update_basis(self, t: float) -> None:
        if t - self.last_basis < self.cfg.basis_update_s or self.pi.size == 0:
            return
        self.last_basis = t
        st = self.book.state
        fresh = (st[:, NTICK] > 0) & (t - st[:, LAST_T] <= self.cfg.max_quote_age_s)
        ok = fresh[self.pi] & fresh[self.pj]
        d = np.log(st[self.pi, MID] + 1e-300) - np.log(st[self.pj, MID] + 1e-300)
        for_init = ok & (self.basis_n == 0)
        self.basis[for_init] = d[for_init]
        upd = ok & (self.basis_n > 0)
        a = np.maximum(self.alpha_b, 1.0 / np.maximum(self.basis_n, 1))
        self.basis[upd] += a[upd] * (d[upd] - self.basis[upd])
        self.basis_n[ok] += 1

    # -------------------------------------------------------------------- sizing helpers
    def _top_notional(self, idx: int, side: int) -> float:
        st = self.book.state[idx]
        meta = self.book.metas[idx]
        px = st[ASK] if side > 0 else st[BID]
        q = st[AQ] if side > 0 else st[BQ]
        if meta.extra.get("size_unit") == "usd":
            return q
        usd_per_quote = float(self.book.state[0, MID]) if meta.quote == "BTC" else 1.0     # BTC-quoted legs -> USD
        return q * px * usd_per_quote

    def _fee(self, idx: int) -> float:
        return taker_fee_bps(self.book.metas[idx], float(self.book.state[idx, MID]), self.cfo.cfg.fee_taker_bps)

    def _slip(self, idxs: List[int], notional: float, sides: List[int]) -> float:
        c = self.cfo.cfg
        s = 0.0
        for idx, sd in zip(idxs, sides):
            st = self.book.state[idx]
            spread = (st[ASK] - st[BID]) / st[MID] * BPS
            top = max(self._top_notional(idx, sd), 1e-9)
            s += c.slip_depth_coeff * spread * min(notional / top, 4.0)
        return s

    # -------------------------------------------------------------------- scan
    def scan(self, t: float) -> List[ArbOpp]:
        c = self.cfg
        if t - self.last_scan < c.scan_min_interval_s:
            return []
        self.last_scan = t
        self.n_scans += 1
        self.update_basis(t)
        out: List[ArbOpp] = []
        st = self.book.state
        if self.pi.size:
            fresh = (st[:, NTICK] > 0) & (t - st[:, LAST_T] <= c.max_quote_age_s)
            ok = fresh[self.pi] & fresh[self.pj] & (self.basis_n >= c.basis_min_samples)
            _pair_gaps(st, self.pi, self.pj, self.basis, ok, self._gaps)
            hot = np.argwhere(self._gaps >= c.record_gap_bps)
            seen = set()
            for k, d in hot:
                k, d = int(k), int(d)
                seen.add((k, d))
                key = (self.pair_names[k], d)
                if key in self.active:
                    continue
                i, j = int(self.pi[k]), int(self.pj[k])
                sell, buy = (i, j) if d == 0 else (j, i)
                opp = self._make_opp("xvenue", f"{self.book.ids[sell]}>{self.book.ids[buy]}", t,
                                     [Leg(sell, -1), Leg(buy, +1)], float(self._gaps[k, d]))
                self.active[key] = opp
                out.append(opp)
            for key in [k for k in self.active if k[0] in self.pair_names_set() and (self.pair_index(k[0]), k[1]) not in seen]:
                self._end_episode(key, t)
        for name, xy, xz, yz in self.tris:
            for d in (0, 1):
                g = self._tri_gap(xy, xz, yz, d, t)
                key = (name, d)
                if g is None or g < c.record_gap_bps:
                    if key in self.active:
                        self._end_episode(key, t)
                    continue
                if key in self.active:
                    continue
                legs = ([Leg(xz, +1), Leg(xy, -1), Leg(yz, -1)] if d == 0 else [Leg(yz, +1), Leg(xy, +1), Leg(xz, -1)])
                opp = self._make_opp("triangle", name + (">" if d == 0 else "<"), t, legs, g)
                self.active[key] = opp
                out.append(opp)
        return out

    def pair_names_set(self):
        if not hasattr(self, "_pns"):
            self._pns = set(self.pair_names)
            self._pni = {n: k for k, n in enumerate(self.pair_names)}
        return self._pns

    def pair_index(self, name: str) -> int:
        self.pair_names_set()
        return self._pni[name]

    def _tri_gap(self, xy: int, xz: int, yz: int, d: int, t: float) -> Optional[float]:
        st = self.book.state
        c = self.cfg
        for i in (xy, xz, yz):
            if st[i, NTICK] == 0 or t - st[i, LAST_T] > c.max_quote_age_s:
                return None
        if d == 0:      # buy X with Z, sell X for Y, sell Y for Z
            r = st[xy, BID] * st[yz, BID] / st[xz, ASK]
        else:           # buy Y with Z, buy X with Y, sell X for Z
            r = st[xz, BID] / (st[xy, ASK] * st[yz, ASK])
        return (math.log(r)) * BPS

    def _end_episode(self, key, t: float) -> None:
        opp = self.active.pop(key, None)
        if opp is not None:
            opp.t_end = t
            self.episode_lifetimes.append(t - opp.t0)

    # -------------------------------------------------------------------- opportunity -> CFO -> pending execution
    def _make_opp(self, kind: str, name: str, t: float, legs: List[Leg], gap: float) -> ArbOpp:
        c, cc = self.cfg, self.cfo.cfg
        idxs = [l.idx for l in legs]
        sides = [l.side for l in legs]
        eq = self.cfo.equity
        notional = min(cc.max_notional_frac * eq, *(cc.liquidity_frac * self._top_notional(i, s) for i, s in zip(idxs, sides)))
        notional *= cc.size_mult
        fee = sum(self._fee(i) for i in idxs)
        slip = self._slip(idxs, notional, sides)
        net = gap - (fee + slip + cc.safety_hurdle_bps)
        self._aid += 1
        reason = "ok"
        approved = True
        if self.cfo.halted:
            approved, reason = False, "halted"
        elif self.cfo.is_blacklisted(name, t):
            approved, reason = False, "quarantined"
        elif net <= 0:
            approved, reason = False, "gap_below_cost"
        elif notional < cc.min_notional:
            approved, reason = False, "size_below_min"
        opp = ArbOpp(self._aid, kind, name, t, legs, gap, fee, slip, net, notional, approved, reason)
        for l in legs:                                                        # IOC limit = detected price, with slack = half the margin
            st = self.book.state[l.idx]
            slack = max(0.5 * net, 0.0) / BPS if approved else 0.0
            l.limit = (st[ASK] * (1 + slack)) if l.side > 0 else (st[BID] * (1 - slack))
        self.pending.append(opp)
        self.opps.append(opp)
        if len(self.opps) > 50_000:
            del self.opps[:10_000]
        return opp

    # -------------------------------------------------------------------- resolution (as-of quotes at t0 + latency)
    def poll(self, now: float) -> List[TradeResult]:
        lat = self.cfo.cfg.latency_s
        done: List[TradeResult] = []
        keep = []
        for o in self.pending:
            if now < o.t0 + lat:
                keep.append(o)
                continue
            tf = o.t0 + lat
            quotes = [self.book.quote_asof(l.idx, tf) for l in o.legs]
            if any(q is None for q in quotes):
                o.resolved, o.status = True, "missed"
                self.resolved_buffer.append(o.row())
                continue
            filled = []
            for l, (b, a) in zip(o.legs, quotes):
                px = a if l.side > 0 else b
                filled.append((px <= l.limit) if l.side > 0 else (px >= l.limit))
            o.gap_fill_bps = self._gap_at(o, quotes)
            o.net_fill_bps = o.gap_fill_bps - (o.fee_bps + o.slip_bps + self.cfo.cfg.safety_hurdle_bps)
            o.resolved = True
            self.resolved_buffer.append(o.row())
            if not o.approved:
                o.status = "shadow"
            elif all(filled):
                o.status = "locked"
                tr = self._trade(o, tf, o.gap_fill_bps, o.fee_bps + o.slip_bps, "locked")
                done.append(tr)
            elif any(filled):
                o.status = "leg_risk"
                loss_bps = 0.0
                for l, (b, a), f in zip(o.legs, quotes, filled):
                    if f:                                                  # unwind the stray leg: pay half-spread both ways + fees
                        loss_bps += (a - b) / (0.5 * (a + b)) * BPS + 2 * self._fee(l.idx)
                tr = self._trade(o, tf, -loss_bps, 0.0, "leg_risk")
                done.append(tr)
            else:
                o.status = "missed"
            st = self.pair_stats.setdefault(o.name, {"n": 0, "locked": 0, "leg_risk": 0, "missed": 0, "pnl": 0.0, "net_bps": []})
            st["n"] += 1
            if o.status in st:
                st[o.status] += 1
        self.pending = keep
        return done

    def _gap_at(self, o: ArbOpp, quotes) -> float:
        px = [(a if l.side > 0 else b) for l, (b, a) in zip(o.legs, quotes)]
        if o.kind == "xvenue":
            si, bi = o.legs[0].idx, o.legs[1].idx
            k = self._pair_of(si, bi)
            basis = self.basis[k[0]] * (1.0 if k[1] == 0 else -1.0)
            return (math.log(px[0]) - math.log(px[1]) - basis) * BPS
        # triangle: product/ratio of leg prices according to the cycle
        l0, l1, l2 = o.legs
        if l0.side > 0 and l1.side < 0:      # buy X(Z), sell X(Y), sell Y(Z)
            r = px[1] * px[2] / px[0]
        else:                                 # buy Y(Z), buy X(Y), sell X(Z)
            r = px[2] / (px[1] * px[0])
        return math.log(r) * BPS

    def _pair_of(self, sell: int, buy: int) -> Tuple[int, int]:
        """(pair index, direction) for sell/buy markets."""
        if not hasattr(self, "_pidx"):
            self._pidx = {(int(i), int(j)): k for k, (i, j) in enumerate(zip(self.pi, self.pj))}
        if (sell, buy) in self._pidx:
            return self._pidx[(sell, buy)], 0
        return self._pidx[(buy, sell)], 1

    def _trade(self, o: ArbOpp, tf: float, gross_bps: float, cost_bps: float, why: str) -> TradeResult:
        notional = o.notional
        gross_usd = notional * gross_bps / BPS
        fees_usd = notional * (o.fee_bps if why == "locked" else cost_bps) / BPS
        slip_usd = notional * (o.slip_bps if why == "locked" else 0.0) / BPS
        net = gross_usd - fees_usd - slip_usd if why == "locked" else gross_usd
        o.pnl_usd = net
        st = self.pair_stats.setdefault(o.name, {"n": 0, "locked": 0, "leg_risk": 0, "missed": 0, "pnl": 0.0, "net_bps": []})
        st["pnl"] += net
        st["net_bps"].append(net / notional * BPS)
        tr = TradeResult(oid=o.aid, sid=o.aid, market=o.name, side=1, mode="arb", t_entry=tf, t_exit=tf, entry_px=0.0, exit_px=0.0,
                         qty=0.0, notional=notional, gross_bps=gross_bps, fees_usd=fees_usd + slip_usd, net_pnl_usd=net,
                         net_bps=net / notional * BPS, R=net / max(notional * 5.0 / BPS, 1e-9), exit_reason=why, hold_s=0.0,
                         entry_slip_bps=0.0, exit_slip_bps=0.0, spread_bps_entry=0.0, predicted_net_bps=o.net_bps,
                         gap_bps=o.gap_bps, predicted_slip_bps=o.slip_bps)
        self.closed_trades.append(tr)
        self.cfo.on_trade_closed(tr, tf)
        return tr

    # -------------------------------------------------------------------- telemetry
    def summary(self) -> dict:
        rows = [o for o in self.opps if o.resolved]
        g = np.array([o.gap_bps for o in self.opps]) if self.opps else np.zeros(0)
        net0 = np.array([o.gap_bps - (o.fee_bps + o.slip_bps) for o in self.opps]) if self.opps else np.zeros(0)
        gf = np.array([o.gap_fill_bps for o in rows if np.isfinite(o.gap_fill_bps)]) if rows else np.zeros(0)
        out = {"pairs": len(self.pair_names), "triangles": len(self.tris), "scans": self.n_scans, "episodes": len(self.opps),
               "gross_gt_0": int((g > 0).sum()), "net_gt_0_at_detect": int(sum(1 for o in self.opps if o.net_bps > 0)),
               "net_gt_0_at_fill": int(sum(1 for o in rows if np.isfinite(o.net_fill_bps) and o.net_fill_bps > 0)),
               "executed": len(self.closed_trades), "pnl_usd": float(sum(t.net_pnl_usd for t in self.closed_trades)),
               "gap_p50": float(np.median(g)) if g.size else 0.0, "gap_p90": float(np.percentile(g, 90)) if g.size else 0.0,
               "gap_max": float(g.max()) if g.size else 0.0,
               "gap_fill_mean": float(gf.mean()) if gf.size else 0.0,
               "life_p50": float(np.median(self.episode_lifetimes)) if self.episode_lifetimes else 0.0,
               "life_p90": float(np.percentile(self.episode_lifetimes, 90)) if self.episode_lifetimes else 0.0,
               "reasons": {}}
        for o in self.opps:
            out["reasons"][o.reason] = out["reasons"].get(o.reason, 0) + 1
        return out
