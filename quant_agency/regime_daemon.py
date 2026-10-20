"""Phase 9 — volatility-regime trigger: supervises `run_live --phase7` so that capture happens in active / high-liquidity windows instead of dead chop.

    python -m quant_agency.regime_daemon                       # pre-registered thresholds; runs until N* floor-passed fills or the capture-hours cap
    python -m quant_agency.regime_daemon --dry-run             # log what it would do, launch nothing

Standby cost: ONE Binance Vision websocket (btcusdt@bookTicker), a 60-sample ring and a 5-second decision tick; no engine, no Polymarket/Hyperliquid feeds, no numba. When a trigger
fires it starts a recorded Pure-B session (`run_live --phase7 --b-exit fixed0.7`, sleeves active, Architecture A never built) and keeps watching; when the trigger releases it asks the
session to stop gracefully (stop-file → tape saved, positions finalised) and goes back to standby. Every decision and a 60 s volatility trace are appended to the daemon log.

`--continuous` (Phase 10): ONE long-lived `run_live --phase7` process that is never stopped for regime reasons — feeds, the Hunter's lead-lag calibration and the oracle variance stay warm 24/7; the event
log is rotated into numbered tape parts every `--rotate-min` minutes; the pre-impulse sigma60 gate (`--max-sigma60`) is applied inside Architecture B, per signal, instead of by starting/stopping sessions;
every finished shadow row is appended to `b_shadow.jsonl`. The daemon only supervises (restart on a crash with back-off, count-based stop, graceful stop on SIGINT/SIGTERM).
LIMIT: the Polymarket market set is discovered once per process and the MarketBook is fixed-size, so a process is cycled every `--session-h` (default 1.5 h) and restarted immediately; that costs ≈ 1–2 min
(oracle warm-up 20 s + discovery + the 75 s of BTC history the pre-impulse gate needs) per session ≈ 2 %, instead of a 24/7 warm process whose 5-minute markets would silently run out.

The decision rules are pure functions of (clock, sigma60) — see `Decider` — and are unit-tested with an injected clock.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import math
import os
import signal
import sys
import time
from dataclasses import dataclass, field, asdict
from typing import Callable, List, Optional, Tuple

from .regime import RollingSigma60, TRIGGER_THR

# ----------------------------------------------------------------------------- pre-registered defaults (docs/PREREG_PHASE9.md)
START_THR = TRIGGER_THR            # 0.45 bps/sqrt(s)
STOP_THR = 0.35                    # hysteresis: release only below this ...
CONFIRM_S = 30.0                   # ... start only after sigma60 >= START_THR for this long
CALM_S = 300.0                     # ... and only after sigma60 < STOP_THR (and outside every window) for this long
MIN_SESSION_S = 600.0
MAX_SEGMENT_S = 2700.0
WINDOWS: Tuple[Tuple[str, int, int], ...] = (("london", 7 * 60, 10 * 60), ("us", 13 * 60 + 30, 16 * 60 + 30))      # minutes after 00:00 UTC
WEEKDAYS_ONLY = True


@dataclass
class DaemonConfig:
    start_thr: float = START_THR
    stop_thr: float = STOP_THR
    confirm_s: float = CONFIRM_S
    calm_s: float = CALM_S
    min_session_s: float = MIN_SESSION_S
    max_segment_s: float = MAX_SEGMENT_S
    windows: Tuple[Tuple[str, int, int], ...] = WINDOWS
    weekdays_only: bool = WEEKDAYS_ONLY


def in_window(now: dt.datetime, cfg: DaemonConfig) -> Optional[str]:
    """Name of the scheduled high-liquidity window containing ``now`` (UTC), else None."""
    if now.tzinfo is None:
        raise ValueError("naive datetime")
    now = now.astimezone(dt.timezone.utc)
    if cfg.weekdays_only and now.weekday() >= 5:
        return None
    m = now.hour * 60 + now.minute
    for name, a, b in cfg.windows:
        if a <= m < b:
            return name
    return None


@dataclass
class Decider:
    """Hysteresis state machine. ``step`` is called every decision tick with the clock and the latest sigma60 (NaN = unknown); it returns ('start'|'stop', reason) or None."""
    cfg: DaemonConfig = field(default_factory=DaemonConfig)
    capturing: bool = False
    hot_since: Optional[float] = None          # sigma60 >= start_thr since
    calm_since: Optional[float] = None         # sigma60 < stop_thr and outside any window since
    started_at: Optional[float] = None

    def step(self, now: dt.datetime, sigma: float) -> Optional[Tuple[str, str]]:
        c = self.cfg
        ts = now.timestamp()
        win = in_window(now, c)
        known = sigma == sigma
        if not self.capturing:
            self.calm_since = None
            if win:
                self.hot_since = None
                return self._start(ts, f"window:{win}")
            if known and sigma >= c.start_thr:
                self.hot_since = self.hot_since if self.hot_since is not None else ts
                if ts - self.hot_since >= c.confirm_s:
                    return self._start(ts, f"vol:{sigma:.2f}>={c.start_thr:.2f}")
            else:
                self.hot_since = None
            return None
        # capturing
        self.hot_since = None
        calm = (not win) and known and sigma < c.stop_thr
        if calm:
            self.calm_since = self.calm_since if self.calm_since is not None else ts
            if ts - self.calm_since >= c.calm_s and ts - (self.started_at or ts) >= c.min_session_s:
                self.capturing, self.calm_since = False, None
                return ("stop", f"calm:{sigma:.2f}<{c.stop_thr:.2f} for {c.calm_s:.0f}s, outside windows")
        else:
            self.calm_since = None
        return None

    def _start(self, ts: float, why: str) -> Tuple[str, str]:
        self.capturing, self.started_at, self.calm_since = True, ts, None
        return ("start", why)

    def segment_ended(self) -> None:
        """The child process exited by itself (segment cap, fill target, crash): back to standby; the next tick may start a new segment immediately."""
        self.capturing, self.calm_since = False, None


@dataclass
class Plan:
    n_star: int
    prior_fills: int = 0
    cap_capture_h: float = 24.0
    out_dir: str = "runs"
    tape_dir: str = "tapes"
    prefix: str = "p9_seg"
    b_exit: str = "fixed0.7"
    log_path: str = "runs/p9_daemon/daemon_log.jsonl"
    validation: bool = False
    dry_run: bool = False
    extra: List[str] = field(default_factory=list)
    continuous: bool = False
    rotate_min: float = 30.0
    max_sigma60: float = 0.50
    max_restarts: int = 20
    session_h: float = 1.5


class Daemon:
    def __init__(self, cfg: DaemonConfig, plan: Plan, clock: Callable[[], dt.datetime] = lambda: dt.datetime.now(dt.timezone.utc)):
        self.cfg, self.plan, self.clock = cfg, plan, clock
        self.decider = Decider(cfg)
        self.sigma = RollingSigma60()
        self.proc: Optional[asyncio.subprocess.Process] = None
        self.seg = 0
        self.cum_fills = plan.prior_fills
        self.capture_s = 0.0
        self.seg_t0 = 0.0
        self.stop_file = ""
        self.count_file = ""
        self.stop_requested = False
        self.n_ticks = 0
        self.tick_s = 5.0
        os.makedirs(os.path.dirname(plan.log_path) or ".", exist_ok=True)

    # ---------------------------------------------------------------- logging
    def log(self, kind: str, **kw) -> None:
        rec = {"t": self.clock().isoformat(), "kind": kind, "validation": self.plan.validation, **kw}
        with open(self.plan.log_path, "a") as f:
            f.write(json.dumps(rec, default=float) + "\n")
        print(f"{rec['t'][11:19]} {kind} " + " ".join(f"{k}={v}" for k, v in kw.items()), flush=True)

    # ---------------------------------------------------------------- feed
    async def feed(self) -> None:
        import websockets
        import orjson
        url = "wss://data-stream.binance.vision/ws/btcusdt@bookTicker"
        backoff = 1.0
        while not self.stop_requested:
            try:
                async with websockets.connect(url, ping_interval=20, max_size=2 ** 20) as ws:
                    self.log("feed_up")
                    backoff = 1.0
                    async for raw in ws:
                        m = orjson.loads(raw)
                        b, a = float(m.get("b", 0)), float(m.get("a", 0))
                        if b > 0 and a >= b:
                            self.sigma.update(time.time(), 0.5 * (a + b))
                        self.n_ticks += 1
                        if self.stop_requested:
                            return
            except asyncio.CancelledError:
                raise
            except Exception as e:                                      # reconnect with backoff; sigma stays NaN-safe (stale data is detected by the tick age)
                self.log("feed_down", err=type(e).__name__)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)

    def current_sigma(self) -> float:
        if not self.sigma.samples or time.time() - self.sigma.last_t > 10.0:   # stale feed → unknown
            return float("nan")
        return self.sigma.value(time.time())

    # ---------------------------------------------------------------- child session
    def _argv(self) -> List[str]:
        p = self.plan
        tag = f"{p.prefix}{self.seg}"
        self.stop_file = os.path.join(p.out_dir, f"{tag}.stop")
        self.count_file = os.path.join(p.out_dir, f"{tag}.count.json")
        for f in (self.stop_file, self.count_file):
            if os.path.exists(f):
                os.remove(f)
        remaining = max(self.plan.cap_capture_h * 3600.0 - self.capture_s, 60.0)
        argv = [sys.executable, "-m", "quant_agency.run_live", "--phase7", "--b-exit", p.b_exit, "--duration", f"{min(self.cfg.max_segment_s, remaining):.0f}",
                "--stop-fills", str(p.n_star), "--prior-fills", str(self.cum_fills), "--record", os.path.join(p.tape_dir, f"{tag}.npz"), "--tag", tag, "--out", p.out_dir,
                "--status-every", "300", "--stop-file", self.stop_file, "--count-file", self.count_file] + p.extra
        return argv

    def _argv_continuous(self) -> List[str]:
        p = self.plan
        tag = f"{'p10v' if p.validation else 'p10r'}{self.seg}"
        self.stop_file = os.path.join(p.out_dir, f"{tag}.stop")
        self.count_file = os.path.join(p.out_dir, f"{tag}.count.json")
        for f in (self.stop_file, self.count_file):
            if os.path.exists(f):
                os.remove(f)
        remaining = max(p.cap_capture_h * 3600.0 - self.capture_s, 60.0)
        return [sys.executable, "-m", "quant_agency.run_live", "--phase7", "--b-exit", p.b_exit, "--max-sigma60", f"{p.max_sigma60}", "--shadow-log", "--rotate-min", f"{p.rotate_min}",
                "--duration", f"{min(remaining, p.session_h * 3600.0):.0f}", "--stop-fills", str(p.n_star), "--prior-fills", str(self.cum_fills), "--record", os.path.join(p.tape_dir, tag), "--tag", tag,
                "--out", p.out_dir, "--status-every", "600", "--stop-file", self.stop_file, "--count-file", self.count_file] + p.extra

    async def run_continuous(self) -> None:
        """Supervise one long-lived warm process. A crash restarts it (cold, logged) after a back-off; N* reached, the capture-hours cap, or a stop request ends the daemon."""
        p = self.plan
        self.log("daemon_start", mode="continuous", n_star=p.n_star, prior=p.prior_fills, max_sigma60=p.max_sigma60, rotate_min=p.rotate_min, cap_h=p.cap_capture_h, dry_run=p.dry_run)
        restarts, backoff = 0, 10.0
        try:
            while not self.stop_requested:
                self.seg += 1
                argv = self._argv_continuous()
                self.seg_t0 = time.time()
                if p.dry_run:
                    self.log("DRY_RUN_start", why="continuous", argv=" ".join(argv))
                    return
                os.makedirs(p.tape_dir, exist_ok=True)
                os.makedirs(p.out_dir, exist_ok=True)
                logf = open(os.path.join(p.out_dir, f"{'p10v' if p.validation else 'p10r'}{self.seg}.log"), "w")
                self.proc = await asyncio.create_subprocess_exec(*argv, stdout=logf, stderr=asyncio.subprocess.STDOUT)
                self.log("start", why="continuous", segment=self.seg, pid=self.proc.pid, cum_fills=self.cum_fills)
                next_trace = 0.0
                while self.proc.returncode is None and not self.stop_requested:
                    await asyncio.sleep(self.tick_s)
                    if time.time() >= next_trace:
                        next_trace = time.time() + 300.0
                        self.log("trace", live_fills=self.cum_fills + self.read_count(), elapsed_h=round((time.time() - self.seg_t0 + self.capture_s) / 3600, 2))
                if self.stop_requested and self.proc.returncode is None:
                    open(self.stop_file, "w").close()
                    self.log("stop_requested", why="signal", segment=self.seg)
                    await self._reap(timeout=300.0)
                    break
                self._account_segment()
                if self.cum_fills >= p.n_star:
                    self.log("done", reason="N* reached (live counter)", cum_fills=self.cum_fills)
                    break
                if self.capture_s >= p.cap_capture_h * 3600.0:
                    self.log("done", reason="capture-hours cap", cum_fills=self.cum_fills)
                    break
                planned = min(p.session_h * 3600.0, max(p.cap_capture_h * 3600.0 - (self.capture_s - (time.time() - self.seg_t0)), 60.0))
                if time.time() - self.seg_t0 >= 0.9 * planned and self.proc is None:       # a normal end of a session (its market set expires): start the next one immediately
                    self.log("session_cycle", segment=self.seg, cum_fills=self.cum_fills)
                    continue
                restarts += 1                                           # the child ended early: a crash (feed library, OOM, …) — restart cold after a back-off
                self.log("child_crash", restarts=restarts, backoff_s=backoff)
                if restarts > p.max_restarts:
                    self.log("done", reason="too many restarts")
                    break
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 300.0)
        finally:
            if self.proc is not None and self.proc.returncode is None:
                open(self.stop_file, "w").close()
                await self._reap(timeout=300.0)
            self.log("daemon_end", cum_fills=self.cum_fills, capture_h=round(self.capture_s / 3600, 2))

    async def start_segment(self, why: str) -> None:
        self.seg += 1
        argv = self._argv()
        self.seg_t0 = time.time()
        if self.plan.dry_run:
            self.log("DRY_RUN_start", why=why, argv=" ".join(argv))
            self.proc = None
            return
        os.makedirs(self.plan.tape_dir, exist_ok=True)
        os.makedirs(self.plan.out_dir, exist_ok=True)
        logf = open(os.path.join(self.plan.out_dir, f"{self.plan.prefix}{self.seg}.log"), "w")
        self.proc = await asyncio.create_subprocess_exec(*argv, stdout=logf, stderr=asyncio.subprocess.STDOUT)
        self.log("start", why=why, segment=self.seg, pid=self.proc.pid, cum_fills=self.cum_fills, tape=argv[argv.index("--record") + 1])

    def read_count(self) -> int:
        try:
            with open(self.count_file) as f:
                return int(json.load(f)["floor_fills"])
        except Exception:
            return 0

    async def stop_segment(self, why: str) -> None:
        if self.plan.dry_run or self.proc is None:
            self.log("DRY_RUN_stop", why=why)
            return
        open(self.stop_file, "w").close()
        self.log("stop_requested", why=why, segment=self.seg)
        await self._reap(timeout=240.0)

    async def _reap(self, timeout: float) -> None:
        proc = self.proc
        try:
            await asyncio.wait_for(proc.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            self.log("child_kill", segment=self.seg)
            proc.kill()
            await proc.wait()
        self._account_segment()

    def _account_segment(self) -> None:
        dur = time.time() - self.seg_t0
        n = self.read_count()
        self.capture_s += dur
        self.cum_fills += n
        self.log("segment_end", segment=self.seg, seconds=round(dur), live_floor_fills=n, cum_fills=self.cum_fills, capture_h=round(self.capture_s / 3600, 2), rc=self.proc.returncode)
        self.proc = None
        self.decider.segment_ended()

    # ---------------------------------------------------------------- supervisor
    async def run(self) -> None:
        feed = asyncio.create_task(self.feed())
        self.log("daemon_start", n_star=self.plan.n_star, prior=self.plan.prior_fills, cfg=asdict(self.cfg), dry_run=self.plan.dry_run)
        next_trace = 0.0
        try:
            while not self.stop_requested:
                await asyncio.sleep(self.tick_s)
                now = self.clock()
                s = self.current_sigma()
                if time.time() >= next_trace:
                    next_trace = time.time() + 60.0
                    self.log("trace", sigma60=None if s != s else round(s, 3), capturing=self.decider.capturing, window=in_window(now, self.cfg), cum_fills=self.cum_fills + (self.read_count() if self.proc else 0))
                if self.proc is not None and self.proc.returncode is not None:                    # child ended by itself
                    self._account_segment()
                if self.cum_fills >= self.plan.n_star or self.capture_s >= self.plan.cap_capture_h * 3600.0:
                    self.log("done", reason="N* reached (live counter)" if self.cum_fills >= self.plan.n_star else "capture-hours cap", cum_fills=self.cum_fills)
                    break
                act = self.decider.step(now, s)
                if act is None:
                    continue
                if act[0] == "start":
                    await self.start_segment(act[1])
                else:
                    await self.stop_segment(act[1])
        finally:
            self.stop_requested = True
            if self.proc is not None and self.proc.returncode is None:
                open(self.stop_file, "w").close()
                await self._reap(timeout=240.0)
            feed.cancel()
            try:
                await feed
            except (asyncio.CancelledError, Exception):
                pass
            self.log("daemon_end", cum_fills=self.cum_fills, capture_h=round(self.capture_s / 3600, 2))


def parse(argv: Optional[List[str]] = None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n-star", type=int, default=None, help="target floor-passed Polymarket fills (default: N* from docs/PREREG_PHASE9.json)")
    ap.add_argument("--prior-fills", type=int, default=0, help="fresh fills already collected under this protocol (NOT the Phase 4–8 sample)")
    ap.add_argument("--cap-hours", type=float, default=None, help="hard cap on total capture hours (default from the pre-registration)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--continuous", action="store_true", help="Phase 10: one warm 24/7 process, tape rotation, regime gate inside Architecture B (N*, cap and gate from docs/PREREG_PHASE10.json)")
    ap.add_argument("--rotate-min", type=float, default=None)
    ap.add_argument("--session-h", type=float, default=None, help="continuous mode: hours per run_live process; Polymarket markets are discovered once per process, so the process is cycled before its market set runs dry")
    ap.add_argument("--max-sigma60", type=float, default=None)
    ap.add_argument("--out", default="runs")
    ap.add_argument("--tapes", default="tapes")
    ap.add_argument("--log", default="runs/p9_daemon/daemon_log.jsonl")
    # overrides below exist for validation only; using any of them marks the run `validation` and its data must be excluded from the confirmatory analysis
    ap.add_argument("--start-thr", type=float, default=None)
    ap.add_argument("--stop-thr", type=float, default=None)
    ap.add_argument("--confirm-s", type=float, default=None)
    ap.add_argument("--calm-s", type=float, default=None)
    ap.add_argument("--min-session-s", type=float, default=None)
    ap.add_argument("--max-segment-s", type=float, default=None)
    ap.add_argument("--extra-window", default=None, help="validation only: HH:MM-HH:MM (UTC) additional scheduled window, any weekday")
    ap.add_argument("--prefix", default=None)
    return ap.parse_args(argv)


def build(a) -> Tuple[DaemonConfig, Plan]:
    prereg = {}
    pj = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "PREREG_PHASE10.json" if getattr(a, "continuous", False) else "PREREG_PHASE9.json")
    if os.path.exists(pj):
        prereg = json.load(open(pj))
    cfg = DaemonConfig()
    over = {k: getattr(a, k) for k in ("start_thr", "stop_thr", "confirm_s", "calm_s", "min_session_s", "max_segment_s") if getattr(a, k) is not None}
    for k, v in over.items():
        setattr(cfg, k, v)
    if a.extra_window:
        lo, hi = a.extra_window.split("-")
        h1, m1 = map(int, lo.split(":"))
        h2, m2 = map(int, hi.split(":"))
        cfg.windows = cfg.windows + (("extra", h1 * 60 + m1, h2 * 60 + m2),)
        cfg.weekdays_only = False
    c_over = {k: v for k, v in (("max_sigma60", a.max_sigma60),) if v is not None}      # the rotation interval does not touch any result, the gate does
    validation = bool(over) or bool(a.extra_window) or bool(a.prefix) or (bool(c_over) and not getattr(a, "continuous_ok", False)) or (a.n_star is not None and a.continuous and prereg.get("n_star") != a.n_star)
    n_star = a.n_star or prereg.get("n_star")
    if not n_star:
        raise SystemExit("no N*: pass --n-star or create docs/PREREG_PHASE9.json")
    plan = Plan(n_star=int(n_star), prior_fills=a.prior_fills, cap_capture_h=a.cap_hours or prereg.get("cap_capture_hours", 24.0), out_dir=a.out, tape_dir=a.tapes,
                prefix=a.prefix or ("p9v_seg" if validation else "p9_seg"), log_path=a.log if not validation else a.log.replace("daemon_log", "validation_log"),
                validation=validation, dry_run=a.dry_run, continuous=a.continuous,
                rotate_min=a.rotate_min if a.rotate_min is not None else prereg.get("rotate_min", 30.0), session_h=a.session_h if a.session_h is not None else prereg.get("session_h", 1.5), max_sigma60=a.max_sigma60 if a.max_sigma60 is not None else prereg.get("max_sigma60", 0.50))
    return cfg, plan


def main():
    a = parse()
    cfg, plan = build(a)
    d = Daemon(cfg, plan)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def _stop(*_):
        d.stop_requested = True
    for sg in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sg, _stop)
    try:
        loop.run_until_complete(d.run_continuous() if plan.continuous else d.run())
    finally:
        pending = asyncio.all_tasks(loop)                              # let the websocket keepalive tasks unwind before the loop closes
        for t in pending:
            t.cancel()
        if pending:
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        loop.close()


if __name__ == "__main__":
    main()
