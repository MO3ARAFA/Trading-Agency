# Phase 12 — slow-horizon structural strategies for a 100 USD account

> **How to read this report.** Two Polymarket sessions were recorded. **Run A** (1.0 h) used a slow-market filter that let ended / in-play
> tennis matches with generic end dates into the "slow" universe, so its **passive-quoting results are contaminated** and are kept only
> for the record; its structural scan (complete-set prices) does not depend on that filter and is valid. **Run B** (0.51 h, after the fix)
> was cut short by a container restart; its tape was replayed through the same engine afterwards, with group legs rebuilt from Gamma
> (32 of its 40 groups could be rebuilt). Track 2 uses historical Hyperliquid data with a train/test split chosen before the test data
> was looked at. Phase 13 (`docs/PHASE13_COMPLETE_SET_ARB.md`) builds on the one structural result here.

## 1. The 100 USD account in numbers

Hyperliquid minimum order ≈ 10 USD; positions of 20 USD, ≤ 4 at once, ≤ 2× leverage, stop at −10 %. Polymarket minimum order 5 shares (≈ 0.5–4.5 USD). Fees are public base-tier assumptions: Hyperliquid maker 1.5 / taker 4.5 bps, Binance spot 7.5 bps, Polymarket maker 0 and taker per the market's fee schedule. **One basis point of 20 USD is 0.0020 USD**: a 30 bps edge is 0.06 USD per trade; the per-trade noise of an unhedged perp position (≈ 90 bps s.d. over 15–30 minutes) is ≈ 0.18 USD. This repository contains no code that sends an order and reads no credentials; everything here is measurement or paper simulation.

## 2. Track 1 — Polymarket slow event markets

### Run A — slow filter admitted in-play matches (maker results contaminated)

**Live capture:** 1.00 h, 2,863,694 CLOB messages, 4 reconnects. Universe from 2,100 Gamma events / 41,099 markets (34,632 live): **385 slow markets** pass the filter (> 24 h to expiry, 24 h volume ≥ 500 USD, cached spread 3–8 ¢, mid 5–95 ¢); the 80 most active are quoted; 8 BTC up/down markets are the control; 885 NegRisk groups exist, 40 are scanned live.

#### 2.1 Structural scan (live CLOB books, net of the fee schedule, ≥ 5 shares on the thinnest leg)

92,178 group evaluations (95,864 skipped while a leg had no book). Binary YES/NO mirror check: 646,798 comparisons, min ask(YES)+ask(NO) = 1.001, max bid(YES)+bid(NO) = 0.999, **0 crossed** — the two books are mirrors, there is no binary free lunch.

Locked-margin opportunities seen (a *set* is one share of every leg; margin is per set after fees; capital is what is tied up until the event resolves):

| group | kind | legs | exhaustive-like | peak net / set | peak gross | thinnest leg (shares) | lasted | days to resolution | net on capital | annualised |
|---|---|---|---|---|---|---|---|---|---|---|
| Who wins the Senate pending Hormuz Agreement b | buy_set | 3 | yes | 0.0215 USD | 0.0310 | 9 | 0 s | 14.6 | 2% | 55% |
| Who wins the Senate pending Hormuz Agreement b | buy_set | 3 | yes | 0.0204 USD | 0.0300 | 64 | 0 s | 14.6 | 2% | 53% |
| Who wins the Senate pending Hormuz Agreement b | buy_set | 3 | yes | 0.0156 USD | 0.0250 | 28 | 0 s | 14.6 | 2% | 40% |
| Who wins the Senate pending oil below $85 befo | buy_set | 4 | yes | 0.0146 USD | 0.0350 | 171 | 1623 s | 14.6 | 2% | 38% |
| Who wins the Senate pending oil below $85 befo | buy_set | 4 | yes | 0.0115 USD | 0.0330 | 1156 | 288 s | 14.6 | 1% | 30% |
| Who wins the Senate pending Hormuz Agreement b | buy_set | 3 | yes | 0.0048 USD | 0.0130 | 8 | 416 s | 14.6 | 0% | 12% |
| Who wins the Senate pending oil below $85 befo | buy_set | 4 | yes | 0.0044 USD | 0.0260 | 107 | 9 s | 14.6 | 0% | 11% |
| Who wins the Senate pending oil below $85 befo | buy_set | 4 | yes | 0.0005 USD | 0.0220 | 10 | 1 s | 14.6 | 0% | 1% |
| Who wins the Senate pending Hormuz Agreement b | buy_set | 3 | yes | 0.0002 USD | 0.0090 | 7 | 2 s | 14.6 | 0% | 1% |
| Who wins the Senate pending Hormuz Agreement b | buy_set | 3 | yes | 0.0002 USD | 0.0090 | 7 | 1 s | 14.6 | 0% | 1% |

