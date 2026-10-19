"""Tier 3 – instant trade preparation + latency-aware PAPER execution.

``prepare`` builds the complete executable payload the moment the CFO approves a signal
(IOC taker sniper or post-only maker, exact tick-rounded limit, liquidity-capped size, convergence
take-profit, hard time-stop, adverse-selection stop). ``PaperExchange`` then simulates it with an
order-entry latency, as-of quotes (no look-ahead), partial IOC fills, maker fills only when the
market trades *through* the resting price, and taker exits.

No exchange credentials exist in this project and no live order is ever sent.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, asdict, field
from typing import Dict, List, Optional

from .cfo_agent import CFOAgent, Decision
from .config import ExecConfig
from .inefficiency_hunter import Signal
from .market_watchers import AQ, ASK, BID, BQ, MID, MarketBook, MarketMeta, maker_fee_bps, taker_fee_bps

BPS = 1e4


def _floor_to(x: float, q: float) -> float:
    return math.floor(x / q + 1e-9) * q if q > 0 else x


def _ceil_to(x: float, q: float) -> float:
    return math.ceil(x / q - 1e-9) * q if q > 0 else x


@dataclass
class OrderPayload:
    oid: int
    sid: int
    market: str
    symbol: str
    venue: str
    side: str                    # BUY | SELL
    order_type: str              # LIMIT_MAKER (post-only) | LIMIT (IOC)
    time_in_force: str           # GTC | IOC
    price: float
    qty: float
    notional: float
    mode: str                    # taker | maker
    tp_price: float              # convergence take-profit (mid terms)
    stop_price: float            # adverse-selection stop (mid terms)
    time_stop_s: float
    maker_ttl_s: float
    expected_net_bps: float
    gap_bps: float
    t_signal: float
    t_prepared: float
    prep_latency_us: float = 0.0
    sig_quote_px: float = 0.0
    sig_mid: float = 0.0
    beta: float = 1.0
    stop_bps: float = 0.0

    def exchange_params(self) -> dict:
        """Binance-spot style NEW_ORDER parameters (for the record; never transmitted)."""
        p = {"symbol": self.symbol, "side": self.side, "type": self.order_type, "quantity": f"{self.qty:.8f}".rstrip("0").rstrip("."),
             "price": f"{self.price:.10f}".rstrip("0").rstrip("."), "newClientOrderId": f"qa{self.oid}"}
        if self.order_type == "LIMIT":
            p["timeInForce"] = self.time_in_force
        return p

    def as_dict(self):
        d = asdict(self)
        d["exchange_params"] = self.exchange_params()
        return d


@dataclass
class TradeResult:
    oid: int
    sid: int
    market: str
    side: int
    mode: str
    t_entry: float
    t_exit: float
    entry_px: float
    exit_px: float
    qty: float
    notional: float
    gross_bps: float
    fees_usd: float
    net_pnl_usd: float
    net_bps: float
    R: float
    exit_reason: str
    hold_s: float
    entry_slip_bps: float
    exit_slip_bps: float
    spread_bps_entry: float
    predicted_net_bps: float
    gap_bps: float
    predicted_slip_bps: float = 0.0

    def as_dict(self):
        return asdict(self)


@dataclass
class _Order:
    p: OrderPayload
    sig: Signal
    dec: Decision
    ready_t: float
    resting: bool = False
    rest_t: float = 0.0
    side: int = 1


@dataclass
class _Pos:
    p: OrderPayload
    sig: Signal
    dec: Decision
    entry_t: float
    entry_px: float
    qty: float
    entry_fee: float
    fill_mid: float
    exit_ready: float = 0.0
    exit_reason: str = ""
    exit_trig_px: float = 0.0
    side: int = 1


class ExecutionEngine:
    def __init__(self, book: MarketBook, cfo: CFOAgent, cfg: Optional[ExecConfig] = None):
        self.book, self.cfo = book, cfo
        self.cfg = cfg or ExecConfig()
        self.cfg.latency_s = cfo.cfg.latency_s
        self._oid = 0
        self.orders: Dict[int, _Order] = {}
        self.positions: Dict[int, _Pos] = {}           # by market idx
        self.pending_idx: Dict[int, int] = {}          # market idx -> oid of entry order in flight
        self.active_idx: set = set()
        self.closed: List[TradeResult] = []
        self.payload_log: List[dict] = []
        self.rejected_exec: Dict[str, int] = {}
        self.n_submitted = 0
        self.n_filled = 0
        self.n_partial = 0

    # ----------------------------------------------------------------- preparation
    def has_position(self, idx: int) -> bool:
        return idx in self.positions or idx in self.pending_idx

    def prepare(self, sig: Signal, dec: Decision, t_now: float, t_wall_us: float = 0.0) -> Optional[OrderPayload]:
        meta: MarketMeta = self.book.metas[sig.idx]
        c = self.cfo.cfg
        s = sig.side
        if dec.mode == "taker":
            cap_bps = max(2.0 * dec.slip_bps, 0.5 * sig.spread_bps, 0.5)
            raw = sig.ask * (1 + cap_bps / BPS) if s > 0 else sig.bid * (1 - cap_bps / BPS)
            price = _ceil_to(raw, meta.tick) if s > 0 else _floor_to(raw, meta.tick)
            otype, tif = "LIMIT", "IOC"
        else:
            raw = sig.bid if s > 0 else sig.ask
            price = _floor_to(raw, meta.tick) if s > 0 else _ceil_to(raw, meta.tick)
            otype, tif = "LIMIT_MAKER", "GTC"
        qty = _floor_to(dec.notional / price, meta.step)
        if qty <= 0 or qty * price < max(meta.min_notional, c.min_notional):
            self.rejected_exec["below_min_notional"] = self.rejected_exec.get("below_min_notional", 0) + 1
            return None
        self._oid += 1
        p = OrderPayload(
            oid=self._oid, sid=sig.sid, market=sig.market, symbol=meta.symbol, venue=meta.venue,
            side="BUY" if s > 0 else "SELL", order_type=otype, time_in_force=tif, price=price, qty=qty,
            notional=qty * price, mode=dec.mode, tp_price=sig.mid * (1 + s * dec.tp_bps / BPS),
            stop_price=sig.mid * (1 - s * dec.stop_bps / BPS), time_stop_s=dec.time_stop_s,
            maker_ttl_s=c.maker_ttl_s, expected_net_bps=dec.net_edge_bps, gap_bps=sig.gap_bps,
            t_signal=sig.t, t_prepared=t_now, prep_latency_us=t_wall_us,
            sig_quote_px=sig.ask if s > 0 else sig.bid, sig_mid=sig.mid, beta=sig.beta, stop_bps=dec.stop_bps)
        return p

    def submit(self, p: OrderPayload, sig: Signal, dec: Decision, now: float) -> bool:
        if len(self.positions) + len(self.pending_idx) >= self.cfg.max_open:
            self.rejected_exec["max_open"] = self.rejected_exec.get("max_open", 0) + 1
            return False
        o = _Order(p=p, sig=sig, dec=dec, ready_t=now + self.cfg.latency_s, side=sig.side)
        self.orders[p.oid] = o
        self.pending_idx[sig.idx] = p.oid
        self.active_idx.add(sig.idx)
        self.n_submitted += 1
        self.payload_log.append(p.as_dict())
        if len(self.payload_log) > 5000:
            del self.payload_log[:1000]
        return True

    # ----------------------------------------------------------------- event/poll driven simulation
    def on_quote(self, idx: int, t: float) -> None:
        """Called for every quote of a market that has activity; cheap early-out otherwise."""
        if idx not in self.active_idx:
            return
        oid = self.pending_idx.get(idx)
        if oid is not None:
            o = self.orders[oid]
            if o.resting and t > o.rest_t:
                st = self.book.state[idx]
                L = o.p.price
                crossed = (st[ASK] <= L) if o.side > 0 else (st[BID] >= L)
                if crossed:
                    self._fill_entry(o, t, L, o.p.qty, maker=True)
        pos = self.positions.get(idx)
        if pos is not None and not pos.exit_reason:
            mid = self.book.state[idx, MID]
            if (pos.side > 0 and mid >= pos.p.tp_price) or (pos.side < 0 and mid <= pos.p.tp_price):
                self._trigger_exit(pos, t, "take_profit")
            elif (pos.side > 0 and mid <= pos.p.stop_price) or (pos.side < 0 and mid >= pos.p.stop_price):
                self._trigger_exit(pos, t, "adverse_stop")

    def poll(self, now: float) -> List[TradeResult]:
        """Advance order/position state machines to ``now``. Returns trades closed during this call."""
        out: List[TradeResult] = []
        for oid in list(self.pending_idx.values()):
            o = self.orders[oid]
            idx = o.sig.idx
            if not o.resting and now >= o.ready_t:
                q = self.book.quote_asof(idx, o.ready_t)
                if q is None:
                    q = (self.book.state[idx, BID], self.book.state[idx, ASK])
                bid, ask = q
                if o.p.order_type == "LIMIT":                      # IOC taker
                    px = ask if o.side > 0 else bid
                    ok = (px <= o.p.price) if o.side > 0 else (px >= o.p.price)
                    if not ok:
                        self._drop_entry(o, "ioc_price_moved")
                        continue
                    top = self.book.state[idx, AQ] if o.side > 0 else self.book.state[idx, BQ]
                    qty = min(o.p.qty, top)
                    if qty * px < 0.5 * o.p.notional:           # <50% fillable -> treat as miss
                        self._drop_entry(o, "ioc_no_liquidity")
                        continue
                    if qty < o.p.qty:
                        self.n_partial += 1
                    self._fill_entry(o, o.ready_t, px, qty, maker=False)
                else:                                              # post-only maker
                    crosses = (ask <= o.p.price) if o.side > 0 else (bid >= o.p.price)
                    if crosses:
                        self._drop_entry(o, "post_only_would_cross")
                        self.cfo.on_maker_result(False)
                        continue
                    o.resting, o.rest_t = True, o.ready_t
            elif o.resting and now >= o.rest_t + o.p.maker_ttl_s:
                self._drop_entry(o, "maker_ttl_expired")
                self.cfo.on_maker_result(False)
        for idx, pos in list(self.positions.items()):
            if not pos.exit_reason and now >= pos.entry_t + pos.p.time_stop_s:
                self._trigger_exit(pos, pos.entry_t + pos.p.time_stop_s, "time_stop")
            if pos.exit_reason and now >= pos.exit_ready:
                tr = self._close(pos, pos.exit_ready)
                if tr is not None:
                    out.append(tr)
        return out

    def flatten_all(self, now: float, reason: str = "flatten") -> None:
        for oid in list(self.pending_idx.values()):
            self._drop_entry(self.orders[oid], reason)
        for pos in self.positions.values():
            if not pos.exit_reason:
                self._trigger_exit(pos, now, reason)

    # ----------------------------------------------------------------- internals
    def _drop_entry(self, o: _Order, why: str) -> None:
        self.rejected_exec[why] = self.rejected_exec.get(why, 0) + 1
        self.pending_idx.pop(o.sig.idx, None)
        self.orders.pop(o.p.oid, None)
        if o.sig.idx not in self.positions:
            self.active_idx.discard(o.sig.idx)

    def _fill_entry(self, o: _Order, t: float, px: float, qty: float, maker: bool) -> None:
        idx = o.sig.idx
        self.pending_idx.pop(idx, None)
        self.orders.pop(o.p.oid, None)
        meta = self.book.metas[idx]
        fee_bps = maker_fee_bps(meta, self.cfo.cfg.fee_maker_bps) if maker else taker_fee_bps(meta, px, self.cfo.cfg.fee_taker_bps)
        st = self.book.state[idx]
        fm = self.book.mid_asof(idx, t)
        pos = _Pos(p=o.p, sig=o.sig, dec=o.dec, entry_t=t, entry_px=px, qty=qty, entry_fee=qty * px * fee_bps / BPS,
                   fill_mid=float(st[MID]) if math.isnan(fm) else float(fm), side=o.side)
        # adverse stop is anchored to the mid at fill (so latency drift doesn't pre-trigger it)
        pos.p.stop_price = pos.fill_mid * (1 - pos.side * pos.p.stop_bps / BPS)
        self.positions[idx] = pos
        self.cfo.on_open(o.p.market, o.side, qty * px, o.p.beta)
        if maker:
            self.cfo.on_maker_result(True)
        self.n_filled += 1

    def _trigger_exit(self, pos: _Pos, t: float, reason: str) -> None:
        pos.exit_reason = reason
        pos.exit_ready = t + self.cfg.latency_s

    def _close(self, pos: _Pos, t: float) -> Optional[TradeResult]:
        idx = pos.sig.idx
        q = self.book.quote_asof(idx, t)
        if q is None:
            q = (float(self.book.state[idx, BID]), float(self.book.state[idx, ASK]))
        bid, ask = q
        s = pos.side
        exit_px = bid if s > 0 else ask                         # taker exit crosses the spread
        fee_exit = pos.qty * exit_px * taker_fee_bps(self.book.metas[idx], exit_px, self.cfo.cfg.fee_taker_bps) / BPS
        gross = s * (exit_px - pos.entry_px) * pos.qty
        fees = pos.entry_fee + fee_exit
        net = gross - fees
        notional = pos.qty * pos.entry_px
        risk = max(notional * pos.p.stop_bps / BPS, 1e-9)
        exp_px = pos.p.sig_quote_px
        entry_slip = s * (pos.entry_px - exp_px) / exp_px * BPS if exp_px else 0.0
        trig_mid = self.book.mid_asof(idx, pos.exit_ready - self.cfg.latency_s)
        exit_slip = s * (trig_mid - exit_px) / trig_mid * BPS if trig_mid and not math.isnan(trig_mid) else 0.0
        tr = TradeResult(
            oid=pos.p.oid, sid=pos.p.sid, market=pos.p.market, side=s, mode=pos.p.mode, t_entry=pos.entry_t, t_exit=t,
            entry_px=pos.entry_px, exit_px=exit_px, qty=pos.qty, notional=notional,
            gross_bps=s * (exit_px - pos.entry_px) / pos.entry_px * BPS, fees_usd=fees, net_pnl_usd=net,
            net_bps=net / notional * BPS, R=net / risk, exit_reason=pos.exit_reason, hold_s=t - pos.entry_t,
            entry_slip_bps=entry_slip, exit_slip_bps=exit_slip, spread_bps_entry=pos.sig.spread_bps,
            predicted_net_bps=pos.dec.net_edge_bps, gap_bps=pos.sig.gap_bps,
            predicted_slip_bps=pos.dec.slip_bps)
        self.positions.pop(idx, None)
        if idx not in self.pending_idx:
            self.active_idx.discard(idx)
        self.cfo.on_close(pos.p.market, s, notional, pos.p.beta)
        self.cfo.on_trade_closed(tr, t)
        self.closed.append(tr)
        if len(self.closed) > 50_000:
            del self.closed[:10_000]
        return tr

    def stats(self) -> dict:
        return {"submitted": self.n_submitted, "filled": self.n_filled, "partial": self.n_partial,
                "closed": len(self.closed), "open": len(self.positions), "pending": len(self.pending_idx),
                "dropped": dict(self.rejected_exec)}
