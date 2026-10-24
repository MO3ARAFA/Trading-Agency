"""Omega engine, layer 4: isolated sleeve books (CFO) and the supervisor (CEO) for the 100 USD account.

Same principle as ``sleeves.py`` (Phase 7), rebuilt for micro-sized spot positions: each strategy sleeve owns its cash, positions,
realised P&L, fees, equity history and state, and nothing in one sleeve reads or writes another. The CEO only *reads* sleeve equity and
*commands* a sleeve (quarantine / probation / halt); a quarantine in ``meme_momentum`` cannot touch ``breakout_scalp``.

Breakers:
  * **sleeve hourly drawdown**: equity peak-to-now within the last rolling hour ≥ ``hourly_dd_usd`` (5 USD = 5 % of the 100 USD bankroll)
    -> QUARANTINED: the engine closes that sleeve's positions at the next executable price, the sleeve is all cash for ``quarantine_s``,
    then PROBATION at half size; a second breach during probation quarantines again for twice as long;
  * **account**: total equity ≤ bankroll − ``account_kill_usd`` -> every sleeve HALTED until an operator restarts;
  * **kill file**: its existence halts everything at once;
  * **trade-rate cap**: at most ``max_fills_per_hour`` fills across the account (rolling hour).
"""
from __future__ import annotations

import os
from collections import deque
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Deque, Dict, List, Optional


class OState(str, Enum):
    NORMAL = "NORMAL"
    PROBATION = "PROBATION"
    QUARANTINED = "QUARANTINED"
    HALTED = "HALTED"


@dataclass
class GovConfig:
    bankroll: float = 100.0
    alloc: Dict[str, float] = field(default_factory=lambda: {"meme_momentum": 40.0, "social_sentiment": 30.0, "breakout_scalp": 30.0})
    hourly_dd_usd: float = 5.0
    quarantine_s: float = 1800.0
    probation_size: float = 0.5
    probation_clean_s: float = 3600.0
    account_kill_usd: float = 20.0
    max_fills_per_hour: int = 1000
    kill_file: str = "runs/omega/KILL"
    review_every_s: float = 5.0


@dataclass
class GovEvent:
    t: float
    sleeve: str
    kind: str
    frm: str
    to: str
    reason: str
    evidence: dict

    def as_dict(self) -> dict:
        return asdict(self)


class SleeveBook:
    """One strategy's paper account. Positions are owned by the engine but booked here (cash moves only through ``open`` / ``close``)."""

    def __init__(self, name: str, capital: float):
        self.name, self.capital = name, capital
        self.cash = capital
        self.open_cost: Dict[int, float] = {}            # pid -> USD paid (incl. fees)
        self.mark_value: Dict[int, float] = {}           # pid -> USD the position would fetch now (after exit costs)
        self.realised = 0.0
        self.fees = 0.0
        self.fills = 0
        self.round_trips = 0
        self.wins = 0
        self.state = OState.NORMAL
        self.until = 0.0
        self.n_quarantines = 0
        self.size_mult = 1.0
        self.since = 0.0
        self.eq_hist: Deque[tuple] = deque(maxlen=4000)   # (t, equity), pruned to the last hour

    @property
    def equity(self) -> float:
        return self.cash + sum(self.mark_value.get(p, c) for p, c in self.open_cost.items())

    def can_open(self, usd: float) -> bool:
        return self.state in (OState.NORMAL, OState.PROBATION) and usd <= self.cash + 1e-9

    def open(self, pid: int, usd_paid: float, fees: float) -> None:
        self.cash -= usd_paid
        self.open_cost[pid] = usd_paid
        self.mark_value[pid] = usd_paid
        self.fees += fees
        self.fills += 1

    def mark(self, pid: int, value_now: float) -> None:
        if pid in self.open_cost:
            self.mark_value[pid] = value_now

    def close(self, pid: int, usd_received: float, fees: float) -> float:
        cost = self.open_cost.pop(pid)
        self.mark_value.pop(pid, None)
        self.cash += usd_received
        pnl = usd_received - cost
        self.realised += pnl
        self.fees += fees
        self.fills += 1
        self.round_trips += 1
        self.wins += pnl > 0
        return pnl

    def failed_tx(self, fee_usd: float) -> None:
        """A transaction that landed but failed (e.g. slippage limit): the network fee is lost."""
        self.cash -= fee_usd
        self.realised -= fee_usd
        self.fees += fee_usd

    def record(self, now: float) -> None:
        self.eq_hist.append((now, self.equity))
        while self.eq_hist and self.eq_hist[0][0] < now - 3600.0:
            self.eq_hist.popleft()

    def hourly_drawdown(self) -> float:
        if not self.eq_hist:
            return 0.0
        peak = max(e for _, e in self.eq_hist)
        return max(0.0, peak - self.eq_hist[-1][1])

    def summary(self) -> dict:
        return {"sleeve": self.name, "state": self.state.value, "capital": self.capital, "equity": round(self.equity, 4), "cash": round(self.cash, 4),
                "realised": round(self.realised, 4), "fees": round(self.fees, 4), "fills": self.fills, "round_trips": self.round_trips,
                "win_rate": round(self.wins / self.round_trips, 3) if self.round_trips else None, "open": len(self.open_cost),
                "quarantines": self.n_quarantines, "hourly_dd": round(self.hourly_drawdown(), 4)}


