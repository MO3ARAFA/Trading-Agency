"""Omega engine, layer 2: X (Twitter) social velocity, bot filtering, sentiment, and the Social Alpha Score.

Data access is the **official X API v2** (``GET /2/tweets/search/recent``) with a bearer token read from the environment variable
``X_BEARER_TOKEN``; nothing else. This module does not scrape x.com or mirror sites: X's terms forbid it, and a crawler that evades a
platform's access controls is not something to put a trading system's correctness on. Without a token the live source reports itself
unavailable and every score is ``None`` (unknown), never 0 and never invented. ``JsonlTweetSource`` replays recorded or synthetic tweets
through exactly the same tracker.

Per tracked symbol (cashtag or contract address) the tracker keeps a bounded, time-pruned ring of mentions and computes:

* velocity: mentions per minute over 1 / 5 / 60 minutes and the 5-minute rate relative to the hour (acceleration);
* breadth: unique authors, author concentration (Herfindahl), follower-weighted reach by tier;
* bot signals: duplicate-text share (normalized text, cashtags / CAs / URLs / numbers stripped), new-account share, low-follower share,
  author concentration, and posting regularity (bots post on a timer: low coefficient of variation of inter-arrival gaps);
* sentiment: a crypto-aware lexicon with negation, mean in [-1, 1].

``social_alpha_score`` fuses them with on-chain volume acceleration into 0-100 and **caps the score at 20 when the bot score is high**,
so a bot-farm hype loop can never rank as genuine momentum.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import re
import time
from collections import Counter, OrderedDict, deque
from dataclasses import asdict, dataclass, field
from typing import Callable, Deque, Dict, Iterable, List, Optional, Sequence

X_SEARCH = "https://api.x.com/2/tweets/search/recent"


@dataclass
class Tweet:
    id: str
    t: float                          # created_at, unix seconds
    author: str
    followers: int = 0
    author_created_t: float = float("nan")
    text: str = ""
    symbols: List[str] = field(default_factory=list)     # tracked keys this tweet mentions (cashtags upper-cased, CAs verbatim)
    retweet: bool = False


# ================================================================================ text handling
_URL = re.compile(r"https?://\S+")
_CASHTAG = re.compile(r"\$([A-Za-z][A-Za-z0-9_]{1,15})")
_SOL_CA = re.compile(r"\b[1-9A-HJ-NP-Za-km-z]{32,44}\b")
_EVM_CA = re.compile(r"\b0x[a-fA-F0-9]{40}\b")
_NUM = re.compile(r"\d+([.,]\d+)?[kmbx%]?", re.I)
_WORD = re.compile(r"[a-z']+|[\U0001F300-\U0001FAFF☀-➿]")

POS = {"moon": 1.0, "mooning": 1.0, "gem": 0.8, "bullish": 1.0, "send": 0.6, "sending": 0.7, "pump": 0.4, "pumping": 0.6, "ath": 0.6,
       "breakout": 0.7, "buy": 0.4, "buying": 0.5, "long": 0.4, "lfg": 0.8, "wagmi": 0.6, "based": 0.4, "early": 0.5, "100x": 1.0, "1000x": 1.0,
       "huge": 0.5, "strong": 0.5, "love": 0.6, "great": 0.6, "amazing": 0.7, "legit": 0.6, "\U0001F680": 0.8, "\U0001F525": 0.6, "\U0001F48E": 0.7,
       "\U0001F4C8": 0.7, "win": 0.5, "winning": 0.6, "up": 0.2, "green": 0.4, "rip": -0.3}
NEG = {"rug": -1.0, "rugged": -1.0, "rugpull": -1.0, "scam": -1.0, "honeypot": -1.0, "dump": -0.8, "dumping": -0.9, "dumped": -0.8, "bearish": -1.0,
       "sell": -0.4, "selling": -0.5, "short": -0.4, "dead": -0.8, "exit": -0.4, "fake": -0.8, "bot": -0.4, "bots": -0.5, "jeet": -0.5,
       "jeets": -0.5, "ngmi": -0.7, "avoid": -0.8, "warning": -0.7, "careful": -0.4, "down": -0.3, "red": -0.4, "crash": -0.9, "lost": -0.6,
       "\U0001F4C9": -0.7, "⚠": -0.6, "\U0001F6A8": -0.6}
LEX = {**POS, **NEG}
NEGATORS = {"not", "no", "never", "dont", "don't", "isnt", "isn't", "wont", "won't", "aint", "ain't"}


def normalize_text(text: str) -> str:
    """Text with URLs, cashtags, contract addresses, numbers and punctuation removed: what a template-driven bot reuses."""
    s = _URL.sub(" ", text)
    s = _EVM_CA.sub(" ", s)
    s = _SOL_CA.sub(" ", s)
    s = _CASHTAG.sub(" ", s)
    s = _NUM.sub(" ", s.lower())
    s = re.sub(r"[^a-z\s]", " ", s)
    return " ".join(s.split())


def text_key(text: str) -> str:
    return hashlib.blake2b(normalize_text(text).encode(), digest_size=8).hexdigest()


def sentiment(text: str) -> float:
    """Lexicon score in [-1, 1]; a negator flips the next scored word within 3 tokens."""
    toks = _WORD.findall(_URL.sub(" ", text.lower()))
    tot, n, neg_left = 0.0, 0, 0
    for w in toks:
        if w in NEGATORS:
            neg_left = 3
            continue
        v = LEX.get(w)
        if v is not None:
            tot += -v if neg_left > 0 else v
            n += 1
        neg_left = max(0, neg_left - 1)
    return 0.0 if n == 0 else max(-1.0, min(1.0, tot / n))


def extract_symbols(text: str, tracked: Iterable[str]) -> List[str]:
    """Tracked keys mentioned in ``text``: cashtags (case-insensitive) and contract addresses (exact)."""
    tags = {m.upper() for m in _CASHTAG.findall(text)}
    cas = set(_SOL_CA.findall(text)) | {m.lower() for m in _EVM_CA.findall(text)}
    out = []
    for k in tracked:
        if k.startswith("$") and k[1:].upper() in tags:
            out.append(k)
        elif k in cas or k.lower() in cas:
            out.append(k)
    return out


# ================================================================================ per-symbol tracker
FOLLOWER_TIERS = (100, 1_000, 10_000, 100_000)


@dataclass
class SocialMetrics:
    t: float
    n_1m: int
    n_5m: int
    n_60m: int
    tpm_1m: float
    tpm_5m: float
    tpm_60m: float
    accel: float                      # tpm_5m / max(tpm_60m, floor)
    unique_5m: int
    author_hhi: float                 # 0..1 over the last 60 min
    reach_5m: float                   # sum of log10(1 + followers) over the last 5 min
    tiers: Dict[str, int]
    dup_share: float
    new_acct_share: float
    low_follower_share: float
    regularity: float                 # 1 - CV of inter-arrival gaps (clipped 0..1): 1 = clockwork
    sentiment: float
    bot_score: float

    def as_dict(self) -> dict:
        return asdict(self)


class SocialTracker:
    """Bounded mention history for one symbol."""

    def __init__(self, key: str, horizon_s: float = 3600.0, maxlen: int = 1000):
        self.key, self.horizon_s = key, horizon_s
        self.ring: Deque[tuple] = deque(maxlen=maxlen)     # (t, author, followers, age_days, text_key, sentiment)
        self.last_t = 0.0

    def add(self, tw: Tweet, tkey: Optional[str] = None, senti: Optional[float] = None) -> None:
        age = (tw.t - tw.author_created_t) / 86400.0 if tw.author_created_t == tw.author_created_t else float("nan")
        self.ring.append((tw.t, tw.author, int(tw.followers), age, tkey or text_key(tw.text), sentiment(tw.text) if senti is None else senti))
        self.last_t = max(self.last_t, tw.t)
        self.prune(tw.t)

    def prune(self, now: float) -> None:
        while self.ring and self.ring[0][0] < now - self.horizon_s:
            self.ring.popleft()

    def metrics(self, now: float) -> Optional[SocialMetrics]:
        self.prune(now)
        rows = list(self.ring)
        if not rows:
            return None
        r1 = [r for r in rows if r[0] >= now - 60]
        r5 = [r for r in rows if r[0] >= now - 300]
        span60 = max(60.0, min(3600.0, now - rows[0][0]))
        tpm60 = len(rows) / (span60 / 60.0)
        tpm5 = len(r5) / 5.0
        authors = Counter(r[1] for r in rows)
        hhi = sum((c / len(rows)) ** 2 for c in authors.values())
        tiers = {"<100": 0, "<1k": 0, "<10k": 0, "<100k": 0, ">=100k": 0}
        for r in r5:
            f = r[2]
            k = "<100" if f < 100 else "<1k" if f < 1_000 else "<10k" if f < 10_000 else "<100k" if f < 100_000 else ">=100k"
            tiers[k] += 1
        keys = Counter(r[4] for r in rows)
        dup = sum(c for c in keys.values() if c > 1) / len(rows)
        ages = [r[3] for r in rows if r[3] == r[3]]
        new_share = sum(1 for a in ages if a < 30) / len(ages) if ages else 0.0
        low_share = sum(1 for r in rows if r[2] < 50) / len(rows)
        ts = sorted(r[0] for r in rows)
        gaps = [b - a for a, b in zip(ts, ts[1:]) if b > a]
        if len(gaps) >= 5:
            mu = sum(gaps) / len(gaps)
            sd = math.sqrt(sum((g - mu) ** 2 for g in gaps) / (len(gaps) - 1))
            regular = max(0.0, min(1.0, 1.0 - sd / mu)) if mu > 0 else 0.0
        else:
            regular = 0.0
        senti = sum(r[5] for r in r5) / len(r5) if r5 else sum(r[5] for r in rows) / len(rows)
        conc = max(0.0, min(1.0, (hhi - 0.02) / 0.3))
        bot = max(0.0, min(1.0, 0.35 * dup + 0.2 * new_share + 0.15 * low_share + 0.15 * conc + 0.15 * regular))
        return SocialMetrics(now, len(r1), len(r5), len(rows), float(len(r1)), tpm5, tpm60, tpm5 / max(tpm60, 0.2), len({r[1] for r in r5}), hhi,
                             sum(math.log10(1 + r[2]) for r in r5), tiers, dup, new_share, low_share, regular, senti, bot)


def social_alpha_score(m: Optional[SocialMetrics], volume_accel: Optional[float]) -> Optional[dict]:
    """0-100. ``volume_accel`` = on-chain quote volume over the last 5 min / (last 30 min / 6); None if unknown.

    Components (each 0..1): velocity (log2 of the 5-min acceleration, 0 at 1x, 1 at 8x), breadth (unique authors in 5 min, log-scaled to 50),
    reach (follower-weighted, log-scaled), sentiment (mapped from [-1, 1]), on-chain confirmation (log2 of volume acceleration, 0 at 1x, 1 at 8x).
    Weights 0.25 / 0.15 / 0.10 / 0.15 / 0.35. Quality multiplier (1 - bot_score). Bot score > 0.6 caps the score at 20."""
    if m is None:
        return None
    vel = max(0.0, min(1.0, math.log2(max(m.accel, 1e-9)) / 3.0))
    breadth = max(0.0, min(1.0, math.log1p(m.unique_5m) / math.log1p(50)))
    reach = max(0.0, min(1.0, m.reach_5m / 60.0))
    sent = (m.sentiment + 1.0) / 2.0
    chain = None if volume_accel is None else max(0.0, min(1.0, math.log2(max(volume_accel, 1e-9)) / 3.0))
    parts = {"velocity": vel, "breadth": breadth, "reach": reach, "sentiment": sent, "onchain": chain}
    w = {"velocity": 0.25, "breadth": 0.15, "reach": 0.10, "sentiment": 0.15, "onchain": 0.35}
    if chain is None:                                  # renormalize over what is known; the output says so
        w.pop("onchain")
    raw = sum(parts[k] * v for k, v in w.items()) / sum(w.values())
    score = 100.0 * raw * (1.0 - m.bot_score)
    capped = m.bot_score > 0.6
    if capped:
        score = min(score, 20.0)
    return {"score": round(score, 2), "parts": {k: (None if v is None else round(v, 4)) for k, v in parts.items()}, "bot_score": round(m.bot_score, 4),
            "bot_capped": capped, "onchain_known": chain is not None}


class SocialBook:
    """All trackers, bounded (LRU over symbols)."""

    def __init__(self, max_symbols: int = 2000, dedup: int = 50_000):
        self.max_symbols = max_symbols
        self.trackers: "OrderedDict[str, SocialTracker]" = OrderedDict()
        self.seen: "OrderedDict[str, None]" = OrderedDict()      # one bounded de-duplication set for every symbol
        self.dedup = dedup
        self.tweets = self.duplicates = 0

    def tracker(self, key: str) -> SocialTracker:
        tr = self.trackers.get(key)
        if tr is None:
            tr = self.trackers[key] = SocialTracker(key)
            while len(self.trackers) > self.max_symbols:
                self.trackers.popitem(last=False)
        else:
            self.trackers.move_to_end(key)
        return tr

    def on_tweet(self, tw: Tweet) -> None:
        if tw.id in self.seen:
            self.duplicates += 1
            return
        self.seen[tw.id] = None
        if len(self.seen) > self.dedup:
            self.seen.popitem(last=False)
        self.tweets += 1
        tk, se = text_key(tw.text), sentiment(tw.text)
        for k in tw.symbols:
            self.tracker(k).add(tw, tk, se)

    def expire(self, now: float, idle_s: float = 3600.0) -> int:
        dead = [k for k, tr in self.trackers.items() if now - tr.last_t > idle_s]
        for k in dead:
            del self.trackers[k]
        return len(dead)

    def score(self, key: str, now: float, volume_accel: Optional[float]) -> Optional[dict]:
        tr = self.trackers.get(key)
        return social_alpha_score(tr.metrics(now) if tr else None, volume_accel)


# ================================================================================ sources
class JsonlTweetSource:
    """Replays tweets (one JSON object per line with the ``Tweet`` fields)."""

    def __init__(self, path: str):
        self.path = path

    def __iter__(self):
        import gzip
        op = gzip.open if self.path.endswith(".gz") else open
        with op(self.path, "rt") as f:
            for line in f:
                d = json.loads(line)
                if d.get("kind", "tweet") == "tweet":
                    d.pop("kind", None)
                    yield Tweet(**d)


@dataclass
class XApiStatus:
    available: bool
    reason: str = ""
    requests: int = 0
    tweets: int = 0
    rate_limited: int = 0
    errors: int = 0


class XApiV2Source:
    """Official X API v2 recent search. Polls one OR-query per batch of tracked keys (≤ 512 characters), honours the rate-limit headers,
    and walks ``since_id`` so no tweet is fetched twice. The token is read from ``X_BEARER_TOKEN`` and never logged."""

    def __init__(self, session, min_interval_s: float = 15.0, env: str = "X_BEARER_TOKEN"):
        self.session = session
        self._token = os.environ.get(env, "")
        self.status = XApiStatus(available=bool(self._token), reason="" if self._token else f"{env} not set: social scores are unknown (None)")
        self.min_interval_s = min_interval_s
        self.since: Dict[str, str] = {}
        self.next_ok = 0.0

    @staticmethod
    def build_queries(keys: Sequence[str], max_len: int = 480) -> List[str]:
        out, cur = [], []
        for k in keys:
            term = k if k.startswith("$") else f'"{k}"'
            trial = " OR ".join(cur + [term])
            if cur and len(f"({trial}) -is:retweet") > max_len:
                out.append(f"({' OR '.join(cur)}) -is:retweet")
                cur = [term]
            else:
                cur.append(term)
        if cur:
            out.append(f"({' OR '.join(cur)}) -is:retweet")
        return out

    @staticmethod
    def parse(payload: dict, tracked: Sequence[str]) -> List[Tweet]:
        import datetime as dt
        users = {u["id"]: u for u in (payload.get("includes") or {}).get("users", [])}

        def ts(s):
            try:
                return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
            except Exception:
                return float("nan")
        out = []
        for d in payload.get("data") or []:
            u = users.get(d.get("author_id"), {})
            text = d.get("text", "")
            out.append(Tweet(id=d["id"], t=ts(d.get("created_at", "")), author=d.get("author_id", ""),
                             followers=int((u.get("public_metrics") or {}).get("followers_count", 0)), author_created_t=ts(u.get("created_at", "")),
                             text=text, symbols=extract_symbols(text, tracked)))
        return out

    async def poll(self, keys: Sequence[str]) -> List[Tweet]:
        if not self.status.available or time.time() < self.next_ok or not keys:
            return []
        got: List[Tweet] = []
        for q in self.build_queries(keys):
            params = {"query": q, "max_results": "100", "tweet.fields": "created_at,author_id", "expansions": "author_id",
                      "user.fields": "created_at,public_metrics"}
            if q in self.since:
                params["since_id"] = self.since[q]
            try:
                async with self.session.get(X_SEARCH, params=params, headers={"Authorization": f"Bearer {self._token}"}) as r:
                    self.status.requests += 1
                    if r.status == 429:
                        self.status.rate_limited += 1
                        self.next_ok = float(r.headers.get("x-rate-limit-reset", time.time() + 900))
                        break
                    if r.status in (401, 403):
                        self.status.available, self.status.reason = False, f"HTTP {r.status}: token rejected or plan lacks recent search"
                        break
                    payload = await r.json(content_type=None)
                    if int(r.headers.get("x-rate-limit-remaining", "1")) <= 0:
                        self.next_ok = float(r.headers.get("x-rate-limit-reset", time.time() + 900))
            except Exception:
                self.status.errors += 1
                continue
            tw = self.parse(payload, keys)
            if (payload.get("meta") or {}).get("newest_id"):
                self.since[q] = payload["meta"]["newest_id"]
            got += tw
        self.status.tweets += len(got)
        self.next_ok = max(self.next_ok, time.time() + self.min_interval_s)
        return got
