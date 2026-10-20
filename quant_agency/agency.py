"""Wires the four tiers. Fully synchronous & clock-injected: drive it with ``on_quote`` / ``step``
from the live asyncio feeds or from a deterministic replay (tests, offline sim)."""
from __future__ import annotations

import json
import os
import time
from array import array
from typing import List, Optional, Sequence

import numpy as np

from .btc_oracle import BtcOracle
from .ceo_agent import CEOAgent
from .cfo_agent import CFOAgent
from .cfo_agent import MarkoutTracker
from .config import AgencyConfig
from .cross_venue_arb import CrossVenueArb
from .execution_engine import ExecutionEngine, TradeResult
from .inefficiency_hunter import InefficiencyHunter, Signal
from .market_watchers import MarketBook, MarketMeta


class LatencyStats:
    """Fixed-size sample ring of microsecond latencies."""

    def __init__(self, cap: int = 200_000):
        self.a = np.zeros(cap)
        self.n = 0
        self.cap = cap

    def add(self, us: float) -> None:
        self.a[self.n % self.cap] = us
        self.n += 1

    def summary(self) -> dict:
        m = min(self.n, self.cap)
        if m == 0:
            return {"n": 0}
        x = self.a[:m]
        return {"n": self.n, "p50": float(np.percentile(x, 50)), "p90": float(np.percentile(x, 90)),
                "p99": float(np.percentile(x, 99)), "max": float(x.max()), "mean": float(x.mean())}


