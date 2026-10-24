"""Omega engine, layer 1: meme / micro-cap universe discovery, real trade prints, and a safety gate.

Sources (all public, no keys; probed reachable from this environment on 2026-10-24):

* **pump.fun bonding curves, live.** ``logsSubscribe`` on the public Solana RPC websocket for the pump program. Every swap emits an
  Anchor ``TradeEvent`` (mint, SOL and token amounts, side, trader, virtual/real reserves after the trade, protocol and creator fee in bps).
  That is a complete, exact trade-print feed and the full AMM state, so a paper fill can be priced on the same curve the venue uses.
  ``Program data`` lines are attributed with the log's invoke stack: only events emitted by the pump program itself count (any other
  program in the same transaction can print look-alike bytes).
* **Gate.io spot meme pairs** (CLOB): ``spot.book_ticker`` + ``spot.trades`` websockets; lot rules (``amount_precision``,
  ``min_quote_amount``, per-pair fee) from REST, so sizes are exchange-valid.
* **DexScreener** latest token profiles / boosts (REST) for discovery and the token's X handle.
* Not used: Binance (HTTP 451 from this host), PumpPortal trades (needs a funded API key).

Safety gate (``SafetyGate.evaluate`` is pure; ``SafetyChecker`` gathers the facts from the Solana RPC): mint authority revoked, freeze
authority revoked, holder concentration outside the curve, curve liquidity, age, fee cap, creator not dumping. LP lock does not apply to a
bonding curve (there is no LP to pull: the program holds the reserves), and is reported as such rather than faked.

Memory: every per-token structure is a bounded ring; the universe is an LRU with a hard cap and a staleness TTL.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import math
import struct
import time
from collections import OrderedDict, deque
from dataclasses import asdict, dataclass, field
from typing import Callable, Deque, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
from numba import njit

PUMP_PROGRAM = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
SOLANA_WS = "wss://api.mainnet-beta.solana.com"
SOLANA_RPC = "https://api.mainnet-beta.solana.com"
GATE_WS = "wss://api.gateio.ws/ws/v4/"
GATE_REST = "https://api.gateio.ws/api/v4"
DEXSCREENER = "https://api.dexscreener.com"
TRADE_EVENT = bytes.fromhex("bddb7fd34ee661ee")          # sha256("event:TradeEvent")[:8]
CREATE_EVENT = bytes.fromhex("1b72a94ddeeb6376")         # sha256("event:CreateEvent")[:8]
COMPLETE_EVENT = bytes.fromhex("5f72619cd42e9808")       # sha256("event:CompleteEvent")[:8]  (curve finished -> migrates)
LAMPORTS = 1e9
PUMP_DECIMALS = 6

_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def b58encode(b: bytes) -> str:
    n = int.from_bytes(b, "big")
    s = ""
    while n:
        n, r = divmod(n, 58)
        s = _B58[r] + s
    return "1" * (len(b) - len(b.lstrip(b"\0"))) + s


# ================================================================================ normalized events
@dataclass
class TradePrint:
    t: float                       # local receive time (engine clock)
    venue: str                     # pump | gate
    key: str                       # mint (pump) or currency pair (gate)
    side: int                      # +1 buy / -1 sell (taker side)
    qty: float                     # base units (tokens)
    quote: float                   # quote units (SOL for pump, USDT for gate) excluding fees
    price: float                   # executed average price, quote per token
    post_price: float = float("nan")   # curve price after the trade (pump), quote per token
    v_quote: float = float("nan")      # virtual SOL reserves after the trade (pump)
    v_base: float = float("nan")       # virtual token reserves after the trade (pump)
    real_quote: float = float("nan")   # real SOL in the curve (pump): what a seller can actually get out
    fee_bps: float = float("nan")      # protocol + creator fee, bps of the quote amount
    user: str = ""
    ts_chain: float = float("nan")
    sig: str = ""


@dataclass
class TokenCreated:
    t: float
    mint: str
    name: str
    symbol: str
    creator: str
    uri: str = ""


@dataclass
class Quote:
    t: float
    venue: str
    key: str
    bid: float
    ask: float
    bq: float
    aq: float


# ================================================================================ pump.fun log decoding
def _decode_trade(b: bytes) -> Optional[dict]:
    if len(b) < 8 + 32 + 16 + 1 + 32 + 40 + 32 + 16 or b[:8] != TRADE_EVENT:
        return None
    o = 8
    mint = b58encode(b[o:o + 32]); o += 32
    sol, tok = struct.unpack_from("<QQ", b, o); o += 16
    is_buy = b[o]; o += 1
    user = b58encode(b[o:o + 32]); o += 32
    ts, vs, vt, rs, rt = struct.unpack_from("<qQQQQ", b, o); o += 40
    o += 32                                                # fee recipient
    fbps, fee = struct.unpack_from("<QQ", b, o); o += 16
    cbps = 0
    if len(b) >= o + 32 + 16:
        o += 32                                            # creator
        cbps, _cfee = struct.unpack_from("<QQ", b, o)
    return {"mint": mint, "sol": sol / LAMPORTS, "tok": tok / 10 ** PUMP_DECIMALS, "is_buy": bool(is_buy), "user": user, "ts": float(ts),
            "vsol": vs / LAMPORTS, "vtok": vt / 10 ** PUMP_DECIMALS, "rsol": rs / LAMPORTS, "fee_bps": float(fbps + cbps)}


def _decode_create(b: bytes) -> Optional[dict]:
    """CreateEvent: name, symbol, uri (borsh strings), mint, bonding curve, user."""
    if b[:8] != CREATE_EVENT:
        return None
    try:
        o = 8
        out = {}
        for k in ("name", "symbol", "uri"):
            (n,) = struct.unpack_from("<I", b, o); o += 4
            out[k] = b[o:o + n].decode("utf-8", "replace"); o += n
        out["mint"] = b58encode(b[o:o + 32]); o += 32
        o += 32                                            # bonding curve
        out["creator"] = b58encode(b[o:o + 32])
        return out
    except (struct.error, IndexError):
        return None


def plausible_trade(d: dict, tol: float = 0.25) -> bool:
    """Reject garbage: zero reserves / amounts, or an executed price that is not near the curve price (a real swap of size s on a
    constant-product curve executes between the pre- and post-trade price)."""
    if d["sol"] <= 0 or d["tok"] <= 0 or d["vsol"] <= 0 or d["vtok"] <= 0:
        return False
    post = d["vsol"] / d["vtok"]
    if d["is_buy"]:
        pre = (d["vsol"] - d["sol"]) / (d["vtok"] + d["tok"])
    else:
        pre = (d["vsol"] + d["sol"]) / (d["vtok"] - d["tok"]) if d["vtok"] > d["tok"] else post
    lo, hi = min(pre, post), max(pre, post)
    ex = d["sol"] / d["tok"]
    return lo * (1 - tol) <= ex <= hi * (1 + tol)


def parse_pump_logs(logs: Sequence[str], sig: str, t: float) -> Tuple[List[TradePrint], List[TokenCreated], List[str]]:
    """Trade prints, creations and completed curves emitted *by the pump program* in one transaction's logs."""
    stack: List[str] = []
    prints: List[TradePrint] = []
    creates: List[TokenCreated] = []
    completes: List[str] = []
    for line in logs:
        if line.startswith("Program ") and " invoke [" in line:
            stack.append(line.split(" ", 2)[1])
            continue
        if line.startswith("Program ") and (line.endswith(" success") or " failed" in line):
            if stack and line.split(" ", 2)[1] == stack[-1]:
                stack.pop()
            continue
        if not line.startswith("Program data: ") or not stack or stack[-1] != PUMP_PROGRAM:
            continue
        try:
            b = base64.b64decode(line[14:])
        except Exception:
            continue
        head = b[:8]
        if head == TRADE_EVENT:
            d = _decode_trade(b)
            if d and plausible_trade(d):
                prints.append(TradePrint(t=t, venue="pump", key=d["mint"], side=1 if d["is_buy"] else -1, qty=d["tok"], quote=d["sol"],
                                         price=d["sol"] / d["tok"], post_price=d["vsol"] / d["vtok"], v_quote=d["vsol"], v_base=d["vtok"],
                                         real_quote=d["rsol"], fee_bps=d["fee_bps"], user=d["user"], ts_chain=d["ts"], sig=sig))
        elif head == CREATE_EVENT:
            c = _decode_create(b)
            if c:
                creates.append(TokenCreated(t, c["mint"], c["name"][:40], c["symbol"][:16], c["creator"], c["uri"][:200]))
        elif head == COMPLETE_EVENT and len(b) >= 8 + 64:
            completes.append(b58encode(b[8 + 32:8 + 64]))      # (user, mint, ...): the mint is the second key
    return prints, creates, completes


