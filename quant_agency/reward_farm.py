"""Phase 15, candidate R: paper-farm Polymarket liquidity rewards from complete sets, net of adverse selection.

Per selected market (rules fixed in ``docs/PREREG_P15R.json`` before the live session):
  * split N USDC into N YES + N NO (no fee, exactly 1 USDC per pair; N = the market's reward minimum size);
  * rest an ask of N YES at max(ceil(mid + 0.5 c), best YES ask) and an ask of N NO at the same rule on the NO book; re-place (back of the
    queue, after a 1 s latency) when the order drifts more than half the reward spread from the target;
  * a resting ask fills only when real trades consume the displayed size ahead of it at its price, or trade through it (the "trades"
    queue model of phases 5-12; size cancelled ahead of us shortens the queue);
  * after a fill the market stops quoting: the remaining outcome is held to the end of the session and marked at its best *bid*
    (liquidation value); unfilled pairs merge back into exactly 1 USDC each;
  * rewards: once per minute at a random second, the market's Q_min for our resting orders and for the whole visible book are computed
    with the published scoring function (``reward_share``); accrual = rate_per_day / 1440 x ours / (ours + book).
Equity per market = cash from fills + pairs x 1 + held outcome x best bid + accrued rewards - N (the USDC put in).
Paper only: nothing is signed or sent.
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import random
import time
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional

from . import reward_share as rs
from .polymarket_watcher import WS_URL, PmBooks, handle_clob_message


@dataclass
class Ask:
    token: str
    price: float
    size: float
    t_live: float                 # becomes live (placement latency)
    ahead: float = float("nan")   # displayed size ahead of us at our price when we went live
    filled: float = 0.0


@dataclass
class Farm:
    cid: str
    question: str
    yes: str
    no: str
    n: float                      # pairs split
    v: float                      # reward max spread, cents
    min_size: float
    rate: float                   # USD per day
    end_date: str
    asks: Dict[str, Ask] = field(default_factory=dict)
    cash: float = 0.0             # USDC received from fills
    held: Dict[str, float] = field(default_factory=dict)   # token -> shares held after the other side sold
    pairs: float = 0.0            # unsold complete pairs
    rewards: float = 0.0
    samples: int = 0
    scored: int = 0
    stopped: bool = False
    fills: List[dict] = field(default_factory=list)

    def equity(self, books: PmBooks, mark: str = "bid") -> float:
        """``bid``: held outcome at its best bid (what selling now fetches; primary); ``mid``: at its midpoint (for reference)."""
        val = self.cash + self.pairs + self.rewards
        for tok, sh in self.held.items():
            px = books.bb.get(tok, 0.0)
            if mark == "mid":
                m = mid_of(books, tok)
                px = m if m is not None else px
            val += sh * px
        return val - self.n


def mid_of(books: PmBooks, tok: str) -> Optional[float]:
    t = books.top(tok)
    return None if t is None else (t[0] + t[1]) / 2.0


def target_price(books: PmBooks, tok: str) -> Optional[float]:
    t = books.top(tok)
    if t is None:
        return None
    return round(max(rs.tick_round_up((t[0] + t[1]) / 2.0 + 0.005), t[1]), 4)


class RewardFarm:
    def __init__(self, farms: List[Farm], out_dir: str, latency_s: float = 1.0, seed: int = 1):
        self.farms = {f.cid: f for f in farms}
        self.by_tok = {}
        for f in farms:
            self.by_tok[f.yes], self.by_tok[f.no] = f, f
            f.pairs = f.n
        self.books = PmBooks()
        self.lat = latency_s
        self.rng = random.Random(seed)
        self.out_dir = out_dir
        os.makedirs(out_dir, exist_ok=True)
        self.log_f = open(os.path.join(out_dir, "farm_log.jsonl"), "a", buffering=1)
        self.next_sample = 0.0
        self.trades = 0
        self.t0 = None

    def log(self, kind: str, **kw) -> None:
        self.log_f.write(json.dumps({"kind": kind, "t": time.time(), **kw}, default=float) + "\n")

    # ------------------------------------------------------------------ quoting
    def requote(self, now: float) -> None:
        for f in self.farms.values():
            if f.stopped:
                continue
            for tok in (f.yes, f.no):
                px = target_price(self.books, tok)
                if px is None or px >= 0.99:
                    f.asks.pop(tok, None)
                    continue
                a = f.asks.get(tok)
                if a is None or abs(a.price - px) > f.v / 200.0:
                    f.asks[tok] = Ask(tok, px, f.n, now + self.lat)

    def _activate(self, a: Ask, now: float) -> None:
        if a.ahead != a.ahead and now >= a.t_live:
            a.ahead = self.books.a.get(a.token, {}).get(a.price, 0.0)      # join behind what is displayed at our price

    # ------------------------------------------------------------------ market events
    def on_top(self, tok: str) -> None:
        f = self.by_tok.get(tok)
        if f is None or tok not in f.asks:
            return
        a = f.asks[tok]
        now = time.time()
        self._activate(a, now)
        if a.ahead == a.ahead:
            lvl = self.books.a.get(tok, {}).get(a.price, 0.0)
            a.ahead = min(a.ahead, lvl)                                      # cancellations ahead of us shorten the queue
            bb = self.books.bb.get(tok, 0.0)
            if bb >= a.price:                                                # a bid now crosses our ask: certainly filled
                self._fill(f, a, a.size - a.filled, a.price, now, "crossed")

    def on_trade(self, tok: str, px: float, sz: float, side: str) -> None:
        self.trades += 1
        f = self.by_tok.get(tok)
        if f is None or tok not in f.asks or f.stopped:
            return
        a = f.asks[tok]
        now = time.time()
        self._activate(a, now)
        if a.ahead != a.ahead or side.upper() != "BUY":
            return
        if px > a.price + 1e-9:
            self._fill(f, a, a.size - a.filled, a.price, now, "through")
        elif abs(px - a.price) < 1e-9:
            if sz > a.ahead:
                self._fill(f, a, min(sz - a.ahead, a.size - a.filled), a.price, now, "queue")
                a.ahead = 0.0
            else:
                a.ahead -= sz

    def _fill(self, f: Farm, a: Ask, q: float, px: float, now: float, how: str) -> None:
        if q <= 0:
            return
        a.filled += q
        f.cash += q * px
        other = f.no if a.token == f.yes else f.yes
        f.pairs -= q
        f.held[other] = f.held.get(other, 0.0) + q
        both = f.yes in f.held and f.no in f.held
        if both:                                                             # each side sold once: held YES and NO re-form pairs
            k = min(f.held[f.yes], f.held[f.no])
            f.held[f.yes] -= k
            f.held[f.no] -= k
            f.pairs += k
        f.fills.append({"t": now, "token": a.token, "px": px, "q": q, "how": how})
        self.log("fill", cid=f.cid, q=f.question, token=a.token, px=px, size=q, how=how)
        f.stopped = True                                                     # stand down after the first fill (pre-registered)
        f.asks.clear()

    # ------------------------------------------------------------------ reward sampling
    def sample(self, now: float) -> None:
        for f in self.farms.values():
            f.samples += 1
            ay, an = f.asks.get(f.yes), f.asks.get(f.no)
            if f.stopped or ay is None or an is None or now < max(ay.t_live, an.t_live):
                continue
            m = mid_of(self.books, f.yes)
            if m is None:
                continue
            yb = {"bids": [{"price": p, "size": s} for p, s in self.books.b.get(f.yes, {}).items()],
                  "asks": [{"price": p, "size": s} for p, s in self.books.a.get(f.yes, {}).items()]}
            nb = {"bids": [{"price": p, "size": s} for p, s in self.books.b.get(f.no, {}).items()],
                  "asks": [{"price": p, "size": s} for p, s in self.books.a.get(f.no, {}).items()]}
            qo, qt = rs.book_q(yb, nb, m, f.v, f.min_size)
            theirs = rs.q_min(qo, qt, m)
            sy = rs.score((ay.price - m) * 100.0, f.v) * ay.size
            sn = rs.score((an.price - (1 - m)) * 100.0, f.v) * an.size
            ours = rs.q_min(sn, sy, m)                                       # Q_one gets the NO ask, Q_two the YES ask
            if ours <= 0:
                continue
            f.scored += 1
            f.rewards += f.rate / 1440.0 * ours / (ours + theirs)

    def summary(self) -> dict:
        rows = []
        for f in self.farms.values():
            rows.append({"cid": f.cid, "question": f.question, "n": f.n, "rate": f.rate, "rewards": round(f.rewards, 4), "equity": round(f.equity(self.books), 4),
                         "markout": round(f.equity(self.books) - f.rewards, 4), "equity_mid": round(f.equity(self.books, "mid"), 4), "fills": f.fills, "samples": f.samples, "scored": f.scored, "end_date": f.end_date})
        return {"t0": self.t0, "t1": time.time(), "trades_seen": self.trades, "markets": rows,
                "total_equity": round(sum(r["equity"] for r in rows), 4), "total_rewards": round(sum(r["rewards"] for r in rows), 4),
                "capital": sum(r["n"] for r in rows)}


def select(markets: List[dict], books: Dict[str, dict], max_min_size: float, min_hours: float, k: int) -> List[Farm]:
    """Pre-registered selection: reward markets ending > ``min_hours`` from now, mid in [0.10, 0.90], min size <= ``max_min_size``,
    ranked by estimated reward per USD per day (snapshot), one market per event, top ``k``."""
    import datetime as dt
    now = dt.datetime.now(dt.timezone.utc)
    cands, seen_ev = [], set()
    for m in markets:
        try:
            end = dt.datetime.fromisoformat(str(m.get("end_date", "")).replace(" ", "T").replace("+00", "+00:00"))
        except ValueError:
            continue
        if (end - now).total_seconds() < min_hours * 3600 or float(m["rewards_min_size"]) > max_min_size:
            continue
        e = rs.estimate(m, float(m["rewards_min_size"]), books)
        if e is None or not (0.10 <= e["mid"] <= 0.90):
            continue
        cands.append((e["ret_per_day"], m, e))
    cands.sort(key=lambda x: -x[0])
    out = []
    for _, m, e in cands:
        ev = m.get("event_id") or m["condition_id"]
        if ev in seen_ev:
            continue
        seen_ev.add(ev)
        out.append(Farm(m["condition_id"], m["question"][:90], e["tokens"]["yes"], e["tokens"]["no"], float(m["rewards_min_size"]), float(m["rewards_max_spread"]),
                        float(m["rewards_min_size"]), e["rate"], str(m.get("end_date"))))
        if len(out) >= k:
            break
    return out


async def run(duration_s: float, out_dir: str, k: int, max_min_size: float, min_hours: float) -> dict:
    import aiohttp
    import orjson
    markets = await asyncio.to_thread(rs.reward_markets, 4)
    books0 = await asyncio.to_thread(rs.fetch_books, [t["token_id"] for m in markets for t in m["tokens"]])
    farms = select(markets, books0, max_min_size, min_hours, k)
    eng = RewardFarm(farms, out_dir)
    eng.t0 = time.time()
    eng.log("start", markets=[asdict(f) for f in farms])
    print(f"farming {len(farms)} markets, capital {sum(f.n for f in farms):.0f} USD", flush=True)
    toks = [t for f in farms for t in (f.yes, f.no)]
    t_end = time.time() + duration_s
    eng.next_sample = time.time() + eng.rng.uniform(0, 60)
    last_print = 0.0
    async with aiohttp.ClientSession() as s:
        while time.time() < t_end:
            try:
                async with s.ws_connect(WS_URL, heartbeat=20) as ws:
                    await ws.send_str(orjson.dumps({"assets_ids": toks, "type": "market"}).decode())
                    while time.time() < t_end:
                        try:
                            msg = await ws.receive(timeout=5)
                        except asyncio.TimeoutError:
                            msg = None
                        if msg is not None and msg.type == aiohttp.WSMsgType.TEXT and msg.data not in ("PONG", "pong"):
                            try:
                                handle_clob_message(orjson.loads(msg.data), eng.books, eng.on_top, eng.on_trade)
                            except ValueError:
                                pass
                        elif msg is not None and msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                            break
                        now = time.time()
                        eng.requote(now)
                        if now >= eng.next_sample:
                            eng.sample(now)
                            eng.next_sample = (math.floor(now / 60.0) + 1) * 60.0 + eng.rng.uniform(0, 60)
                        if now - last_print > 300:
                            last_print = now
                            sm = eng.summary()
                            print(f"[{time.strftime('%H:%M:%S')}] rewards={sm['total_rewards']:.3f} equity={sm['total_equity']:+.3f} fills={sum(len(r['fills']) for r in sm['markets'])} trades_seen={sm['trades_seen']}", flush=True)
                            json.dump(sm, open(os.path.join(out_dir, "farm_summary.json"), "w"), indent=1, default=float)
            except Exception as e:
                eng.log("error", err=repr(e)[:200])
                await asyncio.sleep(2)
    sm = eng.summary()
    json.dump(sm, open(os.path.join(out_dir, "farm_summary.json"), "w"), indent=1, default=float)
    return sm


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--duration", type=float, default=3 * 3600)
    p.add_argument("--k", type=int, default=30)
    p.add_argument("--max-min-size", type=float, default=50.0)
    p.add_argument("--min-hours", type=float, default=48.0)
    p.add_argument("--out", default="runs/p15/farm")
    a = p.parse_args(argv)
    out = os.path.join(a.out, time.strftime("%Y%m%d_%H%M%S"))
    sm = asyncio.run(run(a.duration, out, a.k, a.max_min_size, a.min_hours))
    print(json.dumps({k: sm[k] for k in ("total_rewards", "total_equity", "capital")}))
    print("artifacts:", out)


if __name__ == "__main__":
    main()
