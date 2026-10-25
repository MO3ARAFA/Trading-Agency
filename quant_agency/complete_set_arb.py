"""Phase 13: complete-set (market-rebalancing) arbitrage on Polymarket NegRisk events.

Why this and not another predictor: Phases 1-12 tested every *predictive / latency* edge we could build (BTC lead-lag, cross-venue lag,
sector oracles, maker quoting, funding, basis) and none survived realistic costs. A complete set is different in kind: its payoff does not
depend on any forecast.

* **Buy-set (exhaustive events).** In a NegRisk event exactly one outcome resolves YES. Buying one YES share of *every* outcome costs
  sum(ask_i) + fees and pays exactly 1 USDC at resolution. If that cost is below 1, the difference is locked in at the moment the last leg
  fills. Valid **only** when the listed outcomes are exhaustive: augmented events (placeholder outcomes / "Other", ``negRiskAugmented``)
  are excluded because the winner may be an outcome nobody can buy.
* **No-set (mutually exclusive events).** Buying one NO share of every named outcome pays at least n-1 (at most one named outcome can win;
  if an unnamed one wins it pays n). Valid even for augmented events, as long as only named legs are used.

What can still go wrong, and what this module does about it:
  1. *Legging*: the asks move between seeing them and filling every leg -> the paper executor re-reads every leg's book after a latency
     and fills only what is still profitable at the fresh prices (walking the depth); a second read later measures how fast books move.
  2. *Fees*: per-market taker fee = shares x rate x (p(1-p))^exponent (Polymarket docs); applied per leg per level.
  3. *Depth*: the set size is bounded by the thinnest leg's ladder at a profitable marginal price, never by the top of book alone.
  4. *Resolution risk*: exhaustiveness is checked against ~a year of closed NegRisk events (``resolution_backtest``) and capital is locked
     until the event resolves, so returns are reported per day of lock-up.
  5. *Account risk*: a ``RiskManager`` caps capital per event, total deployed capital, number of events, days to resolution, and has a kill
     file. Paper only: this module never builds, signs or sends an order and reads no credential.
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
RESOLUTION_BUFFER_DAYS = 2.0          # UMA proposal + liveness after the end date


# ================================================================================ fees
def fee_usd(shares: float, p: float, rate: float, exponent: float = 1.0) -> float:
    """Polymarket taker fee: C x feeRate x (p(1-p))^exponent (makers pay nothing)."""
    if rate <= 0.0 or shares <= 0.0:
        return 0.0
    p = min(max(p, 1e-9), 1.0 - 1e-9)
    return shares * rate * (p * (1.0 - p)) ** exponent


# ================================================================================ data model
@dataclass
class Leg:
    question: str
    yes_token: str
    no_token: str
    fee_rate: float = 0.0
    fee_exp: float = 1.0
    min_size: float = 5.0
    tick: float = 0.01
    is_other: bool = False
    fees_enabled: bool = False          # Gamma ``feesEnabled``; the per-market schedule may still say rate 0 (``feeType: zero_fees``)


@dataclass
class Event:
    eid: str
    slug: str
    title: str
    legs: List[Leg]
    augmented: bool
    end_ts: float                       # event end date (wall clock)
    n_markets_total: int                # including closed / inactive ones
    complete: bool                      # every market of the event is a live leg
    volume24: float = 0.0

    @property
    def exhaustive_buyable(self) -> bool:
        """A YES full set is a lock only if the listed outcomes are the whole outcome space and every one of them can be bought."""
        return (not self.augmented) and self.complete and len(self.legs) >= 2 and not any(l.is_other for l in self.legs)


def _f(x, d=0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


def _ts(s) -> Optional[float]:
    if not s:
        return None
    import datetime as dt
    try:
        return dt.datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def parse_event(e: dict) -> Optional[Event]:
    """Gamma event -> Event (None if not a usable NegRisk event)."""
    if not e.get("negRisk") or e.get("closed"):
        return None
    mk = e.get("markets", []) or []
    legs: List[Leg] = []
    settled_no = 0                      # markets already closed as NO (e.g. an eliminated candidate): not needed for a full set
    for m in mk:
        if m.get("closed"):
            settled_no += resolved_yes(m) is False
            continue
        if not m.get("acceptingOrders") or not m.get("enableOrderBook") or not m.get("clobTokenIds"):
            continue
        try:
            toks = json.loads(m["clobTokenIds"]) if isinstance(m["clobTokenIds"], str) else m["clobTokenIds"]
        except Exception:
            continue
        fs = m.get("feeSchedule") or {}
        rate = _f(fs.get("rate")) if m.get("feesEnabled") else 0.0
        legs.append(Leg(question=(m.get("question") or "")[:140], yes_token=str(toks[0]), no_token=str(toks[1]), fee_rate=rate,
                        fee_exp=_f(fs.get("exponent"), 1.0) or 1.0, min_size=_f(m.get("orderMinSize"), 5.0) or 5.0,
                        tick=_f(m.get("orderPriceMinTickSize"), 0.01) or 0.01, is_other=bool(m.get("negRiskOther")),
                        fees_enabled=bool(m.get("feesEnabled"))))
    end = _ts(e.get("endDate"))
    if len(legs) < 2 or end is None:
        return None
    return Event(eid=str(e.get("id")), slug=e.get("slug", ""), title=(e.get("title") or "")[:140], legs=legs,
                 augmented=bool(e.get("negRiskAugmented")), end_ts=end, n_markets_total=len(mk), complete=len(legs) + settled_no == len(mk),
                 volume24=_f(e.get("volume24hr")))


# ================================================================================ order-book walk
Ladder = List[Tuple[float, float]]           # [(price, size)] best first


def ladder_from_clob(asks: Sequence[dict]) -> Ladder:
    """CLOB /books returns asks sorted from the worst (highest) price to the best: reverse and parse."""
    out = [(float(a["price"]), float(a["size"])) for a in asks if float(a.get("size", 0)) > 0]
    out.sort(key=lambda x: x[0])
    return out


@dataclass
class SetFill:
    sets: float                   # complete sets bought
    cost: float                   # USDC spent on shares, all legs
    fees: float                   # USDC taker fees, all legs
    payout: float                 # guaranteed payout of the sets (1 per YES set, n-1 per NO set)
    worst_marginal: float         # net margin of the last (most expensive) set
    legs_vwap: List[float]
    takes: List[Dict[float, float]] = field(default_factory=list)   # per leg: price -> shares taken at that level

    @property
    def net(self) -> float:
        return self.payout - self.cost - self.fees

    @property
    def capital(self) -> float:
        return self.cost + self.fees


def walk_sets(ladders: Sequence[Ladder], fee_params: Sequence[Tuple[float, float]], payout_per_set: float, min_marginal: float,
              max_capital: float = float("inf"), max_sets: float = float("inf")) -> SetFill:
    """Buy complete sets across ``ladders`` (one per leg, best price first) while the *marginal* set still nets >= ``min_marginal``.

    Each step takes the largest quantity available at every leg's current level, so the marginal price is exact. Capital and set caps
    bind exactly (the last step is cut to fit)."""
    n = len(ladders)
    if n == 0 or any(len(l) == 0 for l in ladders):
        return SetFill(0.0, 0.0, 0.0, 0.0, float("nan"), [float("nan")] * n, [{} for _ in range(n)])
    idx = [0] * n
    takes: List[Dict[float, float]] = [defaultdict(float) for _ in range(n)]
    left = [ladders[i][0][1] for i in range(n)]
    sets = cost = fees = 0.0
    spent = [0.0] * n
    worst = float("nan")
    while True:
        prices = [ladders[i][idx[i]][0] for i in range(n)]
        unit_fee = sum(fee_usd(1.0, p, r, e) for p, (r, e) in zip(prices, fee_params))
        unit_cost = sum(prices)
        marginal = payout_per_set - unit_cost - unit_fee
        if marginal < min_marginal:
            break
        q = min(left)
        q = min(q, max_sets - sets)
        cap_left = max_capital - (cost + fees)
        if unit_cost + unit_fee > 0:
            q = min(q, cap_left / (unit_cost + unit_fee))
        if q <= 1e-9:
            break
        sets += q
        cost += q * unit_cost
        fees += q * unit_fee
        for i in range(n):
            spent[i] += q * prices[i]
            left[i] -= q
            takes[i][prices[i]] += q
        worst = marginal
        if sets >= max_sets - 1e-9 or (cost + fees) >= max_capital - 1e-9:
            break
        done = False
        for i in range(n):
            if left[i] <= 1e-9:
                idx[i] += 1
                if idx[i] >= len(ladders[i]):
                    done = True
                    break
                left[i] = ladders[i][idx[i]][1]
        if done:
            break
    return SetFill(sets, cost, fees, sets * payout_per_set, worst, [s / sets if sets > 0 else float("nan") for s in spent], [dict(t) for t in takes])


# ================================================================================ opportunity evaluation
@dataclass
class CsaConfig:
    min_marginal: float = 0.005           # USDC per set: the last set bought must still clear half a cent after fees
    min_return: float = 0.004             # net / capital of the whole fill
    min_set_shares: float = 5.0           # every leg order must be >= the market's minimum size (5 shares)
    max_days: float = 60.0                # capital lock-up limit (end date + resolution buffer)
    min_annualized: float = 0.10          # net return per year of lock-up
    use_no_sets: bool = True
    latency_s: float = 0.5                # paper: wait this long, re-read the books, fill only what is still profitable
    recheck_s: float = 3.0                # second read: how often does the opportunity survive a slower execution?
    sweep_interval_s: float = 30.0
    rediscover_s: float = 600.0
    batch: int = 450
    max_book_age_s: float = 30.0
    # slug families whose listed outcomes are not exhaustive in practice: in 47,180 closed plain NegRisk events (Jul-Oct 2026) the only
    # YES-set total losses were NFL "highest scoring quarter" (ties) and tennis "exact score" events (resolution_backtest)
    yes_set_exclude: Tuple[str, ...] = ("highest-scoring", "exact-score")
    # Fee uncertainty: Gamma marks many fee-enabled markets ``zero_fees`` (rate 0) while the public docs list category taker rates up to
    # 0.05 (0.07 crypto). ``fee_stress_rate`` > 0 trades as if every fee-enabled leg charged at least that rate; every opportunity also
    # logs its net under ``report_stress_rate`` so the two readings can be compared on the same fills.
    fee_stress_rate: float = 0.0
    report_stress_rate: float = 0.05


@dataclass
class Opportunity:
    t: float
    eid: str
    title: str
    kind: str                             # yes_set | no_set
    n_legs: int
    fill: SetFill
    days: float
    tokens: List[str]
    net_stressed: float = float("nan")    # net if every fee-enabled leg paid ``report_stress_rate``

    @property
    def ret(self) -> float:
        return self.fill.net / self.fill.capital if self.fill.capital > 0 else float("nan")

    @property
    def annualized(self) -> float:
        return self.ret * 365.0 / max(self.days, 0.5)

    def row(self) -> dict:
        f = self.fill
        return {"t": self.t, "eid": self.eid, "title": self.title, "kind": self.kind, "n_legs": self.n_legs, "sets": f.sets, "cost": f.cost, "fees": f.fees,
                "payout": f.payout, "net": f.net, "ret": self.ret, "days": self.days, "annualized": self.annualized, "worst_marginal": f.worst_marginal,
                "net_stressed": self.net_stressed, "ret_stressed": self.net_stressed / f.capital if f.capital > 0 else float("nan")}


def leg_fee_params(legs: Sequence[Leg], stress: float) -> List[Tuple[float, float]]:
    return [(max(l.fee_rate, stress) if l.fees_enabled else l.fee_rate, l.fee_exp) for l in legs]


def fees_on_takes(fill: SetFill, params: Sequence[Tuple[float, float]]) -> float:
    """Fees the same fill would pay under other fee parameters (exact per level)."""
    return sum(fee_usd(q, p, r, e) for tk, (r, e) in zip(fill.takes, params) for p, q in tk.items())


def evaluate_event(ev: Event, books: Dict[str, Ladder], cfg: CsaConfig, now_wall: float, max_capital: float = float("inf")) -> List[Opportunity]:
    """All profitable set trades available in ``ev`` right now (YES-set if exhaustive, NO-set always), sized by depth and ``max_capital``."""
    out: List[Opportunity] = []
    days = (ev.end_ts - now_wall) / 86400.0 + RESOLUTION_BUFFER_DAYS
    if days > cfg.max_days or days <= 0:
        return out
    named = [l for l in ev.legs if not l.is_other]
    cands = []
    if ev.exhaustive_buyable and not any(x in ev.slug for x in cfg.yes_set_exclude):
        cands.append(("yes_set", named, [l.yes_token for l in named], 1.0))
    if cfg.use_no_sets and len(named) >= 2:
        cands.append(("no_set", named, [l.no_token for l in named], float(len(named) - 1)))
    for kind, legs, toks, payout in cands:
        lads = [books.get(t) for t in toks]
        if any(not l for l in lads):
            continue
        fill = walk_sets(lads, leg_fee_params(legs, cfg.fee_stress_rate), payout, cfg.min_marginal, max_capital=max_capital)
        if fill.sets < max(cfg.min_set_shares, max(l.min_size for l in legs)):
            continue
        stressed = fill.payout - fill.cost - fees_on_takes(fill, leg_fee_params(legs, cfg.report_stress_rate))
        op = Opportunity(now_wall, ev.eid, ev.title, kind, len(legs), fill, days, toks, stressed)
        if op.ret >= cfg.min_return and op.annualized >= cfg.min_annualized:
            out.append(op)
    return out


# ================================================================================ risk and ledger
@dataclass
class Position:
    pid: int
    eid: str
    title: str
    kind: str
    sets: float
    capital: float
    payout: float
    t_open: float
    end_ts: float
    status: str = "open"                  # open | settled | void
    pnl: float = 0.0


@dataclass
class RiskLimits:
    bankroll: float = 100.0
    max_per_event: float = 25.0
    max_deployed: float = 100.0
    max_open_events: int = 8
    max_days: float = 60.0
    kill_file: str = "runs/p13/KILL"


class RiskManager:
    """Every paper (or future live) fill passes through ``approve``. Nothing here can lose money by itself; it only says no."""

    def __init__(self, lim: Optional[RiskLimits] = None):
        self.lim = lim or RiskLimits()
        self.positions: List[Position] = []
        self.refusals: Dict[str, int] = defaultdict(int)
        self.halted = False
        self.halt_reason = ""

    @property
    def deployed(self) -> float:
        return sum(p.capital for p in self.positions if p.status == "open")

    @property
    def cash(self) -> float:
        realised = sum(p.pnl for p in self.positions if p.status != "open")
        return self.lim.bankroll + realised - self.deployed

    def room(self, eid: str) -> float:
        """Capital that one more fill on ``eid`` may use."""
        if self.halted or os.path.exists(self.lim.kill_file):
            return 0.0
        used = sum(p.capital for p in self.positions if p.status == "open" and p.eid == eid)
        return max(0.0, min(self.lim.max_per_event - used, self.lim.max_deployed - self.deployed, self.cash))

    def approve(self, op: Opportunity) -> Tuple[bool, str]:
        if os.path.exists(self.lim.kill_file):
            self.halted, self.halt_reason = True, "kill file"
        if self.halted:
            return False, "halted: " + self.halt_reason
        open_events = {p.eid for p in self.positions if p.status == "open"}
        if op.eid not in open_events and len(open_events) >= self.lim.max_open_events:
            return False, "max_open_events"
        if op.days > self.lim.max_days:
            return False, "lockup_too_long"
        if op.fill.capital > self.room(op.eid) + 1e-9:
            return False, "capital_limit"
        if op.fill.net <= 0:
            return False, "not_profitable"
        return True, "ok"

    def book(self, op: Opportunity) -> Position:
        p = Position(len(self.positions) + 1, op.eid, op.title, op.kind, op.fill.sets, op.fill.capital, op.fill.payout, op.t, op.t + op.days * 86400.0)
        self.positions.append(p)
        return p

    def settle(self, eid: str, payout_override: Optional[float] = None) -> None:
        """At resolution: a valid set pays its guaranteed payout; ``payout_override`` records anything else (e.g. a void / disputed event)."""
        for p in self.positions:
            if p.eid == eid and p.status == "open":
                pay = p.payout if payout_override is None else payout_override
                p.pnl = pay - p.capital
                p.status = "settled" if payout_override is None else "void"

    def halt(self, reason: str) -> None:
        self.halted, self.halt_reason = True, reason


# ================================================================================ resolution backtest
def resolved_yes(m: dict) -> Optional[bool]:
    """True / False when a closed market resolved cleanly to YES / NO; None otherwise (unresolved, 50-50, malformed)."""
    try:
        px = json.loads(m.get("outcomePrices") or "[]")
        y = float(px[0])
    except Exception:
        return None
    if y >= 0.99:
        return True
    if y <= 0.01:
        return False
    return None


def resolution_backtest(events: Iterable[dict], exclude: Sequence[str] = CsaConfig.yes_set_exclude) -> dict:
    """On closed NegRisk events: how often does exactly one *named* outcome resolve YES (the payoff assumption of a YES set), and what did
    one YES set / one NO set actually pay (resolved prices, so 50-50 and several-YES resolutions are counted as the venue paid them)?"""
    res = {"events": 0, "augmented": defaultdict(int), "plain": defaultdict(int), "plain_examples": [], "aug_examples": [],
           "payout": {b: {"n": 0, "yes_lt1": 0, "yes_shortfall": 0.0, "no_lt": 0, "no_shortfall": 0.0, "yes_lt1_after_exclusion": 0,
                          "yes_shortfall_after_exclusion": 0.0, "n_after_exclusion": 0} for b in ("plain", "augmented")},
           "end_min": None, "end_max": None}
    for e in events:
        if not e.get("negRisk"):
            continue
        mk = e.get("markets") or []
        if len(mk) < 2:
            continue
        res["events"] += 1
        end = e.get("endDate") or ""
        res["end_min"] = min(res["end_min"] or end, end)
        res["end_max"] = max(res["end_max"] or end, end)
        named = [m for m in mk if not m.get("negRiskOther")]
        rs = [resolved_yes(m) for m in named]
        if any(r is None for r in rs):
            outcome = "unclean"
        else:
            k = sum(1 for r in rs if r)
            outcome = "exactly_one" if k == 1 else ("none" if k == 0 else "several")
        bucket = "augmented" if e.get("negRiskAugmented") else "plain"
        res[bucket][outcome] += 1
        ex = res["aug_examples"] if bucket == "augmented" else res["plain_examples"]
        if outcome != "exactly_one" and len(ex) < 12:
            ex.append({"slug": e.get("slug"), "outcome": outcome, "n": len(named), "prices": [m.get("outcomePrices") for m in named][:6]})
        try:
            px = [json.loads(m.get("outcomePrices") or "[]") for m in named]
            ys, ns = sum(float(p[0]) for p in px), sum(float(p[1]) for p in px)
        except Exception:
            continue
        b = res["payout"][bucket]
        b["n"] += 1
        b["yes_lt1"] += ys < 1 - 1e-3
        b["yes_shortfall"] += max(0.0, 1.0 - ys)
        b["no_lt"] += ns < len(named) - 1 - 1e-3
        b["no_shortfall"] += max(0.0, len(named) - 1 - ns)
        if not any(x in (e.get("slug") or "") for x in exclude):
            b["n_after_exclusion"] += 1
            b["yes_lt1_after_exclusion"] += ys < 1 - 1e-3
            b["yes_shortfall_after_exclusion"] += max(0.0, 1.0 - ys)
    res["augmented"] = dict(res["augmented"])
    res["plain"] = dict(res["plain"])
    for b in res["payout"].values():               # mean loss per set, in USDC
        for k in ("yes_shortfall", "no_shortfall"):
            b[k + "_per_set"] = b[k] / max(b["n"], 1)
        b["yes_shortfall_after_exclusion_per_set"] = b["yes_shortfall_after_exclusion"] / max(b["n_after_exclusion"], 1)
    return res


_KEEP_M = ("id", "question", "outcomePrices", "negRiskOther", "closed", "clobTokenIds", "umaResolutionStatus", "volumeNum", "groupItemTitle",
           "endDate", "closedTime", "feesEnabled")


def fetch_closed(days: int, out_path: str, end: Optional[float] = None, workers: int = 6) -> int:
    """Closed NegRisk events whose end date falls in the last ``days`` days (one-day Gamma windows, each capped at 2,100 events, so busy
    days are a sample), written compactly (only the fields the backtest uses) to ``out_path``."""
    import datetime as dt
    import urllib.request
    from concurrent.futures import ThreadPoolExecutor
    hi0 = dt.datetime.fromtimestamp(end or time.time(), dt.timezone.utc)

    def get(url):
        for k in range(4):
            try:
                return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=60).read())
            except Exception:
                if k == 3:
                    return []
                time.sleep(2 * (k + 1))

    def day(d):
        hi = hi0 - dt.timedelta(days=d)
        lo = hi - dt.timedelta(days=1)
        got = []
        for off in range(0, 2100, 100):
            part = get(f"{GAMMA}/events?closed=true&limit=100&offset={off}&end_date_min={lo:%Y-%m-%dT%H:%M:%SZ}&end_date_max={hi:%Y-%m-%dT%H:%M:%SZ}")
            got += [{"id": e.get("id"), "slug": e.get("slug"), "title": e.get("title"), "negRisk": True, "negRiskAugmented": e.get("negRiskAugmented"),
                     "endDate": e.get("endDate"), "closedTime": e.get("closedTime"), "tags": [t.get("slug") for t in (e.get("tags") or [])][:8],
                     "markets": [{k: m.get(k) for k in _KEEP_M} for m in (e.get("markets") or [])]} for e in part if e.get("negRisk")]
            if len(part) < 100:
                break
        return got

    out: Dict[str, dict] = {}
    with ThreadPoolExecutor(workers) as ex:
        for got in ex.map(day, range(days)):
            for e in got:
                out[e["id"]] = e
    with open(out_path, "w") as f:
        json.dump(list(out.values()), f)
    return len(out)


def realised_payout(kind: str, sets: float, markets: Sequence[dict], tokens: Sequence[str]) -> Optional[float]:
    """Actual payout of ``sets`` complete sets once every leg's market has closed (None while any leg is unresolved).

    Uses the resolved price of every held token, so a several-YES or 50-50 resolution is paid exactly as the venue would pay it."""
    px: Dict[str, float] = {}
    for m in markets:
        if not m.get("closed"):
            continue
        try:
            toks = json.loads(m["clobTokenIds"]) if isinstance(m.get("clobTokenIds"), str) else m.get("clobTokenIds")
            prices = json.loads(m.get("outcomePrices") or "[]")
            px[str(toks[0])], px[str(toks[1])] = float(prices[0]), float(prices[1])
        except Exception:
            continue
    if any(t not in px for t in tokens):
        return None
    return sets * sum(px[t] for t in tokens)


def settle_run(run_dir: str) -> dict:
    """Mark a finished paper run to the venue's actual resolutions (re-run until every position is settled)."""
    import urllib.request
    log = os.path.join(run_dir, "csa_log.jsonl")
    if not os.path.exists(log):                      # the committed copy (docs/live_runs/phase13/...) drops the per-sweep lines
        log = os.path.join(run_dir, "csa_log_events.jsonl")
    fills = [json.loads(l) for l in open(log) if '"event": "fill"' in l]
    cache: Dict[str, list] = {}
    rows = []
    for f in fills:
        if f["eid"] not in cache:
            req = urllib.request.Request(f"{GAMMA}/events/{f['eid']}", headers={"User-Agent": "Mozilla/5.0"})
            cache[f["eid"]] = json.loads(urllib.request.urlopen(req, timeout=30).read()).get("markets", [])
        pay = realised_payout(f["kind"], f["sets"], cache[f["eid"]], f["tokens"])
        rows.append({"pid": f["pid"], "eid": f["eid"], "title": f["title"], "kind": f["kind"], "capital": f["cost"] + f["fees"], "expected_payout": f["payout"],
                     "realised_payout": pay, "pnl": None if pay is None else pay - f["cost"] - f["fees"]})
    done = [r for r in rows if r["pnl"] is not None]
    res = {"positions": len(rows), "settled": len(done), "pnl_settled": sum(r["pnl"] for r in done),
           "capital_settled": sum(r["capital"] for r in done), "shortfalls": [r for r in done if r["realised_payout"] < r["expected_payout"] - 1e-6], "rows": rows}
    with open(os.path.join(run_dir, "csa_settlement.json"), "w") as fh:
        json.dump(res, fh, indent=1)
    return res


