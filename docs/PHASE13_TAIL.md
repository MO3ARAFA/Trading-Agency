## 4. Settlement of the paper positions

No paper position has resolved yet. The first ones end 10–50 days after entry. Until then the P&L above is **locked, not realised**.
Mark it with `python -m quant_agency.complete_set_arb --settle <run dir>`, which writes `csa_settlement.json`, and repeat until every
position is settled. A position that pays less than its expected payout is listed under `shortfalls`. One shortfall is enough to stop
any move toward real money until it is explained.

How long the capital stays locked after the end date, measured on the 48,443 closed events of §2 (Gamma `closedTime` − `endDate`):

| | events | median | 90th pct | 99th pct | max | share later than the 2-day buffer |
|---|---|---|---|---|---|---|
| sports | 40,936 | 0.17 d | 0.38 d | 24.2 d | 58.1 d | 3.8 % |
| other | 7,507 | 0.44 d | 1.11 d | 26.8 d | 46.9 d | 4.8 % |

About 1 event in 20 takes longer than the 2-day buffer the engine assumes. In the worst observed case that adds two months of
lock-up. That costs annualised yield, not principal.

## 5. Risks this does not remove

| risk | what is known | mitigation in the code |
|---|---|---|
| A listed outcome set is not exhaustive (tie, retirement, "none") | 12 of 47,180 plain events, all in two families | those families excluded; augmented events never get a YES set |
| Dispute / wrong resolution (UMA) | not measurable from Gamma prices; it would show as a shortfall at settlement | ≤ 25 USD per event, ≤ 8 events |
| Legging: the asks move while legs are bought one by one | measured by the 3 s re-read (§3.1) | a real executor must buy the thinnest leg first with fill-or-kill orders and sell back the filled legs if a later leg fails |
| Fees differ from the schedule | 35 of 36 audited markets matched exactly (§1b) | per-leg schedule; `--fee-stress` and the stressed column |
| Capital locked longer than planned | §4: ~5 % of events take > 2 days | the ≥ 10 %-a-year filter leaves room; ≤ 60 days of planned lock-up |
| Platform / smart-contract / USDC risk | not quantifiable here | a dedicated wallet holding only the capped capital |
| Competition | the edge is small because bots already take most of it | the engine takes only what is left at 0.5 s; it does not race |

## 6. Release gate for real money (not met)

All of these must hold, and the owner must approve in writing, before any real order:

1. **Settlement.** Every position of at least one full paper session has settled with zero shortfalls (§4).
2. **More evidence.** Paper sessions on at least 5 different days show a capital-weighted locked yield above the risk-free rate
   (≈ 4 % a year) after schedule fees.
3. **Fees.** A fee audit of the exact markets to be traded matches their schedule.
4. **Execution.** A leg-by-leg fill-or-kill executor exists, with a sell-back on a failed leg. Its paper version reproduces the 3 s
   re-read survival rate. Its first live use is one set of ≥ 5 shares.
5. **Operations.** Everything in `OPERATOR_GUIDE.md` §6: dedicated wallet, keys outside the repo, an external kill switch, alerts.

## 7. Reproduce

```bash
pip install -r requirements.txt && python -m pytest tests -q
python -m quant_agency.complete_set_arb --duration 3600 --bankroll 100 --max-per-event 25 --out runs/p13
python -m quant_agency.fee_audit --events 1075157 --trades 2 --markets 2 --out runs/p13/fee_audit.json
python -m quant_agency.complete_set_arb --fetch-closed 80 --out runs/p13      # ≈ 200 MB, about 30 min
python -m quant_agency.complete_set_arb --backtest runs/p13/closed_negrisk_compact.json --out runs/p13
python -m quant_agency.phase13_report --runs runs/p13/paper_* --head docs/PHASE13_HEAD.md --tail docs/PHASE13_TAIL.md
```

The closed-event file (≈ 200 MB) is not committed. It came from Gamma `/events?closed=true` in one-day `end_date_min/max` windows (≤ 2,100
events per window), keeping `negRisk` events. The backtest's output and the fee audit are committed under `docs/live_runs/phase13/`.
