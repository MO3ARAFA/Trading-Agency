"""Omega daemon: runs ``HFPaperEngine`` 24/7 on live feeds, a synthetic market, or a recorded tape. Paper only.

    python -m quant_agency.omega_daemon --continuous --out runs/omega                 # live: pump.fun (Solana RPC) + Gate meme pairs
    python -m quant_agency.omega_daemon --continuous --duration 3600 --record         # one hour, tape recorded
    python -m quant_agency.omega_daemon --synthetic --duration 900 --speed 1           # synthetic market in real time
    python -m quant_agency.omega_daemon --synthetic --duration 21600 --speed 0         # six synthetic hours as fast as possible
    python -m quant_agency.omega_daemon --replay runs/omega/<run>/tape.jsonl.gz --speed 0
    touch runs/omega/KILL                                                              # halt every sleeve at the next review

Every run directory gets ``omega_audit.jsonl`` (appended every 5 minutes), ``omega_state.json`` (warm state, every 60 s; ``--resume``
reloads it), ``omega_status.jsonl`` (one line per status tick, including resident memory) and ``omega_summary.json`` at exit.
X sentiment runs only when ``X_BEARER_TOKEN`` is set (official API v2); otherwise the social sleeve stays idle and says why.
"""
from __future__ import annotations

import argparse
import asyncio
import gzip
import json
import os
import signal
import time
from typing import Callable, Optional

from .hf_paper_engine import EngineConfig, HFPaperEngine
from .meme_discovery import Quote, TokenCreated, TradePrint
from .x_sentiment_crawler import Tweet


def rss_mb() -> float:
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024.0
    except OSError:
        pass
    return float("nan")


# ================================================================================ tape (normalized events, JSON lines, gzip, rotated)
class Tape:
    def __init__(self, path: str, max_bytes: float = 500e6):
        self.base, self.max_bytes, self.part = path, max_bytes, 0
        self.n = 0
        self._open(path)

    def _open(self, path: str) -> None:
        import io
        self.raw = open(path, "wb")
        self.gz = gzip.GzipFile(fileobj=self.raw, mode="wb", compresslevel=3)
        self.f = io.TextIOWrapper(self.gz, encoding="utf-8")

    def write(self, ev: dict) -> None:
        self.f.write(json.dumps(ev, separators=(",", ":"), default=float) + "\n")
        self.n += 1
        if self.n % 20000 == 0 and self.raw.tell() > self.max_bytes:     # compressed bytes on disk
            self.close()
            self.part += 1
            self._open(self.base.replace(".jsonl.gz", f".{self.part}.jsonl.gz"))

    def close(self) -> None:
        self.f.close()
        self.raw.close()


def dispatch(eng: HFPaperEngine, ev: dict, facts: Optional[Callable[[str], dict]] = None) -> list:
    """One normalized event into the engine (shared by synthetic, replay and the live recorder). Returns the safety events it answered
    from ``facts`` so a recorder can keep them on the tape."""
    k = ev["kind"]
    if k == "print":
        eng.on_print(TradePrint(ev["t"], ev["venue"], ev["key"], ev["side"], ev["qty"], ev["quote"], ev["price"], ev.get("post_price", float("nan")),
                                ev.get("v_quote", float("nan")), ev.get("v_base", float("nan")), ev.get("real_quote", float("nan")),
                                ev.get("fee_bps", float("nan")), ev.get("user", "")))
    elif k == "quote":
        eng.on_quote(Quote(ev["t"], ev["venue"], ev["key"], ev["bid"], ev["ask"], ev["bq"], ev["aq"]))
    elif k == "create":
        eng.on_create(TokenCreated(ev["t"], ev["mint"], ev.get("name", ""), ev.get("symbol", ""), ev.get("creator", "")))
    elif k == "complete":
        eng.on_complete(ev["mint"], ev["t"])
    elif k == "tweet":
        eng.on_tweet(Tweet(ev["id"], ev["t"], ev["author"], ev.get("followers", 0), ev.get("author_created_t", float("nan")), ev.get("text", ""),
                           ev.get("symbols", [])))
    elif k == "sol":
        eng.set_sol_usd(ev["px"])
    elif k == "rules":
        eng.set_pair_rules(ev["rows"])
    elif k == "safety":
        eng.set_safety(ev["key"], ev["facts"])
    elif k == "twitter":
        eng.set_twitter(ev["key"], ev["handle"])
    answered = []
    if facts is not None:                                   # offline: answer the engine's safety questions from the generator's ground truth
        while eng.need_safety:
            key = eng.need_safety.popleft()
            f = facts(key)
            eng.set_safety(key, f)
            answered.append({"kind": "safety", "t": ev["t"], "key": key, "facts": f})
    return answered


