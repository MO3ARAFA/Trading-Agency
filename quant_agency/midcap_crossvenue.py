"""1-to-1 same-asset cross-venue tail lag: Binance Vision spot  ->  Hyperliquid perp.

Coin i on Binance is the dedicated oracle for coin i on Hyperliquid. There is no beta, no calibration and no second asset: the
fair value of the Hyperliquid perp after a Binance move is its own earlier value carried by the Binance move,

    gap_i(t, h) = [ln B_i(t) - ln B_i(t-h)] - [ln H_i(t) - ln H_i(t-h)]        (+ : the perp should still rise)

which is basis-neutral (a constant spot/perp premium, or its slow drift, cancels in the two differences). A signal is recorded when,
on a Binance tick of coin i,

  * the Binance leg made a fast move over h in {1 s, 3 s}:  |dB| >= impulse_min_bps,
  * the perp has not followed: sign(gap) == sign(dB) and |gap| >= record_bps (the shadow floor, 4 bps).

Tiers (flags, evaluated afterwards): |gap| >= 8 / 10 / 15 bps, and "full cost cleared": |gap| >= HL spread + 2 x taker fee + slippage
(the brief's 12-15 bps). The entry is a taker order on the perp (ask for an up move, bid for a down move) ``latency`` seconds after the
Binance tick; markouts at 1/3/5/10/30 s cross the spread again on exit. Fee tiers (taker 4.5 bps / maker 1.5 bps per side) are applied
afterwards from the spread-crossing result ``net0`` so a single capture serves all of them.

Measurement only: nothing here prepares or sends an order.
"""
from __future__ import annotations

import json
import math
import os
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional, Sequence

import numpy as np

from .cfo_agent import Decision, MarkoutTracker
from .inefficiency_hunter import Signal
from .market_watchers import AQ, ASK, BID, BQ, LAST_T, LMID, MID, NTICK, SPR_SLOW, MarketMeta, log_mid_asof
from .venues import VENUE_MAKER_BPS, VENUE_TAKER_BPS

BPS = 1e4
BASELINE_ASSETS = ("BTC", "ETH")
NEVER = ("PAXG", "XAUT", "USDC", "FDUSD", "TUSD", "USDE", "DAI", "USD1", "RLUSD", "EUR", "AEUR", "BTC", "ETH")


@dataclass
class XvConfig:
    n_pairs: int = 50                       # mid-cap pairs (BTC / ETH are added on top as the baseline)
    horizons_s: Sequence[float] = (1.0, 3.0)
    record_bps: float = 4.0                 # shadow floor: every gap above this is recorded (tiers are cut afterwards)
    impulse_min_bps: float = 4.0            # the Binance leg itself must have moved this much over the horizon
    cooldown_s: float = 3.0                 # per pair
    min_ticks_b: int = 30
    min_ticks_h: int = 20
    max_age_b_s: float = 2.0                # the Binance quote that triggers must be live
    fee_taker_hl_bps: float = 4.5
    fee_maker_hl_bps: float = 1.5
    clip_usd: float = 1000.0                # clip for the depth term of the slippage estimate and the 'tradable at the touch' flag
    latencies_s: Sequence[float] = (0.0, 0.15, 0.5, 1.0)
    block_s: float = 10.0                   # cluster = 10-second time block (a market-wide move hits many coins at once)
    id_base: int = 70_000_000
    # universe
    min_binance_vol: float = 1_000_000.0
    min_hl_vol: float = 500_000.0
    max_binance_spread_bps: float = 15.0
    max_tick_bps: float = 10.0              # 1 Binance tick above this -> price quantisation dominates (PEPE-like), excluded
    sig_keep: int = 20000


# ================================================================================ universe
@dataclass
class XvUniverse:
    metas: List[MarketMeta]
    pairs: List[dict]
    dropped: Dict[str, str]
    counts: Dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"pairs": self.pairs, "dropped": self.dropped, "counts": self.counts}


def _bspread(x: dict) -> float:
    try:
        b, a = float(x["bidPrice"]), float(x["askPrice"])
    except (KeyError, TypeError, ValueError):
        return 1e9
    return (a - b) / ((a + b) / 2) * BPS if b > 0 and a >= b else 1e9


def hl_to_asset(name: str) -> str:
    """Hyperliquid's 1000x contracts are k-prefixed (kPEPE, kBONK ...): the canonical asset drops the prefix."""
    return name[1:] if len(name) > 1 and name[0] == "k" and name[1:].isupper() else name


