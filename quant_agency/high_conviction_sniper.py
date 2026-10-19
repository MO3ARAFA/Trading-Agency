"""Phase 6 / Architecture B — high-conviction absolute-magnitude taker sniper with a passive maker exit.

Phase 5's lesson: a *taker* entry only pays when the predicted move is large relative to the round-trip cost, and the Z-score of the
BTC impulse says nothing about that (a 3-sigma impulse in a quiet market is still ~1 cent on Polymarket). Architecture B therefore
puts a hard **absolute floor** in front of the taker:

    fire only if   |predicted move|  >=  floor_mult x (spread + entry taker fee + exit maker fee)          floor_mult = 1.5 (CEO-tunable)

(all in bps of the entry price; ``|predicted move| = edge_credit x |gap|`` — the CFO's haircut of the hunter's measured gap).
Below the floor the engine *abstains*; the rest of the machinery only matters when it fires:

  * IOC taker entry at the touch (150 ms order latency charged, as-of quote at arrival, partial-liquidity rejection);
  * the instant the entry fills, a post-only maker take-profit rests at the *converged* touch (0 fee on Polymarket, maker fee on HL);
  * **scratch**: if the impulse stalls (Binance has given back most of it AND the venue has done < ``stall_frac`` of the credited gap)
    the take-profit is replaced by a passive exit at the current touch — the old order is cancelled with the 150 ms latency charged
    (it can still fill inside that window) and is replaced only once the cancel has landed, so the position can never be over-sold;
  * a taker stop fires only on a *genuine* reversal (BTC back through the pre-impulse level by >= half the impulse and the position
    under water) or the CFO's worst-case stop; a time stop / work deadline falls back to a taker exit.

Phase 7 adds *exit policies* run side by side on identical signals (``BConfig.exit_variants``):
``fixed0.7`` (Phase 6 reference), ``fixed1.0`` (a fixed maker TP at 1.0x the credited gap), ``wide1.5`` / ``wide2.0`` (wider TP with a longer horizon),
``adaptive`` (start at 1.0x; each time Binance extends the impulse by ``widen_ext`` beyond the signal level, cancel — latency charged — and re-post one step wider,
up to 2.0x) and ``trail`` (no resting TP: stay in while Binance velocity is supportive; exit passively at the touch when the venue has done the credited gap and the
Binance 1 s velocity has faded, or when the venue gives back 40 % of its peak progress, or on a stall; reversal / adverse / time stops as before).

Shadow rows are spawned for **every** hunter signal (not only the ones above the floor) and tagged ``floor_ok``/``ratio``, so the
report can show exactly what the floor filters out; the ACCOUNT attempt only fires on a CFO-approved (floor + net-edge + binary risk
sizing + expiry guard) decision.
"""
from __future__ import annotations

import math
from bisect import bisect_right
from typing import Dict, List, Optional, Tuple

from .config import BConfig
from .execution_engine import TradeResult
from .inefficiency_hunter import Signal
from .maker_sniper import Attempt, MakerSniper, Order, QuoteHist, Variant

BPS = 1e4
EPS = 1e-12


def parse_exit(name: str):
    """'fixed0.7' -> ('fixed', 0.7); 'wide1.5' -> ('wide', 1.5); 'adaptive' -> ('adaptive', 1.0); 'trail' -> ('trail', 1.0)."""
    for kind in ("fixed", "wide"):
        if name.startswith(kind):
            return kind, float(name[len(kind):])
    return name, 1.0


