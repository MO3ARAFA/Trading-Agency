"""Phase 15, Track 3: passive (maker) fade of cross-sectional over-extension, 80 liquid Binance perps, 1 h bars, 2023-2026.

Declared before evaluation:
  * each hour t, rel_i = k-hour log return of coin i minus the cross-sectional median; the top decile gets a resting SELL limit at
    close_t x (1 + delta), the bottom decile a BUY limit at close_t x (1 - delta), valid for hour t+1 only;
  * a limit fills only if hour t+1 trades strictly through it (high > sell limit, low < buy limit): fills therefore happen exactly when
    the price keeps running against the fade (adverse selection is in the test, not assumed away);
  * exit: taker at the open of hour t+1+H; costs 2 bps maker entry + 5 bps taker exit + 3 bps spread / slippage = 10 bps per round trip,
    plus funding settled during the hold;
  * grid: k in {4, 12}, H in {4, 12}, delta in {0.002, 0.005}; splits and qualification exactly as rounds 2-3 (train 2024, validation
    2025-H1, OOS 2025-07..2026-09); standard errors cluster by entry day.
"""
from __future__ import annotations

import itertools
import json
from typing import List

import numpy as np

from .alpha_hourly import Hourly, _in, _stats

COST = 10.0


def align(H: Hourly):
    t = np.unique(np.concatenate([H.bars[s][:, 0] for s in H.syms]))
    ix = {v: i for i, v in enumerate(t)}
    T, N = len(t), len(H.syms)
    O, Hh, L, C = (np.full((T, N), np.nan) for _ in range(4))
    for j, s in enumerate(H.syms):
        b = H.bars[s]
        ii = np.array([ix[v] for v in b[:, 0]])
        O[ii, j], Hh[ii, j], L[ii, j], C[ii, j] = b[:, 1], b[:, 2], b[:, 3], b[:, 4]
    return t, O, Hh, L, C


def run(H: Hourly, A, k: int, Hold: int, delta: float, sp: str, q: float = 0.1) -> List[dict]:
    t, O, Hh, L, C = A
    lc = np.log(C)
    out = []
    busy = np.full(len(H.syms), -1)
    fund = {s: H.fund.get(s, np.zeros((0, 2))) for s in H.syms}
    for i in range(k, len(t) - Hold - 2):
        if not _in(t[i + 1], sp):
            continue
        r = lc[i] - lc[i - k]
        ok = ~np.isnan(r)
        if ok.sum() < 30:
            continue
        rel = r - np.nanmedian(r)
        hi_q, lo_q = np.nanquantile(rel[ok], 1 - q), np.nanquantile(rel[ok], q)
        for j in np.nonzero(ok)[0]:
            if i < busy[j]:
                continue
            if rel[j] >= hi_q:
                d, lim = -1, C[i, j] * (1 + delta)
                filled = Hh[i + 1, j] > lim
            elif rel[j] <= lo_q:
                d, lim = 1, C[i, j] * (1 - delta)
                filled = L[i + 1, j] < lim
            else:
                continue
            if not filled:
                continue
            x = i + 1 + Hold
            px = O[x, j]
            if not px > 0:
                continue
            gross = d * (px / lim - 1.0) * 1e4
            F = fund[H.syms[j]]
            f = 0.0
            if len(F):
                m = (F[:, 0] > t[i + 1]) & (F[:, 0] <= t[x])
                f = -d * float(F[m, 1].sum()) * 1e4
            out.append({"t": float(t[i + 1]), "sym": H.syms[j], "dir": d, "gross_bps": gross, "net_bps": gross + f - COST})
            busy[j] = x
    return out


GRID = {"k": [4, 12], "Hold": [4, 12], "delta": [0.002, 0.005]}


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--stage", choices=["screen", "oos"], default="screen")
    p.add_argument("--prereg", default="docs/PREREG_P15T3.json")
    a = p.parse_args(argv)
    H = Hourly("runs/p15/bn_1h.npz", "runs/p15/bn_daily.npz")
    A = align(H)
    if a.stage == "screen":
        rows = []
        for k, Hold, delta in itertools.product(GRID["k"], GRID["Hold"], GRID["delta"]):
            row = {"params": {"k": k, "Hold": Hold, "delta": delta}}
            for sp in ("train", "val"):
                row[sp] = _stats(run(H, A, k, Hold, delta, sp))
            rows.append(row)
            print(row["params"], "train", row["train"], "| val", row["val"], flush=True)
        json.dump(rows, open("runs/p15/maker_screen.json", "w"), default=float)
        ok = [r for r in rows if r["train"]["n"] >= 30 and r["train"]["mean"] > 0 and r["train"]["t"] > 2 and r["val"]["mean"] > 0]
        print("QUALIFIED:", max(ok, key=lambda r: r["val"]["t"]) if ok else None)
    else:
        pre = json.load(open(a.prereg))
        c = pre["params"]
        tr = run(H, A, c["k"], c["Hold"], c["delta"], "oos")
        s = _stats(tr)
        print("OOS", s)
        json.dump({"oos": s, "trades": tr}, open("runs/p15/maker_oos.json", "w"), default=float)


if __name__ == "__main__":
    main()