# ================================================================================ bonding-curve math (pump.fun constant product)
def curve_buy(v_sol: float, v_tok: float, sol_in: float, fee_bps: float) -> Tuple[float, float, float]:
    """Spend ``sol_in`` SOL in total (fee included): -> (tokens out, fee paid, new v_sol). The fee is taken on top of the curve amount."""
    net = sol_in / (1.0 + fee_bps / 1e4)
    tok = v_tok - v_sol * v_tok / (v_sol + net)
    return tok, sol_in - net, v_sol + net


def curve_sell(v_sol: float, v_tok: float, tok_in: float, fee_bps: float) -> Tuple[float, float, float]:
    """Sell ``tok_in`` tokens: -> (SOL received after fee, fee paid, new v_sol)."""
    gross = v_sol - v_sol * v_tok / (v_tok + tok_in)
    fee = gross * fee_bps / 1e4
    return gross - fee, fee, v_sol - gross


# ================================================================================ per-token activity (bounded)
RING = 512


@njit(cache=True)
def window_stats(ts, side, quote, px, uid, n, now, w):
    """Flow over the last ``w`` seconds of a logical-index ring (``n`` writes, capacity ``len(ts)``):
    (count, buys, sells, buy_quote, sell_quote, unique traders, first price, last price)."""
    cap = ts.shape[0]
    lo = max(0, n - cap)
    buys = 0.0
    sells = 0.0
    bq = 0.0
    sq = 0.0
    p_first = np.nan
    p_last = np.nan
    ids = np.empty(min(n, cap), np.int64)
    m = 0
    k = n - 1
    while k >= lo:
        i = k % cap
        if ts[i] < now - w:
            break
        if side[i] > 0:
            buys += 1.0
            bq += quote[i]
        else:
            sells += 1.0
            sq += quote[i]
        ids[m] = uid[i]
        m += 1
        p_first = px[i]
        if p_last != p_last:
            p_last = px[i]
        k -= 1
    uniq = 0
    if m > 0:
        srt = np.sort(ids[:m])
        uniq = 1
        for j in range(1, m):
            if srt[j] != srt[j - 1]:
                uniq += 1
    return buys + sells, buys, sells, bq, sq, uniq, p_first, p_last


