"""Reward-farm sleeve under the Omega CFO/CEO governance (``omega_governance``): paper only.

``RewardFarm`` (the pre-registered engine, unchanged) is wrapped in a ``SleeveBook`` named ``reward_farm``:
  * the sleeve's equity (bid-marked farm equity minus on-chain gas for the split and the merge of every market) is recorded every review;
  * a rolling-hour drawdown >= ``hourly_dd_usd`` quarantines the sleeve: every resting ask is withdrawn, held outcomes are kept and
    marked, quoting resumes at probation after the cool-down; the account kill (-20 USD) and the kill file halt it for good;
  * gas: a Polygon split and a merge cost ``gas_usd`` each per market (default 0.05 USD, conservative for Polygon PoS).
    Order placement and cancels on the Polymarket CLOB are off-chain and free.

    python -m quant_agency.reward_sleeve --duration 86400 --bankroll 100
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import time
from typing import List, Optional

from . import reward_farm as rf
from . import reward_share as rs
from .omega_governance import GovConfig, OmegaCEO, OState


class GovernedFarm:
    def __init__(self, farm: rf.RewardFarm, capital: float, gas_usd: float = 0.05, gov: Optional[GovConfig] = None):
        self.farm = farm
        self.gas = gas_usd * 2 * len(farm.farms)
        cfg = gov or GovConfig(bankroll=capital, alloc={"reward_farm": capital}, kill_file="runs/p15/KILL")
        self.ceo = OmegaCEO(cfg)
        self.book = self.ceo.books["reward_farm"]
        self.book.open(0, capital, 0.0)                                     # the split capital is one open "position"
        self.events: List[dict] = []

    def equity_change(self) -> float:
        return sum(f.equity(self.farm.books) for f in self.farm.farms.values()) - self.gas

    def review(self, now: float) -> None:
        self.book.mark(0, self.book.open_cost[0] + self.equity_change())
        for ev in self.ceo.review(now):
            self.events.append(ev.as_dict())
            self.farm.log("gov", **{("gov_kind" if k == "kind" else k): v for k, v in ev.as_dict().items()})
        if self.ceo.halted or self.book.state in (OState.QUARANTINED, OState.HALTED):
            for f in self.farm.farms.values():                              # withdraw every resting ask; positions stay
                f.asks.clear()
        self.ceo.to_flatten.clear()

    def quoting_allowed(self) -> bool:
        return not self.ceo.halted and self.book.state in (OState.NORMAL, OState.PROBATION)


async def run(duration_s: float, bankroll: float, out_dir: str, min_hours: float = 48.0, max_min_size: float = 50.0) -> dict:
    markets = await asyncio.to_thread(rs.reward_markets, 4)
    books0 = await asyncio.to_thread(rs.fetch_books, [t["token_id"] for m in markets for t in m["tokens"]])
    farms, cap = [], 0.0
    for f in rf.select(markets, books0, max_min_size, min_hours, 200):
        if cap + f.n <= bankroll:
            farms.append(f)
            cap += f.n
    eng = rf.RewardFarm(farms, out_dir)
    gov = GovernedFarm(eng, cap)
    orig = eng.requote

    def requote(now):                                                       # quoting only while governance allows it
        if gov.quoting_allowed():
            orig(now)
    eng.requote = requote
    task = asyncio.create_task(_drive(eng, duration_s, out_dir))
    t_end = time.time() + duration_s
    while time.time() < t_end and not task.done():
        gov.review(time.time())
        await asyncio.sleep(5)
    sm = await task
    sm["governance"] = {"events": gov.events, "gas_usd": gov.gas, "state": gov.book.state.value, "net_after_gas": round(gov.equity_change(), 4)}
    json.dump(sm, open(os.path.join(out_dir, "farm_summary.json"), "w"), indent=1, default=float)
    return sm


async def _drive(eng: rf.RewardFarm, duration_s: float, out_dir: str) -> dict:
    import aiohttp
    import orjson
    eng.t0 = time.time()
    eng.log("start", markets=[{"cid": f.cid, "question": f.question, "n": f.n, "rate": f.rate} for f in eng.farms.values()])
    toks = [t for f in eng.farms.values() for t in (f.yes, f.no)]
    t_end = time.time() + duration_s
    eng.next_sample = time.time() + eng.rng.uniform(0, 60)
    async with aiohttp.ClientSession() as s:
        while time.time() < t_end:
            try:
                async with s.ws_connect(rf.WS_URL, heartbeat=20) as ws:
                    await ws.send_str(orjson.dumps({"assets_ids": toks, "type": "market"}).decode())
                    while time.time() < t_end:
                        try:
                            msg = await ws.receive(timeout=5)
                        except asyncio.TimeoutError:
                            msg = None
                        if msg is not None and msg.type == aiohttp.WSMsgType.TEXT and msg.data not in ("PONG", "pong"):
                            try:
                                rf.handle_clob_message(orjson.loads(msg.data), eng.books, eng.on_top, eng.on_trade)
                            except ValueError:
                                pass
                        elif msg is not None and msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                            break
                        now = time.time()
                        eng.requote(now)
                        if now >= eng.next_sample:
                            eng.sample(now)
                            eng.next_sample = (math.floor(now / 60.0) + 1) * 60.0 + eng.rng.uniform(0, 60)
            except Exception as e:
                eng.log("error", err=repr(e)[:200])
                await asyncio.sleep(2)
    return eng.summary()


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--duration", type=float, default=86400.0)
    p.add_argument("--bankroll", type=float, default=100.0)
    p.add_argument("--out", default="runs/p15/sleeve")
    a = p.parse_args(argv)
    out = os.path.join(a.out, time.strftime("%Y%m%d_%H%M%S"))
    sm = asyncio.run(run(a.duration, a.bankroll, out))
    print(json.dumps({"rewards": sm["total_rewards"], "equity_bid": sm["total_equity"], "governance": sm["governance"]}, default=float))
    print("artifacts:", out)


if __name__ == "__main__":
    main()
