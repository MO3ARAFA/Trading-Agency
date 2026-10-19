"""Phase 7 — strictly isolated risk sleeves.

Phase 6 ran two engines on one CFO book and one CEO state machine: Architecture A lost $25 and the portfolio-level expectancy gate
halted Architecture B (122 B decisions refused). A *sleeve* removes that coupling by construction:

  * its own ``CFOAgent`` — own equity / peak / exposure / per-market P&L / blacklist / breakers / ``halted`` flag / config copy
    (so a CEO change to one sleeve's floor or size multiplier cannot leak into another);
  * its own governor — a four-state machine (NORMAL → TIGHTENED → DEFENSIVE → HALTED, then timed probation) that looks **only at that
    sleeve's own account round trips** (cluster-robust by BTC impulse) and only moves that sleeve's knobs (b_floor_mult, size_mult).

Nothing in a sleeve reads another sleeve, and nothing outside the sleeve (the global CEO, the legacy taker CFO) reads or writes it.
Sleeves are independent paper bankrolls (``capital_usd`` each), so "polymarket_b" can lose money without moving "hyperliquid_b".
"""
from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Dict, List, Optional

import numpy as np

from .cfo_agent import CFOAgent
from .config import CFOConfig
from .market_watchers import MarketBook


class SleeveState(str, Enum):
    NORMAL = "NORMAL"
    TIGHTENED = "TIGHTENED"
    DEFENSIVE = "DEFENSIVE"
    HALTED = "HALTED"


@dataclass
class SleeveConfig:
    review_interval_s: float = 30.0
    n_min: int = 6                       # fresh round trips needed before the governor acts either way
    tol_bps: dict = field(default_factory=lambda: {"hyperliquid": 0.5, "polymarket": 150.0})   # |mean net| tolerance, bps of notional
    floor_step: float = 0.5
    floor_cap: float = 4.0
    size_mult: dict = field(default_factory=lambda: {"NORMAL": 1.0, "TIGHTENED": 0.5, "DEFENSIVE": 0.25, "HALTED": 0.0})
    halt_cooldown_s: float = 600.0


@dataclass
class SleeveEvent:
    t: float
    sleeve: str
    kind: str
    from_state: str
    to_state: str
    reason: str
    evidence: dict
    before: dict
    after: dict

    def as_dict(self):
        return asdict(self)


def cluster_se(rows: List[dict], key: str = "net_bps") -> float:
    n = len(rows)
    if n < 2:
        return 0.0
    x = np.array([r[key] for r in rows], dtype=float)
    mu = x.mean()
    by: Dict[object, float] = {}
    for r, v in zip(rows, x):
        k = r.get("imp", id(r))
        by[k] = by.get(k, 0.0) + (v - mu)
    cl = np.array(list(by.values()))
    return float(np.sqrt((cl ** 2).sum()) / n) if len(cl) > 1 else float(x.std(ddof=1) / np.sqrt(n))