The largest dollar opportunity of the hour: 0.0115 USD per set × 1156 shares on the thinnest leg ≈ **13.28 USD**. With a 100 USD account the binding limits are depth (the thinnest leg) and capital locked until resolution, not the margin.

Best net margin seen per group and kind (including ones that never reached 5 shares):

| group | kind | legs | exhaustive-like | best net / set | best gross | shares at that moment |
|---|---|---|---|---|---|---|
| Who wins the Senate pending Hormuz Agreement b | buy | 3 | yes | +0.0215 | +0.0310 | 9.3 |
| Who wins the Senate pending oil below $85 befo | buy | 4 | yes | +0.0146 | +0.0350 | 171.2 |
| Fed Decision in January? | buy | 5 | yes | -0.0004 | +0.0250 | 0.8 |
| How many Fed rate cuts in 2026? | buy | 13 | yes | -0.0008 | +0.0020 | 15.0 |
| How many House seats will the Democrats win in | sell | 7 | yes | -0.0017 | +0.0090 | 1.3 |
| # of views of Grand Theft Auto VI Launch Trail | buy | 7 | yes | -0.0057 | +0.0170 | 8.5 |
| ECB Interest Rates: October 2026 | buy | 5 | yes | -0.0091 | -0.0060 | 97.0 |
| Who wins the Senate pending Hormuz Agreement b | sell | 3 | yes | -0.0093 | +0.0020 | 5.8 |

#### 2.2 Passive quoting (virtual post-only orders, 5 shares = the Polymarket minimum, TTL 300 s)

*trades* is the primary fill model (real trade prints consume the queue ahead of us); *strict* is a lower bound; *depletion* counts any displayed-size drop as a trade and is an **upper bound shown for completeness**. Markout = (later mid − fill price) × side, in cents per share; dollars are at 5 shares. The ± after a per-fill markout treats every fill as independent and is **too small** (one print can fill several orders, a moving market fills them all); the *market mean* column averages within a market first and takes the s.e. across markets — that is the honest one.

| universe | policy | model | attempts | fills | markets with fills | top market's share of fills | fill rate | spread capture (¢) | markout 300 s, per fill (¢) | markout 300 s, **market mean** (¢) | USD per fill (300 s) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| slow | join | strict | 1569 | 84 | – | – | 5% | 1.11 | -3.57 ± 1.67 | – | -0.179 |
| slow | join | trades | 1572 | 90 | – | – | 6% | 1.08 | -1.54 ± 1.63 | – | -0.077 |
| slow | join | depletion | 2277 | 1081 | – | – | 47% | 2.05 | +1.88 ± 0.22 | – | +0.094 |
| slow | penny | strict | 1404 | 93 | – | – | 7% | 0.92 | -3.13 ± 1.47 | – | -0.157 |
| slow | penny | trades | 1410 | 106 | – | – | 8% | 0.92 | -2.42 ± 1.35 | – | -0.121 |
| slow | penny | depletion | 5040 | 4570 | – | – | 91% | 1.44 | +1.44 ± 0.06 | – | +0.072 |
| control | join | strict | 252 | 101 | – | – | 40% | 0.50 | -1.82 ± 3.39 | – | -0.091 |
| control | join | trades | 253 | 102 | – | – | 40% | 0.50 | -1.53 ± 3.38 | – | -0.076 |
| control | join | depletion | 346 | 201 | – | – | 58% | 0.51 | -2.69 ± 2.43 | – | -0.135 |
| control | penny | strict | 25 | 21 | – | – | 84% | 0.64 | -11.55 ± 8.80 | – | -0.577 |
| control | penny | trades | 27 | 23 | – | – | 85% | 0.61 | -10.52 ± 8.05 | – | -0.526 |
| control | penny | depletion | 33 | 29 | – | – | 88% | 0.53 | -8.29 ± 6.41 | – | -0.415 |