# ================================================================================ live paper runner
async def fetch_universe(session, horizon_days: float = 62.0) -> List[Event]:
    """Every live NegRisk event ending within ``horizon_days``. Gamma caps one listing at offset 2100, so the end-date range is split into
    windows (1 day for the busy first two weeks, 7 days after) that each stay below the cap."""
    import datetime as dt
    import orjson
    now = dt.datetime.now(dt.timezone.utc)
    edges = [now + dt.timedelta(days=d) for d in list(range(0, 14)) + list(range(14, int(horizon_days) + 7, 7))]
    sem = asyncio.Semaphore(6)

    async def window(lo, hi):
        got = []
        for off in range(0, 2100, 100):
            params = {"active": "true", "closed": "false", "limit": 100, "offset": off,
                      "end_date_min": lo.strftime("%Y-%m-%dT%H:%M:%SZ"), "end_date_max": hi.strftime("%Y-%m-%dT%H:%M:%SZ")}
            async with sem:
                async with session.get(f"{GAMMA}/events", params=params) as r:
                    if r.status != 200:
                        break
                    part = orjson.loads(await r.read())
            got += part
            if len(part) < 100:
                break
        return got

    seen: Dict[str, Event] = {}
    for part in await asyncio.gather(*[window(a, b) for a, b in zip(edges[:-1], edges[1:])]):
        for e in part:
            ev = parse_event(e)
            if ev is not None:
                seen[ev.eid] = ev
    return list(seen.values())


