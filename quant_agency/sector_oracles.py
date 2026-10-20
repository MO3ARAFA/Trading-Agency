"""Secondary (sector) oracles: lead-lag beyond BTC.

BTC is the oracle for the whole market. This module adds *sector leaders* - SOL for the Solana ecosystem, PEPE (and DOGE) for
memecoins, RENDER (and TAO) for AI/compute - each with its **own** ``BtcOracle`` ring buffers (1/3/5/10 s impulse returns, EW
variances, micro-price) fed from that leader's Binance top of book, and its **own** ``InefficiencyHunter`` whose members are the
ecosystem's altcoins on Binance, Gate, Kraken and Hyperliquid. Everything shares ONE ``MarketBook`` (so one set of rings and one
tick clock) and every hunter reports into the same markout machinery, tagged with the oracle that produced the signal.

    Net Gap = |Fair Return(delta sector leader)| - (Spread + Fee Tier + Slippage)

is computed per signal with the CFO cost model at a fixed clip size, and the sector hunters scale their gap hurdle with the leader's
own volatility (``Signal.hurdle_bps``). This is a *measurement* layer: sector signals are observed and marked out, never traded.
"""
from __future__ import annotations

import copy
import json
import os
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional, Sequence

import numpy as np

from .btc_oracle import BtcOracle
from .cfo_agent import Decision, MarkoutTracker
from .config import OracleConfig
from .inefficiency_hunter import InefficiencyHunter, Signal
from .market_watchers import (SECTOR_DEFS, MarketBook, MarketMeta, SectorDef, leader_index, sector_assets, sector_members)
from .venues import VENUE_MAKER_BPS, VENUE_TAKER_BPS

BPS = 1e4


@dataclass
class SectorConfig:
    sectors: Sequence[str] = ("sol", "pepe", "render", "doge", "tao")
    gap_vol_mult: float = 0.5              # sector hurdle = max(min_gap, mult * beta * sigma_leader(h)); the BTC baseline keeps 0
    max_spread_bps: float = 40.0           # hunter spread gate for ALL hunters in a sector run (spreads are recorded, not hidden)
    wide_ratio: float = 3.0                # quote-validation gate: fast EW spread <= wide_ratio x slow EW spread
    observe_notional_usd: float = 1000.0   # clip size used for the slippage term of the net gap
    id_stride: int = 10_000_000            # signal / impulse id offset per hunter (globally unique clusters)
    latencies_s: Sequence[float] = (0.0, 0.15, 0.5)
    oracle_tick_cap: int = 65536
    oracle_gap_s: float = 8.0              # a thin leader being quiet for >1.5 s is not a feed outage (BTC keeps 1.5)
    min_gap_bps: float = 1.0
    sig_keep: int = 20000


def sector_oracle_config(sc: SectorConfig) -> OracleConfig:
    oc = OracleConfig()
    oc.tick_cap = sc.oracle_tick_cap
    oc.gap_s = sc.oracle_gap_s
    return oc


# ================================================================================ discovery
@dataclass
class SectorUniverse:
    metas: List[MarketMeta]
    sectors: List[dict]
    dropped: Dict[str, Dict[str, str]]       # asset -> {venue: reason}
    counts: Dict[str, int]

    def as_dict(self) -> dict:
        return {"sectors": self.sectors, "dropped": self.dropped, "counts": self.counts, "markets": [m.id for m in self.metas]}


def _bs(x: dict) -> float:
    try:
        b, a = float(x["bidPrice"]), float(x["askPrice"])
    except (KeyError, TypeError, ValueError):
        return 1e9
    return (a - b) / ((a + b) / 2) * BPS if b > 0 and a >= b else 1e9


