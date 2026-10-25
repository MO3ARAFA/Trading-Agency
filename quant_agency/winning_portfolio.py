"""Final sprint: 100 USD multi-sleeve paper engine. A sleeve is enabled only if its pre-registered pass rule was met; everything else
stays in cash. Paper only: no sleeve signs or sends an order.

    python -m quant_agency.winning_portfolio --status            # which sleeves are enabled and why
    python -m quant_agency.winning_portfolio --run 2700          # run the enabled sleeves (paper) for N seconds
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Dict, List

VERDICTS = "docs/live_runs/final/verdicts.json"

SLEEVES = {
    "K3_fast_arb": {"cmd": ["-m", "quant_agency.fast_arb_scanner", "--out", "runs/final/portfolio_k3"], "role": "idle cash: arbitrage locks"},
    "K1_listing_short": {"cmd": None, "role": "risk sleeve: capped post-listing short (needs a perps venue; no paper runner)"},
    "K2_specialist_consensus": {"cmd": None, "role": "risk sleeve: Polymarket consensus copy (paper runner: copy_live)"},
}


def enabled(verdicts: Dict[str, dict]) -> List[str]:
    return [k for k in SLEEVES if verdicts.get(k, {}).get("passed") is True]


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--run", type=float, metavar="SECONDS")
    a = ap.parse_args(argv)
    v = json.load(open(VERDICTS)) if os.path.exists(VERDICTS) else {}
    on = enabled(v)
    for k, s in SLEEVES.items():
        print(f"{k:26s} {'ENABLED ' if k in on else 'disabled'}  {s['role']}  -- {v.get(k, {}).get('why', 'no verdict')}")
    print(f"cash not allocated to an enabled sleeve stays in cash ({'all of it' if not on else 'the rest'})")
    if a.run:
        for k in on:
            if SLEEVES[k]["cmd"]:
                subprocess.run([sys.executable, *SLEEVES[k]["cmd"], "--duration", str(a.run)], check=False)


if __name__ == "__main__":
    main()