def _status_line(eng: HFPaperEngine) -> str:
    s = eng.status()
    sl = " ".join(f"{k[:6]}={v[0][:4]}:{v[1]:.2f}/{v[2]}" for k, v in s["sleeves"].items())
    return (f"[{time.strftime('%H:%M:%S')}] t+{s['elapsed_s']:.0f}s equity={s['equity']:.2f} fills={s['fills']} ({s['fills_per_hour']:.0f}/h) "
            f"open={s['open']} pend={s['pending']} tokens={s['tokens']} prints={s['prints']} rss={rss_mb():.0f}MB | {sl}")


def _finish(eng: HFPaperEngine, out: str, extra: dict) -> dict:
    eng.flush()
    if eng.out_dir:
        eng.save_snapshot()
    res = {**eng.summary(), **extra, "rss_mb_end": rss_mb()}
    with open(os.path.join(out, "omega_summary.json"), "w") as f:
        json.dump(res, f, indent=1, default=float)
    return res


# ================================================================================ offline (synthetic / replay)
def run_offline(events, out: str, duration_s: float, speed: float, facts: Optional[Callable[[str], dict]] = None, cfg: Optional[EngineConfig] = None,
                social: bool = True, record: Optional[str] = None, status_every_s: float = 30.0, resume: Optional[str] = None) -> dict:
    """``speed`` = market seconds per wall second (0: as fast as possible). Polls the engine every 0.5 market seconds."""
    os.makedirs(out, exist_ok=True)
    eng = HFPaperEngine(cfg, out_dir=out, social_enabled=social)
    if resume:
        eng.load_snapshot(resume)
    tape = Tape(record) if record else None
    st_f = open(os.path.join(out, "omega_status.jsonl"), "a", buffering=1)
    wall0, t0, last_poll, last_status, n = time.time(), None, None, -1e18, 0
    rss = []
    for ev in events:
        t = ev["t"]
        if t0 is None:
            t0 = t
        if t - t0 > duration_s:
            break
        if speed > 0:
            wait = (t - t0) / speed - (time.time() - wall0)
            if wait > 0:
                time.sleep(wait)
        while last_poll is not None and t - last_poll >= 0.5:
            last_poll += 0.5
            eng.poll(last_poll)
        if last_poll is None:
            last_poll = t
        extra = dispatch(eng, ev, facts)
        if tape:
            tape.write(ev)
            for x in extra:
                tape.write(x)
        n += 1
        if t - last_status >= status_every_s:
            last_status = t
            r = rss_mb()
            rss.append((round(t - t0, 1), round(r, 1)))
            st_f.write(json.dumps({**eng.status(), "rss_mb": r, "wall_s": round(time.time() - wall0, 2)}) + "\n")
            if speed > 0:
                print(_status_line(eng), flush=True)
    if last_poll is not None:
        eng.poll(last_poll + 0.5)
    if tape:
        tape.close()
    st_f.close()
    return _finish(eng, out, {"mode": "offline", "events": n, "wall_s": round(time.time() - wall0, 2), "rss_series": rss})


def read_tape(path: str):
    with gzip.open(path, "rt") as f:
        for line in f:
            try:
                yield json.loads(line)
            except ValueError:                            # a run killed mid-write leaves a truncated last line
                return