class Agency:
    def __init__(self, metas: Sequence[MarketMeta], cfg: Optional[AgencyConfig] = None, out_dir: Optional[str] = None,
                 t0: float = 0.0, wall0: Optional[float] = None, perf=time.perf_counter):
        self.cfg = cfg or AgencyConfig()
        self.perf = perf
        self.book = MarketBook(metas, self.cfg.watchers)
        self.oracle = BtcOracle(self.cfg.oracle)
        self.hunter = InefficiencyHunter(self.book, self.oracle, self.cfg.hunter)
        self.cfo = CFOAgent(self.book, self.cfg.cfo)
        self.cfo.poly_min_ttl = self.cfg.poly.min_ttl_s
        self.engine = ExecutionEngine(self.book, self.cfo, self.cfg.exec)
        self.arb = CrossVenueArb(self.book, self.cfo, self.cfg.arb)
        self.pm = None                            # set by attach_polymarket()
        self.sniper = None                        # set by attach_sniper()
        self.mm = None                            # Phase 6 Architecture A, set by attach_mm()
        self.hc = None                            # Phase 6 Architecture B, set by attach_hc()
        self.sleeves = None                       # Phase 7 isolated per-venue risk sleeves, set by attach_sleeves()
        self.sectors = None                       # sector oracles + observe-only sink, set by attach_sectors()
        self.n_mkt_trades = 0
        # latency-sensitivity shadow trackers: same signals, different assumed order latency (does the edge survive speed?)
        self.alt_trackers = {lat: MarkoutTracker(self.book, self.cfg.cfo.markout_horizons_s, lat, self.cfg.cfo.fee_taker_bps)
                             for lat in (0.0, 0.5) if lat != self.cfg.cfo.latency_s}
        self.out_dir = out_dir
        self._files = {}
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        wall0 = time.time() if wall0 is None else wall0
        self.ceo = CEOAgent(self.cfo, self.hunter, self.engine, self.oracle, self.cfg.ceo,
                            audit_path=os.path.join(out_dir, "ceo_audit.jsonl") if out_dir else None,
                            wall0=wall0, t0=t0)
        self.ceo.arb = self.arb
        self.t0 = t0
        self.scan_lat = LatencyStats()
        self.decide_lat = LatencyStats()          # BTC tick received -> executable payload ready
        self.signals: List[Signal] = []
        self.max_signal_keep = 5000
        self.n_events = 0
        self.n_btc = 0
        self._recv_wall = 0.0
        self.last_step = -1.0
        self.tape = None                       # set record=True to capture every event for replay
        self.last_t = t0

    # ------------------------------------------------------------------ ingestion
    def attach_polymarket(self, watcher) -> None:
        self.pm = watcher

    def attach_sniper(self, sniper) -> None:
        self.sniper = sniper
        self.ceo.sniper = sniper

    def attach_mm(self, mm) -> None:
        self.mm = mm
        self.ceo.mm = mm

    def attach_hc(self, hc, govern: bool = True) -> None:
        self.hc = hc
        self.ceo.hc = hc if govern else None            # Phase 7: the sleeves govern B themselves; the global CEO must not touch it

    def attach_sleeves(self, sleeves) -> None:
        self.sleeves = sleeves

    def attach_sectors(self, hub) -> None:
        """Sector oracles (SOL / PEPE / RENDER ...): every hunter's signals - BTC included - become observe-only markout rows."""
        self.sectors = hub

    def start_recording(self) -> None:
        self.tape = tuple(array("d") for _ in range(6))

    def save_tape(self, path: str, extra: Optional[dict] = None) -> None:
        import dataclasses
        t, i, b, a, bq, aq = (np.frombuffer(x, dtype=np.float64) for x in self.tape)
        metas = json.dumps([dataclasses.asdict(m) for m in self.book.metas])
        np.savez_compressed(path, t=t, i=i.astype(np.int32), b=b, a=a, bq=bq, aq=aq, metas=np.array(metas),
                            extra=np.array(json.dumps(extra or {}, default=float)))

    def on_quote(self, i: int, t: float, bid: float, ask: float, bq: float, aq: float) -> None:
        tp = self.tape
        if tp is not None:
            tp[0].append(t); tp[1].append(i); tp[2].append(bid); tp[3].append(ask); tp[4].append(bq); tp[5].append(aq)
        self.n_events += 1
        if not self.book.on_quote(i, t, bid, ask, bq, aq):
            return
        if i == 0:
            self._recv_wall = self.perf()
            self.oracle.on_book(t, bid, ask, bq, aq)
            self.hunter.dirty = True
            self.n_btc += 1
            if self.hc is not None:
                self.hc.on_btc_mid(t, 0.5 * (bid + ask))
        else:
            if self.sectors is not None:
                self.sectors.on_quote(i, t, bid, ask, bq, aq)
            self.engine.on_quote(i, t)
            if self.sniper is not None:
                self.sniper.on_quote(i, t, bid, ask, bq, aq)
            if self.mm is not None:
                self.mm.on_quote(i, t, bid, ask, bq, aq)
            if self.hc is not None:
                self.hc.on_quote(i, t, bid, ask, bq, aq)
        self.last_t = t

    def on_market_trade(self, i: int, t: float, price: float, size: float, aggressor: int) -> None:
        """Trade print on market i (aggressor +1 = buyer-initiated). Recorded on the tape as idx = -(i+2)."""
        tp = self.tape
        if tp is not None:
            tp[0].append(t); tp[1].append(-(i + 2)); tp[2].append(price); tp[3].append(size); tp[4].append(float(aggressor)); tp[5].append(0.0)
        self.n_mkt_trades += 1
        if self.sniper is not None:
            self.sniper.on_trade(i, t, price, size, aggressor)
        if self.mm is not None:
            self.mm.on_trade(i, t, price, size, aggressor)
        if self.hc is not None:
            self.hc.on_trade(i, t, price, size, aggressor)

    def on_trade(self, t: float, price: float, qty: float, buyer_is_maker: bool) -> None:
        tp = self.tape
        if tp is not None:                      # trades are stored as idx=-1: (price, qty, maker_flag)
            tp[0].append(t); tp[1].append(-1); tp[2].append(price); tp[3].append(qty); tp[4].append(float(buyer_is_maker)); tp[5].append(0.0)
        self.oracle.on_trade(t, price, qty, buyer_is_maker)

    def on_feed_reset(self, t: float, idxs=None, hold_s: float = 15.0) -> None:
        """A feed reconnected: quiet the affected markets so stale quotes can't masquerade as gaps."""
        if idxs is None or 0 in idxs:
            self.oracle.reset_feed(t)
        if idxs is None:
            self.hunter.cooldown_until[:] = np.maximum(self.hunter.cooldown_until, t + hold_s)
        else:
            for i in idxs:
                self.hunter.cooldown_until[i] = max(self.hunter.cooldown_until[i], t + hold_s)
        if self.sectors is not None:
            self.sectors.reset(t, idxs, hold_s)

    # ------------------------------------------------------------------ main step
    def housekeeping(self, t: float) -> None:
        """Markout resolution, paper-exchange state machines, CEO cadence. ~20 Hz is plenty."""
        self.last_t = t
        self.cfo.markouts.poll(t)
        for tk in self.alt_trackers.values():
            tk.poll(t)
        if self.sectors is not None:
            self.sectors.poll(t)
        for tr in self.engine.poll(t):
            self._write("trades", tr.as_dict())
        self.arb.scan(t)                                                   # also scanned on the BTC path; 10 ms internal throttle
        self._poll_arb(t)
        self._poll_engines(t)
        if self.sleeves is not None:
            for ev in self.sleeves.review(t):
                self._write("sleeve_events", ev.as_dict())
        if self.sectors is None:                                            # measurement runs: nothing may retune the baseline hunter mid-capture
            self.ceo.maybe_review(t)
        if self.cfo.flatten_requested:
            self.engine.flatten_all(t, "breaker_flatten")
            self.cfo.flatten_requested = False

    def _poll_engines(self, t: float) -> None:
        S = float(self.oracle.micro)
        if self.sniper is not None:
            self.sniper.poll(t, S)
        if self.mm is not None:
            self.mm.poll(t, S)
        if self.hc is not None:
            self.hc.poll(t, S)

    def _poll_arb(self, t: float) -> None:
        for tr in self.arb.poll(t):
            self.engine.closed.append(tr)
            self._write("trades", tr.as_dict())
        if self.arb.resolved_buffer:
            for r in self.arb.resolved_buffer:
                self._write("arb_opps", r)
            self.arb.resolved_buffer.clear()

    def scan(self, t: float, force: bool = False) -> List[Signal]:
        """Latency-critical path: hunter scan -> CFO gate -> payload -> paper order."""
        sec = self.sectors
        sec_dirty = sec is not None and sec.any_dirty()
        if not (self.hunter.dirty or force or sec_dirty):
            return []
        t1 = self.perf()
        sigs = self.hunter.scan(t, self._recv_wall) if (self.hunter.dirty or force) else []
        if sec_dirty:
            sigs = sigs + sec.scan(t)
        if self.pm is not None:
            sigs = sigs + self.pm.scan(t, self.oracle.state(t))
        self.scan_lat.add((self.perf() - t1) * 1e6)
        for s in sigs:
            self._handle_signal(s, t)
        self.arb.scan(t)
        self._poll_arb(t)
        self._poll_engines(t)
        return sigs

    def step(self, t: float, force_scan: bool = False) -> List[Signal]:
        """Deterministic combined step for replay/tests."""
        self.housekeeping(t)
        return self.scan(t, force_scan)

    def _handle_signal(self, s: Signal, t: float) -> None:
        if self.sectors is not None:                    # measurement mode: no order is ever prepared, the CFO/CEO books stay untouched
            self.sectors.observe(s, t)
            return
        meta = self.book.metas[s.idx]
        sn = self.sniper
        hc = self.hc
        if hc is not None and hc.enabled and hc.eligible(s.idx) and self.cfo.cfg.b_enabled:
            S = float(self.oracle.micro)
            cfo_b = hc.cfo_for(s.idx)                                  # the venue's isolated sleeve (Phase 7) or the shared book (Phase 6)
            venue_b = meta.venue
            n_open_b = sum(1 for k in hc.account_open if self.book.metas[k].venue == venue_b) if hc.sleeves is not None else len(hc.account_open)
            dec = cfo_b.evaluate_sniper_b(s, t, has_position=hc.has_position(s.idx), n_open=n_open_b, regime_ok=hc.regime_tags(s.t)["gate_ok"])
            s.decision = dec
            hc.on_signal(s, S, dec)
            if self.mm is not None:
                self.mm.on_signal(s, S, dec)
            self.cfo.markouts.register(s, dec)
            for tk in self.alt_trackers.values():
                tk.register(s, dec)
            self._write("signals", {**s.as_dict(), "decision": dec.as_dict()})
            self.signals.append(s)
            return
        if sn is not None and sn.enabled and sn.eligible(s.idx) and self.cfo.cfg.snipe_enabled and self.cfo.cfg.mode_policy != "taker_only":
            dec = self.cfo.evaluate_snipe(s, t, has_position=sn.has_position(s.idx), n_open=len(sn.account_open))
            s.decision = dec
            sn.on_signal(s, float(self.oracle.micro), dec)
            self.cfo.markouts.register(s, dec)
            for tk in self.alt_trackers.values():
                tk.register(s, dec)
            self._write("signals", {**s.as_dict(), "decision": dec.as_dict()})
            self.signals.append(s)
            return
        dec = self.cfo.evaluate(s, t, has_position=self.engine.has_position(s.idx), tradable=meta.tradable)
        s.decision = dec
        payload = None
        if dec.approved:
            lat = (self.perf() - self._recv_wall) * 1e6 if self._recv_wall else 0.0
            payload = self.engine.prepare(s, dec, t, lat)
            if payload is None:
                self.cfo.revoke(dec, "size_below_min")
            else:
                payload.prep_latency_us = (self.perf() - self._recv_wall) * 1e6 if self._recv_wall else lat
                self.decide_lat.add(payload.prep_latency_us)
                self.engine.submit(payload, s, dec, t)
                self._write("payloads", payload.as_dict())
        self.cfo.markouts.register(s, dec)
        for tk in self.alt_trackers.values():
            tk.register(s, dec)
        self._write("signals", {**s.as_dict(), "decision": dec.as_dict()})
        self.signals.append(s)
        if len(self.signals) > self.max_signal_keep:
            del self.signals[: self.max_signal_keep // 5]

    # ------------------------------------------------------------------ io
    def _write(self, name: str, obj: dict) -> None:
        if not self.out_dir:
            return
        f = self._files.get(name)
        if f is None:
            f = self._files[name] = open(os.path.join(self.out_dir, f"{name}.jsonl"), "a", buffering=1 << 16)
        f.write(json.dumps(obj, default=float) + "\n")

    def close(self) -> None:
        for f in self._files.values():
            f.flush()
            f.close()
        self._files.clear()
