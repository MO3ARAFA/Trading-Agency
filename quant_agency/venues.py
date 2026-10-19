"""Venue catalogue for Phase 4: cross-venue same-asset markets, assumed fee schedules, Binance scalp universe.

FEES ARE ASSUMPTIONS. They are public *retail* schedules (lowest volume tier) and cannot be verified from public
data for any account; the "zero-fee" Binance list in particular reflects historical promotions and the operator's
brief. Every run prints the assumption and the reports show net markouts at several fee levels (net0 - 2*fee).
"""
from __future__ import annotations

import json
from typing import Dict, List, Optional, Sequence

from .market_watchers import MarketMeta

# per-side taker fee (bps), lowest public retail tier
VENUE_TAKER_BPS: Dict[str, float] = {
    "binance": 7.5,        # VIP0 paying fees in BNB
    "gate": 20.0,          # 0.20 %
    "kraken": 40.0,        # Kraken Pro, lowest tier taker 0.40 %
    "coinbase": 60.0,      # Advanced, lowest tier taker 0.60 %
    "hyperliquid": 4.5,    # perps base tier taker 0.045 %
    "deribit": 5.0,        # perps taker 0.05 %
}
VENUE_MAKER_BPS: Dict[str, float] = {
    "binance": 7.5, "gate": 20.0, "kraken": 25.0, "coinbase": 40.0, "hyperliquid": 1.5, "deribit": 0.0,
}

# Binance symbols the operator brief treats as zero-fee (ASSUMED; promotions change without notice)
ZERO_FEE_SUFFIXES = ("FDUSD",)
ZERO_FEE_SYMBOLS = {"BTCUSDC", "ETHUSDC"}

CROSS_ASSETS = ("BTC", "ETH", "SOL", "XRP", "DOGE", "ADA", "AVAX", "LINK", "LTC")
DERIBIT_ASSETS = ("BTC", "ETH")
TRI_QUOTES = ("USDT", "USDC", "FDUSD")
# stablecoin/cross components needed for synthetic/triangular detection
STABLE_LEGS = ("USDCUSDT", "FDUSDUSDT")
CROSS_PAIRS = ("ETHBTC", "BNBBTC", "SOLBTC", "XRPBTC", "LTCBTC", "ADABTC", "LINKBTC", "DOGEBTC", "AVAXBTC")


def binance_fee_for(symbol: str) -> Optional[float]:
    """Assumed per-side taker fee for a Binance symbol (0 for the brief's zero-fee set, else None -> default)."""
    if symbol in ZERO_FEE_SYMBOLS or symbol.endswith(ZERO_FEE_SUFFIXES):
        return 0.0
    return None


def cross_venue_metas(assets: Sequence[str] = CROSS_ASSETS, venues: Sequence[str] = ("gate", "kraken", "coinbase", "hyperliquid"),
                      deribit_assets: Sequence[str] = DERIBIT_ASSETS) -> List[MarketMeta]:
    out: List[MarketMeta] = []
    for a in assets:
        if "gate" in venues:
            out.append(MarketMeta(id=f"gate:{a}_USDT", venue="gate", symbol=f"{a}_USDT", base=a, asset=a, kind="spot", quote="USDT",
                                  fee_taker_bps=VENUE_TAKER_BPS["gate"], fee_maker_bps=VENUE_MAKER_BPS["gate"]))
        if "kraken" in venues:
            out.append(MarketMeta(id=f"kraken:{a}/USD", venue="kraken", symbol=f"{a}/USD", base=a, asset=a, kind="spot", quote="USD",
                                  fee_taker_bps=VENUE_TAKER_BPS["kraken"], fee_maker_bps=VENUE_MAKER_BPS["kraken"]))
        if "coinbase" in venues:
            out.append(MarketMeta(id=f"coinbase:{a}-USD", venue="coinbase", symbol=f"{a}-USD", base=a, asset=a, kind="spot", quote="USD",
                                  fee_taker_bps=VENUE_TAKER_BPS["coinbase"], fee_maker_bps=VENUE_MAKER_BPS["coinbase"]))
        if "hyperliquid" in venues:
            out.append(MarketMeta(id=f"hyperliquid:{a}", venue="hyperliquid", symbol=a, base=a, asset=a, kind="perp", quote="USDC",
                                  fee_taker_bps=VENUE_TAKER_BPS["hyperliquid"], fee_maker_bps=VENUE_MAKER_BPS["hyperliquid"]))
    if "deribit" in venues or deribit_assets:
        for a in deribit_assets:
            out.append(MarketMeta(id=f"deribit:{a}-PERP", venue="deribit", symbol=f"{a}-PERPETUAL", base=a, asset=a, kind="perp", quote="USD",
                                  fee_taker_bps=VENUE_TAKER_BPS["deribit"], fee_maker_bps=VENUE_MAKER_BPS["deribit"], extra={"size_unit": "usd"}))
    return out


