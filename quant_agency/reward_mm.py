"""Phase 15, candidate R3: toxicity-gated passive bid pairs on zero-fee rewarded Polymarket markets, with zero-fee merge. Paper only.

Per market (rules frozen in docs/PREREG_P15R3.json before the live session):
  * universe: rewarded binary markets with fee rate 0 (Gamma feeSchedule), mid in [0.15, 0.85], reward min size <= 50, end > 72 h away,
    no breaking-news keywords in the question, and a mid that did not move during a 5-minute warm-up; one market per event;
  * quotes: a YES bid at mid - d and a NO bid at (1 - mid) - d, d = max(1 c, the current half spread rounded up to the tick) and inside
    the reward spread; size = reward min size; the two bids cost <= 0.98 per pair;
  * toxicity gate: a bid is pulled (1 s cancel latency, fills inside it count) when the top-of-book imbalance against it exceeds 0.65
    (OBI = (bid size - ask size) / sum on its own token, against = OBI < -0.65) or >= 3 sell trades hit its token within 10 s; it is
    re-placed when calm for 30 s;
  * fills: a resting bid fills when sell trades consume the displayed size ahead of it at its price or trade through it, or when the
    ask crosses it;
  * after one side fills, its bid is not re-placed; the other bid keeps resting (passive re-pairing). When both sides of a pair are
    held they are merged into 1 USDC each (CTF merge, no fee; 0.05 USD gas per merge);
  * rewards: once a minute at a random second, the published score of our resting bids against the visible book (``reward_share``);
  * equity = cash (including merges) + held outcomes x best bid + accrued rewards - capital; checkpointed to disk every 60 s.
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import random
import re
import time
import urllib.request
from collections import deque
from dataclasses import asdict, dataclass, field
from typing import Deque, Dict, List, Optional

from . import reward_share as rs
from .polymarket_watcher import WS_URL, PmBooks, handle_clob_message

NEWS = re.compile(r"\b(attack|strike|target|military|war|ceasefire|missile|invade|invasion|troops|drone|hormuz|houthi|ukraine|russia|israel|"
                  r"iran|gaza|nuclear|coup|killed|assassinat|bomb|shooting)\b", re.I)
GAS_MERGE = 0.05


@dataclass
class Bid:
    token: str
    price: float
    size: float
    t_live: float
    ahead: float = float("nan")
    filled: float = 0.0
    pulled_until: float = 0.0
    cancel_at: Optional[float] = None


@dataclass
class Mkt:
    cid: str
    question: str
    yes: str
    no: str
    n: float
    v: float
    rate: float
    end_date: str
    bids: Dict[str, Bid] = field(default_factory=dict)
    held: Dict[str, float] = field(default_factory=dict)
    cash: float = 0.0
    rewards: float = 0.0
    merges: int = 0
    fills: List[dict] = field(default_factory=list)
    pulls: int = 0
    done: Dict[str, bool] = field(default_factory=dict)         # side already filled once: not re-placed
    sells: Dict[str, Deque[float]] = field(default_factory=dict)
    pulled_until: Dict[str, float] = field(default_factory=dict)  # token -> no quote before this time (toxicity gate)

    def equity(self, books: PmBooks) -> float:
        """P&L so far: cash flows from fills and merges (start 0) + rewards + held outcomes at their best bid."""
        return self.cash + self.rewards + sum(sh * books.bb.get(t, 0.0) for t, sh in self.held.items())

    def n_capital(self) -> float:
        return self.n                                             # USDC set aside for the market (both bids together cost <= n)


class RewardMM:
    def __init__(self, mkts: List[Mkt], out_dir: str, lat: float = 1.0, seed: int = 3):
        self.m = {x.cid: x for x in mkts}
        self.tok = {}
        for x in mkts:
            self.tok[x.yes], self.tok[x.no] = x, x
        self.books = PmBooks()
        self.lat = lat
        self.rng = random.Random(seed)
        self.out = out_dir
        os.makedirs(out_dir, exist_ok=True)
        self.logf = open(os.path.join(out_dir, "mm_log.jsonl"), "a", buffering=1)
        self.t0 = time.time()
        self.trades = 0

    def log(self, kind, **kw):
        self.logf.write(json.dumps({"kind": kind, "t": time.time(), **kw}, default=float) + "\n")

    # ---------------------------------------------------------------- quoting
    def targets(self, x: Mkt) -> Optional[Dict[str, float]]:
        ty, tn = self.books.top(x.yes), self.books.top(x.no)
        if ty is None or tn is None:
            return None
        mid = (ty[0] + ty[1]) / 2.0
        d = max(0.01, math.ceil(((ty[1] - ty[0]) / 2.0) * 100 - 1e-9) / 100.0)
        if d * 100 >= x.v:
            return None
        by, bn = round(mid - d, 2), round((1 - mid) - d, 2)
        if by + bn > 0.98 + 1e-9 or by <= 0.01 or bn <= 0.01:
            return None
        return {x.yes: by, x.no: bn}

    def requote(self, now: float) -> None:
        for x in self.m.values():
            tg = self.targets(x)
            for tok in (x.yes, x.no):
                b = x.bids.get(tok)
                if b is not None and b.cancel_at is not None and now >= b.cancel_at:
                    del x.bids[tok]
                    b = None
                if x.done.get(tok) or tg is None or x.pulled_until.get(tok, 0.0) > now:
                    continue
                if b is not None and (b.pulled_until > now or b.cancel_at is not None):
                    continue
                if b is None or abs(b.price - tg[tok]) > 0.0051:
                    if b is not None and b.filled > 0:
                        continue
                    pu = b.pulled_until if b else 0.0
                    if pu > now:
                        continue
                    x.bids[tok] = Bid(tok, tg[tok], x.n, now + self.lat)

    def _activate(self, b: Bid, now: float) -> None:
        if b.ahead != b.ahead and now >= b.t_live:
            b.ahead = self.books.b.get(b.token, {}).get(b.price, 0.0)

    def _toxic(self, x: Mkt, tok: str, now: float) -> bool:
        t = self.books.top(tok)
        if t is not None:
            bq, aq = t[2], t[3]
            if bq + aq > 0 and (bq - aq) / (bq + aq) < -0.65:
                return True
        q = x.sells.get(tok)
        return bool(q) and sum(1 for s in q if s >= now - 10.0) >= 3

    def _gate(self, x: Mkt, tok: str, now: float) -> None:
        b = x.bids.get(tok)
        if b is None or b.cancel_at is not None or b.filled > 0:
            return
        if self._toxic(x, tok, now):
            b.cancel_at = now + self.lat
            b.pulled_until = now + 30.0
            x.pulled_until[tok] = now + 30.0
            x.pulls += 1
            self.log("pull", cid=x.cid, token=tok)

    def on_top(self, tok: str) -> None:
        x = self.tok.get(tok)
        if x is None:
            return
        now = time.time()
        self._gate(x, tok, now)
        b = x.bids.get(tok)
        if b is None:
            return
        self._activate(b, now)
        if b.ahead == b.ahead:
            b.ahead = min(b.ahead, self.books.b.get(tok, {}).get(b.price, 0.0))
            if self.books.ba.get(tok, 1.0) <= b.price:
                self._fill(x, b, b.size - b.filled, now, "crossed")

    def on_trade(self, tok: str, px: float, sz: float, side: str) -> None:
        self.trades += 1
        x = self.tok.get(tok)
        if x is None:
            return
        now = time.time()
        if side.upper() == "SELL":
            x.sells.setdefault(tok, deque(maxlen=20)).append(now)
        self._gate(x, tok, now)
        b = x.bids.get(tok)
        if b is None or side.upper() != "SELL":
            return
        self._activate(b, now)
        if b.ahead != b.ahead:
            return
        if px < b.price - 1e-9:
            self._fill(x, b, b.size - b.filled, now, "through")
        elif abs(px - b.price) < 1e-9:
            if sz > b.ahead:
                self._fill(x, b, min(sz - b.ahead, b.size - b.filled), now, "queue")
                b.ahead = 0.0
            else:
                b.ahead -= sz

    def _fill(self, x: Mkt, b: Bid, q: float, now: float, how: str) -> None:
        if q <= 1e-9:
            return
        b.filled += q
        x.cash -= q * b.price
        x.held[b.token] = x.held.get(b.token, 0.0) + q
        x.fills.append({"t": now, "token": b.token, "px": b.price, "q": q, "how": how})
        self.log("fill", cid=x.cid, token=b.token, px=b.price, q=q, how=how)
        if b.filled >= b.size - 1e-9:
            x.done[b.token] = True
            x.bids.pop(b.token, None)
        k = min(x.held.get(x.yes, 0.0), x.held.get(x.no, 0.0))
        if k > 1e-9:                                                       # both outcomes held: merge pairs into USDC at no fee
            x.held[x.yes] -= k
            x.held[x.no] -= k
            x.cash += k - GAS_MERGE
            x.merges += 1
            self.log("merge", cid=x.cid, pairs=k)
            if x.done.get(x.yes) and x.done.get(x.no):                     # a full cycle: quote again from scratch
                x.done = {}

    # ---------------------------------------------------------------- rewards
    def sample(self, now: float) -> None:
        for x in self.m.values():
            by, bn = x.bids.get(x.yes), x.bids.get(x.no)
            live = [b for b in (by, bn) if b is not None and now >= b.t_live and b.cancel_at is None]
            if not live:
                continue
            ty = self.books.top(x.yes)
            if ty is None:
                continue
            mid = (ty[0] + ty[1]) / 2.0
            yb = {"bids": [{"price": p, "size": s} for p, s in self.books.b.get(x.yes, {}).items()],
                  "asks": [{"price": p, "size": s} for p, s in self.books.a.get(x.yes, {}).items()]}
            nb = {"bids": [{"price": p, "size": s} for p, s in self.books.b.get(x.no, {}).items()],
                  "asks": [{"price": p, "size": s} for p, s in self.books.a.get(x.no, {}).items()]}
            theirs = rs.q_min(*rs.book_q(yb, nb, mid, x.v, x.n), mid)
            q1 = rs.score((mid - by.price) * 100, x.v) * (by.size - by.filled) if by in live else 0.0   # YES bid -> Q_one
            q2 = rs.score(((1 - mid) - bn.price) * 100, x.v) * (bn.size - bn.filled) if bn in live else 0.0   # NO bid -> Q_two
            ours = rs.q_min(q1, q2, mid)
            if ours > 0:
                x.rewards += x.rate / 1440.0 * ours / (ours + theirs)

    def summary(self) -> dict:
        rows = [{"cid": x.cid, "question": x.question, "n": x.n, "rate": x.rate, "rewards": round(x.rewards, 4), "equity": round(x.equity(self.books), 4),
                 "fills": len(x.fills), "merges": x.merges, "pulls": x.pulls, "held": {k: v for k, v in x.held.items() if v > 1e-9}} for x in self.m.values()]
        return {"t0": self.t0, "t1": time.time(), "trades_seen": self.trades, "markets": rows, "capital": sum(r["n"] for r in rows),
                "total_rewards": round(sum(r["rewards"] for r in rows), 4), "total_equity": round(sum(r["equity"] for r in rows), 4)}

    def checkpoint(self) -> None:
        tmp = os.path.join(self.out, "mm_summary.json.tmp")
        json.dump(self.summary(), open(tmp, "w"), indent=1, default=float)
        os.replace(tmp, os.path.join(self.out, "mm_summary.json"))


def fee_rates(cids: List[str]) -> Dict[str, float]:
    out = {}
    for i in range(0, len(cids), 20):
        q = "&".join(f"condition_ids={c}" for c in cids[i:i + 20])
        req = urllib.request.Request(f"https://gamma-api.polymarket.com/markets?{q}&limit=50", headers={"User-Agent": "Mozilla/5.0"})
        for m in json.loads(urllib.request.urlopen(req, timeout=30).read()):
            fs = m.get("feeSchedule") or {}
            out[m.get("conditionId")] = float(fs.get("rate") or 0.0) if m.get("feesEnabled") else 0.0
    return out


def universe(k: int, min_hours: float = 72.0, max_min_size: float = 50.0) -> List[Mkt]:
    import datetime as dt
    mk = rs.reward_markets(4)
    now = dt.datetime.now(dt.timezone.utc)
    pre = []
    for m in mk:
        try:
            end = dt.datetime.fromisoformat(str(m.get("end_date", "")).replace(" ", "T").replace("+00", "+00:00"))
        except ValueError:
            continue
        if (end - now).total_seconds() < min_hours * 3600 or float(m["rewards_min_size"]) > max_min_size or NEWS.search(m["question"]):
            continue
        p = float(m["tokens"][0]["price"] or 0)
        if not 0.15 <= p <= 0.85:
            continue
        pre.append(m)
    fees = fee_rates([m["condition_id"] for m in pre])
    pre = [m for m in pre if fees.get(m["condition_id"], 1.0) == 0.0]
    books = rs.fetch_books([t["token_id"] for m in pre for t in m["tokens"]])
    ranked = []
    for m in pre:
        e = rs.estimate(m, float(m["rewards_min_size"]), books)
        if e and 0.15 <= e["mid"] <= 0.85:
            ranked.append((e["ret_per_day"], m, e))
    ranked.sort(key=lambda r: -r[0])
    out, seen = [], set()
    for _, m, e in ranked:
        ev = m.get("event_id") or m["condition_id"]
        if ev in seen:
            continue
        seen.add(ev)
        out.append(Mkt(m["condition_id"], m["question"][:90], e["tokens"]["yes"], e["tokens"]["no"], float(m["rewards_min_size"]), float(m["rewards_max_spread"]),
                       e["rate"], str(m.get("end_date"))))
        if len(out) >= 3 * k:
            break
    return out


async def run(duration_s: float, out_dir: str, k: int, warmup_s: float = 300.0) -> dict:
    import aiohttp
    import orjson
    cands = await asyncio.to_thread(universe, k)
    eng = RewardMM(cands, out_dir)
    toks = [t for x in cands for t in (x.yes, x.no)]
    mids0: Dict[str, float] = {}
    phase = "warmup"
    t_start = time.time()
    t_end = t_start + warmup_s + duration_s
    next_sample = t_start + warmup_s + eng.rng.uniform(0, 60)
    next_ck = time.time() + 60
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
                                handle_clob_message(orjson.loads(msg.data), eng.books, eng.on_top if phase == "live" else (lambda a: None),
                                                    eng.on_trade if phase == "live" else None)
                            except ValueError:
                                pass
                        elif msg is not None and msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                            break
                        now = time.time()
                        if phase == "warmup":
                            for x in cands:
                                t = eng.books.top(x.yes)
                                if t is not None and x.cid not in mids0:
                                    mids0[x.cid] = (t[0] + t[1]) / 2.0
                            if now - t_start >= warmup_s:              # keep the k markets whose mid did not move in the warm-up
                                calm = []
                                for x in cands:
                                    t = eng.books.top(x.yes)
                                    if t is None or x.cid not in mids0:
                                        continue
                                    if abs((t[0] + t[1]) / 2.0 - mids0[x.cid]) < 1e-9 and (t[1] - t[0]) * 100 < x.v:
                                        calm.append(x)
                                eng.m = {x.cid: x for x in calm[:k]}
                                eng.tok = {}
                                for x in eng.m.values():
                                    eng.tok[x.yes], eng.tok[x.no] = x, x
                                eng.t0 = now
                                eng.log("start", markets=[{"cid": x.cid, "question": x.question, "n": x.n, "rate": x.rate} for x in eng.m.values()])
                                print(f"live: {len(eng.m)} calm zero-fee markets, capital {sum(x.n for x in eng.m.values()):.0f}", flush=True)
                                phase = "live"
                            continue
                        eng.requote(now)
                        if now >= next_sample:
                            eng.sample(now)
                            next_sample = (math.floor(now / 60.0) + 1) * 60.0 + eng.rng.uniform(0, 60)
                        if now >= next_ck:
                            next_ck = now + 60
                            eng.checkpoint()
                            sm = eng.summary()
                            print(f"[{time.strftime('%H:%M:%S')}] rewards={sm['total_rewards']:.3f} equity={sm['total_equity']:+.3f} fills={sum(r['fills'] for r in sm['markets'])} merges={sum(r['merges'] for r in sm['markets'])} pulls={sum(r['pulls'] for r in sm['markets'])}", flush=True)
            except Exception as e:
                eng.log("error", err=repr(e)[:200])
                await asyncio.sleep(2)
    eng.checkpoint()
    return eng.summary()


def evaluate(run_dir: str, bankroll: float = 100.0) -> dict:
    s = json.load(open(os.path.join(run_dir, "mm_summary.json")))
    start = [json.loads(l) for l in open(os.path.join(run_dir, "mm_log.jsonl")) if '"start"' in l][-1]
    order = [m["cid"] for m in start["markets"]]
    by = {m["cid"]: m for m in s["markets"]}
    rets = [by[c]["equity"] / by[c]["n"] for c in order if c in by]
    n = len(rets)
    mu = sum(rets) / n
    sd = math.sqrt(sum((r - mu) ** 2 for r in rets) / (n - 1))
    t = mu / (sd / math.sqrt(n)) if sd > 0 else float("inf")
    acct, cap = [], 0.0
    for c in order:
        if c in by and cap + by[c]["n"] <= bankroll:
            acct.append(c)
            cap += by[c]["n"]
    net = sum(by[c]["equity"] for c in acct)
    return {"minutes": round((s["t1"] - s["t0"]) / 60, 1), "markets": n, "mean_ret": mu, "t": t, "total_rewards": s["total_rewards"],
            "total_equity": s["total_equity"], "fills": sum(m["fills"] for m in s["markets"]), "merges": sum(m["merges"] for m in s["markets"]),
            "pulls": sum(m["pulls"] for m in s["markets"]), "account": {"markets": len(acct), "capital": cap, "net_usd": round(net, 4)},
            "pass": bool(mu > 0 and t > 2.5 and net > 0)}


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--duration", type=float, default=2700.0)
    p.add_argument("--k", type=int, default=40)
    p.add_argument("--out", default="runs/p15/r3")
    p.add_argument("--eval", default=None)
    p.add_argument("--warmup", type=float, default=300.0)
    a = p.parse_args(argv)
    if a.eval:
        print(json.dumps(evaluate(a.eval), indent=1))
        return
    out = os.path.join(a.out, time.strftime("%Y%m%d_%H%M%S"))
    sm = asyncio.run(run(a.duration, out, a.k, a.warmup))
    print(json.dumps(evaluate(out), indent=1))
    print("artifacts:", out)


if __name__ == "__main__":
    main()
