# Phase 16 — copying the top Polymarket wallets

*Paper only. Nothing in this repository signs or sends an order.*

## Verdict

**Fail.** Copying the best-ranked wallets does not reach the pre-registered bar of t > 2.5 after latency and fees.

**`docs/WINNING_STRATEGY_PROOF.md` has not been written.** The live copy session was not run, because the pre-registered rule only
allows it after the historical test passes.

## Design (pre-registered: `docs/PREREG_P16_COPY.json`, committed before evaluation)

- **Universe.** 1,685 wallets: the top 1,000 by traded *volume* on the all-time and month leaderboards. Volume, not profit, so the
  selection does not start from the winners.
- **Selection (before D = 2026-08-26).** Each wallet's BUYs in the 60 days before D, on markets that resolved before D. A wallet needs
  ≥ 30 such buys and ≥ 2,000 USD bought. Wallets are ranked by the market-clustered t of their return and the top K = 25 are kept.
  1,009 wallets qualified.
- **Copy (D → now − 1 day).** Every BUY by the 25 selected wallets on a market that has since resolved. The copy pays the wallet's price
  plus max(1¢, 2 %), plus the market's taker fee, and holds to resolution.
- **Pass rule.** Mean > 0 with clustered t > 2.5, *and* a 100 USD account copying each trade with 2 USD ends above 100. If both hold,
  a live paper copy session runs next.

## Result

| | copies | markets | mean return per USD | t (clustered by market) | win rate |
|---|---|---|---|---|---|
| pre-registered evaluation, as first run | 49,634 | 10,857 | +2.8 % | 1.95 | 93 % |
| **after the price-cap bug fix (the result that counts)** | **7,841** | **1,517** | **+12.8 %** | **1.48** | **57 %** |

**Bug found and fixed before any conclusion.** The first run capped the copy price at 0.99. That cap made 29,460 copies of buys made
at 0.999 look as if they were bought at 0.99, i.e. cheaper than the wallet itself paid. Those trades are fake edge. The fix: the copy
price is never below the wallet's price, and a trade is skipped when nothing is left to buy below 1.00. The fix can only *lower* the
result. It is tested in `tests/test_phase16.py`.

**The +61 USD account figure is not evidence.** The account model does not recycle cash, so the 100 USD covered only the first 50 of
7,841 copies. 32 of those 50 came from a single wallet (`0x37e4728b`). That wallet's full copy-window record is t = 0.16.

### By the wallet's entry price (exploratory, not confirmatory)

| price | copies | markets | mean | t |
|---|---|---|---|---|
| < 0.20 | 877 | 202 | +47 % | 0.95 |
| 0.20–0.50 | 2,546 | 649 | −8.8 % | −0.92 |
| 0.50–0.80 | 3,771 | 569 | +20.8 % | 2.35 |
| 0.80–0.99 | 647 | 244 | +4.6 % | 1.88 |

One bucket out of four reaches t = 2.35. That is a look after the fact, below 2.5, and expected by chance among four cuts. It is not a
strategy.

## What it says

- **Most top "winners" are not forecasters.** Much of the leaderboard's high-t activity is resolution sniping: buying at 0.99–0.999
  minutes before a market (often a 5-minute crypto "Up or Down" market) settles. The median hold for these buys is ≈ 0.5 h. A copier
  arrives seconds late and buys at a worse price, which leaves no edge.
- **The selection rule is fragile.** Wallets that almost never lose have near-zero variance, so their t-stat explodes (10⁸–10¹⁶) and
  they crowd the top 25. This is a flaw in the pre-registered design. It is disclosed, not fixed after seeing the result.
- **What remains is noisy.** The genuinely directional copies (prices 0.05–0.95) average a positive return, but with a few thousand
  trades over 2 months the evidence is t ≈ 1.5. That is not distinguishable from luck.
- **A screenshot claiming +4,893 USD from a copy bot is the survivor of many such bots.** This test was built to avoid exactly that
  survivorship. It does not show a reliable copy edge.

## Reproduce

```bash
python -m quant_agency.copy_study --step fetch      # ~1 h: leaderboards, 1,685 wallets' activity, 210,634 markets (cached in runs/p16)
python -m quant_agency.copy_study --step evaluate   # result above; summary in docs/live_runs/phase16/copy_eval_summary.json
python -m quant_agency.copy_live --wallets runs/p16/selected.json --duration 3600   # live paper copier (not run: the test failed)
```
