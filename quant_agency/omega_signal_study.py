"""Forward returns of the ``meme_momentum`` entry signal on recorded live pump.fun tapes, net of the round-trip cost.

The paper engine trades few of the signals it sees: one position per token, six per sleeve, and none while the sleeve is quarantined.
This study scores *every* signal instead, at most one per token per ``cooldown_s``. It applies the same entry conditions as
``HFPaperEngine._momentum`` (same ``MomentumCfg``) and uses only information available at the signal. The entry price is the curve price
as of landing (signal time + latency). The exit is the curve price as of +h seconds; the net return subtracts the round-trip fee and
network cost of a 5 USD trade at the tape's SOL price. Each token counts as one cluster for the standard error.

    python -m quant_agency.omega_signal_study runs/omega/*/tape.jsonl.gz
"""
from __future__ import annotations

import argparse
import bisect
import json
import math
from collections import defaultdict
from typing import Dict, List, Sequence

from .hf_paper_engine import EngineConfig
from .meme_discovery import TradePrint, Universe
from .omega_daemon import read_tape

HORIZONS = (10, 30, 60, 120, 300)


def study(paths: Sequence[str], cfg: EngineConfig = None, cooldown_s: float = 60.0, trade_usd: float = 5.0) -> dict:
    cfg = cfg or EngineConfig()
    c = cfg.momentum
    uni = Universe(max_tokens=20000, ttl_s=1e9)
    curve: Dict[str, List[tuple]] = defaultdict(list)          # mint -> [(t, price, real_sol)]
    signals: List[tuple] = []                                   # (mint, t)
    last_sig: Dict[str, float] = {}
    sol_px: List[float] = []
    for path in paths:
        for ev in read_tape(path):
            if ev["kind"] == "sol":
                sol_px.append(ev["px"])
                continue
            if ev["kind"] == "create":
                st = uni.get(ev["mint"], "pump", ev["t"])
                st.created_t = ev["t"]
                continue
            if ev["kind"] != "print" or ev.get("venue") != "pump":
                continue
            p = TradePrint(ev["t"], "pump", ev["key"], ev["side"], ev["qty"], ev["quote"], ev["price"], ev.get("post_price", float("nan")),
                           ev.get("v_quote", float("nan")), ev.get("v_base", float("nan")), ev.get("real_quote", float("nan")), ev.get("fee_bps", float("nan")),
                           ev.get("user", ""))
            st = uni.on_print(p)
            curve[p.key].append((p.t, p.v_quote / p.v_base, p.real_quote))
            if p.t - last_sig.get(p.key, -1e18) < cooldown_s or not (st.real_quote >= c.min_real_sol):
                continue
            f = st.window(p.t, c.w_fast)
            if f["n"] < c.min_prints or f["unique"] < c.min_unique or f["buy_quote"] < c.min_buy_ratio * max(f["sell_quote"], 1e-9) or f["net_quote"] < c.min_net_sol:
                continue
            if not (c.min_ret <= f["ret"] <= c.max_ret):
                continue
            s = st.window(p.t, c.w_slow)
            acc = ((f["buy_quote"] + f["sell_quote"]) / c.w_fast) / max((s["buy_quote"] + s["sell_quote"]) / c.w_slow, 1e-12)
            if acc < c.min_accel:
                continue
            last_sig[p.key] = p.t
            signals.append((p.key, p.t))
    sol = sum(sol_px) / len(sol_px) if sol_px else 180.0
    fee = max(cfg.pump_fee_floor_bps, 0.0) / 1e4
    fixed = 2 * (cfg.sol_tx_fee_sol + cfg.sol_priority_fee_sol) * sol / trade_usd
    cost = 2 * fee + fixed                                      # round trip, as a fraction of the 5 USD notional

    def asof(rows, t):
        i = bisect.bisect_right(rows, (t, float("inf"), float("inf"))) - 1
        return rows[i] if i >= 0 else None

    res = {"signals": len(signals), "tokens": len({m for m, _ in signals}), "sol_usd": round(sol, 2), "round_trip_cost": round(cost, 5), "horizons": {}}
    for h in HORIZONS:
        by_tok: Dict[str, List[float]] = defaultdict(list)
        for mint, t in signals:
            rows = curve[mint]
            if rows[-1][0] < t + h:                             # the tape ends before the horizon: not scored
                continue
            a, b = asof(rows, t + cfg.pump_latency_s), asof(rows, t + h)
            if a is None or b is None or a[1] <= 0:
                continue
            gross = b[1] / a[1] - 1.0
            by_tok[mint].append(gross)
        xs = [g for v in by_tok.values() for g in v]
        n = len(xs)
        if n == 0:
            res["horizons"][str(h)] = {"n": 0}
            continue
        m = sum(xs) / n
        cl = [sum(v) - m * len(v) for v in by_tok.values()]
        se = math.sqrt(sum(x * x for x in cl)) / n if len(cl) > 1 else float("nan")
        xs_sorted = sorted(xs)
        res["horizons"][str(h)] = {"n": n, "clusters": len(by_tok), "gross_mean": round(m, 5), "gross_se": round(se, 5), "net_mean": round(m - cost, 5),
                                   "t_net": round((m - cost) / se, 2) if se == se and se > 0 else None, "median": round(xs_sorted[n // 2], 5),
                                   "share_gt_cost": round(sum(x > cost for x in xs) / n, 4), "p10": round(xs_sorted[int(0.1 * n)], 5),
                                   "p90": round(xs_sorted[min(n - 1, int(0.9 * n))], 5)}
    return res


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("tapes", nargs="+")
    p.add_argument("--out", default=None)
    a = p.parse_args(argv)
    r = study(a.tapes)
    print(json.dumps(r, indent=1))
    if a.out:
        json.dump(r, open(a.out, "w"), indent=1)


if __name__ == "__main__":
    main()