def build_xv_universe(data: dict, cfg: Optional[XvConfig] = None) -> XvUniverse:
    """Pure builder. ``data``: b24, bbook, binfo (Binance Vision), hl_meta = the [meta, assetCtxs] pair of Hyperliquid's metaAndAssetCtxs."""
    cfg = cfg or XvConfig()
    b24 = {x["symbol"]: x for x in data.get("b24", [])}
    bbook = {x["symbol"]: x for x in data.get("bbook", [])}
    binfo = {s["symbol"]: s for s in data.get("binfo", {}).get("symbols", [])}
    uni, ctxs = data["hl_meta"]
    dropped: Dict[str, str] = {}
    cand = []
    for u, c in zip(uni["universe"], ctxs):
        name = u["name"]
        asset = hl_to_asset(name)
        sym = f"{asset}USDT"
        if u.get("isDelisted"):
            continue
        if sym not in b24:
            continue                                         # HL-only coin: not part of a 1-to-1 pair
        hlv = float(c.get("dayNtlVlm") or 0.0)
        bv = float(b24[sym]["quoteVolume"])
        inf = binfo.get(sym)
        sp = _bspread(bbook.get(sym, {}))
        f = {y["filterType"]: y for y in (inf or {}).get("filters", [])}
        tick = float(f.get("PRICE_FILTER", {}).get("tickSize", 0) or 0)
        px = float(c.get("midPx") or c.get("markPx") or 0.0)
        tick_bps = tick / px * BPS if px > 0 else 0.0
        base = asset in BASELINE_ASSETS
        why = None
        if asset in NEVER and not base:
            why = "excluded asset (gold / stablecoin)"
        elif inf is None or inf.get("status", "TRADING") != "TRADING":
            why = "Binance symbol not trading"
        elif not base and bv < cfg.min_binance_vol:
            why = f"Binance 24h volume ${bv / 1e6:.2f}M < ${cfg.min_binance_vol / 1e6:g}M"
        elif not base and hlv < cfg.min_hl_vol:
            why = f"HL 24h volume ${hlv / 1e6:.2f}M < ${cfg.min_hl_vol / 1e6:g}M"
        elif not base and sp > cfg.max_binance_spread_bps:
            why = f"Binance spread {sp:.1f} bps > {cfg.max_binance_spread_bps:g}"
        elif not base and tick_bps > cfg.max_tick_bps:
            why = f"one tick = {tick_bps:.1f} bps > {cfg.max_tick_bps:g} (quantised book)"
        if why:
            dropped[asset] = why
            continue
        cand.append({"asset": asset, "hl_coin": name, "symbol": sym, "hl_vol": hlv, "bn_vol": bv, "bn_spread_bps": sp, "tick_bps": tick_bps,
                     "baseline": base, "inf": inf, "mark": px})
    base_pairs = sorted((c for c in cand if c["baseline"]), key=lambda c: BASELINE_ASSETS.index(c["asset"]))
    mids = sorted((c for c in cand if not c["baseline"]), key=lambda c: -c["hl_vol"])
    for c in mids[cfg.n_pairs:]:
        dropped[c["asset"]] = f"rank {mids.index(c) + 1} by HL volume > {cfg.n_pairs}"
    chosen = base_pairs + mids[: cfg.n_pairs]
    metas: List[MarketMeta] = []
    if not any(c["asset"] == "BTC" for c in chosen):
        raise ValueError("BTC must be in the matched set: index 0 of the book is the Binance BTCUSDT feed")
    order = sorted(chosen, key=lambda c: (c["asset"] != "BTC", c["asset"] != "ETH"))
    for c in order:
        f = {y["filterType"]: y for y in c["inf"]["filters"]}
        metas.append(MarketMeta(id=c["symbol"], venue="binance", symbol=c["symbol"], base=c["asset"], asset=c["asset"], kind="spot", quote="USDT",
                                tick=float(f.get("PRICE_FILTER", {}).get("tickSize", 0) or 0), step=float(f.get("LOT_SIZE", {}).get("stepSize", 0) or 0),
                                min_notional=float((f.get("NOTIONAL") or f.get("MIN_NOTIONAL") or {}).get("minNotional", 5) or 5),
                                quote_vol_usd=c["bn_vol"], fee_taker_bps=VENUE_TAKER_BPS["binance"], fee_maker_bps=VENUE_MAKER_BPS["binance"],
                                hunt=False, tradable=False))
    for c in order:
        metas.append(MarketMeta(id=f"hyperliquid:{c['hl_coin']}", venue="hyperliquid", symbol=c["hl_coin"], base=c["asset"], asset=c["asset"], kind="perp",
                                quote="USDC", quote_vol_usd=c["hl_vol"], fee_taker_bps=cfg.fee_taker_hl_bps, fee_maker_bps=cfg.fee_maker_hl_bps,
                                hunt=False, tradable=False, extra={"unit_mult": 1000 if c["hl_coin"] != c["asset"] else 1}))
    pairs = [{"asset": c["asset"], "binance": c["symbol"], "hl": f"hyperliquid:{c['hl_coin']}", "baseline": c["baseline"], "hl_vol": c["hl_vol"],
              "bn_vol": c["bn_vol"], "bn_spread_bps": c["bn_spread_bps"], "tick_bps": c["tick_bps"]} for c in order]
    return XvUniverse(metas, pairs, dropped, {"pairs": len(pairs), "midcap": sum(not p["baseline"] for p in pairs), "markets": len(metas)})


