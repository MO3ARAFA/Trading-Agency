"""Final sprint, kernel 1: new-listing short after exhaustion confirmation, hard stop, optional take-profit, BTC-hedged (daily bars).

Declared before any result was computed (grid of 8):
  * listing day f = first daily bar of a Binance USD-M perp listed >= 2023-02 with listing-week median quote volume >= 5 M USD;
  * exhaustion trigger: the first day f+d (d = 1..5) whose close is below day f's typical price (h+l+c)/3 AND whose high is below the
    highest high so far (lower high); entry = short at the open of the next day, long the same notional of BTC. No trigger -> no trade;
  * stop s in {0.25, 0.35} above entry: the first day whose high reaches it closes the short at stop x 1.02 (2 % stop slippage), or at
    that day's open x 1.02 if it gapped above; take-profit tp in {none, 0.30}: the first day whose low reaches entry x (1 - tp) closes
    at that price (a stop and a take-profit on the same day count as the stop); hold H in {14, 30} days otherwise;
  * costs: 20 bps per round trip per leg + actual funding of both legs (``alpha_daily`` conventions); t clustered by entry month;
  * TRAIN 2024, VALIDATION 2025-H1, OOS 2025-07..2026-09; qualify: TRAIN mean > 0 with t > 2 (n >= 30) and VALIDATION mean > 0; the
    qualifier with the best validation t is frozen (docs/PREREG_FINAL_K1.json) before OOS.
Disclosure: the OOS window was already used by F5 (uncapped) and Track 2 (stop, no trigger); only the trigger is new.
"""
from __future__ import annotations

import datetime as dt
import itertools
import json
from typing import List, Optional

import numpy as np

from .alpha_daily import COST_BPS, SPLITS, Daily, _ts
from .alpha_listing import account, stats

GRID = list(itertools.product([0.25, 0.35], [None, 0.30], [14, 30]))


def load_hl(D: Daily, npz: str):
    z = np.load(npz)
    hi, lo = np.full_like(D.o, np.nan), np.full_like(D.o, np.nan)
    ix = {d: i for i, d in enumerate(D.days)}
    for j, s in enumerate(D.syms):
        a = z["d__" + s]
        ii = np.array([ix[d] for d in a[:, 0]])
        hi[ii, j], lo[ii, j] = a[:, 2], a[:, 3]
    return hi, lo


def trigger(D: Daily, Hi, Lo, j: int) -> Optional[int]:
    f = D.first[j]
    tp0 = (Hi[f, j] + Lo[f, j] + D.c[f, j]) / 3
    for d in range(1, 6):
        k = f + d
        if k + 1 >= len(D.days):
            return None
        if D.c[k, j] < tp0 and Hi[k, j] < np.nanmax(Hi[f:k, j]):
            return k + 1
    return None


def trades(D: Daily, Hi, Lo, s: float, tp: Optional[float], H: int, win: str, min_qv: float = 5e6) -> List[dict]:
    a, b = SPLITS[win]
    out = []
    for j in range(len(D.syms)):
        f = D.first[j]
        if j == D.btc or D.days[f] < _ts("2023-02-01") or np.median(D.qv[f:f + 7, j]) < min_qv:
            continue
        e = trigger(D, Hi, Lo, j)
        if e is None or e + H >= len(D.days) or not (_ts(a) <= D.days[e] < _ts(b)):
            continue
        pe = D.o[e, j]
        if not pe > 0:
            continue
        stop, take = pe * (1 + s), (pe * (1 - tp) if tp else -np.inf)
        x, px, how = e + H, D.o[e + H, j], "time"
        for k in range(e, e + H):
            if D.o[k, j] >= stop:
                x, px, how = k, D.o[k, j] * 1.02, "stop"
                break
            if Hi[k, j] >= stop:
                x, px, how = k, stop * 1.02, "stop"
                break
            if Lo[k, j] <= take:
                x, px, how = k, take, "take"
                break
        if not px > 0:
            continue
        short = -(px / pe - 1.0) * 1e4
        intraday = how != "time"
        bx = D.c[x, D.btc] if intraday else D.o[x, D.btc]
        hedge = (bx / D.o[e, D.btc] - 1.0) * 1e4
        last = x + 1 if intraday else x
        fund = float(D.fund[e:last, j].sum()) * 1e4 - float(D.fund[e:last, D.btc].sum()) * 1e4
        day = dt.datetime.fromtimestamp(float(D.days[e]), dt.timezone.utc)
        out.append({"t": float(D.days[e]), "sym": D.syms[j], "net_bps": short + hedge + fund - 2 * COST_BPS, "short_bps": short, "fund_bps": fund,
                    "stopped": how == "stop", "how": how, "cluster": day.strftime("%Y-%m"), "hold_days": last - e, "lag_days": int(e - f)})
    return out


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--stage", choices=["screen", "oos"], default="screen")
    a = p.parse_args(argv)
    D = Daily("runs/p15/bn_daily.npz")
    Hi, Lo = load_hl(D, "runs/p15/bn_daily.npz")
    if a.stage == "screen":
        rows = []
        for s, tp, H in GRID:
            tr, va = stats(trades(D, Hi, Lo, s, tp, H, "train")), stats(trades(D, Hi, Lo, s, tp, H, "val"))
            ok = tr.get("n", 0) >= 30 and tr.get("mean_bps", -1) > 0 and (tr.get("t") or 0) > 2 and va.get("mean_bps", -1) > 0
            rows.append({"s": s, "tp": tp, "H": H, "train": tr, "val": va, "qualifies": ok})
            print(s, tp, H, "TRAIN", tr, "VAL", va, "Q" if ok else "", flush=True)
        q = [r for r in rows if r["qualifies"]]
        best = max(q, key=lambda r: r["val"]["t"] or -9) if q else None
        print("FROZEN CANDIDATE", best)
        json.dump({"rows": rows, "best": best}, open("runs/p15/k1_screen.json", "w"), indent=1)
    else:
        pre = json.load(open("docs/PREREG_FINAL_K1.json"))
        tr = trades(D, Hi, Lo, pre["s"], pre["tp"], pre["H"], "oos")
        res = {"stats": stats(tr), "account": account(tr, stop=pre["s"]), "trades": tr}
        print(res["stats"], {k: v for k, v in res["account"].items() if k != "curve"})
        json.dump(res, open("runs/p15/k1_oos.json", "w"), default=float)


if __name__ == "__main__":
    main()
