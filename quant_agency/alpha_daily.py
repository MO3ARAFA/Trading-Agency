"""Phase 15, round 2: multi-day hypotheses on Binance USD-M perpetuals (daily bars, data.binance.vision, 2023-01 .. 2026-09).

Declared before the daily data was loaded:
  * families F5 new_listing_short, F6 ts_momentum, F7 xs_rank (momentum / reversal), F8 funding_carry; grids below (38 configurations);
  * entry at a daily open, exit at a later daily open; cost 20 bps per round trip per leg (5 bps taker + 5 bps spread / slippage
    each side) plus the actual funding paid or received over the hold;
  * liquid universe for F6-F8: the 50 symbols with the highest trailing 30-day median quote volume (computed with data before the
    entry day only); F5 requires a listing-week median quote volume >= 5 M USD;
  * splits by entry date: TRAIN 2024-01-01..2024-12-31, VALIDATION 2025-01-01..2025-06-30, OOS 2025-07-01..2026-09-30;
  * qualification and freezing exactly as in ``alpha_tournament``: TRAIN net > 0 with t > 2 (n >= 30), VALIDATION net > 0; best
    validation t per family; frozen before OOS is evaluated. Standard errors cluster by entry week (F6-F8) or entry month (F5).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import itertools
import json
import math
from typing import Dict, List, Optional, Sequence

import numpy as np

COST_BPS = 20.0
SPLITS = {"train": ("2024-01-01", "2025-01-01"), "val": ("2025-01-01", "2025-07-01"), "oos": ("2025-07-01", "2026-10-01")}


def _ts(s: str) -> float:
    return dt.datetime.fromisoformat(s).replace(tzinfo=dt.timezone.utc).timestamp()


class Daily:
    def __init__(self, npz: str):
        z = np.load(npz)
        syms = sorted(k[3:] for k in z.files if k.startswith("d__"))
        days = np.unique(np.concatenate([z["d__" + s][:, 0] for s in syms]))
        self.days, self.syms = days, syms
        T, N = len(days), len(syms)
        ix = {d: i for i, d in enumerate(days)}
        self.o = np.full((T, N), np.nan)
        self.c = np.full((T, N), np.nan)
        self.qv = np.zeros((T, N))
        self.fund = np.zeros((T, N))                       # sum of funding rates settled during day t (fraction of notional)
        self.first = np.full(N, -1)
        for j, s in enumerate(syms):
            a = z["d__" + s]
            ii = np.array([ix[d] for d in a[:, 0]])
            self.o[ii, j], self.c[ii, j], self.qv[ii, j] = a[:, 1], a[:, 4], a[:, 5]
            self.first[j] = ii.min()
            if "f__" + s in z.files:
                f = z["f__" + s]
                fi = np.searchsorted(days, f[:, 0], side="right") - 1
                ok = fi >= 0
                np.add.at(self.fund[:, j], fi[ok], f[ok, 1])
        self.btc = syms.index("BTCUSDT")

    def liquid(self, t: int, n: int = 50) -> np.ndarray:
        if t < 30:
            return np.array([], int)
        med = np.median(self.qv[t - 30:t], axis=0)
        alive = ~np.isnan(self.o[t]) & (self.first <= t - 30)
        idx = np.nonzero(alive)[0]
        return idx[np.argsort(-med[idx])][:n]


def trade(D: Daily, j: int, e: int, x: int, d: int, cluster: str, hedge: bool = False) -> Optional[dict]:
    if x >= len(D.days) or e < 0:
        return None
    pe, px = D.o[e, j], D.o[x, j]
    if not (pe > 0 and px > 0):
        return None
    gross = d * (px / pe - 1.0) * 1e4
    fund = -d * float(D.fund[e:x, j].sum()) * 1e4
    cost = COST_BPS
    if hedge:                                             # opposite BTC leg, same notional
        b0, b1 = D.o[e, D.btc], D.o[x, D.btc]
        gross += -d * (b1 / b0 - 1.0) * 1e4
        fund += d * float(D.fund[e:x, D.btc].sum()) * 1e4
        cost += COST_BPS
    t = float(D.days[e])
    day = dt.datetime.fromtimestamp(t, dt.timezone.utc)
    ck = day.strftime("%Y-%m") if cluster == "month" else f"{day.isocalendar()[0]}-{day.isocalendar()[1]}"
    return {"t": t, "sym": D.syms[j], "dir": d, "gross_bps": gross, "fund_bps": fund, "cost_bps": cost, "net_bps": gross + fund - cost, "cluster": ck,
            "hold_days": x - e}


def stats(tr: Sequence[dict]) -> dict:
    n = len(tr)
    if n < 2:
        return {"n": n, "mean": float("nan"), "t": float("nan")}
    x = np.array([r["net_bps"] for r in tr])
    mu = float(x.mean())
    cl: Dict[str, float] = {}
    for r, v in zip(tr, x):
        cl[r["cluster"]] = cl.get(r["cluster"], 0.0) + v - mu
    c = np.array(list(cl.values()))
    se = float(np.sqrt((c ** 2).sum()) / n) if len(c) > 1 else float("nan")
    return {"n": n, "mean": round(mu, 2), "se": round(se, 2), "t": round(mu / se, 3) if se > 0 else float("nan"), "clusters": len(c),
            "gross": round(float(np.mean([r["gross_bps"] for r in tr])), 2), "fund": round(float(np.mean([r["fund_bps"] for r in tr])), 2),
            "win": round(float((x > 0).mean()), 3)}


def in_split(D: Daily, e: int, sp: str) -> bool:
    a, b = SPLITS[sp]
    return _ts(a) <= D.days[e] < _ts(b)


# ================================================================================ families
def f5_listing(D: Daily, L: int, H: int, hedge: bool, sp: str) -> List[dict]:
    out = []
    t0 = _ts("2023-03-01")
    for j in range(len(D.syms)):
        f = D.first[j]
        if D.days[f] < t0 or f + L + H >= len(D.days):
            continue
        if np.median(D.qv[f:f + 7, j]) < 5e6:
            continue
        e = f + L
        if not in_split(D, e, sp):
            continue
        r = trade(D, j, e, e + H, -1, "month", hedge)
        if r:
            out.append(r)
    return out


def f6_ts_mom(D: Daily, R: int, H: int, side: int, sp: str) -> List[dict]:
    out = []
    for e in range(31, len(D.days) - H, H):
        if not in_split(D, e, sp):
            continue
        for j in D.liquid(e):
            if e - R < 0 or not (D.o[e - R, j] > 0):
                continue
            r = D.o[e, j] / D.o[e - R, j] - 1.0                # uses opens up to the entry open itself: known at entry
            tr = trade(D, j, e, e + H, side * (1 if r > 0 else -1), "week")
            if tr:
                out.append(tr)
    return out


def f7_xs(D: Daily, R: int, H: int, q: float, side: int, sp: str) -> List[dict]:
    out = []
    for e in range(31, len(D.days) - H, H):
        if not in_split(D, e, sp):
            continue
        liq = D.liquid(e)
        r = np.array([D.o[e, j] / D.o[e - R, j] - 1.0 if D.o[e - R, j] > 0 else np.nan for j in liq])
        ok = ~np.isnan(r)
        liq, r = liq[ok], r[ok]
        if len(liq) < 20:
            continue
        k = max(1, int(q * len(liq)))
        order = np.argsort(r)
        for j in liq[order[-k:]]:
            tr = trade(D, j, e, e + H, side, "week")
            out += [tr] if tr else []
        for j in liq[order[:k]]:
            tr = trade(D, j, e, e + H, -side, "week")
            out += [tr] if tr else []
    return out


def f8_carry(D: Daily, H: int, q: float, sp: str) -> List[dict]:
    out = []
    for e in range(31, len(D.days) - H, H):
        if not in_split(D, e, sp):
            continue
        liq = D.liquid(e)
        fr = D.fund[e - 3:e, liq].sum(axis=0)              # funding settled over the 3 days before entry
        k = max(1, int(q * len(liq)))
        order = np.argsort(fr)
        for j in liq[order[-k:]]:                          # highest funding: short (receive)
            tr = trade(D, j, e, e + H, -1, "week")
            out += [tr] if tr else []
        for j in liq[order[:k]]:                           # lowest (most negative) funding: long (receive)
            tr = trade(D, j, e, e + H, 1, "week")
            out += [tr] if tr else []
    return out


GRID = {
    "F5_listing_short": (f5_listing, {"L": [1, 3, 7], "H": [7, 14, 30], "hedge": [False, True]}),
    "F6_ts_momentum": (f6_ts_mom, {"R": [7, 14, 28], "H": [1, 7], "side": [1]}),
    "F7_xs_rank": (f7_xs, {"R": [7, 28], "H": [7], "q": [0.1, 0.2], "side": [1, -1]}),
    "F8_funding_carry": (f8_carry, {"H": [1, 3, 7], "q": [0.1, 0.2]}),
}


def screen(D: Daily) -> List[dict]:
    rows = []
    for fam, (fn, g) in GRID.items():
        keys = sorted(g)
        for combo in itertools.product(*[g[k] for k in keys]):
            p = dict(zip(keys, combo))
            row = {"family": fam, "params": p, "id": fam + "|" + ",".join(f"{k}={v}" for k, v in sorted(p.items()))}
            for sp in ("train", "val"):
                row[sp] = stats(fn(D, **p, sp=sp))
            rows.append(row)
            print(f"{row['id']:55s} train {row['train'].get('mean')} t={row['train'].get('t')} n={row['train']['n']} | val {row['val'].get('mean')} t={row['val'].get('t')} n={row['val']['n']}", flush=True)
    return rows


def qualify(rows: Sequence[dict]) -> List[dict]:
    out = []
    for fam in GRID:
        ok = [r for r in rows if r["family"] == fam and r["train"]["n"] >= 30 and r["train"]["mean"] > 0 and r["train"]["t"] > 2 and r["val"]["n"] >= 10
              and r["val"]["mean"] > 0]
        if ok:
            out.append(max(ok, key=lambda r: r["val"]["t"]))
    return out


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--npz", default="runs/p15/bn_daily.npz")
    p.add_argument("--stage", choices=["screen", "oos"], default="screen")
    p.add_argument("--prereg", default="docs/PREREG_P15B.json")
    a = p.parse_args(argv)
    D = Daily(a.npz)
    print("symbols", len(D.syms), "days", len(D.days), flush=True)
    if a.stage == "screen":
        rows = screen(D)
        json.dump(rows, open("runs/p15/daily_screen.json", "w"), indent=0, default=float)
        q = qualify(rows)
        print("QUALIFIED:", [(r["id"], r["train"], r["val"]) for r in q])
    else:
        pre = json.load(open(a.prereg))
        res = []
        for c in pre["candidates"]:
            fn = GRID[c["family"]][0]
            tr = fn(D, **c["params"], sp="oos")
            res.append({"id": c["id"], "oos": stats(tr), "trades": tr})
            print(c["id"], res[-1]["oos"], flush=True)
        json.dump(res, open("runs/p15/daily_oos.json", "w"), default=float)


if __name__ == "__main__":
    main()