@dataclass
class TokenState:
    key: str
    venue: str
    symbol: str = ""
    name: str = ""
    creator: str = ""
    created_t: float = float("nan")
    first_seen: float = 0.0
    last_t: float = 0.0
    twitter: str = ""
    # live curve state (pump) / last quote (gate)
    v_quote: float = float("nan")
    v_base: float = float("nan")
    real_quote: float = float("nan")
    fee_bps: float = float("nan")
    last_price: float = float("nan")
    bid: float = float("nan")
    ask: float = float("nan")
    bq: float = 0.0
    aq: float = 0.0
    complete: bool = False
    creator_bought: float = 0.0             # tokens the creator bought after creation (seen in prints)
    creator_sold: float = 0.0               # tokens the creator has sold (pump): the classic rug tell
    safety: Optional[dict] = None
    lot: float = 1e-6                       # smallest order increment in base units
    min_notional: float = 1.0               # quote-USD
    taker_fee_bps: float = float("nan")
    # fixed-size ring of recent prints (numpy, logical index ``n_prints``): memory per token is constant
    r_t: np.ndarray = field(default_factory=lambda: np.zeros(RING))
    r_side: np.ndarray = field(default_factory=lambda: np.zeros(RING, np.int8))
    r_quote: np.ndarray = field(default_factory=lambda: np.zeros(RING))
    r_px: np.ndarray = field(default_factory=lambda: np.zeros(RING))
    r_uid: np.ndarray = field(default_factory=lambda: np.zeros(RING, np.int64))
    n_prints: int = 0

    def push(self, t: float, side: int, quote: float, px: float, user: str) -> None:
        i = self.n_prints % RING
        self.r_t[i], self.r_side[i], self.r_quote[i], self.r_px[i] = t, side, quote, px
        self.r_uid[i] = int.from_bytes(hashlib.blake2b(user.encode(), digest_size=8).digest(), "little", signed=True)
        self.n_prints += 1

    def mid(self) -> float:
        if self.venue == "pump":
            return self.v_quote / self.v_base if self.v_base == self.v_base and self.v_base > 0 else self.last_price
        return 0.5 * (self.bid + self.ask) if self.bid > 0 and self.ask > 0 else self.last_price

    def window(self, now: float, w: float) -> dict:
        """Flow statistics over the last ``w`` seconds (numba kernel over the ring)."""
        n, buys, sells, bq, sq, uniq, p0, p1 = window_stats(self.r_t, self.r_side, self.r_quote, self.r_px, self.r_uid, self.n_prints, now, w)
        return {"n": n, "buys": buys, "sells": sells, "buy_quote": bq, "sell_quote": sq, "net_quote": bq - sq, "unique": int(uniq),
                "ret": (p1 / p0 - 1.0) if p0 == p0 and p0 > 0 else 0.0}


