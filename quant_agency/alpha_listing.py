"""Phase 15, Track 2: new-listing short with a hard per-trade loss bound (isolated-margin stop), BTC-hedged.

Rule (entry identical to F5): short a new Binance USD-M perp at the open of listing day + L, long the same notional of BTC, hold up to H
days. Bound: an isolated-margin stop at entry x (1 + s): on the first day whose high reaches it, the short is closed at the stop price,
or at that day's open if it opened above the stop (gap), plus 1 % stop slippage; the BTC leg is closed at the same day's close.
Costs: 20 bps per round trip per leg + actual funding of both legs.

Windows: SELECT the stop s on 2024-01..2025-06 entries (train + validation of round 2; best mean among s in the grid, which must also be
positive in both halves); OOS-A = entries 2023-03..2023-12 (never used by any earlier test); OOS-B = 2025-07..2026-09 (already used by
the uncapped F5, so it is reported as secondary evidence only).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from typing import Dict, List

import numpy as np

from .alpha_daily import COST_BPS, Daily, _ts

WINDOWS = {"select_a": ("2024-01-01", "2025-01-01"), "select_b": ("2025-01-01", "2025-07-01"),
           "oos_a": ("2023-03-01", "2024-01-01"), "oos_b": ("2025-07-01", "2026-10-01")}


def load_highs(D: Daily, npz: str) -> np.ndarray:
    z = np.load(npz)
    h = np.full_like(D.o, np.nan)
    ix = {d: i for i, d in enumerate(D.days)}
    for j, s in enumerate(D.syms):
        a = z["d__" + s]
        ii = np.array([ix[d] for d in a[:, 0]])
        h[ii, j] = a[:, 2]
    return h


def trades(D: Daily, Hi: np.ndarray, L: int, H: int, s: float, win: str, min_qv: float = 5e6) -> List[dict]:
    a, b = WINDOWS[win]
    out = []
    for j in range(len(D.syms)):
        f = D.first[j]
        e = f + L
        if e + H >= len(D.days) or not (_ts(a) <= D.days[e] < _ts(b)) or D.days[f] < _ts("2023-02-01"):
            continue
        if np.median(D.qv[f:f + 7, j]) < min_qv:
            continue
        pe = D.o[e, j]
        if not pe > 0:
            continue
        stop = pe * (1 + s) if s > 0 else np.inf
        x, px_exit, stopped = e + H, D.o[e + H, j], False
        for k in range(e, e + H):
            if D.o[k, j] >= stop:                       # gapped above the stop at the open
                x, px_exit, stopped = k, D.o[k, j] * 1.01, True
                break
            if Hi[k, j] >= stop:
                x, px_exit, stopped = k, stop * 1.01, True
                break
        if not px_exit > 0:
            continue
        short = -(px_exit / pe - 1.0) * 1e4
        bx = D.c[x, D.btc] if stopped else D.o[x, D.btc]
        hedge = (bx / D.o[e, D.btc] - 1.0) * 1e4
        last = x + 1 if stopped else x
        fund = float(D.fund[e:last, j].sum()) * 1e4 - float(D.fund[e:last, D.btc].sum()) * 1e4   # short receives, long pays
        net = short + hedge + fund - 2 * COST_BPS
        day = dt.datetime.fromtimestamp(float(D.days[e]), dt.timezone.utc)
        out.append({"t": float(D.days[e]), "sym": D.syms[j], "net_bps": net, "short_bps": short, "hedge_bps": hedge, "fund_bps": fund, "stopped": stopped,
                    "cluster": day.strftime("%Y-%m"), "hold_days": last - e})
    return out


def stats(tr: List[dict]) -> dict:
    n = len(tr)
    if n < 2:
        return {"n": n}
    x = np.array([r["net_bps"] for r in tr])
    mu = float(x.mean())
    cl: Dict[str, float] = {}
    for r, v in zip(tr, x):
        cl[r["cluster"]] = cl.get(r["cluster"], 0.0) + v - mu
    c = np.array(list(cl.values()))
    se = float(np.sqrt((c ** 2).sum()) / n)
    return {"n": n, "mean_bps": round(mu, 1), "median_bps": round(float(np.median(x)), 1), "se": round(se, 1), "t": round(mu / se, 3) if se > 0 else None,
            "clusters": len(c), "win": round(float((x > 0).mean()), 3), "stopped": int(sum(r["stopped"] for r in tr)), "worst_bps": round(float(x.min()), 1)}


def account(tr: List[dict], bankroll: float = 100.0, alloc: float = 0.015, stop: float = 0.5) -> dict:
    """100 USD account, trades in entry order, each short sized so that the stop loss (s + slippage + costs) costs ``alloc`` of current
    equity; positions overlap, each sized off equity at its entry; P&L booked at exit."""
    ev = sorted(tr, key=lambda r: r["t"])
    eq, peak, mdd = bankroll, bankroll, 0.0
    curve = []
    open_pos = []
    for r in ev:
        done = [p for p in open_pos if p["exit_t"] <= r["t"]]
        for p in done:
            eq += p["pnl"]
            open_pos.remove(p)
        notional = eq * alloc / (stop + 0.03)
        pnl = notional * r["net_bps"] / 1e4
        open_pos.append({"exit_t": r["t"] + r["hold_days"] * 86400, "pnl": pnl})
        peak = max(peak, eq)
        mdd = max(mdd, (peak - eq) / peak)
        curve.append((r["t"], round(eq, 4)))
    for p in open_pos:
        eq += p["pnl"]
    curve.append((ev[-1]["t"] if ev else 0, round(eq, 4)))
    return {"final_equity": round(eq, 2), "max_drawdown": round(mdd, 4), "trades": len(ev), "curve": curve}


GRID_S = [0.25, 0.5, 1.0, 2.0]


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--stage", choices=["select", "oos"], default="select")
    p.add_argument("--prereg", default="docs/PREREG_P15T2.json")
    a = p.parse_args(argv)
    D = Daily("runs/p15/bn_daily.npz")
    Hi = load_highs(D, "runs/p15/bn_daily.npz")
    if a.stage == "select":
        rows = []
        for s in GRID_S:
            ra, rb = stats(trades(D, Hi, 1, 30, s, "select_a")), stats(trades(D, Hi, 1, 30, s, "select_b"))
            rows.append({"s": s, "a": ra, "b": rb})
            print(s, ra, rb, flush=True)
        ok = [r for r in rows if r["a"].get("mean_bps", -1) > 0 and r["b"].get("mean_bps", -1) > 0]
        best = max(ok, key=lambda r: (r["a"]["n"] * r["a"]["mean_bps"] + r["b"]["n"] * r["b"]["mean_bps"]) / (r["a"]["n"] + r["b"]["n"])) if ok else None
        print("SELECTED", best)
        json.dump(rows, open("runs/p15/listing_select.json", "w"), indent=1)
    else:
        pre = json.load(open(a.prereg))
        s = pre["stop_s"]
        res = {}
        for w in ("oos_a", "oos_b"):
            tr = trades(D, Hi, 1, 30, s, w)
            res[w] = {"stats": stats(tr), "account": account(tr, stop=s), "trades": tr}
            print(w, res[w]["stats"], {k: v for k, v in res[w]["account"].items() if k != "curve"})
        json.dump(res, open("runs/p15/listing_oos.json", "w"), default=float)


if __name__ == "__main__":
    main()