def build_universe(data: dict, defs: Sequence[SectorDef] = SECTOR_DEFS, min_quote_vol: float = 250_000.0, admit_spread_bps: float = 40.0,
                   gate_min_vol: float = 100_000.0, venues: Sequence[str] = ("binance", "gate", "kraken", "hyperliquid")) -> SectorUniverse:
    """Pure builder. ``data`` carries the raw REST payloads: b24, bbook, binfo (Binance), gate_pairs, gate_tickers,
    kraken_pairs, hl_meta. Every refusal is recorded in ``dropped`` so the report can state exactly what was left out and why."""
    b24 = {x["symbol"]: x for x in data.get("b24", [])}
    bbook = {x["symbol"]: x for x in data.get("bbook", [])}
    binfo = {s["symbol"]: s for s in data.get("binfo", {}).get("symbols", [])}
    gpairs = {x["id"]: x for x in data.get("gate_pairs", [])}
    gtick = {x.get("currency_pair"): x for x in data.get("gate_tickers", [])}
    kpairs = {v.get("wsname"): v for v in (data.get("kraken_pairs", {}) or {}).values() if v.get("wsname")}
    hl_names = {u["name"] for u in (data.get("hl_meta", {}) or {}).get("universe", []) if not u.get("isDelisted")}
    leaders = {d.leader for d in defs}
    assets = sector_assets(defs)
    dropped: Dict[str, Dict[str, str]] = defaultdict(dict)

    metas: List[MarketMeta] = [MarketMeta("BTCUSDT", "binance", "BTCUSDT", "BTC", tick=0.01, step=1e-5, min_notional=5.0, asset="BTC",
                                          fee_taker_bps=VENUE_TAKER_BPS["binance"], fee_maker_bps=VENUE_MAKER_BPS["binance"])]
    order = sorted(assets, key=lambda a: (a not in leaders, assets.index(a)))        # leaders first (stable indices), then baskets
    for a in order:
        sym = f"{a}USDT"
        if "binance" in venues:
            x = b24.get(sym)
            inf = binfo.get(sym)
            if x is None or inf is None or inf.get("status", "TRADING") != "TRADING":
                dropped[a]["binance"] = "not listed / not trading"
            elif float(x["quoteVolume"]) < min_quote_vol and a not in leaders:
                dropped[a]["binance"] = f"24h volume ${float(x['quoteVolume']) / 1e6:.2f}M < ${min_quote_vol / 1e6:g}M"
            elif _bs(bbook.get(sym, {})) > admit_spread_bps and a not in leaders:
                dropped[a]["binance"] = f"spread {_bs(bbook.get(sym, {})):.1f} bps > {admit_spread_bps:g}"
            else:
                f = {y["filterType"]: y for y in inf["filters"]}
                metas.append(MarketMeta(id=sym, venue="binance", symbol=sym, base=a, asset=a, kind="spot", quote="USDT",
                                        tick=float(f.get("PRICE_FILTER", {}).get("tickSize", 0) or 0), step=float(f.get("LOT_SIZE", {}).get("stepSize", 0) or 0),
                                        min_notional=float((f.get("NOTIONAL") or f.get("MIN_NOTIONAL") or {}).get("minNotional", 5) or 5),
                                        quote_vol_usd=float(x["quoteVolume"]), fee_taker_bps=VENUE_TAKER_BPS["binance"],
                                        fee_maker_bps=VENUE_MAKER_BPS["binance"]))
    for a in order:
        if "gate" in venues:
            gid = f"{a}_USDT"
            gp = gpairs.get(gid)
            gv = float((gtick.get(gid) or {}).get("quote_volume") or 0.0)
            if gp is None or gp.get("trade_status") != "tradable":
                dropped[a]["gate"] = "not listed / not tradable"
            elif gv < gate_min_vol:
                dropped[a]["gate"] = f"24h volume ${gv / 1e3:.0f}k < ${gate_min_vol / 1e3:g}k"
            else:
                metas.append(MarketMeta(id=f"gate:{gid}", venue="gate", symbol=gid, base=a, asset=a, kind="spot", quote="USDT", quote_vol_usd=gv,
                                        fee_taker_bps=VENUE_TAKER_BPS["gate"], fee_maker_bps=VENUE_MAKER_BPS["gate"]))
        if "kraken" in venues:
            ws = f"{a}/USD"
            kp = kpairs.get(ws)
            if kp is None or kp.get("status", "online") != "online":
                dropped[a]["kraken"] = "not listed / offline"
            else:
                metas.append(MarketMeta(id=f"kraken:{ws}", venue="kraken", symbol=ws, base=a, asset=a, kind="spot", quote="USD",
                                        fee_taker_bps=VENUE_TAKER_BPS["kraken"], fee_maker_bps=VENUE_MAKER_BPS["kraken"]))
        if "hyperliquid" in venues:
            coin = a if a in hl_names else (f"k{a}" if f"k{a}" in hl_names else None)
            if coin is None:
                dropped[a]["hyperliquid"] = "no perp"
            else:
                metas.append(MarketMeta(id=f"hyperliquid:{coin}", venue="hyperliquid", symbol=coin, base=a, asset=a, kind="perp", quote="USDC",
                                        fee_taker_bps=VENUE_TAKER_BPS["hyperliquid"], fee_maker_bps=VENUE_MAKER_BPS["hyperliquid"],
                                        extra={"unit_mult": 1000 if coin != a else 1}))
    have = {m.id for m in metas}
    ok_leaders = {d.name for d in defs if d.leader in {m.asset for m in metas if m.venue == "binance"}}
    sectors = []
    for d in defs:
        if d.name not in ok_leaders:
            dropped.setdefault(d.leader, {})["sector"] = "leader unavailable: sector skipped"
            continue
        mem = [m.id for m in metas if (m.asset in d.group) and not (m.venue == "binance" and m.asset == d.leader)]
        sectors.append({"name": d.name, "leader": d.leader, "label": d.label, "variant_of": d.variant_of, "leader_id": f"{d.leader}USDT",
                        "group": list(d.group), "members": mem})
    counts: Dict[str, int] = defaultdict(int)
    for m in metas:
        counts[m.venue] += 1
    return SectorUniverse(metas, sectors, {k: dict(v) for k, v in dropped.items()}, dict(counts))