class Universe:
    """LRU of tokens with a hard cap; a token with an open position is never evicted (``pinned``)."""

    def __init__(self, max_tokens: int = 3000, ttl_s: float = 1800.0):
        self.max_tokens, self.ttl_s = max_tokens, ttl_s
        self.tokens: "OrderedDict[str, TokenState]" = OrderedDict()
        self.pinned: set = set()
        self.evicted = 0

    def get(self, key: str, venue: str, now: float) -> TokenState:
        st = self.tokens.get(key)
        if st is None:
            st = TokenState(key=key, venue=venue, first_seen=now, last_t=now)
            self.tokens[key] = st
            self._trim(now)
        else:
            self.tokens.move_to_end(key)
        return st

    def _trim(self, now: float) -> None:
        while len(self.tokens) > self.max_tokens:
            for k in self.tokens:                           # oldest first
                if k not in self.pinned:
                    del self.tokens[k]
                    self.evicted += 1
                    break
            else:
                break

    def expire(self, now: float) -> int:
        dead = [k for k, s in self.tokens.items() if now - s.last_t > self.ttl_s and k not in self.pinned]
        for k in dead:
            del self.tokens[k]
        self.evicted += len(dead)
        return len(dead)

    def on_print(self, p: TradePrint) -> TokenState:
        st = self.get(p.key, p.venue, p.t)
        st.last_t = p.t
        st.last_price = p.price
        if p.venue == "pump":
            st.v_quote, st.v_base, st.real_quote = p.v_quote, p.v_base, p.real_quote
            if p.fee_bps == p.fee_bps:
                st.fee_bps = st.taker_fee_bps = p.fee_bps
            if st.creator and p.user == st.creator:
                if p.side > 0:
                    st.creator_bought += p.qty
                else:
                    st.creator_sold += p.qty
        st.push(p.t, p.side, p.quote, p.price if p.venue == "gate" else (p.post_price if p.post_price == p.post_price else p.price), p.user)
        return st

    def on_create(self, c: TokenCreated) -> TokenState:
        st = self.get(c.mint, "pump", c.t)
        st.symbol, st.name, st.creator, st.created_t = c.symbol, c.name, c.creator, c.t
        return st

    def on_quote(self, q: Quote) -> TokenState:
        st = self.get(q.key, q.venue, q.t)
        st.bid, st.ask, st.bq, st.aq, st.last_t = q.bid, q.ask, q.bq, q.aq, q.t
        return st