Trade-print arrival (per-minute counts, Fano factor: 1 = Poisson, ≫ 1 = bursty sweeps):

| universe | markets with ≥ 5 prints | median trades / min | Fano median | Fano p90 |
|---|---|---|---|---|
| slow | 2 | 1.89 | 5.09 | 5.91 |
| control | 8 | 12.82 | 158.21 | 247.52 |

#### 2.3 Maker lock across a whole exhaustive group (join-bids on every leg; legging risk)

74 sets attempted, **0 completed** (0 %). Complete sets locked nothing; incomplete sets left 10 filled legs marked at mid for a mean P&L of -0.001 USD each (no resolution, no spread).

### Run B — after the in-play fix, tape replay

**Live capture:** 0.51 h, 1,026,860 CLOB messages, 0 reconnects. Universe from 2,100 Gamma events / 51,290 markets (45,110 live): **437 slow markets** pass the filter (> 24 h to expiry, 24 h volume ≥ 500 USD, cached spread 3–8 ¢, mid 5–95 ¢); the 80 most active are quoted; 8 BTC up/down markets are the control; 884 NegRisk groups exist, 32 are scanned live.

#### 2.1 Structural scan (live CLOB books, net of the fee schedule, ≥ 5 shares on the thinnest leg)

12,315 group evaluations (17,366 skipped while a leg had no book). Binary YES/NO mirror check: 158,221 comparisons, min ask(YES)+ask(NO) = 1.008, max bid(YES)+bid(NO) = 0.992, **0 crossed** — the two books are mirrors, there is no binary free lunch.

Locked-margin opportunities seen (a *set* is one share of every leg; margin is per set after fees; capital is what is tied up until the event resolves):

| group | kind | legs | exhaustive-like | peak net / set | peak gross | thinnest leg (shares) | lasted | days to resolution | net on capital | annualised |
|---|---|---|---|---|---|---|---|---|---|---|
| Melbourne's wettest month of 2026? | buy_set | 4 | yes | 0.0140 USD | 0.0140 | 7 | 1834 s | – | 1% | – |
| How many Fed rate cuts in 2026? | buy_set | 13 | yes | 0.0060 USD | 0.0060 | 87 | 1846 s | – | 1% | – |

The largest dollar opportunity of the hour: 0.0060 USD per set × 87 shares on the thinnest leg ≈ **0.52 USD**. With a 100 USD account the binding limits are depth (the thinnest leg) and capital locked until resolution, not the margin.

Best net margin seen per group and kind (including ones that never reached 5 shares):

| group | kind | legs | exhaustive-like | best net / set | best gross | shares at that moment |
|---|---|---|---|---|---|---|
| Melbourne's wettest month of 2026? | buy | 4 | yes | +0.0140 | +0.0140 | 7.0 |
| How many Fed rate cuts in 2026? | buy | 13 | yes | +0.0060 | +0.0060 | 87.0 |
| "Resident Evil" total domestic gross by Octobe | buy | 7 | yes | +0.0000 | +0.0000 | 62.7 |
| OpenAI IPO Closing Market Cap | buy | 7 | yes | -0.0010 | -0.0010 | 29.9 |
| What will Anthropic's IPO valuation be? | sell | 8 | yes | -0.0030 | -0.0030 | 20.0 |
| Highest temperature in Wuhan on October 24? | buy | 11 | yes | -0.0090 | -0.0090 | 100.0 |
| Highest temperature in Hong Kong on October 24 | buy | 11 | yes | -0.0100 | -0.0100 | 30.4 |
| Highest temperature in Chengdu on October 24? | buy | 11 | yes | -0.0100 | -0.0100 | 8.9 |

#### 2.2 Passive quoting (virtual post-only orders, 5 shares = the Polymarket minimum, TTL 300 s)