async def fetch_sector_data(session, rest_base: str = "https://data-api.binance.vision") -> dict:
    """Raw REST payloads for ``build_universe`` (public endpoints, no credentials)."""
    import orjson

    async def get(url, **kw):
        async with session.get(url, **kw) as r:
            return orjson.loads(await r.read())

    d: dict = {}
    d["b24"] = await get(f"{rest_base}/api/v3/ticker/24hr")
    d["bbook"] = await get(f"{rest_base}/api/v3/ticker/bookTicker")
    syms = [f"{a}USDT" for a in sector_assets()] + ["BTCUSDT"]
    # exchangeInfo rejects the whole request if one symbol is unknown, so ask only for symbols that exist
    listed = {x["symbol"] for x in d["b24"]}
    ask = [s for s in syms if s in listed]
    d["binfo"] = await get(f"{rest_base}/api/v3/exchangeInfo", params={"symbols": json.dumps(ask, separators=(",", ":"))})
    for key, url in (("gate_pairs", "https://api.gateio.ws/api/v4/spot/currency_pairs"), ("gate_tickers", "https://api.gateio.ws/api/v4/spot/tickers")):
        try:
            d[key] = await get(url)
        except Exception:
            d[key] = []
    try:
        d["kraken_pairs"] = (await get("https://api.kraken.com/0/public/AssetPairs")).get("result", {})
    except Exception:
        d["kraken_pairs"] = {}
    try:
        async with session.post("https://api.hyperliquid.xyz/info", json={"type": "meta"}) as r:
            d["hl_meta"] = orjson.loads(await r.read())
    except Exception:
        d["hl_meta"] = {}
    return d