# ================================================================================ live
async def run_live(out: str, duration_s: float, cfg: Optional[EngineConfig] = None, record: bool = False, resume: Optional[str] = None,
                   gate_pairs: int = 30, status_every_s: float = 30.0) -> dict:
    import aiohttp

    from . import meme_discovery as md
    from .x_sentiment_crawler import XApiV2Source
    os.makedirs(out, exist_ok=True)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):
            pass
    sess = aiohttp.ClientSession(trust_env=True, timeout=aiohttp.ClientTimeout(total=30), headers={"User-Agent": "Mozilla/5.0"})
    xsrc = XApiV2Source(sess)
    eng = HFPaperEngine(cfg, out_dir=out, social_enabled=xsrc.status.available)
    if resume:
        eng.load_snapshot(resume)
    tape = Tape(os.path.join(out, "tape.jsonl.gz")) if record else None

    def rec(ev: dict) -> None:
        if tape:
            tape.write(ev)

    def on_print(p: md.TradePrint) -> None:
        eng.on_print(p)
        rec({"kind": "print", "t": p.t, "venue": p.venue, "key": p.key, "side": p.side, "qty": p.qty, "quote": p.quote, "price": p.price,
             "post_price": p.post_price, "v_quote": p.v_quote, "v_base": p.v_base, "real_quote": p.real_quote, "fee_bps": p.fee_bps, "user": p.user})

    def on_create(c: md.TokenCreated) -> None:
        eng.on_create(c)
        rec({"kind": "create", "t": c.t, "mint": c.mint, "name": c.name, "symbol": c.symbol, "creator": c.creator})

    def on_complete(mint: str, t: float) -> None:
        eng.on_complete(mint, t)
        rec({"kind": "complete", "t": t, "mint": mint})

    def on_quote(q: md.Quote) -> None:
        eng.on_quote(q)
        rec({"kind": "quote", "t": q.t, "venue": q.venue, "key": q.key, "bid": q.bid, "ask": q.ask, "bq": q.bq, "aq": q.aq})

    def set_sol(px: float) -> None:
        eng.set_sol_usd(px)
        rec({"kind": "sol", "t": time.time(), "px": px})

    def on_token(d: dict) -> None:
        eng.set_twitter(d["mint"], d.get("twitter", ""))
        rec({"kind": "twitter", "t": time.time(), "key": d["mint"], "handle": d.get("twitter", "")})

    try:
        rules = await asyncio.to_thread(md.gate_meme_universe, gate_pairs)
    except Exception as e:
        rules = []
        print("gate universe unavailable:", repr(e)[:120], flush=True)
    eng.set_pair_rules(rules)
    rec({"kind": "rules", "t": time.time(), "rows": rules})
    print(f"live: pump.fun via Solana RPC logs, {len(rules)} Gate pairs, X sentiment: {'on' if xsrc.status.available else 'off (' + xsrc.status.reason + ')'}", flush=True)
    stats_pump, stats_gate = md.FeedStats(), md.FeedStats()
    checker = md.SafetyChecker(sess)

    async def safety_worker():
        while not stop.is_set():
            if eng.need_safety:
                key = eng.need_safety.popleft()
                f = await checker.facts(key)
                eng.set_safety(key, f)
                rec({"kind": "safety", "t": time.time(), "key": key, "facts": f})
            else:
                await asyncio.sleep(0.2)

    async def x_worker():
        while not stop.is_set() and xsrc.status.available:
            keys = []
            for st in list(eng.uni.tokens.values())[-200:]:
                if st.venue == "pump" and st.window(time.time(), 120.0)["n"] >= 10:
                    keys += [st.key] + ([f"${st.symbol.upper()}"] if st.symbol else [])
            for tw in await xsrc.poll(keys[:100]):
                eng.on_tweet(tw)
                rec({"kind": "tweet", "id": tw.id, "t": tw.t, "author": tw.author, "followers": tw.followers, "author_created_t": tw.author_created_t,
                     "text": tw.text, "symbols": tw.symbols})
            await asyncio.sleep(1.0)

    async def poller():
        t_end = time.time() + duration_s
        last_status = 0.0
        st_f = open(os.path.join(out, "omega_status.jsonl"), "a", buffering=1)
        errors = 0
        while not stop.is_set() and time.time() < t_end:
            try:
                eng.poll(time.time())
            except Exception as e:                       # never die silently: log, and halt the account after repeated failures
                errors += 1
                eng.stats["poll_errors"] += 1
                eng.log("error", where="poll", err=repr(e)[:300])
                print("poll error:", repr(e)[:200], flush=True)
                if errors >= 20:
                    eng.ceo.halt_all(time.time(), f"{errors} engine errors")
            if time.time() - last_status >= status_every_s:
                last_status = time.time()
                st_f.write(json.dumps({**eng.status(), "rss_mb": rss_mb(), "pump_feed": vars(stats_pump), "gate_feed": vars(stats_gate),
                                       "x": vars(xsrc.status), "safety_calls": checker.calls, "safety_errors": checker.errors}, default=float) + "\n")
                print(_status_line(eng) + f" | pump msgs={stats_pump.msgs} prints={stats_pump.prints} rc={stats_pump.reconnects} gate prints={stats_gate.prints}", flush=True)
            await asyncio.sleep(0.5)
        st_f.close()
        stop.set()

    def guarded(fn):                                     # a callback error is logged and counted; it never kills the feed
        def call(*a):
            try:
                fn(*a)
            except Exception as e:
                eng.stats["callback_errors"] += 1
                eng.log("error", where=fn.__name__, err=repr(e)[:300])
                if eng.stats["callback_errors"] >= 50:
                    eng.ceo.halt_all(time.time(), "repeated callback errors")
        return call

    on_print, on_create, on_complete, on_quote = guarded(on_print), guarded(on_create), guarded(on_complete), guarded(on_quote)

    def task_done(tk: asyncio.Task) -> None:            # a task that ends with an exception stops the run instead of failing silently
        if not tk.cancelled() and tk.exception() is not None:
            eng.log("error", where=tk.get_name(), err=repr(tk.exception())[:300])
            print(f"task {tk.get_name()} died: {tk.exception()!r}"[:300], flush=True)
            stop.set()

    tasks = [asyncio.create_task(md.solana_pump_feed(on_print, on_create, on_complete, stop, stats=stats_pump)),
             asyncio.create_task(md.sol_usd_poll(sess, set_sol, stop)),
             asyncio.create_task(md.dexscreener_poll(sess, on_token, stop)),
             asyncio.create_task(safety_worker()), asyncio.create_task(x_worker()), asyncio.create_task(poller())]
    if rules:
        tasks.append(asyncio.create_task(md.gate_feed([r["pair"] for r in rules], on_quote, on_print, stop, stats=stats_gate)))
    for tk in tasks:
        tk.add_done_callback(task_done)
    await stop.wait()
    for tk in tasks:
        tk.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await sess.close()
    if tape:
        tape.close()
    return _finish(eng, out, {"mode": "live", "pump_feed": vars(stats_pump), "gate_feed": vars(stats_gate), "x": vars(xsrc.status),
                              "safety_calls": checker.calls, "safety_errors": checker.errors})


