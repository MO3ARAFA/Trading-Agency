"""Shared BTC volatility-regime estimator (used by the regime daemon *and* by the Phase 9 analysis, so the label a session was triggered on is the label it is analysed under).

    sigma60(t) = sqrt( mean over the last 60 one-second steps of (1 s log-return of the Binance BTCUSDT mid, in bps)^2 )          [bps / sqrt(s)]

Zero-mean RMS of 1 s returns on a 1 Hz as-of grid. It is causal (uses only data <= t) and needs no tuning parameter besides the 60 s window.
"""
from __future__ import annotations

import math
from collections import deque
from typing import Deque, Optional, Sequence, Tuple

import numpy as np

WINDOW_S = 60
ACTIVE_THR = 0.50              # decomposition label: quiet < 0.50 <= active  (Phase 9 pre-registration)
TRIGGER_THR = 0.45             # daemon start threshold (pre-registered)


def sigma60_series(t: np.ndarray, mid: np.ndarray, at: Sequence[float], window: int = WINDOW_S) -> np.ndarray:
    """sigma60 at each time in ``at`` — the *same* streaming estimator the daemon uses, replayed over a recorded (t, mid) tick series (single pass)."""
    at = np.asarray(at, dtype=float)
    out = np.full(len(at), np.nan)
    order = np.argsort(at)
    rs = RollingSigma60(window)
    k = 0
    n = len(t)
    for qi in order:
        tq = at[qi]
        while k < n and t[k] <= tq:
            rs.update(float(t[k]), float(mid[k]))
            k += 1
        out[qi] = rs.value(tq)
    return out


class RollingSigma60:
    """Streaming version for the daemon: feed (t, mid) ticks; read sigma60 any time. Keeps one sample per second (the last tick of each second)."""

    def __init__(self, window: int = WINDOW_S, keep: Optional[int] = None):
        self.window = window
        self.keep = keep if keep is not None else window + 5          # seconds of history retained (the lagged gate needs window + lag)
        self.samples: Deque[Tuple[int, float]] = deque()          # (second, ln mid) — last tick of that second
        self.last_t = -1.0

    def update(self, t: float, mid: float) -> None:
        if mid <= 0 or t < self.last_t:
            return
        self.last_t = t
        sec = int(math.floor(t))
        lm = math.log(mid)
        if self.samples and self.samples[-1][0] == sec:
            self.samples[-1] = (sec, lm)
        else:
            self.samples.append((sec, lm))
        while self.samples and sec - self.samples[0][0] > self.keep:
            self.samples.popleft()

    def value(self, now: Optional[float] = None) -> float:
        """sigma60 as of ``now`` (default: last tick); NaN if the last ``window`` seconds are not covered.
        Seconds with no tick carry the previous price forward (zero return); the window is seeded with the last sample at or before its start."""
        if not self.samples:
            return float("nan")
        end = int(math.floor(self.last_t if now is None else now))
        if end - self.samples[0][0] < self.window:
            return float("nan")
        by = dict(self.samples)
        seed = None
        for sec in sorted(by):
            if sec <= end - self.window:
                seed = by[sec]
        if seed is None:
            return float("nan")
        cur, acc = seed, 0.0
        for sec in range(end - self.window + 1, end + 1):
            nxt = by.get(sec, cur)
            acc += ((nxt - cur) * 1e4) ** 2
            cur = nxt
        return math.sqrt(acc / self.window)