async def discover_sector_universe(session=None, defs: Sequence[SectorDef] = SECTOR_DEFS, **kw) -> SectorUniverse:
    import aiohttp

    own = session is None
    session = session or aiohttp.ClientSession(trust_env=True, timeout=aiohttp.ClientTimeout(total=40), headers={"User-Agent": "Mozilla/5.0"})
    try:
        return build_universe(await fetch_sector_data(session), defs, **kw)
    finally:
        if own:
            await session.close()


# ================================================================================ runtime wiring
class SectorOracle:
    """One leader: its oracle, its hunter, its members."""

    def __init__(self, book: MarketBook, sd: SectorDef, k: int, sc: SectorConfig, hcfg, cost_model):
        self.sd = sd
        self.leader_idx = leader_index(book, sd)
        self.members = sector_members(book, sd)
        self.oracle = BtcOracle(sector_oracle_config(sc))
        hc = copy.deepcopy(hcfg)
        hc.max_spread_bps = sc.max_spread_bps
        hc.min_gap_bps = sc.min_gap_bps
        self.hunter = InefficiencyHunter(book, self.oracle, hc, name=sd.name, members=self.members, id_base=(k + 1) * sc.id_stride,
                                         gap_vol_mult=sc.gap_vol_mult, wide_ratio=sc.wide_ratio, cost_model=cost_model)


