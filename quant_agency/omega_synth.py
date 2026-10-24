"""Synthetic high-density meme market for the Omega engine: pump.fun curves, Gate meme pairs and X mentions with known ground truth.

It exists to test mechanics (throughput, memory, fills, breakers, bot filtering), **not** to say anything about profitability: the
regimes and their frequencies are invented, so any P&L measured on it is a property of the generator.

Token regimes (pump curves, constant-product with pump.fun's initial reserves and a 1.25 % fee):
  dead      a few prints, then nothing                                   (most launches)
  organic   a buy burst from many wallets, then a slower fade             tweets: many authors, varied text, older accounts
  botpump   a burst from a small wallet pool, then a sharp dump           tweets: few new low-follower accounts, templated text
  rug       creator buys, small burst, creator dumps everything           mint authority sometimes left active
  grinder   two-sided random flow
Gate pairs: geometric random walk with occasional jumps, a book-ticker every ~0.5 s and Poisson trade prints.
"""
from __future__ import annotations

import gzip
import json
import math
import random
from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Optional

from .meme_discovery import curve_buy, curve_sell

V_SOL0, V_TOK0 = 30.0, 1_073_000_000.0
FEE_BPS = 125.0
REGIMES = (("dead", 0.62), ("organic", 0.12), ("botpump", 0.10), ("rug", 0.08), ("grinder", 0.08))
_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def _addr(rng: random.Random, suffix: str = "") -> str:
    return "".join(rng.choice(_B58) for _ in range(40)) + suffix


@dataclass
class SynToken:
    mint: str
    symbol: str
    creator: str
    regime: str
    born: float
    v_sol: float = V_SOL0
    v_tok: float = V_TOK0
    phase_len: float = 0.0
    wallets: List[str] = field(default_factory=list)
    creator_tok: float = 0.0
    dead_at: float = 0.0
    facts: Dict = field(default_factory=dict)


@dataclass
class SynPair:
    pair: str
    mid: float
    spread_bps: float
    vol: float                      # per sqrt(second)
    prev: float = 0.0


