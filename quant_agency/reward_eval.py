"""Evaluate a reward-farm session against docs/PREREG_P15R.json (written before the session's numbers were seen).

    python -m quant_agency.reward_eval runs/p15/farm/<session>
"""
from __future__ import annotations

import json
import math
import os
import sys
from typing import List


def evaluate(run_dir: str, bankroll: float = 100.0) -> dict:
    s = json.load(open(os.path.join(run_dir, "farm_summary.json")))
    start = json.loads(open(os.path.join(run_dir, "farm_log.jsonl")).readline())
    order = [m["cid"] for m in start["markets"]]                    # selection order (pre-registered ranking)
    by = {m["cid"]: m for m in s["markets"]}
    rets: List[float] = [by[c]["equity"] / by[c]["n"] for c in order]
    n = len(rets)
    mu = sum(rets) / n
    sd = math.sqrt(sum((r - mu) ** 2 for r in rets) / (n - 1)) if n > 1 else float("nan")
    t = mu / (sd / math.sqrt(n)) if sd > 0 else float("nan")
    acct, cap = [], 0.0
    for c in order:
        if cap + by[c]["n"] <= bankroll:
            acct.append(c)
            cap += by[c]["n"]
    hours = (s["t1"] - s["t0"]) / 3600.0
    acct_net = sum(by[c]["equity"] for c in acct)
    res = {"hours": round(hours, 3), "markets": n, "capital_all": s["capital"], "mean_ret": mu, "sd_ret": sd, "t": t,
           "total_rewards": s["total_rewards"], "total_equity_bid": s["total_equity"],
           "total_equity_mid": round(sum(m.get("equity_mid", m["equity"]) for m in s["markets"]), 4),
           "fills": sum(len(m["fills"]) for m in s["markets"]), "markout_bid": round(sum(m["markout"] for m in s["markets"]), 4),
           "account": {"markets": len(acct), "capital": cap, "net_usd": round(acct_net, 4), "rewards": round(sum(by[c]["rewards"] for c in acct), 4),
                       "per_day_pct": round(100 * acct_net / cap * 24 / hours, 3) if cap and hours else None},
           "pass": bool(mu > 0 and t > 2.0 and acct_net > 0)}
    return res


if __name__ == "__main__":
    print(json.dumps(evaluate(sys.argv[1]), indent=1))