# ================================================================================ safety gate
@dataclass
class SafetyConfig:
    require_mint_revoked: bool = True
    require_freeze_revoked: bool = True
    max_top10_share: float = 0.35          # of supply, excluding the bonding curve / pool account
    min_real_quote: float = 3.0            # SOL actually in the curve (what sellers can get out)
    min_age_s: float = 60.0                # skip the first minute (sniper bundles, dev's own buys)
    max_fee_bps: float = 200.0
    max_creator_sold_share: float = 0.5    # creator has sold more than half of what we have seen him hold -> rug pattern
    max_spread_bps: float = 150.0          # CLOB pairs
    max_tax_pct: float = 5.0               # EVM buy/sell tax (honeypot.is), when checked


@dataclass
class SafetyReport:
    ok: bool
    reasons: List[str]
    facts: dict

    def as_dict(self) -> dict:
        return asdict(self)


class SafetyGate:
    def __init__(self, cfg: Optional[SafetyConfig] = None):
        self.cfg = cfg or SafetyConfig()

    def evaluate(self, st: TokenState, facts: dict, now: float) -> SafetyReport:
        """``facts``: whatever was verified on chain (``mint_authority``, ``freeze_authority``, ``top10_share``, ``tax_buy``/``tax_sell``,
        ``is_honeypot``). Missing facts that a rule needs are a failure, never a pass."""
        c, why = self.cfg, []
        if st.venue == "pump":
            if c.require_mint_revoked and facts.get("mint_authority", "unknown") is not None:
                why.append(f"mint authority {'unknown' if facts.get('mint_authority', 'unknown') == 'unknown' else 'active'}")
            if c.require_freeze_revoked and facts.get("freeze_authority", "unknown") is not None:
                why.append(f"freeze authority {'unknown' if facts.get('freeze_authority', 'unknown') == 'unknown' else 'active'}")
            top = facts.get("top10_share")
            if top is None or top > c.max_top10_share:
                why.append("holder concentration " + ("unknown" if top is None else f"{top:.0%} > {c.max_top10_share:.0%}"))
            if not (st.real_quote == st.real_quote and st.real_quote >= c.min_real_quote):
                why.append(f"curve liquidity {st.real_quote:.2f} SOL < {c.min_real_quote}")
            if st.complete:
                why.append("curve complete (migrating)")
            age = now - (st.created_t if st.created_t == st.created_t else st.first_seen)
            if age < c.min_age_s:
                why.append(f"age {age:.0f}s < {c.min_age_s:.0f}s")
            if st.creator_sold > 0 and st.creator_sold > c.max_creator_sold_share * max(st.creator_bought, 1e-9):
                why.append("creator dumping")
            facts.setdefault("lp_lock", "n/a: bonding curve holds the reserves (no LP to pull)")
        else:
            if st.bid > 0 and st.ask > 0:
                spr = (st.ask - st.bid) / (0.5 * (st.ask + st.bid)) * 1e4
                if spr > c.max_spread_bps:
                    why.append(f"spread {spr:.0f} bps > {c.max_spread_bps:.0f}")
            else:
                why.append("no two-sided quote")
        if facts.get("is_honeypot") or facts.get("rugged"):
            why.append("honeypot / rugged")
        for risk in facts.get("rugcheck_danger") or []:
            why.append(f"rugcheck: {risk}")
        for k in ("tax_buy", "tax_sell"):
            if facts.get(k) is not None and facts[k] > c.max_tax_pct:
                why.append(f"{k} {facts[k]:.1f}% > {c.max_tax_pct}%")
        if st.fee_bps == st.fee_bps and st.fee_bps > c.max_fee_bps:
            why.append(f"fee {st.fee_bps:.0f} bps > {c.max_fee_bps:.0f}")
        return SafetyReport(not why, why, facts)