def main(argv=None):
    p = argparse.ArgumentParser()
    m = p.add_mutually_exclusive_group(required=True)
    m.add_argument("--continuous", action="store_true", help="live feeds, runs until --duration or SIGTERM")
    m.add_argument("--synthetic", action="store_true")
    m.add_argument("--replay", metavar="TAPE")
    p.add_argument("--duration", type=float, default=365 * 86400.0)
    p.add_argument("--speed", type=float, default=0.0, help="offline: market seconds per wall second (0 = as fast as possible)")
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--density", type=float, default=1.0, help="synthetic: multiplies the token launch rate and the number of CLOB pairs")
    p.add_argument("--out", default="runs/omega")
    p.add_argument("--record", action="store_true")
    p.add_argument("--resume", metavar="STATE_JSON")
    p.add_argument("--gate-pairs", type=int, default=30)
    a = p.parse_args(argv)
    out = os.path.join(a.out, ("live_" if a.continuous else "synth_" if a.synthetic else "replay_") + time.strftime("%Y%m%d_%H%M%S"))
    if a.continuous:
        try:
            import uvloop
            uvloop.install()
        except ImportError:
            pass
        res = asyncio.run(run_live(out, a.duration, record=a.record, resume=a.resume, gate_pairs=a.gate_pairs))
    elif a.synthetic:
        from .omega_synth import SynthMarket
        mk = SynthMarket(seed=a.seed, create_rate=0.6 * a.density, n_pairs=max(1, int(round(8 * a.density))))
        res = run_offline(mk.events(a.duration), out, a.duration, a.speed, facts=mk.facts, record=os.path.join(out, "tape.jsonl.gz") if a.record else None,
                          resume=a.resume)
    else:
        res = run_offline(read_tape(a.replay), out, a.duration, a.speed, facts=None, resume=a.resume)
    print(json.dumps({"status": res["status"], "model_pnl": res["model_pnl"]}, indent=1, default=float))
    print("artifacts:", out)


if __name__ == "__main__":
    main()
