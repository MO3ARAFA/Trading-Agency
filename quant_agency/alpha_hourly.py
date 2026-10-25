"""Phase 15, round 3: hourly hypotheses on the 80 most liquid Binance USD-M perpetuals (2023-01 .. 2026-09, 1 h bars).

Declared before the hourly data was loaded:
  F9  funding_settlement  At each funding settlement S of a symbol, the signal is the *previous* settled rate f (fully known). If
                          |f| >= theta: mode "pre" trades against the payers in the hour before S (short when f > 0; entry at the open
                          of hour S-1, exit at the open of S); mode "post" trades the rebound in the hour after S (long when f > 0,
                          entry at the open of S, exit at S+1).
  F12 liquidation_rev     1 h log return <= -z rolling sd (one week of hourly returns, excluding the bar) with quote volume >= 3 x the
                          weekly median: long at the next open, hold H hours.
Cost 20 bps per round trip; funding paid / received when a settlement falls inside the hold. Splits by entry time (train 2024,
validation 2025-H1, OOS 2025-07..2026-09); qualification and freezing exactly as in rounds 1 and 2; standard errors cluster by entry day.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import itertools
import json
import math
from typing import Dict, List, Sequence

import numpy as np

from .alpha_daily import SPLITS, _ts

COST_BPS = 20.0


class Hourly:
    def __init__(self, npz_h: str, npz_d: str):
        zh, zd = np.load(npz_h), np.load(npz_d)
        self.syms = sorted(k[3:] for k in zh.files if k.startswith("h__"))
        self.bars = {s: zh["h__" + s] for s in self.syms}
        self.fund = {s: zd["f__" + s] for s in self.syms if "f__" + s in zd.files}


def _stats(tr: Sequence[dict]) -> dict:
    n = len(tr)
    if n < 2:
        return {"n": n, "mean": float("nan"), "t": float("nan")}
    x = np.array([r["net_bps"] for r in tr])
    mu = float(x.mean())
    cl: Dict[int, float] = {}
    for r, v in zip(tr, x):
        k = int(r["t"] // 86400)
        cl[k] = cl.get(k, 0.0) + v - mu
    c = np.array(list(cl.values()))
    se = float(np.sqrt((c ** 2).sum()) / n) if len(c) > 1 else float("nan")
    return {"n": n, "mean": round(mu, 2), "se": round(se, 2), "t": round(mu / se, 3) if se > 0 else float("nan"), "clusters": len(c),
            "gross": round(float(np.mean([r["gross_bps"] for r in tr])), 2), "win": round(float((x > 0).mean()), 3)}


def _in(t: float, sp: str) -> bool:
    a, b = SPLITS[sp]
    return _ts(a) <= t < _ts(b)


def _trade(b: np.ndarray, e: int, x: int, d: int, F: np.ndarray, sym: str) -> dict:
    pe, px = b[e, 1], b[x, 1]
    gross = d * (px / pe - 1.0) * 1e4
    fund = 0.0
    if len(F):
        m = (F[:, 0] > b[e, 0]) & (F[:, 0] <= b[x, 0])
        fund = -d * float(F[m, 1].sum()) * 1e4
    return {"t": float(b[e, 0]), "sym": sym, "dir": d, "gross_bps": gross, "fund_bps": fund, "net_bps": gross + fund - COST_BPS}


def f9(H: Hourly, theta: float, mode: str, sp: str) -> List[dict]:
    out = []
    for s in H.syms:
        F = H.fund.get(s)
        if F is None or len(F) < 3:
            continue
        b = H.bars[s]
        tix = {int(round(t)): i for i, t in enumerate(b[:, 0])}
        for k in range(1, len(F)):
            S = int(round(F[k, 0] / 3600.0)) * 3600                   # settlement hour
            f_prev = F[k - 1, 1]
            if abs(f_prev) < theta:
                continue
            if mode == "pre":
                e, x, d = tix.get(S - 3600), tix.get(S), (-1 if f_prev > 0 else 1)
            else:
                e, x, d = tix.get(S), tix.get(S + 3600), (1 if f_prev > 0 else -1)
            if e is None or x is None or not _in(b[e, 0], sp):
                continue
            out.append(_trade(b, e, x, d, F, s))
    return out


def f12(H: Hourly, z: float, Hh: int, sp: str, vr: float = 3.0, look: int = 168) -> List[dict]:
    out = []
    for s in H.syms:
        b = H.bars[s]
        if len(b) < look + 10:
            continue
        r = np.diff(np.log(b[:, 4]), prepend=np.nan)
        F = H.fund.get(s, np.zeros((0, 2)))
        busy = -1
        for t in range(look + 1, len(b) - Hh - 1):
            if t < busy or not _in(b[t + 1, 0], sp):
                continue
            w = r[t - look:t]
            sd = np.nanstd(w)
            if not (sd > 0) or r[t] > -z * sd:
                continue
            if b[t, 5] < vr * np.median(b[t - look:t, 5]):
                continue
            out.append(_trade(b, t + 1, t + 1 + Hh, 1, F, s))
            busy = t + 1 + Hh
    return out


GRID = {"F9_funding_settlement": (f9, {"theta": [0.0005, 0.001], "mode": ["pre", "post"]}),
        "F12_liquidation_rev": (f12, {"z": [4.0, 6.0], "Hh": [1, 3, 6]})}


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--stage", choices=["screen", "oos"], default="screen")
    p.add_argument("--prereg", default="docs/PREREG_P15C.json")
    a = p.parse_args(argv)
    H = Hourly("runs/p15/bn_1h.npz", "runs/p15/bn_daily.npz")
    if a.stage == "screen":
        rows = []
        for fam, (fn, g) in GRID.items():
            keys = sorted(g)
            for combo in itertools.product(*[g[k] for k in keys]):
                pr = dict(zip(keys, combo))
                row = {"family": fam, "params": pr, "id": fam + "|" + ",".join(f"{k}={v}" for k, v in sorted(pr.items()))}
                for sp in ("train", "val"):
                    row[sp] = _stats(fn(H, **pr, sp=sp))
                rows.append(row)
                print(f"{row['id']:50s} train {row['train']['mean']} t={row['train']['t']} n={row['train']['n']} | val {row['val']['mean']} t={row['val']['t']} n={row['val']['n']}", flush=True)
        json.dump(rows, open("runs/p15/hourly_screen.json", "w"), default=float)
        q = []
        for fam in GRID:
            ok = [r for r in rows if r["family"] == fam and r["train"]["n"] >= 30 and r["train"]["mean"] > 0 and r["train"]["t"] > 2 and r["val"]["n"] >= 10 and r["val"]["mean"] > 0]
            if ok:
                q.append(max(ok, key=lambda r: r["val"]["t"]))
        print("QUALIFIED:", [(r["id"], r["train"], r["val"]) for r in q])
    else:
        pre = json.load(open(a.prereg))
        res = []
        for c in pre["candidates"]:
            tr = GRID[c["family"]][0](H, **c["params"], sp="oos")
            res.append({"id": c["id"], "oos": _stats(tr), "trades": tr})
            print(c["id"], res[-1]["oos"])
        json.dump(res, open("runs/p15/hourly_oos.json", "w"), default=float)


if __name__ == "__main__":
    main()
