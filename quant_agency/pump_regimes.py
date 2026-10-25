"""Phase 15, Vector 3: two pump.fun sub-regimes scored on recorded live tapes (same entry/exit/cost rules as omega_signal_study).

  graduation_squeeze   real SOL in the curve >= ``prog`` x 85 SOL (the completion threshold), net buy flow > 0 over 60 s, >= 8 unique
                       traders over 60 s; the exit is the curve price at +h or the last curve price before the completion event
                       (the migrated pool opens at that price), whichever comes first
  capitulation_bounce  price <= (1 - ``drop``) x its 5-minute high, then over the last 30 s buys > ``ratio`` x sells (SOL) with >= 6
                       unique traders; real SOL >= 5
Entry at the curve price as of signal + 0.8 s; cost = round trip of a 5 USD trade (2 x 1.25 % fee + 2 x network fee). One signal per
token per 120 s. Standard errors cluster by token. Tapes are split by file order: the caller declares which are discovery and which OOS.
"""
from __future__ import annotations

import bisect
import json
import math
from collections import defaultdict
from typing import Dict, List, Sequence

from .meme_discovery import TradePrint, Universe
from .omega_daemon import read_tape

COMPLETE_SOL = 85.0


def score(paths: Sequence[str], regime: str, params: dict, horizons=(30, 60, 120, 300), latency=0.8, cooldown=120.0) -> dict:
    uni = Universe(max_tokens=50000, ttl_s=1e9)
    curve: Dict[str, List[tuple]] = defaultdict(list)
    complete_t: Dict[str, float] = {}
    sigs = []
    last: Dict[str, float] = {}
    sol = []
    for path in paths:
        for ev in read_tape(path):
            k = ev["kind"]
            if k == "sol":
                sol.append(ev["px"])
            elif k == "complete":
                complete_t.setdefault(ev["mint"], ev["t"])
            elif k == "print" and ev.get("venue") == "pump":
                p = TradePrint(ev["t"], "pump", ev["key"], ev["side"], ev["qty"], ev["quote"], ev["price"], ev.get("post_price", float("nan")),
                               ev.get("v_quote", float("nan")), ev.get("v_base", float("nan")), ev.get("real_quote", float("nan")), ev.get("fee_bps", float("nan")),
                               ev.get("user", ""))
                st = uni.on_print(p)
                px = p.v_quote / p.v_base
                curve[p.key].append((p.t, px))
                if p.t - last.get(p.key, -1e18) < cooldown or p.key in complete_t:
                    continue
                if regime == "graduation_squeeze":
                    w = st.window(p.t, 60.0)
                    ok = st.real_quote >= params["prog"] * COMPLETE_SOL and w["net_quote"] > 0 and w["unique"] >= 8
                else:
                    if not st.real_quote >= 5.0:
                        continue
                    hist = [x for x in curve[p.key] if x[0] >= p.t - 300.0]
                    hi = max(x[1] for x in hist)
                    w = st.window(p.t, 30.0)
                    ok = px <= (1 - params["drop"]) * hi and w["buy_quote"] > params["ratio"] * max(w["sell_quote"], 1e-9) and w["unique"] >= 6
                if ok:
                    last[p.key] = p.t
                    sigs.append((p.key, p.t))
    s = sum(sol) / len(sol) if sol else 180.0
    cost = 2 * 0.0125 + 2 * 0.000105 * s / 5.0
    res = {"regime": regime, "params": params, "signals": len(sigs), "cost": round(cost, 5), "h": {}}

    def asof(rows, t):
        i = bisect.bisect_right(rows, (t, float("inf"))) - 1
        return rows[i] if i >= 0 else None
    for h in horizons:
        by = defaultdict(list)
        for m, t in sigs:
            rows = curve[m]
            end = complete_t.get(m)
            t_exit = min(t + h, end - 1e-6) if end else t + h
            if not end and rows[-1][0] < t + h:
                continue
            a, b = asof(rows, t + latency), asof(rows, t_exit)
            if not a or not b or a[1] <= 0 or b[0] < a[0]:
                continue
            by[m].append(b[1] / a[1] - 1.0)
        xs = [g for v in by.values() for g in v]
        if not xs:
            res["h"][str(h)] = {"n": 0}
            continue
        mu = sum(xs) / len(xs)
        cl = [sum(v) - mu * len(v) for v in by.values()]
        se = math.sqrt(sum(c * c for c in cl)) / len(xs) if len(cl) > 1 else float("nan")
        res["h"][str(h)] = {"n": len(xs), "tokens": len(by), "gross": round(mu, 4), "net": round(mu - cost, 4),
                            "t_net": round((mu - cost) / se, 2) if se == se and se > 0 else None}
    return res


GRID = {"graduation_squeeze": [{"prog": 0.85}, {"prog": 0.92}],
        "capitulation_bounce": [{"drop": 0.4, "ratio": 1.5}, {"drop": 0.6, "ratio": 1.5}, {"drop": 0.4, "ratio": 3.0}]}


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("tapes", nargs="+")
    a = p.parse_args(argv)
    out = [score(a.tapes, reg, pr) for reg, ps in GRID.items() for pr in ps]
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