class OmegaCEO:
    def __init__(self, cfg: Optional[GovConfig] = None):
        self.cfg = cfg or GovConfig()
        self.books: Dict[str, SleeveBook] = {k: SleeveBook(k, v) for k, v in self.cfg.alloc.items()}
        self.events: Deque[GovEvent] = deque(maxlen=2000)
        self.fill_times: Deque[float] = deque()
        self.halted = False
        self.halt_reason = ""
        self.last_review = -1e18
        self.to_flatten: List[str] = []                    # sleeves whose positions the engine must close now

    # ------------------------------------------------------------------ rate cap
    def fill_budget_ok(self, now: float) -> bool:
        while self.fill_times and self.fill_times[0] < now - 3600.0:
            self.fill_times.popleft()
        return len(self.fill_times) < self.cfg.max_fills_per_hour

    def note_fill(self, now: float) -> None:
        self.fill_times.append(now)

    def size_mult(self, sleeve: str) -> float:
        b = self.books[sleeve]
        if self.halted or b.state in (OState.QUARANTINED, OState.HALTED):
            return 0.0
        return self.cfg.probation_size if b.state == OState.PROBATION else 1.0

    @property
    def equity(self) -> float:
        return sum(b.equity for b in self.books.values())

    def _ev(self, now, b: SleeveBook, kind, to: OState, reason, evidence) -> GovEvent:
        e = GovEvent(now, b.name, kind, b.state.value, to.value, reason, evidence)
        b.state = to
        self.events.append(e)
        return e

    def halt_all(self, now: float, reason: str) -> List[GovEvent]:
        out = []
        if not self.halted:
            self.halted, self.halt_reason = True, reason
            for b in self.books.values():
                if b.state != OState.HALTED:
                    out.append(self._ev(now, b, "HALT", OState.HALTED, reason, {"equity": round(self.equity, 4)}))
                    self.to_flatten.append(b.name)
        return out

    # ------------------------------------------------------------------ review
    def review(self, now: float) -> List[GovEvent]:
        out: List[GovEvent] = []
        for b in self.books.values():
            b.record(now)
        if now - self.last_review < self.cfg.review_every_s:
            return out
        self.last_review = now
        c = self.cfg
        if os.path.exists(c.kill_file):
            return self.halt_all(now, "kill file")
        if self.equity <= c.bankroll - c.account_kill_usd:
            return self.halt_all(now, f"account equity {self.equity:.2f} <= {c.bankroll - c.account_kill_usd:.2f}")
        if self.halted:
            return out
        for b in self.books.values():
            dd = b.hourly_drawdown()
            if b.state in (OState.NORMAL, OState.PROBATION) and dd >= c.hourly_dd_usd * (0.5 if b.state == OState.PROBATION else 1.0):
                b.n_quarantines += 1
                b.until = now + c.quarantine_s * (2 ** (b.n_quarantines - 1))
                out.append(self._ev(now, b, "QUARANTINE", OState.QUARANTINED,
                                    f"hourly drawdown {dd:.2f} USD >= {c.hourly_dd_usd * (0.5 if b.state == OState.PROBATION else 1.0):.2f}; flat until +{b.until - now:.0f}s",
                                    {"equity": round(b.equity, 4), "dd": round(dd, 4)}))
                self.to_flatten.append(b.name)
            elif b.state == OState.QUARANTINED and now >= b.until:
                b.since = now
                b.eq_hist.clear()
                b.eq_hist.append((now, b.equity))           # the drawdown that caused the quarantine is not counted twice
                out.append(self._ev(now, b, "PROBATION", OState.PROBATION, f"cool-down over: resume at {c.probation_size:g}x size", {"equity": round(b.equity, 4)}))
            elif b.state == OState.PROBATION and now - b.since >= c.probation_clean_s:
                out.append(self._ev(now, b, "RESTORE", OState.NORMAL, f"{c.probation_clean_s:.0f}s of probation without a breach", {"equity": round(b.equity, 4)}))
        return out

    def summary(self) -> dict:
        return {"equity": round(self.equity, 4), "halted": self.halted, "halt_reason": self.halt_reason, "sleeves": [b.summary() for b in self.books.values()],
                "events": len(self.events)}

    # ------------------------------------------------------------------ warm state
    def snapshot(self) -> dict:
        return {"halted": self.halted, "halt_reason": self.halt_reason,
                "books": {k: {"cash": b.cash, "realised": b.realised, "fees": b.fees, "fills": b.fills, "round_trips": b.round_trips, "wins": b.wins,
                              "state": b.state.value, "until": b.until, "n_quarantines": b.n_quarantines, "since": b.since,
                              "open_cost": {str(p): v for p, v in b.open_cost.items()}} for k, b in self.books.items()}}

    def restore(self, snap: dict) -> None:
        self.halted, self.halt_reason = snap.get("halted", False), snap.get("halt_reason", "")
        for k, d in snap.get("books", {}).items():
            b = self.books.get(k)
            if b is None:
                continue
            b.cash, b.realised, b.fees, b.fills, b.round_trips, b.wins = d["cash"], d["realised"], d["fees"], d["fills"], d["round_trips"], d["wins"]
            b.state, b.until, b.n_quarantines, b.since = OState(d["state"]), d["until"], d["n_quarantines"], d["since"]
            b.open_cost = {int(p): v for p, v in d.get("open_cost", {}).items()}
            b.mark_value = dict(b.open_cost)