RUGCHECK = "https://api.rugcheck.xyz/v1/tokens"
SOLANA_RPC_FALLBACK = "https://solana-rpc.publicnode.com"


def holder_concentration(report: dict) -> Optional[float]:
    """Top-10 share of supply held outside pools and lockers (RugCheck ``/report``): AMM / bonding-curve / locker accounts and every
    market's own accounts are excluded, the creator is kept."""
    hold = report.get("topHolders")
    if hold is None:
        return None
    known = report.get("knownAccounts") or {}
    pools = {a for a, k in known.items() if (k or {}).get("type") in ("AMM", "LOCKER")}
    for m in report.get("markets") or []:
        for k in ("pubkey", "liquidityA", "liquidityB", "liquidityAAccount", "liquidityBAccount"):
            v = m.get(k)
            if isinstance(v, dict):                          # some fields are account objects
                v = v.get("pubkey") or v.get("owner")
            if isinstance(v, str) and v:
                pools.add(v)
    pct = [float(h.get("pct") or 0.0) for h in hold if h.get("owner") not in pools and h.get("address") not in pools]
    return sum(sorted(pct, reverse=True)[:10]) / 100.0


class SafetyChecker:
    """Gathers safety facts for a pump.fun mint.

    * mint / freeze authority: the mint account itself, read from the Solana RPC (``getAccountInfo``, jsonParsed; Token and Token-2022);
    * holder concentration and RugCheck's own risk list: ``api.rugcheck.xyz`` ``/report`` (the public RPC refuses ``getTokenLargestAccounts``
      with HTTP 429 from shared IPs, measured 2026-10-24).
    Results are cached; calls are spaced to ``max_rps``. A failed lookup leaves the fact missing, and the gate fails a token with a missing fact."""

    def __init__(self, session, rpc: Sequence[str] = (SOLANA_RPC, SOLANA_RPC_FALLBACK), max_rps: float = 2.0, cache_s: float = 600.0):
        self.session, self.rpcs = session, list(rpc)
        self.min_gap = 1.0 / max_rps
        self.cache: "OrderedDict[str, Tuple[float, dict]]" = OrderedDict()
        self.cache_s = cache_s
        self._last = 0.0
        self._lock = asyncio.Lock()
        self.calls = self.errors = 0

    async def _pace(self) -> None:
        async with self._lock:
            wait = self._last + self.min_gap - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self._last = time.monotonic()

    async def _rpc(self, method: str, params: list):
        err = None
        for url in self.rpcs:
            await self._pace()
            self.calls += 1
            try:
                async with self.session.post(url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}) as r:
                    d = await r.json(content_type=None)
                if "error" not in d:
                    return d["result"]
                err = d["error"]
            except Exception as e:
                err = e
        raise RuntimeError(str(err)[:120])

    async def facts(self, mint: str) -> dict:
        hit = self.cache.get(mint)
        if hit and time.monotonic() - hit[0] < self.cache_s:
            return hit[1]
        f: dict = {}
        try:
            acc = await self._rpc("getAccountInfo", [mint, {"encoding": "jsonParsed"}])
            info = (((acc or {}).get("value") or {}).get("data") or {}).get("parsed", {}).get("info", {})
            if info:
                f["mint_authority"] = info.get("mintAuthority")
                f["freeze_authority"] = info.get("freezeAuthority")
        except Exception as e:
            self.errors += 1
            f["error_rpc"] = repr(e)[:120]
        try:
            await self._pace()
            self.calls += 1
            async with self.session.get(f"{RUGCHECK}/{mint}/report") as r:
                if r.status != 200:
                    raise RuntimeError(f"rugcheck HTTP {r.status}")
                rep = await r.json(content_type=None)
            f["top10_share"] = holder_concentration(rep)
            f["rugcheck_danger"] = [x.get("name") for x in rep.get("risks") or [] if x.get("level") == "danger"]
            f["rugged"] = bool(rep.get("rugged"))
            if "mint_authority" not in f:                      # RPC failed: fall back to RugCheck's reading of the same account
                f["mint_authority"], f["freeze_authority"] = rep.get("mintAuthority"), rep.get("freezeAuthority")
                f["authority_source"] = "rugcheck"
        except Exception as e:
            self.errors += 1
            f["error_rugcheck"] = repr(e)[:120]
        self.cache[mint] = (time.monotonic(), f)
        while len(self.cache) > 5000:
            self.cache.popitem(last=False)
        return f


