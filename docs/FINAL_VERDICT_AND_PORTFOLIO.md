# Final verdict and portfolio

*Paper only. Nothing in this repository signs or sends an order.*

## Verdict

**None of the three kernels passed its pre-registered test, so the 100 USD portfolio has no enabled sleeve and holds cash.**

`quant_agency/winning_portfolio.py` is built and enables a sleeve only when its verdict in `docs/live_runs/final/verdicts.json` says
it passed. Today none did:

```
$ python -m quant_agency.winning_portfolio --status
K3_fast_arb                disabled  -- 46-min live: 0 complete sets in 88 sweeps of 7,268 events, 0 of 920 ladder pairs < 1.00
K1_listing_short           disabled  -- OOS 181 trades, mean -74.6 bps, t=-0.30, account 93.63 (pre-registered t>2.5)
K2_specialist_consensus    disabled  -- failed validation: 31 triggers, mean -23.3%, t=-3.68, account 71.08; not taken to OOS
cash not allocated to an enabled sleeve stays in cash (all of it)
```

`docs/WINNING_STRATEGY_PROOF.md` has not been written.

## Kernel 1: capped new-listing short after exhaustion (`listing_short_capped.py`)

**Corrections to the premise.**
- The F5 OOS loss was not "−3,300 % on one trade". F5's OOS mean was −17.9 % per trade, and the 33× squeeze was the worst single
  trade.
- The isolated-stop version had also been tested before, in Phase 15 Track 2 (stops at 25 % to 200 %). It failed: OOS-A t = 0.49 and
  OOS-B −7.3 %.

The genuinely new element here is the **exhaustion trigger**.

**Rule (declared in the module docstring before any result).**
- **Trigger.** The first day 1–5 after listing whose close is below day 0's typical price *and* whose high is a lower high.
- **Entry.** Short at the next open, BTC-hedged.
- **Stop.** s ∈ {25 %, 35 %}, filled with 2 % slippage (worse on gaps).
- **Take-profit.** tp ∈ {none, 30 %}.
- **Hold.** H ∈ {14, 30} days.
- **Costs.** 20 bps per leg + actual funding.

**Screen (train 2024 → validation 2025-H1).** 5 of the 8 configurations qualified. The best on validation was frozen in
`docs/PREREG_FINAL_K1.json` (commit `3daef71`): s = 35 %, tp = 30 %, H = 14 d, with train t = 2.20 and validation t = 2.32.

**OOS (2025-07 → 2026-09, run once).**

| trades | months (clusters) | mean | median | **t** | win | stopped | worst | 100 USD account |
|---|---|---|---|---|---|---|---|---|
| 181 | 15 | −0.75 % | +7.1 % | **−0.30** | 56 % | 58 | −55 % | **93.63** (low 81.12, max DD 19 %) |

**Exploratory check (not used for the verdict).** All 8 configurations are negative OOS (t from −1.29 to −0.30). The 2024–25
post-listing decay did not continue. A typical trade still wins, but a third of trades hit the stop, and that loses more than the
winners make.

**Disclosure.** This OOS window had already been used by F5 and Track 2.

## Kernel 2: category-specialist consensus with bracket exits (`specialist_consensus.py`)

**Rule (single configuration, no grid).**
- **Categories.** Assigned from question keywords.
- **Specialists.** ≥ 80 % of a wallet's interior trades fall in one category, with ≥ 20 trades over ≥ 10 markets and a positive t.
  The top 10 per category qualify.
- **Entry.** Taken only when ≥ 2 specialists buy the same token at 0.20–0.80 within 24 h.
- **Exit.** Take-profit at +12¢, stop at −12¢, a specialist's sell, or resolution, whichever comes first.
- **Price path.** Exits are evaluated on the market's full public trade tape (data-api `/trades`).

**Validation (rank on P1, score P2).**
- **Specialists found:** sports 10, politics 1, crypto 1.
- **Consensus triggers: 31, all sports.** Most were live e-sports matches.
- **Exits:** 17 stops, 10 take-profits, 4 mirrored sells.
- **Return:** mean **−23.3 %**, **t = −3.68** over 31 markets.
- **100 USD account:** **71.08**.
- **Held to resolution instead:** 10 of 31 won at an average entry ≈ 0.47, which is also a loss.

Validation failed, so by protocol there was no OOS run and nothing was frozen.

## Kernel 3: fast arbitrage (`fast_arb_scanner.py`)

**Correction to the premise.** The Phase 13 figure, "0 failures in 39,390 events", tested the *payoff* rule: exactly one YES pays in a
NegRisk event. It says nothing about how often a profitable set exists.

**Live paper session, 46 min, pre-registered in `docs/PREREG_FINAL_K3.json`.**
- **Complete sets.** 88 full sweeps of 7,268 NegRisk events (5,604 exhaustive), about 89,500 books per sweep: **0 opportunities**.
  So no set was bought, and no early unwind could be measured.
- **Date-ladder monotonicity.** 9 scans of 920 pairs: **0 pairs below 1.00** after fees.

Kernel 3 failed its pass rule. The only arbitrage profit in the repository is still Phase 13's +1.385 USD locked on paper, which
settles between 2 Nov and 11 Dec 2026.

## The whole programme

Across Phases 13–16 and this sprint, about 20 candidate families were tested. Every one used pre-registration with SHA-256 before its
confirmatory test. None shows positive risk-adjusted returns after realistic costs at the 100 USD scale.

Two failure patterns recur:
1. **Selection effects that do not persist.** Validation-period winners, top wallets, and 2024–25 listing behaviour all regress
   out of sample.
2. **Costs and adverse selection.** These are larger than any small edge that does persist: spreads, latency, fees, informed fills.

## Commands

```bash
python -m quant_agency.listing_short_capped --stage screen   # K1 train/validation
python -m quant_agency.listing_short_capped --stage oos      # K1 OOS (frozen: docs/PREREG_FINAL_K1.json)
python -m quant_agency.specialist_consensus --step validate  # K2 P1 -> P2
python -m quant_agency.fast_arb_scanner --duration 2700      # K3 live paper session
python -m quant_agency.winning_portfolio --status            # sleeve gating from docs/live_runs/final/verdicts.json
```

Evidence: `docs/live_runs/final/`.