*trades* is the primary fill model (real trade prints consume the queue ahead of us); *strict* is a lower bound; *depletion* counts any displayed-size drop as a trade and is an **upper bound shown for completeness**. Markout = (later mid − fill price) × side, in cents per share; dollars are at 5 shares. The ± after a per-fill markout treats every fill as independent and is **too small** (one print can fill several orders, a moving market fills them all); the *market mean* column averages within a market first and takes the s.e. across markets — that is the honest one.

| universe | policy | model | attempts | fills | markets with fills | top market's share of fills | fill rate | spread capture (¢) | markout 300 s, per fill (¢) | markout 300 s, **market mean** (¢) | USD per fill (300 s) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| slow | join | strict | 445 | 3 | 2 | 67% | 1% | 3.17 | -1.67 ± 1.69 | -1.12 ± 1.63 (n = 2) | -0.083 |
| slow | join | trades | 445 | 3 | 2 | 67% | 1% | 3.17 | -1.67 ± 1.69 | -1.12 ± 1.63 (n = 2) | -0.083 |
| slow | join | depletion | 575 | 168 | 25 | 23% | 29% | 2.32 | +2.02 ± 0.25 | +1.47 ± 0.20 (n = 25) | +0.101 |
| slow | penny | strict | 371 | 10 | 5 | 40% | 3% | 1.25 | -0.85 ± 0.89 | -1.05 ± 0.70 (n = 5) | -0.043 |
| slow | penny | trades | 372 | 12 | 6 | 33% | 3% | 1.46 | -1.13 ± 0.84 | -0.89 ± 0.72 (n = 6) | -0.056 |
| slow | penny | depletion | 965 | 781 | 35 | 13% | 81% | 1.16 | +1.23 ± 0.08 | +1.01 ± 0.15 (n = 35) | +0.061 |
| control | join | strict | 181 | 94 | 8 | 27% | 52% | 0.50 | -8.52 ± 3.39 | -7.70 ± 5.01 (n = 8) | -0.426 |
| control | join | trades | 183 | 97 | 8 | 26% | 53% | 0.52 | -8.74 ± 3.36 | -8.67 ± 3.83 (n = 8) | -0.437 |
| control | join | depletion | 252 | 166 | 8 | 34% | 66% | 0.56 | -5.01 ± 2.61 | -5.49 ± 2.11 (n = 8) | -0.251 |
| control | penny | strict | 19 | 13 | 6 | 23% | 68% | 1.77 | -24.98 ± 5.77 | -24.14 ± 4.70 (n = 6) | -1.249 |
| control | penny | trades | 19 | 13 | 6 | 23% | 68% | 1.77 | -24.98 ± 5.77 | -24.14 ± 4.70 (n = 6) | -1.249 |
| control | penny | depletion | 19 | 13 | 6 | 23% | 68% | 1.77 | -24.98 ± 5.77 | -24.14 ± 4.70 (n = 6) | -1.249 |

Trade-print arrival (per-minute counts, Fano factor: 1 = Poisson, ≫ 1 = bursty sweeps):

| universe | markets with ≥ 5 prints | median trades / min | Fano median | Fano p90 |
|---|---|---|---|---|
| slow | 1 | 0.47 | 1.68 | 1.68 |
| control | 8 | 11.48 | 99.51 | 142.98 |

#### 2.3 Maker lock across a whole exhaustive group (join-bids on every leg; legging risk)

6 sets attempted, **0 completed** (0 %). Complete sets locked nothing; incomplete sets left 0 filled legs marked at mid for a mean P&L of +0.000 USD each (no resolution, no spread).

## 3. Track 2 — Hyperliquid funding and spot-perp basis

### 3.1 Funding (90 days of `fundingHistory`, liquid coins = Hyperliquid 24 h volume ≥ 1M USD, BTC/ETH excluded)

51 coins, 110,160 coin-hours. Median funding **0.125 bps/h** (the interest-rate floor, ≈ 11 % a year); percentiles 1 / 5 / 50 / 95 / 99: -0.68 / -0.24 / +0.12 / +0.26 / +0.89 bps/h.

| |funding| level | share of coin-hours, positive | negative |
|---|---|---|
| ≥ 0.5 bps/h | 2.75 % | 1.76 % |
| ≥ 1 bps/h | 0.75 % | 0.53 % |
| ≥ 3 bps/h | 0.02 % | 0.17 % |
| ≥ 5 bps/h | 0.00 % | 0.09 % |