# ================================================================================ feeds (async, reconnecting)
@dataclass
class FeedStats:
    msgs: int = 0
    prints: int = 0
    creates: int = 0
    reconnects: int = 0
    errors: int = 0
    last_t: float = 0.0


async def solana_pump_feed(on_print: Callable[[TradePrint], None], on_create: Callable[[TokenCreated], None], on_complete: Callable[[str, float], None],
                           stop: asyncio.Event, clock: Callable[[], float] = time.time, url: str = SOLANA_WS, stats: Optional[FeedStats] = None) -> FeedStats:
    import orjson
    import websockets
    st = stats or FeedStats()
    backoff = 1.0
    while not stop.is_set():
        try:
            async with websockets.connect(url, open_timeout=15, max_size=2 ** 24, ping_interval=20) as ws:
                await ws.send(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "logsSubscribe", "params": [{"mentions": [PUMP_PROGRAM]}, {"commitment": "confirmed"}]}))
                backoff = 1.0
                while not stop.is_set():
                    raw = await asyncio.wait_for(ws.recv(), timeout=30)
                    st.msgs += 1
                    m = orjson.loads(raw)
                    v = ((m.get("params") or {}).get("result") or {}).get("value")
                    if not v or v.get("err"):
                        continue
                    now = clock()
                    st.last_t = now
                    prints, creates, completes = parse_pump_logs(v.get("logs") or [], v.get("signature", ""), now)
                    for c in creates:
                        st.creates += 1
                        on_create(c)
                    for p in prints:
                        st.prints += 1
                        on_print(p)
                    for mint in completes:
                        on_complete(mint, now)
        except asyncio.CancelledError:
            raise
        except Exception:
            st.errors += 1
            st.reconnects += 1
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)
    return st


async def gate_feed(pairs: Sequence[str], on_quote: Callable[[Quote], None], on_print: Callable[[TradePrint], None], stop: asyncio.Event,
                    clock: Callable[[], float] = time.time, stats: Optional[FeedStats] = None) -> FeedStats:
    import orjson
    import websockets
    st = stats or FeedStats()
    backoff = 1.0
    while not stop.is_set():
        try:
            async with websockets.connect(GATE_WS, open_timeout=15, max_size=2 ** 22, ping_interval=20) as ws:
                ts = int(time.time())
                await ws.send(json.dumps({"time": ts, "channel": "spot.book_ticker", "event": "subscribe", "payload": list(pairs)}))
                await ws.send(json.dumps({"time": ts, "channel": "spot.trades", "event": "subscribe", "payload": list(pairs)}))
                backoff = 1.0
                while not stop.is_set():
                    m = orjson.loads(await asyncio.wait_for(ws.recv(), timeout=30))
                    st.msgs += 1
                    if m.get("event") != "update":
                        continue
                    now = clock()
                    st.last_t = now
                    r = m.get("result") or {}
                    if m.get("channel") == "spot.book_ticker":
                        on_quote(Quote(now, "gate", r["s"], float(r["b"]), float(r["a"]), float(r["B"]), float(r["A"])))
                    elif m.get("channel") == "spot.trades":
                        q, px = float(r["amount"]), float(r["price"])
                        st.prints += 1
                        on_print(TradePrint(now, "gate", r["currency_pair"], 1 if r["side"] == "buy" else -1, q, q * px, px, user=str(r.get("id", "")),
                                            ts_chain=float(r.get("create_time", 0))))
        except asyncio.CancelledError:
            raise
        except Exception:
            st.errors += 1
            st.reconnects += 1
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)
    return st