async def discover_scalp_universe(session=None, watch_spread_bps: float = 3.0, min_quote_vol: float = 500_000.0,
                                  rest_base: str = "https://data-api.binance.vision") -> List[MarketMeta]:
    """Binance Vision markets for the < 0.5 bps scalp universe + triangular components.

    Index 0 is BTCUSDT (the oracle). We watch everything with a live spread <= ``watch_spread_bps`` so the report can show
    the gate's effect (the 0.5 bps gate itself is enforced in the CFO as a hard rule; wider signals become gated shadows).
    """
    import aiohttp
    import orjson

    own = session is None
    session = session or aiohttp.ClientSession(trust_env=True, timeout=aiohttp.ClientTimeout(total=30))
    try:
        async with session.get(f"{rest_base}/api/v3/ticker/bookTicker") as r:
            bt = {x["symbol"]: x for x in orjson.loads(await r.read())}
        async with session.get(f"{rest_base}/api/v3/ticker/24hr") as r:
            t24 = {x["symbol"]: x for x in orjson.loads(await r.read())}

        def spread(s):
            x = bt.get(s)
            if not x:
                return 1e9
            b, a = float(x["bidPrice"]), float(x["askPrice"])
            return (a - b) / ((a + b) / 2) * 1e4 if a + b > 0 and b > 0 else 1e9

        cand = ["BTCUSDT"]
        for a in CROSS_ASSETS + ("BNB",):
            for q in TRI_QUOTES:
                s = f"{a}{q}"
                if s != "BTCUSDT" and s in bt and s in t24 and float(t24[s]["quoteVolume"]) >= min_quote_vol and spread(s) <= watch_spread_bps:
                    cand.append(s)
        comps = [s for s in CROSS_PAIRS if s in bt and float(t24[s]["quoteVolume"]) * 80000 >= min_quote_vol] + [s for s in STABLE_LEGS if s in bt]
        syms = cand + [c for c in comps if c not in cand]
        async with session.get(f"{rest_base}/api/v3/exchangeInfo", params={"symbols": json.dumps(syms, separators=(",", ":"))}) as r:
            info = orjson.loads(await r.read())
        meta: Dict[str, MarketMeta] = {}
        for s in info["symbols"]:
            f = {x["filterType"]: x for x in s["filters"]}
            tick = float(f.get("PRICE_FILTER", {}).get("tickSize", 0) or 0)
            step = float(f.get("LOT_SIZE", {}).get("stepSize", 0) or 0)
            mn = float((f.get("NOTIONAL") or f.get("MIN_NOTIONAL") or {}).get("minNotional", 5) or 5)
            sym = s["symbol"]
            is_comp = sym in comps and sym not in cand
            meta[sym] = MarketMeta(id=sym, venue="binance", symbol=sym, base=s["baseAsset"], tick=tick, step=step, min_notional=mn,
                                   quote_vol_usd=float(t24[sym]["quoteVolume"]), asset=s["baseAsset"], kind="spot", quote=s["quoteAsset"],
                                   fee_taker_bps=binance_fee_for(sym), fee_maker_bps=binance_fee_for(sym),
                                   tradable=not is_comp, hunt=not is_comp)
        return [meta[s] for s in syms if s in meta]
    finally:
        if own:
            await session.close()
