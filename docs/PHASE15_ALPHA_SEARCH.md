# Phase 15 — autonomous alpha search: every candidate, every result

*Paper only. Nothing in this repository signs or sends an order.*

## Verdict

**No candidate met the bar.** The bar was out-of-sample (or live, pre-registered) t > 2 to 2.5 after real costs, plus positive P&L on the
100 USD account. 14 candidate families were tested across Hyperliquid, Binance (data.binance.vision archive, 2023-2026), pump.fun
and Polymarket.

**`docs/WINNING_STRATEGY_PROOF.md` has not been written, on purpose.** Writing it would require a result that does not exist.

Every confirmatory test was pre-registered with SHA-256 and committed before its out-of-sample data or live session was seen:
`docs/PREREG_P15*.json`. No threshold was relaxed after a result was seen. The one amendment (candidate A) was made and disclosed
*before* its OOS run.

## Results

| # | candidate | data | discovery (train / validation) | confirmatory test | result |
|---|---|---|---|---|---|
| 1 | 5m blow-off fade (short spikes, long crashes), HL perps | 17 d × 91 coins | best of 504 configurations; train t ≈ 1.2–1.4, validation t = 2.4 | OOS-1 HL 4.4 d: +36 bps, t = 0.76; **OOS-2 Binance Jan–Sep 2026, 3,094 trades: −15.8 bps, t = −1.95** | fail: gross ≈ +2 bps against 14+ bps cost |
| 2 | 5m/15m blow-off follow, cross-sectional reversal, cross-sectional momentum | same | net t from −8 to +0.5 | — | fail at screen |
| 3 | new-listing short, BTC-hedged, 30 d (F5) | 883 Binance perps, daily | train t = 2.12, validation t = 3.04 | **OOS 2025-07..2026-09, 217 trades: −17.9 %/trade, t = −1.12** (median +15 %, a 33× squeeze) | fail |
| 4 | daily trend, weekly cross-sectional rank, funding carry (F6–F8) | same | best t ≈ 1.6; carry t = −2.9 | — | fail at screen |
| 5 | hourly funding-settlement drift, 1 h liquidation reversal (F9, F12) | 80 perps × 1 h, 2023–26 | validation t from −3.8 to +1.2 | — | fail at screen |
| 6 | pump.fun near-graduation squeeze, capitulation bounce | 4 live tapes (1.75 h) | gross −2 % to −46 % at every horizon | — | fail at screen |
| 7 | short-dated (≤ 5 d) Polymarket complete sets | live, 7,507 events | 0 opportunities in 68 sweeps | — | fail |
| 8 | listing short with an isolated stop (Track 2), stop chosen on 2024–25H1 | daily | positive in both selection halves | **OOS-A 2023 (never touched before): +4.7 %/trade, t = 0.49**, account 102.76; OOS-B −7.3 %, account 88.58 | fail |
| 9 | passive maker fade of cross-sectional over-extension (Track 3), trade-through fills | 80 perps × 1 h | gross ≈ 0; net −6 to −16 bps, t = −3 to −7 over 10⁴–10⁵ fills | — | fail at screen |
| 10 | Polymarket date-bracket monotonicity arbitrage (Track 4) | live, 156 ladders | 0 of 920 pairs below 1.00 | — | fail |
| 11 | R: liquidity rewards from complete sets, asks, hold after a fill | live 2.42 h (cut by a container restart) | — | rewards +6.70, 18 fills −2.45, t = 0.48, account −3.07 | fail |
| 12 | R2: R plus taker buy-back on every fill | live, 4 h pre-registered | — | at 2.17 h: rewards +17.36, 32 fills, net −0.91, **t = 0.14** (final below) | fail |
| 13 | R3: passive YES+NO bids ≤ 0.98, OBI/sweep toxicity gate, zero-fee merge, zero-fee calm markets | live 45 min, 40 markets | — | rewards +3.47, 640 pulls, 4 fills −6.10, **t = −0.57**, account +0.83 | fail |
| 14 | R4: R3 with bids deep in the reward band | live 45 min, 40 markets | — | rewards +1.80, 764 pulls, 3 fills, **t = −0.69**, account +0.62 | fail |

## What the failures say

- **Liquid crypto perps (1–5, 8, 9).** At retail costs (≥ 10–14 bps per round trip), no simple time-series, cross-sectional,
  funding, listing or liquidation pattern survives. This holds over 9 months to 3 years of data and thousands of trades. Passive
  entry does not rescue it: in the trade-through fill model, the fade fills only when the move continues.
- **Meme curves (6).** Every sub-regime is negative *before* the 2.9 % round trip.
- **Polymarket structure (7, 10).** Tight. Date ladders are monotone, and short-dated sets are not underpriced.
- **Polymarket liquidity rewards (11–14).** The rewards are real income under the published formula, about 0.1 % of capital per hour.
  But the fills are informed: one adverse fill on a 20-share quote costs ≈ 1–3 USD, the same as hours of rewards. Every variant
  failed for that reason:
  - holding the inventory (R),
  - buying back as a taker (R2: the spread is paid on every fill),
  - pulling quotes on order-book imbalance and sweeps (R3: 640 pulls still left 4 fills worth −6.10),
  - quoting deeper (R4).
  The 100 USD account was positive in R3 and R4 (+0.83, +0.62) only because none of its three markets was filled during the
  45 minutes. That is luck of the draw, not evidence, and the pre-registered cross-market t is negative.

## The only positive-expectancy result in the repository

Phase 13's complete-set arbitrage is still open:
- 5 paper positions locked +1.385 USD on 100 USD.
- The payoff backtest found 0 failures in 39,390 plain NegRisk events.
- On-chain checks confirmed zero fees on every leg.

It is not a "live profit" yet: it is realised only when the events settle (2 Nov – 11 Dec 2026). The command
`python -m quant_agency.complete_set_arb --settle docs/live_runs/phase13/session1` will show the realised result. It is also small,
≈ 15–20 USD a year on 100 USD.

## Reproduce

```bash
python -m quant_agency.alpha_tournament --stage screen          # candidates 1-2 (HL 5m/15m)
python -m quant_agency.alpha_daily --stage screen               # 3-4 (needs runs/p15/bn_daily.npz: see the fetch notes in alpha_daily)
python -m quant_agency.alpha_hourly --stage screen              # 5
python -m quant_agency.pump_regimes runs/omega/*/tape.jsonl.gz  # 6
python -m quant_agency.alpha_listing --stage select && python -m quant_agency.alpha_listing --stage oos   # 8
python -m quant_agency.alpha_maker --stage screen               # 9
python -m quant_agency.bracket_arb                              # 10
python -m quant_agency.reward_farm --duration 14400 --k 30 [--hedge]       # 11, 12
python -m quant_agency.reward_mm --duration 2700 --k 40 [--depth-frac 0.6]  # 13, 14
```

Evidence: `docs/live_runs/phase15/`. Pre-registrations: `docs/PREREG_P15.json`, `P15B`, `P15T2`, `P15R`, `P15R2`, `P15R3`, `P15R4`.