class SectorHub:
    """All secondary oracles of an Agency + the observe-only sink for every hunter's signals (BTC baseline included)."""

    def __init__(self, ag, sc: Optional[SectorConfig] = None, defs: Sequence[SectorDef] = SECTOR_DEFS):
        self.ag = ag
        self.sc = sc or SectorConfig()
        cfo = ag.cfo

        def cost_model(sig: Signal):
            px = sig.ask if sig.side > 0 else sig.bid
            return cfo.costs(sig, self.sc.observe_notional_usd / px, "taker")

        self.cost_model = cost_model
        by_name = {d.name: d for d in defs}
        self.sectors: List[SectorOracle] = []
        self.skipped: Dict[str, str] = {}
        for k, name in enumerate(self.sc.sectors):
            try:
                self.sectors.append(SectorOracle(ag.book, by_name[name], k, self.sc, ag.cfg.hunter, cost_model))
            except KeyError as e:
                self.skipped[name] = str(e)
        self.by_leader: Dict[int, List[SectorOracle]] = defaultdict(list)
        for so in self.sectors:
            self.by_leader[so.leader_idx].append(so)
        self.scan_idx = set(self.by_leader)
        # the BTC baseline hunter sees the same markets under the same validation gates and the same cost model
        ag.hunter.cfg.max_spread_bps = self.sc.max_spread_bps
        ag.hunter.wide_ratio = self.sc.wide_ratio
        ag.hunter.cost_model = cost_model
        cfg = ag.cfg.cfo
        self.trackers = {lat: MarkoutTracker(ag.book, cfg.markout_horizons_s, lat, cfg.fee_taker_bps) for lat in self.sc.latencies_s}
        for tr in self.trackers.values():
            tr.max_rows = 2_000_000
        self.main_lat = min(self.trackers, key=lambda x: abs(x - cfg.latency_s))
        self.n_obs: Dict[str, int] = defaultdict(int)
        self.signals: List[Signal] = []
        self.executors: List[ThreadPoolExecutor] = []
        self.placebo_shift = 0.0

    # ---- wiring
    def hunters(self) -> List[InefficiencyHunter]:
        return [so.hunter for so in self.sectors]

    def use_threads(self) -> None:
        for h in self.hunters():
            ex = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"calib-{h.name}")
            h.executor = ex
            self.executors.append(ex)

    def shutdown(self) -> None:
        for ex in self.executors:
            ex.shutdown(wait=False, cancel_futures=True)

    def on_quote(self, i: int, t: float, bid: float, ask: float, bq: float, aq: float) -> None:
        lst = self.by_leader.get(i)
        if lst:
            for so in lst:
                so.oracle.on_book(t, bid, ask, bq, aq)
                so.hunter.dirty = True

    def any_dirty(self) -> bool:
        return any(so.hunter.dirty for so in self.sectors)

    def scan(self, t: float) -> List[Signal]:
        out: List[Signal] = []
        for so in self.sectors:
            if so.hunter.dirty:
                out += so.hunter.scan(t, t)
        return out

    def reset(self, t: float, idxs, hold_s: float) -> None:
        for so in self.sectors:
            if idxs is None or so.leader_idx in idxs:
                so.oracle.reset_feed(t)
            if idxs is None:
                so.hunter.cooldown_until[:] = np.maximum(so.hunter.cooldown_until, t + hold_s)
            else:
                for i in idxs:
                    so.hunter.cooldown_until[i] = max(so.hunter.cooldown_until[i], t + hold_s)

    # ---- observation sink
    def observe(self, s: Signal, t: float) -> None:
        dec = Decision(approved=False, reason="observe", cohort="observe", net_edge_bps=s.net_gap_bps, net_edge_taker_bps=s.net_gap_bps,
                       gap_credit_bps=abs(s.gap_bps), spread_bps=s.spread_bps)
        for tr in self.trackers.values():
            tr.register(s, dec)
        self.n_obs[s.oracle] += 1
        self.ag._write("sector_signals", s.as_dict())
        self.signals.append(s)
        if len(self.signals) > self.sc.sig_keep:
            del self.signals[: self.sc.sig_keep // 5]

    def poll(self, t: float) -> None:
        for tr in self.trackers.values():
            tr.poll(t)

    # ---- artefacts
    def summary(self) -> dict:
        ag = self.ag
        rows = [("BTC", ag.hunter)] + [(so.sd.name, so.hunter) for so in self.sectors]
        return {name: {"impulses": h.n_impulses, "scans": h.n_scans, "signals": h.n_signals, "net_suppressed": h.n_net_suppressed,
                       "members": int(h.model.hunt.sum()), "calibrated": int(h.model.calibrated.sum()), "calib_errors": h.calib_errors[:3],
                       "gap_vol_mult": h.gap_vol_mult, "id_base": h.id_base} for name, h in rows}

    def models(self) -> dict:
        ag = self.ag
        out = {"BTC": ag.hunter.model.table()}
        for so in self.sectors:
            out[so.sd.name] = so.hunter.model.table()
        return out

    def dump(self, run_dir: str, t_end: float) -> None:
        os.makedirs(run_dir, exist_ok=True)
        ag = self.ag
        with open(os.path.join(run_dir, "sector_markouts.jsonl"), "w") as f:
            for lat, tr in self.trackers.items():
                for r in tr.rows:
                    f.write(json.dumps(r, default=float) + "\n")
        info = {"t_start": ag.t0, "t_end": t_end, "config": asdict(self.sc), "skipped": self.skipped,
                "sectors": [{"name": so.sd.name, "leader": so.sd.leader, "label": so.sd.label, "variant_of": so.sd.variant_of,
                             "group": list(so.sd.group), "leader_idx": so.leader_idx,
                             "members": [ag.book.ids[i] for i in np.where(so.members)[0]]} for so in self.sectors],
                "markets": [{"id": m.id, "venue": m.venue, "asset": m.asset, "kind": m.kind, "fee_taker_bps": m.fee_taker_bps} for m in ag.book.metas],
                "summary": self.summary(), "main_latency_s": self.main_lat, "placebo_shift": self.placebo_shift}
        with open(os.path.join(run_dir, "sector_map.json"), "w") as f:
            json.dump(info, f, indent=1, default=float)
        with open(os.path.join(run_dir, "sector_models.json"), "w") as f:
            json.dump(self.models(), f, indent=1, default=float)