async def fetch_books(session, tokens: Sequence[str], batch: int = 450) -> Dict[str, Ladder]:
    """Ask ladders for ``tokens`` (best first) via the CLOB batch endpoint; tokens with no asks are absent."""
    import orjson
    out: Dict[str, Ladder] = {}

    async def one(chunk):
        for k in range(3):
            try:
                async with session.post(f"{CLOB}/books", json=[{"token_id": t} for t in chunk]) as r:
                    if r.status != 200:
                        raise RuntimeError(f"HTTP {r.status}")
                    return orjson.loads(await r.read())
            except Exception:
                if k == 2:
                    return []
                await asyncio.sleep(0.5 * (k + 1))

    chunks = [list(tokens[i:i + batch]) for i in range(0, len(tokens), batch)]
    sem = asyncio.Semaphore(4)

    async def guarded(c):
        async with sem:
            return await one(c)

    for res in await asyncio.gather(*[guarded(c) for c in chunks]):
        for b in res or []:
            lad = ladder_from_clob(b.get("asks") or [])
            if lad:
                out[b["asset_id"]] = lad
    return out


def deplete(books: Dict[str, Ladder], taken: Dict[str, Dict[float, float]]) -> Dict[str, Ladder]:
    """Paper fills do not remove liquidity from the real book, so subtract what we already 'bought' at each price level (for the rest of
    the session: a later order at the same price is indistinguishable from the one we took, so assume it is the same -- conservative)."""
    out: Dict[str, Ladder] = {}
    for tok, lad in books.items():
        tk = taken.get(tok)
        if tk:
            lad = [(p, q - tk.get(p, 0.0)) for p, q in lad]
            lad = [(p, q) for p, q in lad if q > 1e-9]
        if lad:
            out[tok] = lad
    return out