class BAttempt(Attempt):
    """Taker-in / maker-out attempt with stall-scratch and genuine-reversal stop."""

    def __init__(self, hc: "HighConvictionSniper", var: Variant, sig: Signal, notional: float, account: bool, S0: float, stop_bps: float,
                 tp_bps: float, floor_ok: bool, ratio: float, pred_bps: float, floor_bps: float, pred_net_bps: float = 0.0, xname: str = "fixed0.7"):
        self.hc = hc
        self.bcfg = hc.bcfg
        self.xname = xname
        self.xmode, self.xmult = parse_exit(xname)
        self.level = 0                                   # adaptive: index into WIDEN
        self.last_replace_t = -1e18
        self.pending_px: Optional[float] = None
        self.peak_prog = 0.0
        self.trail_exit_reason = ""
        self.floor_ok, self.ratio, self.pred_bps, self.floor_bps = floor_ok, ratio, pred_bps, floor_bps
        self.scratch_state: Optional[str] = None
        self.scratch_at: Optional[float] = None
        self.scratch_kind = "scratch"
        self.scratched = False
        self.rev_stopped = False
        super().__init__(hc, var, sig, notional, account, S0, stop_bps, tp_bps, entry_mode="taker", pred_net_bps=pred_net_bps)

    # ---- event clock: add the scratch re-post
    def _next_event(self):
        nxt = super()._next_event()
        if self.state == "exit" and self.scratch_state == "pending" and self.scratch_at is not None and self.taker_exit is None:
            ev = (self.scratch_at, "scratch_place")
            return ev if nxt is None else min(nxt, ev)
        return nxt

    def _handle(self, t: float, kind: str) -> None:
        if kind == "scratch_place":
            self._scratch_place(t)
        else:
            super()._handle(t, kind)

    WIDEN = (1.0, 1.5, 2.0)

    def _tp_price(self, mult: float) -> float:
        tp = mult * abs(self.sig.gap_bps)
        tgt_ask = self.mid0 * (1 + self.side * tp / BPS) * (1 + self.side * self.hs_bps / BPS)     # converged touch on the exit side
        return self._round(tgt_ask, up=(self.side > 0))

    def _start_exit(self, t: float) -> None:
        super()._start_exit(t)
        if self.var.exit == "passive" and self.xmode in ("wide", "adaptive") and self.entry_fill_t is not None:
            self.work_deadline = self.entry_fill_t + self.bcfg.horizon_s.get(self.venue, 20.0)        # horizon hold: the wider TP gets time to be reached

    # ---- stall / reversal / widen / trail supervision (called on every BTC scan by the engine)
    def supervise(self, t: float, S: float) -> None:
        if self.state != "exit" or self.taker_exit is not None or S <= 0 or self.entry_fill_t is None:
            return
        q = self.hc.hist[self.i].last()
        if q is None:
            return
        mid = 0.5 * (q[1] + q[2])
        adverse_bps = -self.side * (mid - self.fill_mid) / max(self.fill_mid, EPS) * BPS
        rev = self.dir * math.log(S / self.S0) * BPS                      # <0: BTC has retraced from the signal level
        thr = max(self.bcfg.rev_stop_bps, 0.5 * self.impulse_bps)
        if rev <= -thr and adverse_bps > 0.0:
            self.rev_stopped = True
            self._send_taker_exit(t, "reversal_stop")
            return
        ret = self.dir * math.log(S / self.S_ref) * BPS / self.impulse_bps          # fraction of the impulse still intact
        gap_px = abs(self.sig.gap_bps) / BPS * self.mid0
        progress = self.side * (mid - self.mid0) / gap_px if gap_px > 0 else 1.0     # fraction of the credited gap the venue has done
        self.peak_prog = max(self.peak_prog, progress)
        if self.xmode == "trail":
            self._supervise_trail(t, S, progress, ret)
            return
        if self.scratch_state is None and self.xmode == "adaptive" and self.level < len(self.WIDEN) - 1 and self.exit is not None \
                and self.exit.state == "resting" and t - self.last_replace_t >= self.bcfg.widen_gap_s:
            ext = self.dir * math.log(S / self.S0) * BPS / self.impulse_bps          # Binance has kept going in our favour
            if ext >= self.bcfg.widen_ext * (self.level + 1):
                self.level += 1
                self._start_replace(t, self._tp_price(self.WIDEN[self.level]), "widen")
                return
        if self.scratch_state is not None or self.var.exit != "passive":
            return
        if t - self.entry_fill_t < self.bcfg.stall_after_s.get(self.venue, 2.0):
            return
        if ret < self.bcfg.hold_frac and progress < self.bcfg.stall_frac:
            self._start_replace(t, None, "scratch")

    def _supervise_trail(self, t: float, S: float, progress: float, ret: float) -> None:
        if self.scratch_state is not None:
            return
        b = self.bcfg
        v1 = self.hc.velocity(S, t, 1.0, self.dir)                          # Binance 1 s velocity in our direction (bps)
        reached = progress >= b.trail_target
        retrace = self.peak_prog >= 0.5 and (self.peak_prog - progress) >= b.trail_retrace * self.peak_prog
        stalled = (t - self.entry_fill_t) >= b.stall_after_s.get(self.venue, 2.0) and ret < b.hold_frac and progress < b.stall_frac
        why = "trail_capture" if (reached and v1 <= b.trail_stall_vel_bps) else ("trail_retrace" if retrace else ("trail_stall" if stalled else ""))
        if not why:
            return
        self.trail_exit_reason = why
        self.scratch_state, self.scratch_kind, self.scratch_at, self.pending_px = "pending", "trail", t, None
        self.work_deadline = t + self.cfg.order_latency_s + b.scratch_work_s

    def _start_replace(self, t: float, px: Optional[float], kind: str) -> None:
        """Cancel the resting TP (150 ms latency; it can still fill) and re-post at ``px`` (or at the touch for a scratch) only once the cancel has landed."""
        x = self.exit
        if x is None or x.state != "resting":
            return
        x.state = "cancel_pending"
        x.cancel_t = t
        x.cancel_eff = t + self.cfg.cancel_latency_s
        x.cancel_reason = kind
        self.exit_prev.append(x)
        self.exit = None
        self.scratch_state, self.scratch_kind, self.scratch_at, self.pending_px = "pending", kind, x.cancel_eff, px
        self.last_replace_t = t
        if kind == "scratch":
            self.scratched = True
            self.work_deadline = x.cancel_eff + self.cfg.order_latency_s + self.bcfg.scratch_work_s

    def _scratch_place(self, t: float) -> None:
        kind = self.scratch_kind
        self.scratch_state = "placed" if kind in ("scratch", "trail") else None
        self.last_replace_t = t
        self._expire_prev(t)
        rem = self.qty_pos - self._exit_filled()
        if rem <= 1e-12:
            self._maybe_close(t)
            return
        q = self.hc.hist[self.i].last()
        if q is None:
            self._send_taker_exit(t, "no_quote")
            return
        _, bid, ask, _, _ = q
        px = self.pending_px if self.pending_px is not None else (ask if self.side > 0 else bid)   # touch (scratch / trail) or the wider target (widen)
        self.pending_px = None
        self.exit = Order("exit", -self.side, px, rem, "ALO", t, t + self.cfg.order_latency_s)

    def extra_row(self) -> dict:
        return {"floor_ok": self.floor_ok, "ratio": self.ratio, "pred_bps": self.pred_bps, "floor_bps": self.floor_bps, "scratched": self.scratched,
                "rev_stopped": self.rev_stopped, "arch": "B", "xvar": self.xname, "level": self.level, "trail_reason": self.trail_exit_reason, "peak_progress": self.peak_prog}