async def fetch_xv_data(session, rest_base: str = "https://data-api.binance.vision") -> dict:
    import orjson

    async def get(url, **kw):
        async with session.get(url, **kw) as r:
            return orjson.loads(await r.read())

    d: dict = {"b24": await get(f"{rest_base}/api/v3/ticker/24hr"), "bbook": await get(f"{rest_base}/api/v3/ticker/bookTicker")}
    async with session.post("https://api.hyperliquid.xyz/info", json={"type": "metaAndAssetCtxs"}) as r:
        d["hl_meta"] = orjson.loads(await r.read())
    uni, _ = d["hl_meta"]
    syms = sorted({f"{hl_to_asset(u['name'])}USDT" for u in uni["universe"]} & {x["symbol"] for x in d["b24"]})
    # exchangeInfo for ~150 symbols in chunks (one unknown symbol fails a whole request)
    infos = []
    for k in range(0, len(syms), 50):
        part = await get(f"{rest_base}/api/v3/exchangeInfo", params={"symbols": json.dumps(syms[k:k + 50], separators=(",", ":"))})
        infos += part.get("symbols", [])
    d["binfo"] = {"symbols": infos}
    return d


async def discover_xv_universe(session=None, cfg: Optional[XvConfig] = None) -> XvUniverse:
    import aiohttp

    own = session is None
    session = session or aiohttp.ClientSession(trust_env=True, timeout=aiohttp.ClientTimeout(total=40), headers={"User-Agent": "Mozilla/5.0"})
    try:
        return build_xv_universe(await fetch_xv_data(session), cfg)
    finally:
        if own:
            await session.close()


