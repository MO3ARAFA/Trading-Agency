# Phase 16B — copying interior-odds "sharp" wallets with a cash-recycling portfolio

*Paper only. Nothing in this repository signs or sends an order.*

## Verdict

**Fail, at every stage.**
- **Validation.** Negative for every K.
- **Pre-registered out-of-sample test (P3).** t = 0.42.
- **The 100 USD account.** Ends at 43.97 USD.
- **Persistence.** The ranking does not persist: a wallet's interior-odds skill in one period does not predict the next (Spearman ρ = 0.016, p = 0.89).

`docs/WINNING_STRATEGY_PROOF.md` has not been written.

## What changed from Phase 16

Phase 16 was criticised for three flaws, and all three were fixed.

1. **Interior odds only.** Copies are limited to entries in the band 0.15 ≤ p ≤ 0.85. Short-dated crypto "Up or Down" markets are
   excluded. This drops the 0.99–0.999 resolution sniping.
2. **Ranking on skill, not volume.** A wallet needs ≥ 20 closed interior copies across ≥ 10 markets. Market makers are excluded: a
   wallet that buys both tokens of a market within 1 h in ≥ 10 % of its markets is dropped. So is any wallet with a median entry above
   0.85. Wallets are ranked by the market-clustered t of the *copy* return, using exits known before the ranking cut-off only.
3. **A realistic portfolio.** The copy exits when the wallet first sells (at its price − max(1¢, 2 %), minus the fee); otherwise it holds
   to resolution. Cash recycles at every exit. The stake is 4 USD (at least 5 shares), with one position per market and ≤ 15 USD open
   per wallet. Positions still open at the end are marked at cost.

Entry costs are unchanged: the wallet's price + max(1¢, 2 %), plus the market's taker fee.

## Periods

| period | dates | use |
|---|---|---|
| P1 | 2026-06-27 → 08-11 | rank |
| P2 | 08-11 → 08-26 | validate (ranking on P1) |
| P3 | 08-26 → 10-24 | out-of-sample, run **once** after the freeze (ranking on P1+P2) |
| P4 | after the freeze → | forward, the only fully clean period (`--step forward`) |

The pre-registration `docs/PREREG_P16B_SHARP.json` (SHA-256 `d3e5048d…`) was committed in `5f656a5` before P3 was run. It records
the code's SHA-256 and the validation results that were already seen.

## Results

### Validation (rank on P1, score P2)

93 wallets passed the filters.

| K | copies closed | markets | mean / USD | t | 100 USD account |
|---|---|---|---|---|---|
| 10 | 5,979 | 871 | −11.7 % | −1.60 | 40.31 |
| 25 | 19,013 | 1,804 | −5.6 % | −1.23 | 58.98 |
| 50 | 34,224 | 3,420 | −4.2 % | −1.24 | 86.98 |

**Persistence across the 80 wallets with P2 data.**
- The P1 t-stat versus the P2 mean has Spearman ρ = 0.016 (p = 0.89).
- The top P1 quintile has the *worst* P2 mean (−18 %).

**Baseline: every interior copy by every wallet in P2.**
- Copied (with copy costs): −4.6 %, t = −4.9.
- At the wallets' own prices, held to resolution: −2.5 %, t = −2.1.

The large wallets as a group lose money in the interior band. There is no persistent skill to select.

### Out-of-sample P3 (pre-registered, K = 25, run once)

| copies | closed | markets | mean / USD | **t** | win rate | exits |
|---|---|---|---|---|---|---|
| 32,208 | 29,386 | **2,730** | +3.3 % | **0.42** | 45 % | 25,231 resolution, 4,955 mirrored, 2,022 open |

**The 100 USD account.**
- It took 554 copies. Skips: 26,057 for cash, 4,113 for the same market, 1,484 for the wallet cap.
- It ends at **43.97 USD**: 3.68 cash plus 40.28 in 10 unresolved positions marked at cost.

Equity curve, from `docs/live_runs/phase16b/oos.json`:

| date | equity | date | equity |
|---|---|---|---|
| 08-26 | 100.00 | 09-19 | 99.86 |
| 08-30 | 121.26 | 09-22 | 111.85 |
| 09-02 | 140.38 | 09-25 | 68.75 |
| 09-05 | 137.52 | 10-06 | 51.99 |
| 09-10 | 111.18 | 10-23 | 43.97 |

The peak was 152.75 in the first week, then a −71 % fall from the peak. A screenshot taken in week one would show +50 %.

**Pass rule** (t > 2.5 and account > 100): **not met.** P4 was meant to confirm a P3 pass, so it is moot. It can still be run for the
record.

## Why

- **High-t selection wallets are lucky concentrations.** The top P1 ranks are wallets with thousands of buys in 11–26 markets (mean +59 %
  to +132 %). They had a few winning events, and the market-clustered t over so few clusters is noisy. Their luck does not repeat.
- **Copy costs exceed whatever edge exists.** Entry at +2 % and exit at −2 %, plus fees, against an interior band that is already
  negative at the wallets' own prices.
- **Mirroring exits frees cash but does not create edge.** Most copies still close at resolution (86 %).

## Limits (disclosed)

- **P3 is not fully clean.** It had already been viewed by price bucket in Phase 16, and this design was motivated by that view.
  The bias favours a pass, and the result still fails.
- **Activity is capped** at 3,000 trades per wallet per cached window, newest first.
- **Market is used as a proxy for event.** No take-profit-on-repricing rule was tested, because there is no cached price history,
  and adding one after seeing P2 would be fitting.

## Reproduce

```bash
python -m quant_agency.copy_sharp --step validate   # P1 -> P2
python -m quant_agency.copy_sharp --step oos        # P3, frozen rule (docs/PREREG_P16B_SHARP.json)
python -m quant_agency.copy_sharp --step forward    # P4, trades after the freeze (fetches live data)
```
