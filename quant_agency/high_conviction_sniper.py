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

Shadow rows are spawned for **every** hunter signal (not only the ones above the floor) and tagged ``floor_ok``/``ratio``, so the
report can show exactly what the floor filters out; the ACCOUNT attempt only fires on a CFO-approved (floor + net-edge + binary risk
sizing + expiry guard) decision.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

from .config import BConfig
from .execution_engine import TradeResult
from .inefficiency_hunter import Signal
from .maker_sniper import Attempt, MakerSniper, Order, QuoteHist, Variant

BPS = 1e4
EPS = 1e-12


class BAttempt(Attempt):
    """Taker-in / maker-out attempt with stall-scratch and genuine-reversal stop."""

    def __init__(self, hc: "HighConvictionSniper", var: Variant, sig: Signal, notional: float, account: bool, S0: float, stop_bps: float,
                 tp_bps: float, floor_ok: bool, ratio: float, pred_bps: float, floor_bps: float, pred_net_bps: float = 0.0):
        self.hc = hc
        self.bcfg = hc.bcfg
        self.floor_ok, self.ratio, self.pred_bps, self.floor_bps = floor_ok, ratio, pred_bps, floor_bps
        self.scratch_state: Optional[str] = None
        self.scratch_at: Optional[float] = None
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

    # ---- stall / reversal supervision (called on every BTC scan by the engine)
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
        if self.scratch_state is not None or self.var.exit != "passive":
            return
        if t - self.entry_fill_t < self.bcfg.stall_after_s.get(self.venue, 2.0):
            return
        ret = self.dir * math.log(S / self.S_ref) * BPS / self.impulse_bps          # fraction of the impulse still intact
        gap_px = abs(self.sig.gap_bps) / BPS * self.mid0
        progress = self.side * (mid - self.mid0) / gap_px if gap_px > 0 else 1.0     # fraction of the credited gap the venue has done
        if ret < self.bcfg.hold_frac and progress < self.bcfg.stall_frac:
            self._start_scratch(t)

    def _start_scratch(self, t: float) -> None:
        x = self.exit
        if x is None or x.state != "resting":
            return
        x.state = "cancel_pending"
        x.cancel_t = t
        x.cancel_eff = t + self.cfg.cancel_latency_s
        x.cancel_reason = "scratch"
        self.exit_prev.append(x)
        self.exit = None
        self.scratch_state = "pending"
        self.scratch_at = x.cancel_eff
        self.scratched = True
        self.work_deadline = x.cancel_eff + self.cfg.order_latency_s + self.bcfg.scratch_work_s

    def _scratch_place(self, t: float) -> None:
        self.scratch_state = "placed"
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
        px = ask if self.side > 0 else bid                                 # exit side sells at the ask (long) / buys at the bid (short)
        self.exit = Order("exit", -self.side, px, rem, "ALO", t, t + self.cfg.order_latency_s)

    def extra_row(self) -> dict:
        return {"floor_ok": self.floor_ok, "ratio": self.ratio, "pred_bps": self.pred_bps, "floor_bps": self.floor_bps, "scratched": self.scratched,
                "rev_stopped": self.rev_stopped, "arch": "B" if self.var.exit == "passive" else "taker/taker"}


class TakerAttempt(Attempt):
    """The taker/taker reference (same entry, taker take-profit) carrying the same floor tags so the report can gate it identically."""

    def __init__(self, hc, var, sig, notional, account, S0, stop_bps, tp_bps, floor_ok, ratio, pred_bps, floor_bps):
        self.floor_ok, self.ratio, self.pred_bps, self.floor_bps = floor_ok, ratio, pred_bps, floor_bps
        super().__init__(hc, var, sig, notional, account, S0, stop_bps, tp_bps)

    def extra_row(self) -> dict:
        return {"floor_ok": self.floor_ok, "ratio": self.ratio, "pred_bps": self.pred_bps, "floor_bps": self.floor_bps, "scratched": False,
                "rev_stopped": False, "arch": "taker/taker"}


