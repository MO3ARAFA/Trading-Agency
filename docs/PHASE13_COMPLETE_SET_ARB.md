# Phase 13 — complete-set arbitrage on Polymarket NegRisk events

*Paper only. No order was sent, no credential exists in this repository. Why Phases 1–12 never made money, and the plan:
`docs/AUDIT_AND_PLAN.md`.*

## 1. Verdict

**Not yet shown to be profitable.**
- The evidence supports a small, forecast-free edge, and the tests below found nothing that contradicts it.
- In one hour the engine scanned 7,546 live Polymarket NegRisk events every 24 s. It bought 5 complete sets on paper, filling the
  100 USD account.
- Those sets lock **+1.385 USD** at resolution: 1.39 % of the capital, capital-weighted ≈ **17 % a year**. Every fill was still
  fillable 3 s later.
- That is locked, not realised. Nothing has settled; the first event resolves in about 9 days and the last in about 48.

Three tests stand behind it:

| question | test | result |
|---|---|---|
| Does a complete set pay what it should? | 48,443 closed NegRisk events, paid at the venue's resolved prices (§2) | plain events: **0 losses in 39,390** once two tie-prone families are excluded (12 losses in 47,180 before); augmented events fail 5 %, so they are never used |
| Are the fees what the schedule says? | fill events decoded from Polygon receipts of public trades (§1b) | all **27 legs of the 5 filled events** were charged 0 on-chain, as their `zero_fees` schedule says (one 0.00005 USD rounding); 59 of 61 markets overall matched |
| Can it be executed? | 0.5 s re-read before filling, 3 s re-read after, own takes subtracted from later books (§3) | **5 of 5** fills could still be bought at the same size and profit 3 s later; 2 of 7 opportunity events vanished within 0.5 s |

What this is in money:
- 100 USD earns about 1.4 USD per 10–50-day cycle. If the yield holds that is roughly **15–20 USD a year**, and only if the account is
  re-deployed as soon as each event resolves.
- **Capital is the bottleneck, not opportunities.** 57 opportunities were refused only because their event (25 USD) or the account
  (100 USD) was full.
- The "first dollar" is already locked on paper. It is paid on resolution, provided §4 settles with no shortfall.

What it is not:
- It is not proof. That needs settled positions, sessions on more days, and a real executor. The release gate is §6, and none of it is
  met yet.
- **No real money should be used until then**, and never without the owner's explicit approval.
- Under the stressed fee (0.05 on every fee-enabled leg) the same fills lose money (§3). The edge exists only because these markets
  charge no taker fee, which the chain confirms today. If Polymarket switches these markets to category fees, the strategy stops
  working. The engine's `--fee-stress` reading shows that at once.

## 1b. Fees: the schedule checked against the chain

Gamma marks many fee-enabled markets `feeType: zero_fees` (rate 0) while the public docs list category taker rates of 0.03–0.07. `fee_audit.py` settles it: it reads recent public taker trades, fetches each transaction receipt from a public Polygon RPC, decodes the exchange's fill events and computes the rate actually charged, fee / (shares × p(1 − p)). The decoder reproduces the documented crypto rate (0.07) exactly.

| schedule (Gamma) | rate | markets | with decoded trades | charged = schedule | fills read | highest rate charged |
|---|---|---|---|---|---|---|
| `fees disabled` | 0.00 | 6 | 6 | 6 | 25 | 0.0000 |
| `zero_fees` | 0.00 | 45 | 45 | 44 | 237 | 0.0050 |
| `sports_fees_v2` | 0.03 | 2 | 2 | 2 | 12 | 0.0300 |
| `sports_fees_v3` | 0.05 | 6 | 6 | 5 | 39 | 0.1284 |
| `crypto_fees_v2` | 0.07 | 6 | 2 | 2 | 5 | 0.0700 |

**59 of 61 markets were charged their schedule's rate** (within 0.002). The 262 fills read in zero-rate markets (`zero_fees` or fees disabled) paid 0.00005 USD in total, at most 0.00005 USD on one fill: rounding (fees are rounded to 5 decimals), not a fee. The other exception is a sports market (schedule 0.05) where one 5-share fill paid 0.128 while its other fills paid 0.05. It is unexplained, and it is not a zero-fee market. The engine prices every leg with its own schedule. §3 also re-prices each fill at 0.05 as a stress case.

## 2. Backtest of the payoff: what did one set actually pay?