class PaperArb:
    """Discover -> sweep every book -> evaluate -> re-read after a latency -> fill what is still profitable -> ledger."""

    def __init__(self, out_dir: str, cfg: Optional[CsaConfig] = None, lim: Optional[RiskLimits] = None):
        self.cfg, self.out_dir = cfg or CsaConfig(), out_dir
        self.risk = RiskManager(lim)
        self.events: List[Event] = []
        self.stats: Dict[str, float] = defaultdict(float)
        self.taken: Dict[str, Dict[float, float]] = defaultdict(lambda: defaultdict(float))
        os.makedirs(out_dir, exist_ok=True)
        self._f = open(os.path.join(out_dir, "csa_log.jsonl"), "a", buffering=1)

    def log(self, _what: str, **kw) -> None:
        self._f.write(json.dumps({"event": _what, "wall": time.time(), **kw}, default=float) + "\n")

    def tokens(self) -> List[str]:
        s: Dict[str, None] = {}
        for ev in self.events:
            for l in ev.legs:
                if l.is_other:
                    continue
                if ev.exhaustive_buyable:
                    s.setdefault(l.yes_token)
                if self.cfg.use_no_sets:
                    s.setdefault(l.no_token)
        return list(s)

    async def sweep(self, session) -> None:
        c = self.cfg
        t0 = time.time()
        books = deplete(await fetch_books(session, self.tokens(), c.batch), self.taken)
        self.stats["sweeps"] += 1
        self.stats["books"] = len(books)
        now = time.time()
        for ev in self.events:
            for op in evaluate_event(ev, books, c, now):
                self.stats["seen"] += 1
                self.log("seen", **op.row())
                await self.try_fill(session, ev, op)
        self.stats["sweep_s"] = time.time() - t0
        self.log("sweep", books=len(books), sweep_s=self.stats["sweep_s"])

    async def try_fill(self, session, ev: Event, op: Opportunity) -> None:
        c = self.cfg
        if self.risk.room(ev.eid) < 1.0:                       # the event (or the account) is full: not an execution question
            self.stats["refused_no_room"] += 1
            return
        await asyncio.sleep(c.latency_s)
        fresh = deplete(await fetch_books(session, op.tokens, c.batch), self.taken)
        room = self.risk.room(ev.eid)
        ops = [o for o in evaluate_event(ev, fresh, c, time.time(), max_capital=room) if o.kind == op.kind]
        if not ops:
            self.stats["vanished"] += 1
            self.log("vanished", eid=ev.eid, kind=op.kind, first_net=op.fill.net)
            return
        o = ops[0]
        ok, why = self.risk.approve(o)
        if not ok:
            self.stats["refused_" + why] += 1
            self.log("refused", reason=why, **o.row())
            return
        pos = self.risk.book(o)
        for tok, tk in zip(o.tokens, o.fill.takes):
            for px, q in tk.items():
                self.taken[tok][px] += q
        self.stats["fills"] += 1
        self.log("fill", pid=pos.pid, tokens=o.tokens, vwap=o.fill.legs_vwap, **o.row())
        await asyncio.sleep(max(c.recheck_s - c.latency_s, 0.0))
        raw = await fetch_books(session, op.tokens, c.batch)
        # legging proxy: could the same number of sets still be bought at a profit from the *raw* book a few seconds later (a slower,
        # leg-by-leg execution), and is there anything left for us after our own take?
        same = walk_sets([raw.get(t) or [] for t in op.tokens], leg_fee_params([l for l in ev.legs if not l.is_other], c.fee_stress_rate), o.fill.payout / max(o.fill.sets, 1e-9),
                         0.0, max_sets=o.fill.sets)
        alive = [x for x in evaluate_event(ev, deplete(raw, self.taken), c, time.time()) if x.kind == op.kind]
        still = same.sets >= o.fill.sets - 1e-6 and same.net > 0
        self.stats["still_fillable_after_recheck"] += 1 if still else 0
        self.stats["more_left_after_recheck"] += 1 if alive else 0
        self.log("recheck", pid=pos.pid, still_fillable=still, net_same_size_later=same.net if same.sets > 0 else 0.0, more_left=bool(alive))

    def summary(self) -> dict:
        pos = self.risk.positions
        return {"stats": dict(self.stats), "events": len(self.events), "exhaustive": sum(e.exhaustive_buyable for e in self.events),
                "positions": [asdict(p) for p in pos], "deployed": self.risk.deployed, "locked_net": sum(p.payout - p.capital for p in pos),
                "halted": self.risk.halted}