# ================================================================================ scanner
class XvScanner:
    """Runs inside an Agency: every Binance quote of a paired coin is tested against the perp's current mid."""

    def __init__(self, ag, cfg: Optional[XvConfig] = None, pairs: Optional[List[dict]] = None):
        self.ag = ag
        self.cfg = cfg or XvConfig()
        c = self.cfg
        book = ag.book
        self.pairs = []
        for p in pairs or []:
            b, h = book.index[p["binance"]], book.index[p["hl"]]
            self.pairs.append({**p, "b": b, "h": h})
        self.by_b: Dict[int, int] = {p["b"]: k for k, p in enumerate(self.pairs)}
        self.by_h: Dict[int, int] = {p["h"]: k for k, p in enumerate(self.pairs)}
        self.cool = np.zeros(len(self.pairs))
        self.n_eval = np.zeros(len(self.pairs), dtype=np.int64)
        self.n_cand = np.zeros(len(self.pairs), dtype=np.int64)
        self.n_dead = np.zeros(len(self.pairs), dtype=np.int64)
        cfo = ag.cfg.cfo
        self.trackers = {lat: MarkoutTracker(book, cfo.markout_horizons_s, lat, c.fee_taker_hl_bps) for lat in c.latencies_s}
        for tr in self.trackers.values():
            tr.max_rows = 3_000_000
        self.main_lat = min(self.trackers, key=lambda x: abs(x - cfo.latency_s))
        self._sid = c.id_base
        self.n_signals = 0
        self.signals: List[Signal] = []
        self.placebo_shift = 0.0

    # ---- ingestion
    def on_quote(self, i: int, t: float, bid: float, ask: float, bq: float, aq: float) -> None:
        k = self.by_b.get(i)
        if k is None:
            return
        c = self.cfg
        bk = self.ag.book
        st = bk.state
        p = self.pairs[k]
        h = p["h"]
        self.n_eval[k] += 1
        if st[i, NTICK] < c.min_ticks_b or st[h, NTICK] < c.min_ticks_h or self.cool[k] > t:
            return
        best = None
        lb1, lh1 = st[i, LMID], st[h, LMID]
        for hz in c.horizons_s:
            lb0 = log_mid_asof(bk.rt, bk.rb, bk.ra, bk.n, bk.cap, i, t - hz)
            lh0 = log_mid_asof(bk.rt, bk.rb, bk.ra, bk.n, bk.cap, h, t - hz)
            if not (math.isfinite(lb0) and math.isfinite(lh0)):
                continue
            db, dh = (lb1 - lb0) * BPS, (lh1 - lh0) * BPS
            gap = db - dh
            if abs(db) < c.impulse_min_bps or db * gap <= 0.0 or abs(gap) < c.record_bps:
                continue
            if best is None or abs(gap) > abs(best[0]):
                best = (gap, db, dh, hz)
        if best is None:
            return
        self.n_cand[k] += 1
        gap, db, dh, hz = best
        side = 1 if gap > 0 else -1
        bid_h, ask_h, bq_h, aq_h, mid_h = st[h, BID], st[h, ASK], st[h, BQ], st[h, AQ], st[h, MID]
        spread = (ask_h - bid_h) / mid_h * BPS
        px = ask_h if side > 0 else bid_h
        top_units = aq_h if side > 0 else bq_h
        top_usd = top_units * px                            # size x price is USD for the k-contracts too (both are per 1000 units)
        depth = min(c.clip_usd / top_usd, 4.0) if top_usd > 0 else 4.0
        slip = 0.5 * spread * depth
        hurdle = spread + 2.0 * c.fee_taker_hl_bps + slip
        self.cool[k] = t + c.cooldown_s
        self._sid += 1
        t0 = self.ag.t0
        sig = Signal(sid=self._sid, t=t, t_recv=t, market=bk.ids[h], idx=h, side=side, horizon_s=hz, btc_delta_bps=db, btc_z=0.0, btc_obi=0.0, btc_flow_1s=0.0,
                     vol_ratio=1.0, beta=1.0, rho=1.0, lag_s=0.0, window_s=0.0, age_s=0.0, fair_bps=db, actual_bps=dh, gap_bps=gap, gap_z=0.0,
                     sigma_res_bps=0.0, spread_bps=spread, bid=float(bid_h), ask=float(ask_h), bq=float(bq_h), aq=float(aq_h), mid=float(mid_h),
                     impulse_id=c.id_base + 1 + int((t - t0) / c.block_s), oracle="xv", hurdle_bps=hurdle, lead_sigma_bps=0.0, net_gap_bps=abs(gap) - hurdle,
                     tag={"x_asset": p["asset"], "x_baseline": p["baseline"], "x_dB": db, "x_dH": dh, "x_hz": hz, "x_hl_age": float(t - st[h, LAST_T]),
                          "x_top_usd": float(top_usd), "x_hurdle": hurdle, "x_spread_h": spread, "x_slip": slip, "x_spread_b": float((ask - bid) / (0.5 * (ask + bid)) * BPS)})
        self._observe(sig)

    def _observe(self, s: Signal) -> None:
        dec = Decision(approved=False, reason="observe", cohort="observe", net_edge_bps=s.net_gap_bps, net_edge_taker_bps=s.net_gap_bps,
                       gap_credit_bps=abs(s.gap_bps), spread_bps=s.spread_bps)
        for tr in self.trackers.values():
            tr.register(s, dec)
        self.n_signals += 1
        self.ag._write("xv_signals", s.as_dict())
        self.signals.append(s)
        if len(self.signals) > self.cfg.sig_keep:
            del self.signals[: self.cfg.sig_keep // 5]

    def poll(self, t: float) -> None:
        for tr in self.trackers.values():
            tr.poll(t)

    def reset(self, t: float, idxs, hold_s: float) -> None:
        """A feed reconnected: a stale leg would look like a gap, so quiet the affected pairs."""
        for k, p in enumerate(self.pairs):
            if idxs is None or p["b"] in idxs or p["h"] in idxs:
                self.cool[k] = max(self.cool[k], t + hold_s)
                self.n_dead[k] += 1

    # ---- artefacts
    def summary(self) -> dict:
        bk = self.ag.book
        st = bk.state
        rows = []
        for k, p in enumerate(self.pairs):
            b, h = p["b"], p["h"]
            rows.append({"asset": p["asset"], "baseline": p["baseline"], "evals": int(self.n_eval[k]), "candidates": int(self.n_cand[k]), "resets": int(self.n_dead[k]),
                         "ticks_b": int(st[b, NTICK]), "ticks_h": int(st[h, NTICK]), "spr_b": float(st[b, SPR_SLOW]), "spr_h": float(st[h, SPR_SLOW])})
        return {"n_signals": self.n_signals, "pairs": rows}

    def dump(self, run_dir: str, t_end: float) -> None:
        os.makedirs(run_dir, exist_ok=True)
        with open(os.path.join(run_dir, "xv_markouts.jsonl"), "w") as f:
            for tr in self.trackers.values():
                for r in tr.rows:
                    f.write(json.dumps(r, default=float) + "\n")
        info = {"t_start": self.ag.t0, "t_end": t_end, "warm_s": 60.0, "config": asdict(self.cfg), "main_latency_s": self.main_lat, "placebo_shift": self.placebo_shift,
                "pairs": [{k: v for k, v in p.items() if k not in ("b", "h")} for p in self.pairs], "summary": self.summary()}
        with open(os.path.join(run_dir, "xv_map.json"), "w") as f:
            json.dump(info, f, indent=1, default=float)