48,443 closed NegRisk events whose end date falls between 2026-08-04 and 2026-10-22 (Gamma, one-day windows; days with more than 2,100 closed events are a sample, not a census; ≈ 85 % are sports). Each set is paid at the venue's resolved prices, so 50-50 and several-YES resolutions count as the venue paid them.

| events | n | exactly one named YES | none | unclean (50-50 etc.) | YES set paid < 1 | mean YES-set loss per set | NO set paid < n−1 | mean NO-set loss per set |
|---|---|---|---|---|---|---|---|---|
| plain (not augmented) | 47,180 | 47,164 | 12 | 6 | 12 (0.025 %) | 0.0254 ¢ | 4 | 0.0032 ¢ |
| augmented (placeholders / Other) | 1,225 | 1,164 | 61 | 36 | 61 (4.980 %) | 4.9796 ¢ | 0 | 0.0000 ¢ |

**Plain events.** A YES set paid less than 1 in 12 of 47,180 events. Every one of them was an NFL *highest scoring quarter* market (a tie leaves no winner) or an ATP *exact score* market (a retirement leaves no score). Those two families are excluded from YES sets (`CsaConfig.yes_set_exclude`). After the exclusion: **0 losses in 39,390 events**. The exclusion was chosen on this same data, so only future events test it out of sample.

**Augmented events.** A YES set paid nothing in 61 of 1,225 (5.0 %): the winner was an unlisted outcome. The engine never builds a YES set on them. A NO set never paid less than n − 1 there.

**What this does not cover.** It cannot cover a dispute that resolves against the rules, a market voided after entry, or a fee charged differently from the schedule. Settlement of the paper positions themselves (§4) is the direct test.

## 3. Live paper sessions (100 USD account)

Rules: ≤ 25 USD per event, ≤ 100 USD deployed, ≤ 8 events, ≤ 60 days to the end date + 2 days for resolution, the marginal set nets ≥ 0.5 ¢, the whole fill nets ≥ 0.4 % and ≥ 10 % a year. Execution: see it, wait 0.5 s, re-read every leg's book, buy only what is still profitable at the fresh asks (depth-walked, fees per level), subtract what was bought from every later book, re-read 3 s later.

| session | duration | NegRisk events | exhaustive | tokens with asks | sweeps | sweep time | opportunities (sweep × event) | distinct events | fills | vanished at re-read |
|---|---|---|---|---|---|---|---|---|---|---|
| paper_20261024_210420 | 60 min | 7546 | 5818 | 96,400 | 117 | 24 s | 64 | 7 | 5 | 2 |

### 3.1 Paper fills

*net (stressed)* re-prices the same fill as if every fee-enabled leg paid a 0.05 taker rate (the docs' category rate) instead of the per-market schedule the venue reports (often `zero_fees`). *Legging*: could the same number of sets still be bought at a profit from the raw book 3 s later?

| # | event | kind | legs | sets | capital | locked net | net / capital | days | annualised | net (stressed) | annualised (stressed) | legging: still fillable 3 s later |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Swiss National Bank decision in December? | yes_set | 5 | 25.5 | 25.00 | +0.527 | 2.11 % | 48 | 16.0 % | +0.169 | 5.1 % | yes |
| 2 | GOP's worst Great Plains Senate Race (IA, NE, KS)? | yes_set | 3 | 25.2 | 25.00 | +0.227 | 0.91 % | 12 | 27.4 % | -0.589 | -71.0 % | yes |
| 3 | Reserve Bank of Australia Decision in December | yes_set | 5 | 25.4 | 25.00 | +0.363 | 1.45 % | 47 | 11.2 % | -0.367 | -11.4 % | yes |
| 4 | Alphabet’s Market Cap end of October 2026? | yes_set | 7 | 5.1 | 5.04 | +0.025 | 0.50 % | 9 | 20.2 % | -0.111 | -88.3 % | yes |
| 5 | How many House seats will the Democrats win in Ohio? | yes_set | 7 | 20.2 | 19.96 | +0.242 | 1.21 % | 12 | 36.1 % | -0.497 | -74.0 % | yes |

**Total:** 100.00 USD deployed, **+1.385 USD locked** (schedule fees) / -1.395 USD (stressed fees), capital-weighted 17.0 % / -17.1 % a year. Locked means: paid if every leg resolves as the backtest says; nothing is realised until resolution.

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
