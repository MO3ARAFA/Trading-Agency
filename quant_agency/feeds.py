"""Live market-data feeds (asyncio + uvloop + orjson).

* Binance via ``wss://data-stream.binance.vision`` (market-data-only host, reachable where api.binance.com is
  geo-blocked): ONE combined connection carries BTCUSDT bookTicker+aggTrade and every alt bookTicker, so the
  relative arrival order of BTC and alt updates is exactly the venue's publication order (no inter-connection skew).
* Cross-venue BBO: Gate ``spot.book_ticker`` and Kraken v2 ``ticker`` (event_trigger=bbo).

Every message is timestamped with ``perf_counter`` the instant it leaves the socket.
"""
from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

import orjson
from websockets.asyncio.client import connect

from .agency import Agency


@dataclass
class FeedStats:
    name: str
    msgs: int = 0
    quotes: int = 0
    errors: int = 0
    reconnects: int = 0
    connected: bool = False
    last_msg: float = 0.0
    last_error: str = ""
    ws: object = None
    t_connect: float = 0.0


class FeedManager:
    BINANCE_WS = "wss://data-stream.binance.vision/stream?streams="

    def __init__(self, agency: Agency, perf=time.perf_counter):
        self.a = agency
        self.perf = perf
        self.stop = asyncio.Event()
        self.stats: Dict[str, FeedStats] = {}

    # ---------------------------------------------------------------- generic reconnecting runner
    async def _run(self, name: str, url: str, on_open: Callable, handler: Callable, idxs: Optional[List[int]]):
        st = self.stats.setdefault(name, FeedStats(name))
        backoff = 0.5
        while not self.stop.is_set():
            try:
                async with connect(url, open_timeout=15, max_size=2 ** 22, compression=None,
                                   ping_interval=20, ping_timeout=20) as ws:
                    st.ws, st.connected = ws, True
                    st.t_connect = self.perf()
                    st.last_msg = st.t_connect
                    if st.reconnects:
                        self.a.on_feed_reset(self.perf(), idxs)
                    await on_open(ws)
                    backoff = 0.5
                    await handler(ws, st)
            except asyncio.CancelledError:
                raise
            except Exception as e:                              # network error: reconnect with jittered backoff
                st.errors += 1
                st.last_error = f"{type(e).__name__}: {str(e)[:120]}"
            finally:
                st.connected, st.ws = False, None
            if self.stop.is_set():
                break
            st.reconnects += 1
            await asyncio.sleep(backoff * (0.5 + random.random()))
            backoff = min(backoff * 2, 15.0)

    async def _watchdog(self, max_silence: float = 12.0):
        while not self.stop.is_set():
            await asyncio.sleep(2.0)
            now = self.perf()
            for st in self.stats.values():
                if st.connected and st.ws is not None and now - st.last_msg > max_silence:
                    try:
                        await st.ws.close()
                    except Exception:
                        pass

    # ---------------------------------------------------------------- Binance
    async def binance(self):
        a, book = self.a, self.a.book
        syms = [m.symbol for m in book.metas if m.venue == "binance"]
        streams = [f"{s.lower()}@bookTicker" for s in syms] + ["btcusdt@aggTrade"]
        idx = {m.symbol: i for i, m in enumerate(book.metas) if m.venue == "binance"}
        idxs = list(idx.values())
        perf, loads = self.perf, orjson.loads
        on_quote, scan, on_trade = a.on_quote, a.scan, a.on_trade

        async def noop(ws):
            return None

        async def handler(ws, st: FeedStats):
            async for raw in ws:
                t = perf()
                st.msgs += 1
                st.last_msg = t
                d = loads(raw)["data"]
                if "e" in d:                                    # aggTrade (BTC only)
                    on_trade(t, float(d["p"]), float(d["q"]), d["m"])
                    continue
                i = idx.get(d["s"])
                if i is None:
                    continue
                st.quotes += 1
                on_quote(i, t, float(d["b"]), float(d["a"]), float(d["B"]), float(d["A"]))
                if i == 0:
                    scan(t)

        await self._run("binance", self.BINANCE_WS + "/".join(streams), noop, handler, idxs)

    # ---------------------------------------------------------------- Gate
    async def gate(self):
        a, book = self.a, self.a.book
        idx = {m.symbol: i for i, m in enumerate(book.metas) if m.venue == "gate"}
        if not idx:
            return
        perf, loads, on_quote = self.perf, orjson.loads, a.on_quote

        async def on_open(ws):
            await ws.send(orjson.dumps({"time": int(time.time()), "channel": "spot.book_ticker", "event": "subscribe",
                                        "payload": list(idx)}).decode())

        async def handler(ws, st):
            async for raw in ws:
                t = perf()
                st.msgs += 1
                st.last_msg = t
                m = loads(raw)
                if m.get("event") != "update":
                    continue
                r = m["result"]
                i = idx.get(r["s"])
                if i is None:
                    continue
                st.quotes += 1
                on_quote(i, t, float(r["b"]), float(r["a"]), float(r["B"]), float(r["A"]))

        await self._run("gate", "wss://api.gateio.ws/ws/v4/", on_open, handler, list(idx.values()))

    # ---------------------------------------------------------------- Kraken
    async def kraken(self):
        a, book = self.a, self.a.book
        idx = {m.symbol: i for i, m in enumerate(book.metas) if m.venue == "kraken"}
        if not idx:
            return
        perf, loads, on_quote = self.perf, orjson.loads, a.on_quote

        async def on_open(ws):
            await ws.send(orjson.dumps({"method": "subscribe", "params": {"channel": "ticker", "symbol": list(idx),
                                                                          "event_trigger": "bbo"}}).decode())

        async def handler(ws, st):
            async for raw in ws:
                t = perf()
                st.msgs += 1
                st.last_msg = t
                m = loads(raw)
                if m.get("channel") != "ticker" or not m.get("data"):
                    continue
                for r in m["data"]:
                    i = idx.get(r["symbol"])
                    if i is None:
                        continue
                    st.quotes += 1
                    on_quote(i, t, float(r["bid"]), float(r["ask"]), float(r["bid_qty"]), float(r["ask_qty"]))

        await self._run("kraken", "wss://ws.kraken.com/v2", on_open, handler, list(idx.values()))

    def tasks(self) -> List[asyncio.Task]:
        ts = [asyncio.create_task(self.binance(), name="feed-binance"),
              asyncio.create_task(self.gate(), name="feed-gate"),
              asyncio.create_task(self.kraken(), name="feed-kraken"),
              asyncio.create_task(self._watchdog(), name="feed-watchdog")]
        return ts