class TakerAttempt(Attempt):
    """The taker/taker reference (same entry, taker take-profit) carrying the same floor tags so the report can gate it identically."""

    def __init__(self, hc, var, sig, notional, account, S0, stop_bps, tp_bps, floor_ok, ratio, pred_bps, floor_bps):
        self.floor_ok, self.ratio, self.pred_bps, self.floor_bps = floor_ok, ratio, pred_bps, floor_bps
        super().__init__(hc, var, sig, notional, account, S0, stop_bps, tp_bps)

    def extra_row(self) -> dict:
        return {"floor_ok": self.floor_ok, "ratio": self.ratio, "pred_bps": self.pred_bps, "floor_bps": self.floor_bps, "scratched": False,
                "rev_stopped": False, "arch": "taker/taker", "xvar": "taker/taker"}


class HighConvictionSniper(MakerSniper):
    """Same shadow/account plumbing as the Phase 5 sniper; different entry policy, exit supervision and gating.

    With ``sleeves`` (Phase 7) every account decision, exposure, P&L and breaker lives in the sleeve of the signal's venue; without it
    (Phase 6) everything goes through the agency's single CFO book."""

    def __init__(self, agency, cfg: Optional[BConfig] = None, sleeves=None):
        self.bcfg = cfg or BConfig()
        super().__init__(agency, agency.cfg.snipe, variants=[])          # reuse infra (hist / tick_est / account bookkeeping); variants are ours
        self.venues = set(self.bcfg.venues)
        self.elig = [i for i, m in enumerate(self.book.metas) if m.venue in self.venues]
        self.hist = {i: QuoteHist() for i in self.elig}
        self.cfg = _SnipeView(agency.cfg.snipe, self.bcfg)               # Attempt reads latency/ttl/work/hold knobs from here
        self.sleeves = sleeves
        self.n_floor_ok = 0
        self.n_signals_seen = 0
        self.n_floor_fills = 0                                           # Polymarket floor-passed filled entries (sample-size counter for the Phase 8 stopping rule)
        self._ph_t: List[float] = []                                     # Binance micro-price history for the oracle-guided exits
        self._ph_l: List[float] = []

    # -------------------------------------------------------------- isolation
    def cfo_for(self, idx: int):
        if self.sleeves is not None:
            sl = self.sleeves.for_idx(idx)
            if sl is not None:
                return sl.cfo
        return self.cfo

    # -------------------------------------------------------------- Binance velocity
    def _note_price(self, t: float, S: float) -> None:
        if S <= 0:
            return
        if self._ph_t and t - self._ph_t[-1] < 0.01:
            return
        self._ph_t.append(t)
        self._ph_l.append(math.log(S))
        if len(self._ph_t) > 4000:
            del self._ph_t[:2000], self._ph_l[:2000]

    def velocity(self, S: float, t: float, h: float, direction: int) -> float:
        """Binance move over the last ``h`` seconds in the trade's direction, bps (0 if unknown)."""
        j = bisect_right(self._ph_t, t - h) - 1
        if j < 0 or S <= 0:
            return 0.0
        return direction * (math.log(S) - self._ph_l[j]) * BPS

    # -------------------------------------------------------------- the variants
    def _variants(self):
        """[(Variant, exit name)]; the Phase 6 name 'B/taker→maker+scratch' is kept for the reference exit when no sleeves are used."""
        out = []
        for m in self.bcfg.shadow_models:
            for x in self.bcfg.exit_variants:
                name = "B/taker→maker+scratch" if (self.sleeves is None and x == "fixed0.7") else f"B/{x}"
                out.append((Variant(name, "taker", "trail" if x == "trail" else "passive", False, m), x))
        out.append((Variant("taker/taker", "taker", "taker", False, "strict"), "taker"))
        return out

    # -------------------------------------------------------------- polling: time events + supervision
    def poll(self, t: float, S: float) -> None:
        self._note_price(t, S)
        if not self.active:
            return
        for i, atts in list(self.active.items()):
            for at in list(atts):
                at.advance(t)
                if isinstance(at, BAttempt):
                    at.supervise(t, S)
            self._sweep(i)

    # -------------------------------------------------------------- signals
    def on_signal(self, sig: Signal, S: float, dec=None) -> None:
        if not self.enabled or sig.idx not in self.hist:
            return
        self.n_signals += 1
        meta = self.book.metas[sig.idx]
        b = self.bcfg
        notional = b.hl_notional if meta.venue == "hyperliquid" else b.pm_notional
        pred, floor, ratio = self.cfo.b_floor(sig, b.ref_floor_mult)       # shadows are tagged with the *fixed* reference floor
        ok = pred >= floor
        self.n_floor_ok += int(ok)
        gap = abs(sig.gap_bps)
        stop_bps = max(self.cfo.cfg.stop_mult * sig.sigma_res_bps, self.cfo.cfg.min_stop_bps)
        for v, xname in self._variants():
            if v.name == "taker/taker":
                at = TakerAttempt(self, v, sig, notional, False, S, stop_bps, self.cfo.cfg.tp_capture * gap, ok, ratio, pred, floor)
            else:
                at = BAttempt(self, v, sig, notional, False, S, stop_bps, parse_exit(xname)[1] * gap, ok, ratio, pred, floor, xname=xname)
            self.active.setdefault(sig.idx, []).append(at)
        if dec is not None and dec.approved and dec.mode == "b_snipe" and sig.idx not in self.account_open:
            xname = b.account_exit
            v = Variant("ACCOUNT", "taker", "trail" if xname == "trail" else "passive", False, b.account_model)
            at = BAttempt(self, v, sig, dec.notional, True, S, dec.stop_bps, parse_exit(xname)[1] * dec.gap_credit_bps, ok, ratio, pred, floor,
                          pred_net_bps=dec.net_edge_bps, xname=xname)
            self.active.setdefault(sig.idx, []).append(at)
            if at.state != "done":
                self.account_open[sig.idx] = at

    # -------------------------------------------------------------- results
    def _on_result(self, at, r: dict) -> None:
        r.setdefault("floor_ok", getattr(at, "floor_ok", False))
        r.setdefault("ratio", getattr(at, "ratio", 0.0))
        r.setdefault("scratched", False)
        r.setdefault("arch", "taker/taker")
        self.results.append(r)
        if r.get("variant") == "B/trail" and r.get("model") == "strict" and r.get("floor_ok") and r.get("outcome") == "filled" and r.get("venue") == "polymarket":
            self.n_floor_fills += 1
        if len(self.results) > 400_000:
            del self.results[:100_000]
        if at.account:
            cfo = self.cfo_for(at.i)
            self.account_open.pop(at.i, None)
            self.account_results.append(r)
            if self.sleeves is not None:
                sl = self.sleeves.for_idx(at.i)
                if sl is not None:
                    sl.add_result(r)
            if r["outcome"] == "filled":
                tr = TradeResult(oid=at.sig.sid, sid=at.sig.sid, market=r["market"], side=at.side, mode="b_snipe", t_entry=r["fill_t"], t_exit=r["t_end"],
                                 entry_px=r["entry_px"], exit_px=r["exit_px"], qty=r["qty"], notional=r["entry_px"] * r["qty"], gross_bps=r["gross_bps"],
                                 fees_usd=r["fees_usd"], net_pnl_usd=r["net_usd"], net_bps=r["net_bps"],
                                 R=r["net_usd"] / max(r["entry_px"] * r["qty"] * at.stop_bps / BPS, 1e-9), exit_reason=r["exit_reason"], hold_s=r["hold_s"],
                                 entry_slip_bps=0.0, exit_slip_bps=0.0, spread_bps_entry=at.sig.spread_bps, predicted_net_bps=at.pred_net,
                                 gap_bps=at.sig.gap_bps, predicted_slip_bps=0.0)
                cfo.on_open(r["market"], at.side, tr.notional, 1.0)
                cfo.on_close(r["market"], at.side, tr.notional, 1.0)
                cfo.on_trade_closed(tr, r["t_end"])
                cfo.on_b_result(r)
                if self.sleeves is None:
                    self.a.engine.closed.append(tr)
                self.a._write("trades", dict(tr.as_dict(), sleeve=(self.sleeves.for_idx(at.i).name if self.sleeves is not None else "main")))
            self.a._write("b_account", r)


class _SnipeView:
    """Attempt expects SnipeConfig-shaped knobs; Phase 6 keeps the latency/ttl/work values of SnipeConfig (same venue behaviour)."""

    def __init__(self, sc, bc):
        self._sc, self._bc = sc, bc

    def __getattr__(self, k):
        return getattr(self._sc, k)