After an hour at or above the level (positive side — the only side a long-spot hedge can carry), the funding actually collected over the next k hours, and how long such episodes last:

| level | episodes (starts) | carry next 4 h | next 8 h | next 24 h | median run (h) | share of runs ≥ 3 h / ≥ 6 h |
|---|---|---|---|---|---|---|
| ≥ 1 bps/h | 824 | 3.8 bps | 6.4 bps | 14.4 bps | 1 | 27% / 8% |
| ≥ 3 bps/h | 17 | 5.2 bps | 9.1 bps | 20.9 bps | 1 | 0% / 0% |
| ≥ 5 bps/h | 0 | – bps | – bps | – bps | – | – / – |

Hours of carry needed to pay the round-trip cost (public base-tier fees: Hyperliquid maker 1.5 / taker 4.5 bps per side, Binance spot 7.5 bps per side):

| structure | cost (bps) | at the 0.125 floor | at 1 bps/h | at 3 bps/h | at 5 bps/h |
|---|---|---|---|---|---|
| perp only maker | 3 | 24 h | 3 h | 1 h | 0.6 h |
| perp only taker | 9 | 72 h | 9 h | 3 h | 1.8 h |
| hedged perp maker+spot | 18 | 144 h | 18 h | 6 h | 3.6 h |

**Reading.** The "3–5 bps/h extremes" do not exist among liquid coins: positive ≥ 3 bps/h is 0.02 % of coin-hours (17 episodes in 90 days across 51 coins), ≥ 5 bps/h never. A delta-neutral carry needs ≈ 18 bps, i.e. 144 hours at the floor; even a ≥ 3 bps/h episode collects ≈ 21 bps over 24 h, which is the cost, before any basis move. On a 20 USD position 20 bps is +0.040 USD.

### 3.2 Basis reversion at 5 / 15 / 30 minutes (3.4 days of 1-minute bars, 60 mid-caps)

Basis = ln(HL / Binance), 3-minute smoothed, deviation from the trailing 6 h median (excluding the last 10 min), one event per coin per 30 min, **entry one minute after the trigger**; position = short the rich leg / long the cheap leg. Threshold × horizon chosen on the first 2695 minutes (train), evaluated once on the rest (test). Mean ± cluster s.e. (30-min blocks), bps:

| part | threshold | h | events | clusters | mean \|dev\| | perp leg | spot leg | **hedged spread** | net: perp-only maker (3) | hedged (18) |
|---|---|---|---|---|---|---|---|---|---|---|
| train | 8 | 5 min | 944 | 78 | 12.7 | +1.0 ± 2.0 | -0.6 ± 1.9 | **+0.4 ± 0.3** | -2.0 | -17.6 |
| train | 8 | 15 min | 944 | 78 | 12.7 | +2.3 ± 3.2 | -2.0 ± 3.1 | **+0.3 ± 0.4** | -0.7 | -17.7 |
| train | 8 | 30 min | 944 | 78 | 12.7 | +2.6 ± 4.8 | -2.5 ± 4.8 | **+0.1 ± 0.4** | -0.4 | -17.9 |
| train | 15 | 5 min | 174 | 76 | 30.7 | -1.8 ± 5.7 | +1.9 ± 5.8 | **+0.0 ± 1.1** | -4.8 | -18.0 |
| train | 15 | 15 min | 174 | 76 | 30.7 | +0.5 ± 8.4 | +0.1 ± 8.9 | **+0.5 ± 1.3** | -2.5 | -17.5 |
| train | 15 | 30 min | 174 | 76 | 30.7 | +15.4 ± 11.8 | -15.1 ± 12.2 | **+0.3 ± 1.7** | +12.4 | -17.7 |
| train | 30 | 5 min | 54 | 50 | 62.8 | +20.6 ± 14.4 | -20.2 ± 15.0 | **+0.5 ± 2.9** | +17.6 | -17.5 |
| train | 30 | 15 min | 54 | 50 | 62.8 | +6.0 ± 17.7 | -7.3 ± 17.9 | **-1.3 ± 3.1** | +3.0 | -19.3 |
| train | 30 | 30 min | 54 | 50 | 62.8 | +27.8 ± 15.7 | -28.1 ± 17.6 | **-0.3 ± 3.7** | +24.8 | -18.3 |
| test | 8 | 5 min | 970 | 75 | 10.7 | -0.1 ± 1.4 | +0.1 ± 1.4 | **+0.0 ± 0.4** | -3.1 | -18.0 |
| test | 8 | 15 min | 961 | 74 | 10.7 | +2.5 ± 2.4 | -2.2 ± 2.4 | **+0.3 ± 0.3** | -0.5 | -17.7 |
| test | 8 | 30 min | 954 | 74 | 10.7 | +4.6 ± 3.0 | -3.7 ± 2.9 | **+0.9 ± 0.4** | +1.6 | -17.1 |
| test | 15 | 5 min | 167 | 70 | 21.2 | -6.4 ± 5.1 | +7.9 ± 5.2 | **+1.6 ± 1.0** | -9.4 | -16.4 |
| test | 15 | 15 min | 164 | 69 | 21.3 | -3.0 ± 6.8 | +4.9 ± 6.9 | **+1.9 ± 1.0** | -6.0 | -16.1 |
| test | 15 | 30 min | 163 | 69 | 21.3 | +1.7 ± 9.0 | +0.3 ± 9.3 | **+2.0 ± 1.2** | -1.3 | -16.0 |
| test | 30 | 5 min | 25 | 24 | 47.8 | -0.2 ± 6.4 | -1.3 ± 7.6 | **-1.4 ± 2.2** | -3.2 | -19.4 |
| test | 30 | 15 min | 25 | 24 | 47.8 | +1.3 ± 11.4 | -2.8 ± 14.2 | **-1.5 ± 4.0** | -1.7 | -19.5 |
| test | 30 | 30 min | 25 | 24 | 47.8 | +14.7 ± 18.0 | -19.7 ± 18.6 | **-5.0 ± 4.6** | +11.7 | -23.0 |

Selected on train: threshold 30 bps, 30 min (train net +24.8 bps). On test that cell is **+11.7 ± 18.0 bps (n = 25, t = 0.65, one-sided p = 0.26): not significant**.
The perp and spot legs are mirror images (+15 / −15): the unhedged perp P&L is the coin's direction, not the basis. The hedged spread — the only part that is basis — earns −5 to +2 bps against ≈ 18 bps of cost.

Where does the deviation go? Mean signed deviation (bps) k minutes after a ≥ 15 bps trigger: 0 min: 26.1, 1 min: 24.1, 2 min: 21.5, 3 min: 17.3, 5 min: 17.2, 10 min: 15.5, 15 min: 16.3, 30 min: 15.9. About 40 % comes back within 3–5 minutes (mostly before the earliest possible fill) and ≈ 60 % is still there after 30 minutes — the same "persistent" share Phase 11 saw at tick level.

### 3.3 The same question at quote level (Phase 11 tapes: real bid/ask on both legs, 1-second grid, entry at the touch)

Equilibrium here is a 20-minute trailing median (each tape is 1 h long), 60-second smoothed basis, entry 1 s after the trigger, exit at the touch; **2 tapes, 60 coins, 2 hours**.

**4 events ≥ 8 bps in two hours across 60 coins** (the 1-minute candles of 3.2 above gave ≈ 950 in 1.5 days). Per event, hedged spread mid-to-mid / after crossing both spreads: 8|300: +7.2 / +2.4 (n = 1); 8|900: +7.0 / +2.8 (n = 1); 8|1800: +8.1 / -1.2 (n = 1); 8|300: +4.2 ± 3.0 / -2.0 ± 3.1 (n = 3); 8|900: +3.7 ± 0.4 / -1.9 ± 0.6 (n = 3); 8|1800: +6.2 / -0.3 (n = 2).

Most of the "persistent basis" in 1-minute candle data is **last-trade-close mismatch between the two venues**, not a quoted divergence: at quote level a ≥ 8 bps deviation from a 20-minute equilibrium is rare, and the few that occur are worth about nothing after the spreads.

### 3.4 The one pre-declared test: a rich perp underperforms the market over the next hours (hourly bars, ~100 days, discovery window excluded)