class Sleeve:
    def __init__(self, name: str, venue: str, book: MarketBook, base_cfg: CFOConfig, capital: float, poly_min_ttl: float = 60.0,
                 scfg: Optional[SleeveConfig] = None):
        self.name, self.venue = name, venue
        self.scfg = scfg or SleeveConfig()
        cfg = copy.deepcopy(base_cfg)                       # own config object: no knob is shared with anything else
        cfg.capital_usd = capital
        self.cfo = CFOAgent(book, cfg)
        self.cfo.poly_min_ttl = poly_min_ttl
        self.base_floor = cfg.b_floor_mult
        self.state = SleeveState.NORMAL
        self.results: List[dict] = []                       # this sleeve's account round trips only
        self.events: List[SleeveEvent] = []
        self.epoch = -1e18
        self.halt_until = -1.0
        self.last_review = -1e18
        self.n_halts = 0

    # ---- bookkeeping
    def add_result(self, r: dict) -> None:
        self.results.append(r)

    def fresh(self) -> List[dict]:
        return [r for r in self.results if r["outcome"] == "filled" and r["t_end"] >= self.epoch]

    def _log(self, now, kind, frm, reason, ev, before, after) -> SleeveEvent:
        e = SleeveEvent(now, self.name, kind, frm.value, self.state.value, reason, ev, before, after)
        self.events.append(e)
        return e

    def _apply(self, state: SleeveState, floor: Optional[float] = None) -> None:
        self.state = state
        c = self.cfo.cfg
        c.size_mult = self.scfg.size_mult[state.value]
        if floor is not None:
            c.b_floor_mult = floor

    # ---- the governor
    def review(self, now: float) -> List[SleeveEvent]:
        if now - self.last_review < self.scfg.review_interval_s:
            return []
        self.last_review = now
        out: List[SleeveEvent] = []
        c = self.cfo.cfg
        s = self.scfg
        if self.cfo.halted and self.state != SleeveState.HALTED:           # a CFO breaker (drawdown / daily loss) tripped inside this sleeve
            before = {"state": self.state.value, "size_mult": c.size_mult}
            frm, self.state = self.state, SleeveState.HALTED
            self.halt_until = now + c.breaker_cooldown_s
            self.n_halts += 1
            out.append(self._log(now, "SLEEVE_BREAKER_HALT", frm, f"CFO breaker `{self.cfo.halt_reason}` inside this sleeve; standing down {c.breaker_cooldown_s:.0f}s",
                                 {"drawdown": round(self.cfo.drawdown_frac(), 4)}, before, {"state": "HALTED"}))
            self.epoch = now
            return out
        if self.state == SleeveState.HALTED:
            if now >= self.halt_until:
                self.cfo.halted = False
                self.cfo.halt_reason = ""
                self.cfo.peak = self.cfo.equity                      # probation starts from the current equity, not the old high-water mark
                before = {"state": "HALTED"}
                self._apply(SleeveState.DEFENSIVE, max(c.b_floor_mult, 3.0))
                self.epoch = now
                out.append(self._log(now, "SLEEVE_RESUME_PROBATION", SleeveState.HALTED, "cooldown over: resume at 0.25x size and a 3x floor", {}, before,
                                     {"state": "DEFENSIVE", "size_mult": c.size_mult, "b_floor_mult": c.b_floor_mult}))
            return out
        rows = self.fresh()
        if len(rows) < s.n_min:
            return out
        nb = np.array([r["net_bps"] for r in rows])
        se = cluster_se(rows)
        tol = s.tol_bps.get(self.venue, 1.0)
        ev = {"n": len(rows), "net_bps": round(float(nb.mean()), 3), "se": round(se, 3), "floor": c.b_floor_mult, "equity": round(self.cfo.equity, 2)}
        before = {"state": self.state.value, "b_floor_mult": c.b_floor_mult, "size_mult": c.size_mult}
        if float(nb.mean()) + se < -tol:                                    # significantly bad: step the sleeve down
            frm = self.state
            if self.state == SleeveState.NORMAL:
                self._apply(SleeveState.TIGHTENED, min(c.b_floor_mult + s.floor_step, s.floor_cap))
                kind = "SLEEVE_TIGHTEN"
            elif self.state == SleeveState.TIGHTENED:
                self._apply(SleeveState.DEFENSIVE, min(max(c.b_floor_mult + s.floor_step, 3.0), s.floor_cap))
                kind = "SLEEVE_DEFENSIVE"
            else:
                self._apply(SleeveState.HALTED)
                self.cfo.trip("sleeve_governor", now)
                self.halt_until = now + s.halt_cooldown_s
                self.n_halts += 1
                kind = "SLEEVE_HALT"
            self.epoch = now
            out.append(self._log(now, kind, frm, f"net {nb.mean():+.1f}±{se:.1f} bps over {len(rows)} fresh round trips < −{tol:g}", ev, before,
                                 {"state": self.state.value, "b_floor_mult": c.b_floor_mult, "size_mult": c.size_mult}))
        elif float(nb.mean()) - se > 0.0 and self.state != SleeveState.NORMAL:   # significantly good: relax one notch
            frm = self.state
            if self.state == SleeveState.DEFENSIVE:
                self._apply(SleeveState.TIGHTENED, max(c.b_floor_mult - s.floor_step, self.base_floor))
            else:
                self._apply(SleeveState.NORMAL, self.base_floor)
            self.epoch = now
            out.append(self._log(now, "SLEEVE_RELAX", frm, f"net {nb.mean():+.1f}±{se:.1f} bps over {len(rows)} fresh round trips > 0", ev, before,
                                 {"state": self.state.value, "b_floor_mult": c.b_floor_mult, "size_mult": c.size_mult}))
        return out

    def summary(self) -> dict:
        c = self.cfo
        return {"sleeve": self.name, "state": self.state.value, "equity": round(c.equity, 2), "peak": round(c.peak, 2), "halted": c.halted,
                "halt_reason": c.halt_reason, "round_trips": sum(1 for r in self.results if r["outcome"] == "filled"), "fees_paid": round(c.fees_paid, 2),
                "closed_pnl": round(c.closed_pnl, 2), "b_floor_mult": c.cfg.b_floor_mult, "size_mult": c.cfg.size_mult, "n_halts": self.n_halts,
                "events": len(self.events)}


class SleeveSet:
    """One sleeve per venue (``<venue>_b``). The only shared object is the read-only MarketBook."""

    def __init__(self, book: MarketBook, base_cfg: CFOConfig, venues=("hyperliquid", "polymarket"), capital: float = 10_000.0,
                 poly_min_ttl: float = 60.0, scfg: Optional[SleeveConfig] = None):
        self.sleeves: Dict[str, Sleeve] = {v: Sleeve(f"{v}_b", v, book, base_cfg, capital, poly_min_ttl, copy.deepcopy(scfg)) for v in venues}
        self.book = book

    def for_venue(self, venue: str) -> Optional[Sleeve]:
        return self.sleeves.get(venue)

    def for_idx(self, idx: int) -> Optional[Sleeve]:
        return self.sleeves.get(self.book.metas[idx].venue)

    def review(self, now: float) -> List[SleeveEvent]:
        out: List[SleeveEvent] = []
        for s in self.sleeves.values():
            out += s.review(now)
        return out

    def events(self) -> List[SleeveEvent]:
        return sorted((e for s in self.sleeves.values() for e in s.events), key=lambda e: e.t)