class HighConvictionSniper(MakerSniper):
    """Same shadow/account plumbing as the Phase 5 sniper; different entry policy, exit supervision and gating."""

    def __init__(self, agency, cfg: Optional[BConfig] = None):
        self.bcfg = cfg or BConfig()
        super().__init__(agency, agency.cfg.snipe, variants=[])          # reuse infra (hist / tick_est / account bookkeeping); variants are ours
        self.venues = set(self.bcfg.venues)
        self.elig = [i for i, m in enumerate(self.book.metas) if m.venue in self.venues]
        self.hist = {i: QuoteHist() for i in self.elig}
        self.cfg = _SnipeView(agency.cfg.snipe, self.bcfg)               # Attempt reads latency/ttl/work/hold knobs from here
        self.n_floor_ok = 0
        self.n_signals_seen = 0

    # -------------------------------------------------------------- the variants
    def _variants(self) -> List[Variant]:
        out = [Variant("B/taker→maker+scratch", "taker", "passive", False, m) for m in self.bcfg.shadow_models]
        out.append(Variant("taker/taker", "taker", "taker", False, "strict"))
        return out

    # -------------------------------------------------------------- polling: time events + supervision
    def poll(self, t: float, S: float) -> None:
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
        tp_bps = self.cfo.cfg.tp_capture * abs(sig.gap_bps)
        stop_bps = max(self.cfo.cfg.stop_mult * sig.sigma_res_bps, self.cfo.cfg.min_stop_bps)
        for v in self._variants():
            if v.exit == "passive":
                at = BAttempt(self, v, sig, notional, False, S, stop_bps, tp_bps, ok, ratio, pred, floor)
            else:
                at = TakerAttempt(self, v, sig, notional, False, S, stop_bps, tp_bps, ok, ratio, pred, floor)
            self.active.setdefault(sig.idx, []).append(at)
        if dec is not None and dec.approved and dec.mode == "b_snipe" and sig.idx not in self.account_open:
            _, live_floor, live_ratio = self.cfo.b_floor(sig)                    # the account's own (CEO-tunable) floor
            v = Variant("ACCOUNT", "taker", "passive", False, b.account_model)
            at = BAttempt(self, v, sig, dec.notional, True, S, dec.stop_bps, dec.tp_bps, ok, ratio, pred, floor, pred_net_bps=dec.net_edge_bps)
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
        if len(self.results) > 200_000:
            del self.results[:50_000]
        if at.account:
            self.account_open.pop(at.i, None)
            self.account_results.append(r)
            if r["outcome"] == "filled":
                tr = TradeResult(oid=at.sig.sid, sid=at.sig.sid, market=r["market"], side=at.side, mode="b_snipe", t_entry=r["fill_t"], t_exit=r["t_end"],
                                 entry_px=r["entry_px"], exit_px=r["exit_px"], qty=r["qty"], notional=r["entry_px"] * r["qty"], gross_bps=r["gross_bps"],
                                 fees_usd=r["fees_usd"], net_pnl_usd=r["net_usd"], net_bps=r["net_bps"],
                                 R=r["net_usd"] / max(r["entry_px"] * r["qty"] * at.stop_bps / BPS, 1e-9), exit_reason=r["exit_reason"], hold_s=r["hold_s"],
                                 entry_slip_bps=0.0, exit_slip_bps=0.0, spread_bps_entry=at.sig.spread_bps, predicted_net_bps=at.pred_net,
                                 gap_bps=at.sig.gap_bps, predicted_slip_bps=0.0)
                self.cfo.on_open(r["market"], at.side, tr.notional, 1.0)
                self.cfo.on_close(r["market"], at.side, tr.notional, 1.0)
                self.cfo.on_trade_closed(tr, r["t_end"])
                self.cfo.on_b_result(r)
                self.a.engine.closed.append(tr)
                self.a._write("trades", tr.as_dict())
            self.a._write("b_account", r)


class _SnipeView:
    """Attempt expects SnipeConfig-shaped knobs; Phase 6 keeps the latency/ttl/work values of SnipeConfig (same venue behaviour)."""

    def __init__(self, sc, bc):
        self._sc, self._bc = sc, bc

    def __getattr__(self, k):
        return getattr(self._sc, k)
