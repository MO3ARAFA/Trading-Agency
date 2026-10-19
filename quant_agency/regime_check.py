"""Operator tool: is Binance BTC in a quiet or a volatile regime right now?

    python -m quant_agency.regime_check            # last 90 one-minute klines from data-api.binance.vision

Uses the Parkinson high-low estimator per minute, expressed in bps/sqrt(s) — the same unit as the `vol=` field in the live status line. It is an *indicative* number: the live
oracle's EW tick-level estimate is the one the agency uses, and the two differ by a factor that depends on the microstructure. The thresholds are heuristics anchored to the only
regime ever recorded (all four recorded sessions: live `vol` = 0.20–0.25 bps/√s), not calibrated levels. Always confirm against the live status line.
"""
from __future__ import annotations

import argparse
import json
import math
import urllib.request
from typing import List, Sequence

QUIET, ELEVATED = 0.30, 0.60            # bps/sqrt(s) heuristics (see module docstring)


def parkinson_bps_per_sqrt_s(klines: Sequence[Sequence]) -> float:
    """klines rows: [open_time, open, high, low, close, ...] for 1-minute bars. Returns sigma in bps per sqrt(second)."""
    var = []
    for k in klines:
        hi, lo = float(k[2]), float(k[3])
        if hi > 0 and lo > 0 and hi >= lo:
            var.append(math.log(hi / lo) ** 2 / (4.0 * math.log(2.0)))      # variance of ln-price over 60 s
    if not var:
        return float("nan")
    return math.sqrt(sum(var) / len(var) / 60.0) * 1e4


def classify(sigma: float) -> str:
    if sigma != sigma:
        return "unknown"
    return "quiet" if sigma < QUIET else ("elevated" if sigma < ELEVATED else "volatile")


def fetch(n: int = 90, symbol: str = "BTCUSDT") -> List[list]:
    url = f"https://data-api.binance.vision/api/v3/klines?symbol={symbol}&interval=1m&limit={n}"
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=15) as r:
        return json.loads(r.read())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=int, default=90)
    a = ap.parse_args()
    k = fetch(a.minutes)
    last15 = parkinson_bps_per_sqrt_s(k[-15:])
    full = parkinson_bps_per_sqrt_s(k)
    print(f"BTCUSDT 1m klines: last 15 min {last15:.3f} bps/√s ({classify(last15)}), last {len(k)} min {full:.3f} bps/√s ({classify(full)})  "
          f"[thresholds: quiet < {QUIET}, volatile ≥ {ELEVATED}; indicative only]")


if __name__ == "__main__":
    main()