MEME_BASES = ("PEPE", "WIF", "BONK", "FLOKI", "SHIB", "DOGE", "BOME", "POPCAT", "MEW", "BRETT", "TURBO", "MOG", "NEIRO", "PNUT", "GOAT",
              "FARTCOIN", "SPX", "MOODENG", "TRUMP", "PENGU", "AI16Z", "GIGA", "PONKE", "MYRO", "SLERF", "WEN", "BABYDOGE", "DOGS", "CAT", "MEME")


def gate_meme_universe(max_pairs: int = 40, min_quote_vol: float = 200_000.0, movers: int = 15) -> List[dict]:
    """Gate USDT pairs: the listed meme bases plus the biggest 24 h movers, with exchange lot rules. Sync REST (called at startup)."""
    import urllib.request

    def get(path):
        req = urllib.request.Request(GATE_REST + path, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
        return json.loads(urllib.request.urlopen(req, timeout=30).read())

    tick = {t["currency_pair"]: t for t in get("/spot/tickers") if t["currency_pair"].endswith("_USDT")}
    rules = {p["id"]: p for p in get("/spot/currency_pairs") if p.get("trade_status") == "tradable"}
    liquid = [p for p, t in tick.items() if p in rules and float(t.get("quote_volume") or 0) >= min_quote_vol]
    memes = [p for p in liquid if p.split("_")[0] in MEME_BASES]
    mov = sorted((p for p in liquid if p not in memes), key=lambda p: -abs(float(tick[p].get("change_percentage") or 0)))[:movers]
    out = []
    for p in sorted(memes, key=lambda p: -float(tick[p]["quote_volume"]))[: max_pairs - len(mov)] + mov:
        r = rules[p]
        out.append({"pair": p, "lot": 10 ** -int(r.get("amount_precision", 8)), "min_quote": float(r.get("min_quote_amount") or 1.0),
                    "min_base": float(r.get("min_base_amount") or 0.0), "fee_bps": float(r.get("fee") or 0.2) * 100, "quote_vol": float(tick[p]["quote_volume"]),
                    "meme": p in memes})
    return out


async def dexscreener_poll(session, on_token: Callable[[dict], None], stop: asyncio.Event, every_s: float = 60.0) -> None:
    """Latest token profiles and boosts (Solana): the project's X handle when it lists one."""
    seen: "OrderedDict[str, None]" = OrderedDict()
    while not stop.is_set():
        for path in ("/token-profiles/latest/v1", "/token-boosts/latest/v1"):
            try:
                async with session.get(DEXSCREENER + path) as r:
                    rows = await r.json(content_type=None)
                for p in rows or []:
                    if p.get("chainId") != "solana" or p.get("tokenAddress") in seen:
                        continue
                    seen[p["tokenAddress"]] = None
                    while len(seen) > 5000:
                        seen.popitem(last=False)
                    tw = ""
                    for link in p.get("links") or []:
                        u = (link.get("url") or "")
                        if "x.com/" in u or "twitter.com/" in u:
                            tw = u.rstrip("/").split("/")[-1]
                    on_token({"mint": p["tokenAddress"], "twitter": tw, "source": path.split("/")[1]})
            except Exception:
                pass
        try:
            await asyncio.wait_for(stop.wait(), timeout=every_s)
        except asyncio.TimeoutError:
            pass


async def sol_usd_poll(session, set_price: Callable[[float], None], stop: asyncio.Event, every_s: float = 20.0) -> None:
    while not stop.is_set():
        try:
            async with session.get(GATE_REST + "/spot/tickers", params={"currency_pair": "SOL_USDT"}) as r:
                set_price(float((await r.json(content_type=None))[0]["last"]))
        except Exception:
            pass
        try:
            await asyncio.wait_for(stop.wait(), timeout=every_s)
        except asyncio.TimeoutError:
            pass