async def run(duration_s: float, out_dir: str, cfg: Optional[CsaConfig] = None, lim: Optional[RiskLimits] = None) -> dict:
    import aiohttp
    eng = PaperArb(out_dir, cfg, lim)
    c = eng.cfg
    sess = aiohttp.ClientSession(trust_env=True, timeout=aiohttp.ClientTimeout(total=40), headers={"User-Agent": "Mozilla/5.0"})
    t_end = time.time() + duration_s
    last_disc = -1e18
    stop = asyncio.Event()
    import signal
    for sig in (signal.SIGTERM, signal.SIGINT):                 # a stopped session still writes its summary
        try:
            asyncio.get_running_loop().add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):
            pass

    def write_summary() -> dict:
        res = eng.summary()
        with open(os.path.join(out_dir, "csa_summary.json"), "w") as f:
            json.dump(res, f, indent=1, default=float)
        return res

    try:
        while time.time() < t_end and not eng.risk.halted and not stop.is_set():
            if time.time() - last_disc >= c.rediscover_s:
                eng.events = await fetch_universe(sess)
                last_disc = time.time()
                eng.log("universe", events=len(eng.events), exhaustive=sum(e.exhaustive_buyable for e in eng.events), tokens=len(eng.tokens()))
                print(f"universe: {len(eng.events)} NegRisk events ({sum(e.exhaustive_buyable for e in eng.events)} exhaustive), {len(eng.tokens())} tokens", flush=True)
            t0 = time.time()
            try:
                await eng.sweep(sess)
            except Exception as e:                        # a data error must never become a trade; count it and keep the loop alive
                eng.stats["sweep_errors"] += 1
                eng.log("error", err=repr(e)[:200])
                if eng.stats["sweep_errors"] > 20:
                    eng.risk.halt("too many sweep errors")
            s = eng.stats
            print(f"[{time.strftime('%H:%M:%S')}] sweeps={s['sweeps']:.0f} books={s['books']:.0f} seen={s['seen']:.0f} fills={s['fills']:.0f} vanished={s['vanished']:.0f} "
                  f"deployed=${eng.risk.deployed:.2f} locked=${sum(p.payout - p.capital for p in eng.risk.positions):.3f} ({s['sweep_s']:.1f}s)", flush=True)
            write_summary()
            try:
                await asyncio.wait_for(stop.wait(), timeout=max(0.0, c.sweep_interval_s - (time.time() - t0)))
            except asyncio.TimeoutError:
                pass
    finally:
        await sess.close()
    return write_summary()


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--duration", type=float, default=3600.0)
    p.add_argument("--out", default="runs/p13")
    p.add_argument("--bankroll", type=float, default=100.0)
    p.add_argument("--max-per-event", type=float, default=25.0)
    p.add_argument("--max-days", type=float, default=60.0, help="skip events resolving later than this (end date + resolution buffer)")
    p.add_argument("--fee-stress", type=float, default=0.0, help="trade as if every fee-enabled leg paid at least this taker rate")
    p.add_argument("--settle", metavar="RUN_DIR", help="mark a finished paper run to the actual resolutions and exit")
    p.add_argument("--fetch-closed", type=int, metavar="DAYS", help="download closed NegRisk events of the last DAYS days to OUT/closed_negrisk_compact.json and exit")
    p.add_argument("--backtest", metavar="EVENTS_JSON", help="resolution backtest on a JSON list of closed Gamma events and exit")
    a = p.parse_args(argv)
    if a.fetch_closed:
        os.makedirs(a.out, exist_ok=True)
        print(fetch_closed(a.fetch_closed, os.path.join(a.out, "closed_negrisk_compact.json")), "events")
        return
    if a.backtest:
        import orjson
        r = resolution_backtest(orjson.loads(open(a.backtest, "rb").read()))
        out = os.path.join(a.out, "resolution_backtest.json")
        os.makedirs(a.out, exist_ok=True)
        with open(out, "w") as fh:
            json.dump(r, fh, indent=1)
        print(json.dumps({k: r[k] for k in ("events", "plain", "augmented", "payout", "end_min", "end_max")}, indent=1))
        return
    if a.settle:
        r = settle_run(a.settle)
        print(json.dumps({k: r[k] for k in ("positions", "settled", "pnl_settled", "capital_settled")}), "shortfalls:", len(r["shortfalls"]))
        return
    out = os.path.join(a.out, "paper_" + time.strftime("%Y%m%d_%H%M%S"))
    res = asyncio.run(run(a.duration, out, cfg=CsaConfig(fee_stress_rate=a.fee_stress, max_days=a.max_days), lim=RiskLimits(bankroll=a.bankroll, max_per_event=a.max_per_event, max_deployed=a.bankroll, max_days=a.max_days)))
    print(json.dumps({k: res[k] for k in ("stats", "events", "exhaustive", "deployed", "locked_net", "halted")}, default=float))
    print("artifacts:", out)


if __name__ == "__main__":
    main()