class SynthMarket:
    def __init__(self, seed: int = 7, t0: float = 1_800_000_000.0, create_rate: float = 0.6, n_pairs: int = 8, sol_usd: float = 180.0,
                 tweet_scale: float = 1.0):
        self.rng = random.Random(seed)
        self.t = t0
        self.create_rate = create_rate
        self.sol_usd = sol_usd
        self.tokens: Dict[str, SynToken] = {}
        self.tweet_scale = tweet_scale
        self.pairs = [SynPair(f"MEME{i}_USDT", 10 ** self.rng.uniform(-6, 0), self.rng.uniform(4, 15), self.rng.uniform(2e-4, 6e-4)) for i in range(n_pairs)]
        self.organic_pool = [_addr(self.rng) for _ in range(3000)]
        self.facts_db: Dict[str, dict] = {}
        self.n_tweets = 0

    # ---------------------------------------------------------------- ground truth for the safety checker
    def facts(self, mint: str) -> dict:
        f = self.facts_db.get(mint)
        return dict(f) if f is not None else {"error": "unknown mint"}

    def pair_rules(self) -> List[dict]:
        return [{"pair": p.pair, "lot": 1.0 if p.mid < 0.01 else 0.01, "min_quote": 3.0, "min_base": 0.0, "fee_bps": 20.0, "quote_vol": 1e6, "meme": True}
                for p in self.pairs]

    # ---------------------------------------------------------------- events
    def _print(self, tk: SynToken, buy: bool, sol: float, user: str) -> Optional[dict]:
        if buy:
            tok, fee, vs = curve_buy(tk.v_sol, tk.v_tok, sol, FEE_BPS)
            if tok <= 0:
                return None
            net = sol - fee
            tk.v_sol, tk.v_tok = vs, tk.v_tok - tok
            q, quote = tok, net
        else:
            tok = min(sol / max(tk.v_sol / tk.v_tok, 1e-18), (V_TOK0 - tk.v_tok) * 0.9)
            if tok <= 0:
                return None
            got, fee, vs = curve_sell(tk.v_sol, tk.v_tok, tok, FEE_BPS)
            tk.v_sol, tk.v_tok = vs, tk.v_tok + tok
            q, quote = tok, got + fee
        if user == tk.creator:
            tk.creator_tok += q if buy else -q
        return {"kind": "print", "t": self.t, "venue": "pump", "key": tk.mint, "side": 1 if buy else -1, "qty": q, "quote": quote, "price": quote / q,
                "post_price": tk.v_sol / tk.v_tok, "v_quote": tk.v_sol, "v_base": tk.v_tok, "real_quote": tk.v_sol - V_SOL0, "fee_bps": FEE_BPS, "user": user}

    def _tweet(self, tk: SynToken, bot: bool) -> dict:
        r = self.rng
        self.n_tweets += 1
        if bot:
            author = f"bot{r.randrange(12)}_{tk.mint[:4]}"
            text = r.choice([f"${tk.symbol} 100x gem sending now 🚀🚀 {tk.mint}", f"${tk.symbol} next 1000x dont miss 🚀 {tk.mint}"])
            followers, age_days = r.randrange(0, 40), r.uniform(1, 20)
        else:
            author = f"u{r.randrange(200000)}"
            a = r.choice(["looking strong", "chart is clean", "just aped", "community feels legit", "volume picking up", "watching carefully",
                          "devs are active", "holders growing", "bullish structure", "careful could dump", "nice memes", "early maybe", "love this one",
                          "strong hands", "not financial advice", "took profits", "added more", "great vibes", "solid team", "sending"])
            b = r.choice(["today", "right now", "this week", "honestly", "imo", "fr", "ngl", "lol", "again", "finally", "", "", ""])
            c = r.choice(["friends", "frens", "anon", "everyone", "chat", "fam", "guys", "", "", "", ""])
            text = " ".join(x for x in (f"${tk.symbol}", a, b, c) if x)
            followers, age_days = int(10 ** r.uniform(1.5, 4.5)), r.uniform(60, 3000)
        return {"kind": "tweet", "id": f"{self.n_tweets}", "t": self.t, "author": author, "followers": followers, "author_created_t": self.t - age_days * 86400,
                "text": text, "symbols": [f"${tk.symbol.upper()}", tk.mint]}

    def _spawn(self) -> List[dict]:
        r = self.rng
        x, regime = r.random(), "dead"
        for name, p in REGIMES:
            if x < p:
                regime = name
                break
            x -= p
        mint = _addr(r, "pump")
        sym = "".join(r.choice("ABCDEFGHJKLMNPQRSTUVWXYZ") for _ in range(r.randint(3, 6)))
        tk = SynToken(mint, sym, _addr(r), regime, self.t, phase_len=r.uniform(60, 420))
        tk.wallets = [_addr(r) for _ in range(8)] if regime == "botpump" else []
        tk.facts = {"mint_authority": None, "freeze_authority": None, "top10_share": r.uniform(0.08, 0.25)}
        if regime == "rug" and r.random() < 0.5:
            tk.facts["mint_authority"] = _addr(r)
        if regime == "botpump":
            tk.facts["top10_share"] = r.uniform(0.25, 0.6)
        tk.dead_at = self.t + (r.uniform(20, 90) if regime == "dead" else tk.phase_len * 2.2)
        self.tokens[mint] = tk
        self.facts_db[mint] = tk.facts
        while len(self.facts_db) > 50_000:
            self.facts_db.pop(next(iter(self.facts_db)))
        out = [{"kind": "create", "t": self.t, "mint": mint, "name": sym.title(), "symbol": sym, "creator": tk.creator}]
        p = self._print(tk, True, r.uniform(0.2, 1.5), tk.creator)
        if p:
            out.append(p)
        return out

    def _token_step(self, tk: SynToken, dt: float) -> List[dict]:
        r = self.rng
        age = self.t - tk.born
        L = tk.phase_len
        out: List[dict] = []
        if tk.regime == "dead":
            rate, pbuy, size, users = 0.3 if age < 20 else 0.02, 0.5, 0.15, None
        elif tk.regime == "organic":
            if age < 60:
                rate, pbuy, size = 0.4, 0.6, 0.2
            elif age < 60 + L:
                rate, pbuy, size = 2.0, 0.6, 0.12
            else:
                rate, pbuy, size = 1.0, 0.4, 0.12
            users = self.organic_pool
        elif tk.regime == "botpump":
            if age < 60:
                rate, pbuy, size = 0.3, 0.6, 0.2
            elif age < 60 + 0.5 * L:
                rate, pbuy, size = 3.0, 0.75, 0.15
            else:
                rate, pbuy, size = 3.0, 0.15, 0.3
            users = tk.wallets
        elif tk.regime == "rug":
            if age < 0.4 * L:
                rate, pbuy, size = 1.5, 0.7, 0.15
            else:
                if tk.creator_tok > 1:
                    p = self._print(tk, False, tk.creator_tok * tk.v_sol / tk.v_tok, tk.creator)
                    if p:
                        out.append(p)
                rate, pbuy, size = 1.0, 0.15, 0.3
            users = self.organic_pool
        else:
            rate, pbuy, size, users = 1.0, 0.5, 0.12, self.organic_pool
        n = self._poisson(rate * dt)
        for _ in range(n):
            u = r.choice(users) if users else _addr(r)
            p = self._print(tk, r.random() < pbuy, size * math.exp(r.gauss(0, 0.8)), u)
            if p:
                out.append(p)
        if tk.regime in ("organic", "botpump") and 30 < age < 60 + L:
            k = self._poisson((0.3 * (1 + 6 * min(age, L) / L) if tk.regime == "organic" else 2.5) * self.tweet_scale * dt)
            for _ in range(k):
                out.append(self._tweet(tk, tk.regime == "botpump"))
        if tk.v_sol - V_SOL0 > 85:
            out.append({"kind": "complete", "t": self.t, "mint": tk.mint})
            tk.dead_at = self.t
        return out

    def _poisson(self, lam: float) -> int:
        if lam <= 0:
            return 0
        L, k, p = math.exp(-lam), 0, 1.0
        while True:
            p *= self.rng.random()
            if p <= L:
                return k
            k += 1

    def _pair_step(self, pr: SynPair, dt: float) -> List[dict]:
        r = self.rng
        jump = r.gauss(0, 0.004) if r.random() < 0.002 else 0.0
        step = r.gauss(0, pr.vol * math.sqrt(dt)) + jump
        pr.mid *= math.exp(step)
        pr.prev = 0.97 * pr.prev + step                    # recent drift: the taker flow leans the way the price moves
        out = []
        if r.random() < dt / 0.5:
            half = pr.mid * pr.spread_bps / 2e4
            out.append({"kind": "quote", "t": self.t, "venue": "gate", "key": pr.pair, "bid": pr.mid - half, "ask": pr.mid + half,
                        "bq": r.uniform(2e3, 5e4) / pr.mid, "aq": r.uniform(2e3, 5e4) / pr.mid})
        for _ in range(self._poisson(1.5 * dt)):
            side = 1 if r.random() < 0.5 + max(-0.4, min(0.4, pr.prev * 150)) else -1
            half = pr.mid * pr.spread_bps / 2e4
            px = pr.mid + side * half
            q = r.uniform(20, 2000) / px
            out.append({"kind": "print", "t": self.t, "venue": "gate", "key": pr.pair, "side": side, "qty": q, "quote": q * px, "price": px, "user": str(r.random())})
        return out

    def events(self, duration_s: float, dt: float = 0.2) -> Iterator[dict]:
        """Time-ordered events for ``duration_s`` seconds of market time."""
        yield {"kind": "sol", "t": self.t, "px": self.sol_usd}
        yield {"kind": "rules", "t": self.t, "rows": self.pair_rules()}
        end = self.t + duration_s
        while self.t < end:
            self.t += dt
            born: List[dict] = []
            for _ in range(self._poisson(self.create_rate * dt)):
                born += self._spawn()
            batch: List[dict] = []
            for mint in list(self.tokens):
                tk = self.tokens[mint]
                if self.t > tk.dead_at:
                    del self.tokens[mint]
                    continue
                batch += self._token_step(tk, dt)
            for pr in self.pairs:
                batch += self._pair_step(pr, dt)
            self.rng.shuffle(batch)
            batch = born + batch                          # a token's creation always precedes its prints
            for i, e in enumerate(batch):
                e["t"] = self.t - dt + dt * (i + 1) / (len(batch) + 1)
                yield e


def write_tape(path: str, events: Iterator[dict]) -> int:
    n = 0
    with gzip.open(path, "wt", compresslevel=3) as f:
        for e in events:
            f.write(json.dumps(e, separators=(",", ":")) + "\n")
            n += 1
    return n