Found by searching a 3.4-day window (the unhedged perp leg of "short the rich / long the cheap perp", market-neutral, +160 ± 48 bps at 4 h for ≥ 30 bps), so it was **frozen as a hypothesis and tested out of sample** (`docs/PHASE12_PLAN.md`, hashes in `PHASE12_PLAN.json`): hourly bars, 60 coins, 2316 bars (the last 84 never used), trigger |dev| ≥ 30 bps, hold 4 h, outcome = perp leg minus the equal-weight market move, minus 6 bps, one-sided cluster t, ≥ 30 clusters.

**Primary: 350 events, 254 clusters, market-neutral net +15.5 ± 17.8 bps, t = 0.87, one-sided p = 0.194 → do not reject H0.** The in-sample +160 bps is not reproduced (+21.5 ± 17.8). Secondary cells (descriptive):

| threshold | hold | events | clusters | market-neutral perp | raw perp | hedged spread | net (neutral − 6) | t |
|---|---|---|---|---|---|---|---|---|
| 15 | 1 h | 4335 | 572 | +11.4 ± 1.7 | +12.3 ± 2.3 | +15.3 ± 0.2 | +5.4 | 3.12 |
| 15 | 2 h | 4335 | 572 | +12.5 ± 2.5 | +14.5 ± 3.5 | +16.1 ± 0.2 | +6.5 | 2.59 |
| 15 | 4 h | 4335 | 572 | +11.7 ± 3.3 | +13.9 ± 5.7 | +16.6 ± 0.2 | +5.7 | 1.70 |
| 15 | 24 h | 4305 | 567 | +18.4 ± 7.6 | +18.2 ± 13.8 | +17.4 ± 0.2 | +12.4 | 1.62 |
| 30 | 1 h | 350 | 254 | -0.8 ± 10.6 | -3.7 ± 12.0 | +28.9 ± 1.6 | -6.8 | -0.64 |
| 30 | 2 h | 350 | 254 | -0.3 ± 14.5 | -1.9 ± 15.9 | +30.7 ± 1.2 | -6.3 | -0.43 |
| 30 | 4 h | 350 | 254 | +21.5 ± 17.8 | +26.9 ± 23.1 | +31.6 ± 1.5 | +15.5 | 0.87 |
| 30 | 24 h | 350 | 254 | +102.3 ± 38.8 | +112.6 ± 53.0 | +34.7 ± 1.5 | +96.3 | 2.48 |

**Caution on the hedged column.** At hourly resolution it shows +15 to +35 bps with tiny standard errors. That is a measurement artefact: it enters at stale last-trade closes of two venues, so the observed basis at the trigger bar is partly noise that is gone one bar later (the 1-minute study with a one-minute entry delay and the quote-level study both show ≈ 0). It is not tradable and is not used anywhere in the verdict. The 15 bps cells (t ≈ 3.1 at 1 h, market-neutral net +5 bps) are exploratory, one of 8 secondary cells, share the same artefact (entry at the stale close) and are not claimed.

## 4. How this compares with Phases 1–11

| phase | strategy | horizon | execution | best honest result |
|---|---|---|---|---|
| 1–3 | BTC → 60 Binance alts lead-lag | seconds | taker | gaps ≲ 1 bp gross vs ≈ 2 bp spread and 15 bp fees: detected, refused |
| 4–6 | BTC → Hyperliquid / Polymarket (taker, passive maker, pre-positioned maker) | seconds | taker / maker | Hyperliquid +2.5 bps gross vs 4.5 bps taker; Polymarket maker fills adversely, taker loses ≈ 2.4 ¢ per share |
| 7–10 | Architecture B on Polymarket, exits, regime gates | 10 s – minutes | taker in / maker out | never significant; in-sample +128 bps, t = 0.80, pre-registered N\* = 608 not collected |
| 11 | Sector oracles; same-asset Binance → Hyperliquid tail lag | sub-second | taker | pre-registered: net −8.46 ± 1.63 bps (t = −5.2); lag real (+3.9 bps) but sub-second and ≈ ⅓ of the gap |
| **12** | **Funding carry, basis reversion, premium drift (Hyperliquid); structural sets and passive quoting (Polymarket)** | minutes – days | maker / hold | see §1 |
