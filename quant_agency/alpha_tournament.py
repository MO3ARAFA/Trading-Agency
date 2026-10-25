"""Phase 15: hypothesis tournament on Hyperliquid perp candles (91 coins, 5-minute and 15-minute bars).

Protocol (fixed before any family was evaluated):
  * time split per bar interval: TRAIN = first 50 % of the bars, VALIDATION = next 25 %, OOS = last 25 %; nothing in one split is used
    to compute a signal in another (rolling statistics only look backwards, so an OOS signal uses OOS-era and earlier prices only);
  * a signal is computed on a *closed* bar t; entry at the open of bar t+1 (the first trade after the close), exit at the open of bar
    t+1+H; one position per coin at a time;
  * costs per round trip, in bps of notional: 2 x 4.5 taker fee + 2 x 1.5 x (measured half-spread of that coin) + 2 x 2 bps extra
    slippage, plus funding paid/received pro rata over the hold (Hyperliquid funding history);
  * statistics: mean net bps per trade, standard error clustered by entry hour (trades that open in the same hour share one cluster);
  * selection: a configuration qualifies only if its net mean is positive with t > 2 on TRAIN *and* positive on VALIDATION; per family
    the qualifying configuration with the highest validation t is the family's candidate; candidates are frozen (SHA-256 of their
    parameters and of this file) before their OOS split is ever evaluated.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import math
import os
from dataclasses import asdict, dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

TAKER_BPS = 4.5
SPREAD_MULT = 1.5
EXTRA_SLIP_BPS = 2.0
SPLITS = (0.5, 0.75)


# ================================================================================ data
@dataclass
class Panel:
    interval: str
    t: np.ndarray               # (T,) bar open times, seconds
    o: np.ndarray               # (T, N)
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    v: np.ndarray               # USD volume
    coins: List[str]
    half_spread_bps: np.ndarray  # (N,)
    funding: np.ndarray         # (T, N) funding rate per hour applicable to the bar (fraction)

    @property
    def bar_s(self) -> float:
        return float(np.median(np.diff(self.t)))


def load_panel(npz: str, meta: str, interval: str, min_cover: float = 0.9) -> Panel:
    z = np.load(npz)
    m = json.load(open(meta))
    coins = [c for c in m["coins"] if f"{interval}__{c}" in z.files and len(z[f"{interval}__{c}"]) > 0]
    t_all = np.unique(np.concatenate([z[f"{interval}__{c}"][:, 0] for c in coins]))
    keep = [c for c in coins if len(z[f"{interval}__{c}"]) >= min_cover * len(t_all)]
    T, N = len(t_all), len(keep)
    idx = {t: i for i, t in enumerate(t_all)}
    arr = {k: np.full((T, N), np.nan) for k in ("o", "h", "l", "c", "v")}
    fund = np.zeros((T, N))
    for j, c in enumerate(keep):
        a = z[f"{interval}__{c}"]
        ii = np.array([idx[t] for t in a[:, 0]])
        for k, col in (("o", 1), ("h", 2), ("l", 3), ("c", 4)):
            arr[k][ii, j] = a[:, col]
        arr["v"][ii, j] = a[:, 5] * a[:, 4]
        f = z[f"fund__{c}"] if f"fund__{c}" in z.files else np.zeros((0, 2))
        if len(f):
            pos = np.searchsorted(f[:, 0], t_all, side="right") - 1
            fund[:, j] = np.where(pos >= 0, f[np.clip(pos, 0, None), 1], 0.0)
    for k in ("o", "h", "l", "c"):                         # forward-fill gaps (no trade in the bar)
        a = arr[k]
        for i in range(1, T):
            miss = np.isnan(a[i])
            a[i, miss] = arr["c"][i - 1, miss] if k != "c" else a[i - 1, miss]
    arr["v"] = np.nan_to_num(arr["v"])
    hs = np.array([max(m["spread_bps"].get(c, 5.0), 0.5) / 2.0 for c in keep])
    return Panel(interval, t_all, arr["o"], arr["h"], arr["l"], arr["c"], arr["v"], keep, hs, fund)


def split_bounds(T: int) -> Dict[str, Tuple[int, int]]:
    a, b = int(T * SPLITS[0]), int(T * SPLITS[1])
    return {"train": (0, a), "val": (a, b), "oos": (b, T)}


# ================================================================================ features (backward-looking only)
def rolling_std(x: np.ndarray, w: int) -> np.ndarray:
    """Std of x[t-w..t-1] for each t (excludes t)."""
    T = x.shape[0]
    out = np.full_like(x, np.nan)
    cs = np.nancumsum(np.nan_to_num(x), axis=0)
    cs2 = np.nancumsum(np.nan_to_num(x) ** 2, axis=0)
    cs = np.vstack([np.zeros((1, x.shape[1])), cs])
    cs2 = np.vstack([np.zeros((1, x.shape[1])), cs2])
    for t in range(w, T):
        s, s2 = cs[t] - cs[t - w], cs2[t] - cs2[t - w]
        mu = s / w
        out[t] = np.sqrt(np.maximum(s2 / w - mu ** 2, 1e-18))
    return out


def rolling_median(x: np.ndarray, w: int) -> np.ndarray:
    out = np.full_like(x, np.nan)
    for t in range(w, x.shape[0]):
        out[t] = np.median(x[t - w:t], axis=0)
    return out


# ================================================================================ trade simulation
def simulate(P: Panel, sig: np.ndarray, H: int, lo: int, hi: int, taker_bps: float = TAKER_BPS) -> List[dict]:
    """``sig[t, i]`` in {-1, 0, +1} computed at the close of bar t. Entry at o[t+1], exit at o[t+1+H]; trades whose entry falls in
    [lo, hi) and whose exit is inside the panel. One position per coin at a time."""
    T, N = sig.shape
    out = []
    bar_h = P.bar_s / 3600.0
    for i in range(N):
        busy_until = -1
        for t in np.nonzero(sig[:, i])[0]:
            e, x = t + 1, t + 1 + H
            if e < lo or e >= hi or x >= T or t < busy_until:
                continue
            d = sig[t, i]
            pe, px = P.o[e, i], P.o[x, i]
            if not (pe > 0 and px > 0):
                continue
            gross = d * (px / pe - 1.0) * 1e4
            cost = 2 * taker_bps + 2 * SPREAD_MULT * P.half_spread_bps[i] + 2 * EXTRA_SLIP_BPS
            fund = -d * float(P.funding[e:x, i].sum()) * bar_h * 1e4      # longs pay positive funding, shorts receive it
            out.append({"t": float(P.t[e]), "coin": P.coins[i], "dir": int(d), "gross_bps": gross, "cost_bps": cost, "fund_bps": fund,
                        "net_bps": gross - cost + fund, "hold_bars": H})
            busy_until = x
    return out


def stats(trades: Sequence[dict], key: str = "net_bps") -> dict:
    n = len(trades)
    if n < 2:
        return {"n": n, "mean": float("nan"), "se": float("nan"), "t": float("nan"), "clusters": n}
    x = np.array([r[key] for r in trades])
    mu = float(x.mean())
    cl: Dict[int, float] = {}
    for r, v in zip(trades, x):
        k = int(r["t"] // 3600)
        cl[k] = cl.get(k, 0.0) + (v - mu)
    c = np.array(list(cl.values()))
    se = float(np.sqrt((c ** 2).sum()) / n) if len(c) > 1 else float("nan")
    return {"n": n, "mean": round(mu, 3), "se": round(se, 3), "t": round(mu / se, 3) if se > 0 else float("nan"), "clusters": len(c),
            "gross": round(float(np.mean([r["gross_bps"] for r in trades])), 3), "win": round(float((x > 0).mean()), 3)}


# ================================================================================ candidate families
def fam_blowoff(P: Panel, k: int, z: float, vr: float, side: int, stall: bool, look: int) -> np.ndarray:
    """|k-bar log return| > z rolling sd (own history, ``look`` bars, excluding now) with USD volume > vr x rolling median volume.
    side=-1: fade (short a spike up / long a crash); side=+1: follow. ``stall``: require bar t not to make a new k-bar extreme."""
    lc = np.log(P.c)
    r = np.full_like(lc, np.nan)
    r[k:] = lc[k:] - lc[:-k]
    r1 = np.vstack([np.full((1, lc.shape[1]), np.nan), np.diff(lc, axis=0)])
    sd = rolling_std(r1, look) * math.sqrt(k)
    vm = rolling_median(P.v, look)
    zz = r / sd
    hot = (np.abs(zz) > z) & (P.v > vr * np.maximum(vm, 1.0))
    if stall:                                        # the spike bar closed off its extreme (a wick back)
        rng = np.maximum(P.h - P.l, 1e-18)
        up_off = (P.h - P.c) / rng > 0.4
        dn_off = (P.c - P.l) / rng > 0.4
        hot &= np.where(zz > 0, up_off, dn_off)
    s = np.sign(np.nan_to_num(zz)) * hot * side
    return s.astype(int)


def fam_xs_reversal(P: Panel, k: int, q: float, side: int) -> np.ndarray:
    """Cross-sectional: k-bar return minus the cross-sectional median; the top / bottom ``q`` fraction get -side / +side... every k bars."""
    lc = np.log(P.c)
    r = np.full_like(lc, np.nan)
    r[k:] = lc[k:] - lc[:-k]
    rel = r - np.nanmedian(r, axis=1, keepdims=True)
    s = np.zeros_like(r, dtype=int)
    for t in range(k, r.shape[0], k):
        row = rel[t]
        ok = ~np.isnan(row)
        if ok.sum() < 20:
            continue
        lo_q, hi_q = np.nanquantile(row, q), np.nanquantile(row, 1 - q)
        s[t, ok & (row >= hi_q)] = side
        s[t, ok & (row <= lo_q)] = -side
    return s


FAMILIES = {
    "blowoff_fade": (fam_blowoff, {"k": [1, 3, 6], "z": [3.0, 4.0, 5.0], "vr": [3.0, 6.0], "side": [-1], "stall": [False, True], "look": [288]},
                     [3, 6, 12, 24]),
    "blowoff_follow": (fam_blowoff, {"k": [1, 3, 6], "z": [3.0, 4.0, 5.0], "vr": [3.0, 6.0], "side": [1], "stall": [False], "look": [288]},
                       [3, 6, 12, 24]),
    "xs_reversal": (fam_xs_reversal, {"k": [1, 3, 12], "q": [0.05, 0.1], "side": [-1]}, [1, 3, 12]),
    "xs_momentum": (fam_xs_reversal, {"k": [3, 12, 48], "q": [0.05, 0.1], "side": [1]}, [3, 12, 48]),
}


def config_id(fam: str, interval: str, params: dict, H: int) -> str:
    return f"{fam}|{interval}|" + ",".join(f"{k}={v}" for k, v in sorted(params.items())) + f"|H={H}"


def run_family(P: Panel, fam: str, splits: Optional[Sequence[str]] = ("train", "val")) -> List[dict]:
    fn, grid, Hs = FAMILIES[fam]
    b = split_bounds(len(P.t))
    rows = []
    keys = sorted(grid)
    for combo in itertools.product(*[grid[k] for k in keys]):
        params = dict(zip(keys, combo))
        if P.interval == "15m" and "look" in params:
            params = {**params, "look": 96}         # one day of bars at either interval
        sig = fn(P, **params)
        for H in Hs:
            row = {"id": config_id(fam, P.interval, params, H), "family": fam, "interval": P.interval, "params": params, "H": H}
            for sp in splits:
                row[sp] = stats(simulate(P, sig, H, *b[sp]))
            rows.append(row)
    return rows


def qualify(rows: Sequence[dict]) -> Optional[dict]:
    ok = [r for r in rows if r["train"]["n"] >= 30 and r["train"]["mean"] > 0 and r["train"]["t"] > 2.0 and r["val"]["n"] >= 15 and r["val"]["mean"] > 0]
    return max(ok, key=lambda r: r["val"]["t"]) if ok else None


def freeze(cands: Sequence[dict], path: str) -> dict:
    src = open(__file__, "rb").read()
    body = {"candidates": [{k: c[k] for k in ("id", "family", "interval", "params", "H")} for c in cands],
            "code_sha256": hashlib.sha256(src).hexdigest(), "costs": {"taker_bps": TAKER_BPS, "spread_mult": SPREAD_MULT, "extra_slip_bps": EXTRA_SLIP_BPS},
            "splits": SPLITS, "rule": "OOS: one evaluation per frozen candidate; pass = net mean > 0 with t > 2 (Holm-adjusted across candidates reported)"}
    body["sha256"] = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    json.dump(body, open(path, "w"), indent=1)
    return body


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--npz", default="runs/p15/hl_candles.npz")
    p.add_argument("--meta", default="runs/p15/hl_meta.json")
    p.add_argument("--out", default="runs/p15")
    p.add_argument("--stage", choices=["screen", "oos"], default="screen")
    p.add_argument("--prereg", default="docs/PREREG_P15.json")
    a = p.parse_args(argv)
    panels = {iv: load_panel(a.npz, a.meta, iv) for iv in ("5m", "15m")}
    if a.stage == "screen":
        allrows, cands = [], []
        for iv, P in panels.items():
            print(iv, P.c.shape, "bars", {k: (round((P.t[v[1] - 1] - P.t[v[0]]) / 86400, 1)) for k, v in split_bounds(len(P.t)).items()}, flush=True)
            for fam in FAMILIES:
                rows = run_family(P, fam)
                allrows += rows
                best = qualify(rows)
                top = sorted(rows, key=lambda r: -(r["train"]["t"] if r["train"]["t"] == r["train"]["t"] else -9))[:3]
                print(f"  {fam:15s} configs={len(rows):3d} best-train: " + " ; ".join(f"{r['id'].split('|',2)[2]} tr {r['train']['mean']:+.1f}bps t={r['train']['t']} val {r['val']['mean']:+.1f} t={r['val']['t']} n={r['train']['n']}/{r['val']['n']}" for r in top), flush=True)
                if best:
                    cands.append(best)
                    print("   -> QUALIFIES:", best["id"], best["train"], best["val"], flush=True)
        json.dump(allrows, open(os.path.join(a.out, "tournament_screen.json"), "w"), indent=0, default=float)
        print("candidates:", [c["id"] for c in cands])
        if cands:
            print("frozen:", freeze(cands, a.prereg)["sha256"])
    else:
        pre = json.load(open(a.prereg))
        res = []
        for c in pre["candidates"]:
            P = panels[c["interval"]]
            fn = FAMILIES[c["family"]][0]
            sig = fn(P, **c["params"])
            tr = simulate(P, sig, c["H"], *split_bounds(len(P.t))["oos"])
            res.append({"id": c["id"], "oos": stats(tr), "trades": tr})
            print(c["id"], res[-1]["oos"])
        json.dump(res, open(os.path.join(a.out, "tournament_oos.json"), "w"), default=float)


if __name__ == "__main__":
    main()
