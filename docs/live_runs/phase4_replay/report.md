# Quant Agency — Phase 4 report: venue & microstructure specialization

* mode **replay of p4_tape_1.npz**, duration **1199s**, **151** markets: binance/spot: 29, coinbase/spot: 9, deribit/perp: 2, gate/spot: 9, hyperliquid/perp: 9, kraken/spot: 9, polymarket/prediction: 84
* hard microstructure gate: directional trades require live spread ≤ **0.5 bps** (CFO rule; wider signals are shadow-tracked, `rejected_gate` cohort). Prediction markets use their own cost model (spread + price-dependent taker fee).
* order latency assumed **150 ms**; shadow trackers re-score every signal at 0 ms, 500 ms.

> **FEE ASSUMPTIONS (not verifiable from public data):** zero fee on Binance `*FDUSD`, `BTCUSDC`, `ETHUSDC` (per the operator brief; promotions change), 7.5 bps elsewhere on Binance; public retail taker fees Gate 20 / Kraken 40 / Coinbase 60 / Hyperliquid 4.5 / Deribit 5 bps; Polymarket taker `0.07·p·(1−p)` per share (≈ 350 bps at p = 0.5), makers free. Every table below also shows **zero-fee net** (`net0`) so conclusions do not depend on them.

## 1. Feed health & internal latency

_(none)_

* scan→gate (all 150 markets + arb + prediction): n=153437 p50=31µs p90=109µs p99=384µs max=360.6ms
* BTC tick → approved executable payload: n=24 p50=376µs p99=1052µs
* markets that never ticked: 10 (pm:bitcoin-above-on-october-20-2026:above-74000, pm:bitcoin-above-on-october-20-2026:above-90000, pm:bitcoin-above-on-october-20-2026:above-92000, pm:bitcoin-above-on-october-20-2026:above-94000, pm:bitcoin-price-on-october-20-2026:below-74000, pm:bitcoin-price-on-october-20-2026:range-74000-76000, pm:bitcoin-price-on-october-20-2026:range-88000-90000, pm:bitcoin-price-on-october-20-2026:range-90000-92000, pm:bitcoin-price-on-october-20-2026:above-92000, pm:bitcoin-price-on-october-21-2026:range-72000-74000)

## 2. Battleground 1 — the `< 0.5 bps` hypothesis, tested out-of-sample

*Pre-registered claim (from Run 1, n = 35, **zero latency, zero fee**): signals in markets with live spread < 0.5 bps have net@5s > 0 and hit-rate > 60 %. Here it is re-tested on a fresh live session at **realistic latency**. `net0` = spread-crossing net with zero fees; cluster-robust s.e. over BTC impulses.*

| spread bucket (all directional signals, all venues, t+5s) | n | gross bps | net0 bps ±s.e. (zero fee) | net (mixed venue fees) | hit gross | hit net0 |
|---|---|---|---|---|---|---|
| 0–0.5 bps | 124 | +0.89 | +0.63±0.40 | -33.37 | 62% | 58% |
| 0.5–1 bps | 125 | +0.71 | -0.25±0.63 | -30.51 | 48% | 29% |
| 1–3 bps | 132 | +0.50 | -1.21±0.64 | -54.62 | 45% | 17% |
| ≥3 bps | 29 | +1.27 | -2.12±0.72 | -76.94 | 66% | 14% |

*The `net (mixed venue fees)` column blends 0 bps (assumed Binance promo pairs) with 60 bps (Coinbase); read `net0` for the microstructure question and the per-fee-class tables below for the economics.*

**Latency sensitivity of the tight-spread cohort (same signals re-scored at different order latencies; t+5s):**

| order latency | n | gross bps | net0 bps ±s.e. | net (assumed fees) | hit gross | hit net0 |
|---|---|---|---|---|---|---|
| 0 ms | 124 | +1.38 | +1.19±0.37 | -32.81 | 77% | 74% |
| 150 ms | 124 | +0.89 | +0.63±0.40 | -33.37 | 62% | 58% |
| 500 ms | 124 | +0.75 | +0.51±0.46 | -33.49 | 55% | 48% |

**Tight cohort (<0.5 bps) by venue / fee class — order latency 150 ms, t+5s:**

| class | n | gross bps | net0 bps ±s.e. | net (assumed fees) | hit gross | hit net0 |
|---|---|---|---|---|---|---|
| hyperliquid (perp) | 39 | +2.46 | +2.03±0.48 | -6.97 | 90% | 87% |
| kraken (spot) | 27 | +0.55 | +0.32±0.41 | -79.68 | 70% | 70% |
| gate (spot) | 14 | -0.10 | -0.38±0.24 | -40.38 | 29% | 21% |
| Binance, 7.5 bps | 13 | +0.38 | +0.27±0.24 | -14.73 | 46% | 31% |
| Binance, assumed zero-fee | 13 | +0.02 | -0.09±0.26 | -0.09 | 38% | 38% |
| deribit (perp) | 11 | -0.61 | -0.76±0.34 | -10.76 | 36% | 27% |
| coinbase (spot) | 7 | +0.40 | +0.16±0.53 | -119.84 | 57% | 57% |

**Tight cohort (<0.5 bps) by venue / fee class — order latency 0 ms, t+5s:**

| class | n | gross bps | net0 bps ±s.e. | net (assumed fees) | hit gross | hit net0 |
|---|---|---|---|---|---|---|
| hyperliquid (perp) | 39 | +2.47 | +2.12±0.45 | -6.88 | 90% | 87% |
| kraken (spot) | 27 | +1.20 | +1.15±0.37 | -78.85 | 81% | 78% |
| gate (spot) | 14 | +0.74 | +0.49±0.26 | -39.51 | 64% | 64% |
| Binance, 7.5 bps | 13 | +0.92 | +0.81±0.25 | -14.19 | 77% | 62% |
| Binance, assumed zero-fee | 13 | +0.62 | +0.52±0.28 | +0.52 | 69% | 69% |
| deribit (perp) | 11 | +0.39 | +0.25±0.29 | -9.75 | 55% | 55% |
| coinbase (spot) | 7 | +1.18 | +1.08±0.48 | -118.92 | 71% | 71% |


**Claim check (150 ms): n=124 over 19 BTC impulses, net0 +0.63±0.40 bps, hit 58% → NOT SUPPORTED at 2σ.** (Run 1: n=35, +0.98 bps, 77 % at zero latency.)

**Fee sensitivity (tight cohort, t+5s): net = net0 − 2·fee** → fee 0 bps: +0.63, fee 1 bps: -1.37, fee 4.5 bps: -8.37, fee 7.5 bps: -14.37

## 3. CFO gating (this run) vs Run 1

evaluated 527, approved **24** (4.6%); reasons: spread_too_wide=257, net_edge_below_hurdle=135, quarantined=88, ok=24, size_below_min=21, in_position=2

## 4. Cross-venue lead-lag (BTC oracle → other venues' books, same assets)

| venue (t+5s) | n | gross bps | net0 bps ±s.e. | net (assumed fees) | hit gross | hit net0 |
|---|---|---|---|---|---|---|
| gate | 56 | -0.19 | -1.33±0.61 | -41.33 | 32% | 11% |
| kraken | 70 | +1.16 | -0.27±0.51 | -80.27 | 67% | 41% |
| coinbase | 59 | -0.11 | -2.02±0.38 | -122.02 | 37% | 14% |
| hyperliquid | 92 | +2.45 | +1.65±0.57 | -7.35 | 84% | 73% |
| deribit | 12 | -0.59 | -0.75±0.33 | -10.75 | 33% | 25% |

lead-lag map, cross-venue books (HY lag vs the Binance BTC oracle):

| market | β | t(β) | ρ | lag s |
|---|---|---|---|---|
| gate:BTC_USDT | 0.93 | 38.8 | 0.95 | 0.0 |
| hyperliquid:ETH | 1.49 | 17.0 | 0.79 | 0.9 |
| deribit:BTC-PERP | 0.96 | 15.8 | 0.77 | -0.5 |
| gate:ETH_USDT | 1.30 | 15.6 | 0.76 | -0.3 |
| hyperliquid:BTC | 0.94 | 14.8 | 0.74 | 0.7 |
| kraken:BTC/USD | 0.93 | 14.7 | 0.74 | -0.1 |
| coinbase:BTC-USD | 0.96 | 14.6 | 0.74 | 0.0 |
| deribit:ETH-PERP | 0.98 | 13.9 | 0.72 | 0.1 |
| hyperliquid:DOGE | 1.41 | 13.3 | 0.71 | 0.9 |
| coinbase:ETH-USD | 1.26 | 12.4 | 0.68 | 0.0 |
| kraken:ETH/USD | 1.26 | 11.5 | 0.65 | 0.0 |
| kraken:DOGE/USD | 1.56 | 10.7 | 0.63 | -0.1 |

## 5. Direct cross-venue & triangular arbitrage (locked gaps, basis-adjusted)

168 same-asset pairs + 18 triangles scanned (42675 scans). **Episodes with a positive basis-adjusted gross gap: 26328** (gap p50 0.55, p90 1.09, max 9.45 bps; lifetime p50 0.52s, p90 5.00s).

| metric | count |
|---|---|
| gross gap ≥ record threshold | 26328 |
| net of fees+slippage+hurdle > 0 at detection | 59 |
| net > 0 still true after order latency (persistence) | 76 |
| executed (both/any legs) | 27 |
| paper PnL $ | +0.25 |
| mean gap at fill time (bps) | +0.41 |

reasons: gap_below_cost=26269, size_below_min=32, ok=27

**Executed arb by pair** (`locked` = both legs filled at the detected prices; `leg_risk` = one leg missed and the other was unwound):

| pair | opps | locked | leg-risk | missed | paper PnL $ |
|---|---|---|---|---|---|
| ETHFDUSD>ETHUSDC | 91 | 5 | 1 | 0 | +0.132 |
| BTCFDUSD>BTCUSDC | 73 | 12 | 3 | 0 | +0.090 |
| ETHUSDC>ETHFDUSD | 69 | 5 | 1 | 0 | +0.031 |

*27 of 27 executed arb trades had a total modelled fee of 0 bps (the assumed zero-fee Binance pairs). 'Locked' profit is **basis-adjusted**: it assumes the stable-coin / quote-currency basis reverts to its EW mean; it is not risk-free.*

| name | kind | gap bps | fees | slip | net@detect | gap@fill | status | approved/reason |
|---|---|---|---|---|---|---|---|---|
| hyperliquid:AVAX>AVAXUSDT | xvenue | 9.45 | 12.00 | 0.14 | -3.69 | 9.43 | shadow | False/gap_below_cost |
| hyperliquid:AVAX>coinbase:AVAX-USD | xvenue | 8.06 | 64.50 | 0.17 | -57.61 | 8.04 | shadow | False/gap_below_cost |
| hyperliquid:LTC>LTCUSDT | xvenue | 7.60 | 12.00 | 0.02 | -5.42 | 3.25 | shadow | False/gap_below_cost |
| hyperliquid:AVAX>AVAXUSDC | xvenue | 7.42 | 12.00 | 0.45 | -6.02 | 7.40 | shadow | False/gap_below_cost |
| hyperliquid:AVAX>gate:AVAX_USDT | xvenue | 7.40 | 24.50 | 0.23 | -18.33 | 9.47 | shadow | False/gap_below_cost |
| coinbase:AVAX-USD>AVAXUSDT | xvenue | 6.65 | 67.50 | 0.52 | -62.38 | -0.72 | shadow | False/gap_below_cost |
| kraken:AVAX/USD>AVAXUSDT | xvenue | 5.68 | 47.50 | 0.27 | -43.10 | -2.75 | shadow | False/gap_below_cost |
| SOLUSDC>hyperliquid:SOL | xvenue | 5.34 | 12.00 | 0.12 | -7.78 | 7.26 | shadow | False/gap_below_cost |
| hyperliquid:LTC>coinbase:LTC-USD | xvenue | 5.10 | 64.50 | 0.04 | -60.44 | 1.25 | shadow | False/gap_below_cost |
| hyperliquid:LTC>gate:LTC_USDT | xvenue | 5.08 | 24.50 | 0.03 | -20.45 | 2.40 | shadow | False/gap_below_cost |

## 6. Battleground 2 — Polymarket CLOB (50+ BTC markets) driven by the Binance oracle

84 BTC markets watched (Counter({'above': 36, 'range': 27, 'updown_twap': 15, 'updown_terminal': 3, 'below': 3})), book updates: 303660, scans 35283, **signals 117**.

| Polymarket markouts | n | gross bps | net0 bps ±s.e. | net (taker fee schedule) | hit gross | hit net0 |
|---|---|---|---|---|---|---|
| t+1s | 117 | +366.44 | -231.86±103.17 | -972.25 | 53% | 30% |
| t+3s | 117 | +379.36 | -212.29±136.87 | -953.45 | 62% | 30% |
| t+5s | 117 | +511.60 | -97.64±155.85 | -839.28 | 68% | 36% |
| t+10s | 117 | +622.15 | +28.92±162.86 | -711.76 | 70% | 44% |
| t+30s | 115 | +996.98 | +387.53±277.53 | -366.83 | 77% | 43% |

**Economics in cents per share (bps of notional is distorted by contracts priced near 0 or 1, where one tick is a 100 % move)** — t+5s, taker both ways:

| price bucket | n | impulses | gross ¢/share | spread ¢ | net0 ¢ ±s.e. | taker fee ¢ (2 sides) | net ¢ (after fees) |
|---|---|---|---|---|---|---|---|
| p < 0.10 or > 0.90 (near-decided) | 12 | 11 | +0.44 | 1.58 | -0.99±0.76 | 0.94 | -1.93 |
| 0.10 ≤ p ≤ 0.90 (live) | 105 | 38 | +2.33 | 2.17 | +0.48±0.63 | 2.87 | -2.39 |

mean signalled gap 818 bps vs mean spread 696 bps; mean taker fee drag 742 bps round-trip.

**Momentum control — did the CLOB converge to fair value, or did BTC just keep moving?** `gap` = fair-value move minus CLOB move at signal time (prob. points, signed to the trade). After h seconds: `fair drift` = how far the model fair value moved (pure BTC drift), `CLOB move` = how far the CLOB mid moved. If the CLOB merely tracks fair value, CLOB move ≈ fair drift and **closure ≈ 0**.

| horizon | family | n | impulses | gap ¢ | fair drift ¢ | CLOB move ¢ | CLOB − fair ¢ ±s.e. | closure of gap |
|---|---|---|---|---|---|---|---|---|
| t+5s | all | 117 | 39 | +2.80 | +1.25 | +2.48 | +1.23±0.33 | +0.44 |
| t+5s | updown_twap | 46 | 29 | +4.81 | +2.65 | +4.22 | +1.57±0.60 | +0.33 |
| t+5s | updown_terminal | 26 | 21 | +1.94 | +0.91 | +2.37 | +1.46±0.36 | +0.75 |
| t+5s | above/below/range | 45 | 24 | +1.23 | +0.02 | +0.78 | +0.76±0.13 | +0.61 |
| t+30s | all | 115 | 37 | +2.72 | +3.47 | +4.07 | +0.60±0.34 | +0.22 |
| t+30s | updown_twap | 44 | 27 | +4.69 | +7.63 | +7.32 | -0.32±0.84 | -0.07 |
| t+30s | updown_terminal | 26 | 21 | +1.94 | +2.30 | +4.06 | +1.76±0.58 | +0.91 |
| t+30s | above/below/range | 45 | 24 | +1.23 | +0.07 | +0.91 | +0.84±0.11 | +0.68 |

| market | kind | ttl min | ticks | mid | spread ¢ | signals |
|---|---|---|---|---|---|---|
| pm:bitcoin-up-or-down-october-19-2026-3pm-et:updown_1h | updown_terminal | 5 | 21224 | 0.025 | 0.9 | 26 |
| pm:bitcoin-price-on-october-21-2026:range-82000-84000 | range | 2645 | 3366 | 0.350 | 6.0 | 18 |
| pm:btc-updown-15m-1792438200:updown_15m | updown_twap | -10 | 43985 | 0.996 | 0.5 | 14 |
| pm:btc-updown-15m-1792439100:updown_15m | updown_twap | 5 | 34302 | 0.006 | 0.6 | 10 |
| pm:bitcoin-price-on-october-21-2026:range-80000-82000 | range | 2645 | 3290 | 0.375 | 7.0 | 10 |
| pm:bitcoin-price-on-october-21-2026:range-78000-80000 | range | 2645 | 1034 | 0.115 | 1.0 | 6 |
| pm:btc-updown-5m-1792438800:updown_5m | updown_twap | -10 | 46960 | 0.985 | 1.0 | 5 |
| pm:btc-updown-5m-1792439100:updown_5m | updown_twap | -5 | 22880 | 0.002 | 0.1 | 5 |
| pm:btc-updown-4h-1792425600:updown_4h | updown_twap | 5 | 35581 | 0.036 | 4.7 | 5 |
| pm:bitcoin-above-on-october-21-2026:above-82000 | above | 2645 | 1175 | 0.495 | 1.0 | 4 |
| pm:btc-updown-5m-1792438500:updown_5m | updown_twap | -15 | 29419 | 0.985 | 1.0 | 3 |
| pm:btc-updown-5m-1792439400:updown_5m | updown_twap | -0 | 25531 | 0.002 | 0.2 | 2 |

coverage rejects: {'no_model': 92462}

## 7. Before / after vs Run 1

| metric | Run 1 (60 USDT alts, live) | Phase 4 (this run) |
|---|---|---|
| directional signals detected | 197 | 410 |
| CFO-approved (all signal types) | 0 | 24 (4.6%) |
| gross markout @1s (directional) | +0.25 | +0.51 |
| gross markout @5s (directional) | -0.09 | +0.74 |
| gross markout @30s (directional) | +0.45 | +0.25 |
| hit rate gross @5s | 34% | 52% |
| net0 (zero-fee, crosses spread) @5s | -2.31 | -0.43 |
| tight-spread (<0.5 bps) net0 @5s [n, hit] | +0.98 [35, 77%; zero latency] | +0.63±0.40 [124, 58%; 150 ms] |
| closed paper trades / PnL | 0 / $0.00 | 40 / $+23.24 |
| arb episodes net>0 after fees | n/a | 59 |
| Polymarket signals | n/a | 117 |


---
# Appendix: generic agency telemetry (CFO, markouts, execution, CEO)

## (generic) Feed health

_(none)_

* hunter scan (all 150 markets, numba): n=153437  p50=31µs  p90=109µs  p99=384µs  max=360.56ms
* BTC tick received → CFO-approved executable payload ready: n=24  p50=376µs  p90=623µs  p99=1052µs  max=1.09ms
* BTC quotes processed: 153437  | trades(agg): 5491  | book rejects: 0

## 2. BTC oracle (master reference)

BTCUSDT bid/ask 81834.97/81834.98, micro 81834.976, OBI +0.12, spread 0.001 bps, vol 0.29 bps/√s (slow 0.27, ratio 1.06), tick-vol 0.00

BTC impulses detected (|Z|≥3.00 at report time): **23**; hunter scans: 47537

## 3. Lead-lag map (Hayashi-Yoshida peak lag, Kalman β) — top markets by ρ

calibrated: 60/150 markets

| market | β (Kalman) | t(β) | ρ (3s, at lag) | HY ρ peak | HY ρ(0) | lag s | decay s | σ_res 3s bps | spread bps | tick Hz | regime |
|---|---|---|---|---|---|---|---|---|---|---|---|
| gate:BTC_USDT | 0.93 | 38.8 | 0.95 | 1.00 | 1.00 | 0.0 | 0.0 | 0.27 | 0.01 | 8.0 | normal |
| ETHUSDT | 1.38 | 15.9 | 0.91 | 0.08 | 0.08 | 0.0 | 0.1 | 0.95 | 0.04 | 25.0 | normal |
| hyperliquid:ETH | 1.49 | 17.0 | 0.79 | 0.50 | 0.14 | 0.9 | 0.2 | 0.97 | 0.42 | 8.5 | normal |
| deribit:BTC-PERP | 0.96 | 15.8 | 0.77 | 0.23 | 0.21 | -0.5 | 0.1 | 0.54 | 0.06 | 8.7 | normal |
| gate:ETH_USDT | 1.30 | 15.6 | 0.76 | 0.36 | 0.27 | -0.3 | 0.1 | 0.93 | 0.04 | 6.8 | normal |
| BNBUSDT | 0.80 | 15.5 | 0.76 | 0.32 | 0.18 | 0.6 | 0.0 | 0.33 | 0.14 | 10.6 | normal |
| SOLUSDT | 2.28 | 8.2 | 0.75 | 0.02 | 0.02 | 0.0 | 0.0 | 1.47 | 0.96 | 15.6 | normal |
| hyperliquid:BTC | 0.94 | 14.8 | 0.74 | 0.44 | 0.08 | 0.7 | 0.2 | 0.42 | 0.12 | 8.9 | normal |
| kraken:BTC/USD | 0.93 | 14.7 | 0.74 | 0.08 | 0.00 | -0.1 | 0.0 | 0.46 | 0.01 | 8.5 | tight |
| DOGEUSDT | 1.43 | 14.6 | 0.74 | 0.13 | 0.08 | -0.2 | 0.0 | 0.99 | 1.26 | 8.9 | normal |
| coinbase:BTC-USD | 0.96 | 14.6 | 0.74 | 0.59 | 0.59 | 0.0 | 0.0 | 0.50 | 0.00 | 16.3 | tight |
| ETHFDUSD | 1.03 | 14.2 | 0.73 | 0.12 | 0.09 | 0.2 | 0.0 | 0.88 | 0.04 | 13.8 | normal |
| deribit:ETH-PERP | 0.98 | 13.9 | 0.72 | 0.36 | 0.03 | 0.1 | 0.2 | 1.19 | 0.21 | 9.0 | normal |
| DOGEUSDC | 1.62 | 13.4 | 0.71 | 0.14 | 0.12 | -0.5 | 0.5 | 1.03 | 1.26 | 2.6 | normal |
| hyperliquid:DOGE | 1.41 | 13.3 | 0.71 | 0.54 | 0.23 | 0.9 | 0.1 | 1.07 | 0.25 | 3.0 | normal |

## 4. Detected micro-gaps (hunter signals): **410**

per market (top 10): pm:bitcoin-up-or-down-october-19-2026-3pm-et:updown_1h:26, pm:bitcoin-price-on-october-21-2026:range-82000-84000:18, pm:btc-updown-15m-1792438200:updown_15m:14, hyperliquid:ETH:12, hyperliquid:SOL:11, hyperliquid:DOGE:11, hyperliquid:LINK:11, AVAXUSDC:10, kraken:SOL/USD:10, hyperliquid:XRP:10

| t | market | side | BTC Δ | Z | β | lag | gap bps | gap Z | spread | CFO | pred net | gross@1s | gross@5s | net@5s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
|  978.8s | pm:bitcoin-up-or-down-october-19-2026-3pm-et:updown_1h | BUY | +2.0@1s | 6.4 | 1.00 | 0.0 | +5038.7 | 3.3 | 1538.5 | quarantined | +1856.0 | +1176.5 | -588.2 | -3510.2 |
|  392.3s | pm:btc-updown-5m-1792438800:updown_5m | BUY | +2.0@1s | 9.1 | 1.00 | 0.0 | +4036.5 | 15.5 | 259.7 | ok (taker) | +2864.1 | +4675.3 | +6493.5 | +5467.8 |
|  955.8s | pm:bitcoin-up-or-down-october-19-2026-3pm-et:updown_1h | SELL | -1.8@3s | -2.8 | 1.00 | 0.0 | -3938.3 | 2.2 | 1818.2 | quarantined | +460.2 | +1818.2 | -0.0 | -3323.0 |
| 1006.6s | pm:bitcoin-up-or-down-october-19-2026-3pm-et:updown_1h | SELL | -2.0@10s | -1.3 | 1.00 | 0.0 | -3689.2 | 2.4 | 1538.5 | quarantined | +594.3 | +833.3 | -833.3 | -5316.0 |
|  649.0s | pm:btc-updown-5m-1792439100:updown_5m | SELL | -1.2@1s | -4.7 | 1.00 | 0.0 | -3678.3 | 2.8 | 1333.3 | size_below_min | +746.2 | +1538.5 | +1538.5 | -1316.0 |
|  890.7s | pm:bitcoin-up-or-down-october-19-2026-3pm-et:updown_1h | SELL | -3.4@10s | -2.0 | 1.00 | 0.0 | -2929.0 | 3.1 | 952.4 | size_below_min | +567.4 | -0.0 | -476.2 | -3246.0 |
|  880.9s | pm:btc-updown-5m-1792439400:updown_5m | SELL | -3.6@1s | -11.6 | 1.00 | 0.0 | -2763.9 | 9.0 | 307.7 | ok (taker) | +1435.0 | +1692.3 | +5230.8 | +3936.0 |
| 1001.6s | pm:bitcoin-up-or-down-october-19-2026-3pm-et:updown_1h | SELL | -1.5@3s | -2.2 | 1.00 | 0.0 | -2529.7 | 1.4 | 1818.2 | quarantined | +1307.5 | -0.0 | -909.1 | -5316.0 |
|  610.8s | pm:btc-updown-5m-1792439100:updown_5m | SELL | -2.3@10s | -2.2 | 1.00 | 0.0 | -2172.4 | 6.0 | 363.6 | ok (taker) | +729.2 | -172.4 | +172.4 | -1358.1 |
|  943.8s | pm:btc-updown-5m-1792439400:updown_5m | SELL | -1.6@3s | -2.5 | 1.00 | 0.0 | -1966.7 | 1.1 | 1818.2 | ok (maker) | +744.5 | -0.0 | +1818.2 | -1330.0 |
|  641.2s | pm:btc-updown-5m-1792439100:updown_5m | SELL | -1.2@10s | -1.1 | 1.00 | 0.0 | -1825.6 | 2.5 | 740.7 | ok (maker) | +1007.7 | -0.0 | +2222.2 | +306.5 |
|  629.4s | pm:btc-updown-5m-1792439100:updown_5m | SELL | -1.1@1s | -4.5 | 1.00 | 0.0 | -1804.4 | 1.5 | 1176.5 | size_below_min | +807.4 | -0.0 | +2424.2 | +678.0 |
|  318.7s | pm:btc-updown-5m-1792438800:updown_5m | SELL | -1.1@1s | -4.5 | 1.00 | 0.0 | -1769.8 | 7.3 | 241.0 | size_below_min | +648.4 | +2650.6 | +4096.4 | +2964.4 |
|  830.5s | pm:btc-updown-4h-1792425600:updown_4h | BUY | -1.5@10s | -1.5 | 1.00 | 0.0 | +1727.3 | 4.8 | 363.6 | size_below_min | +690.0 | +0.0 | -1250.0 | -2561.6 |

## 5. CFO gating & accounting

evaluated 527, approved 24; reasons: spread_too_wide=257, net_edge_below_hurdle=135, quarantined=88, ok=24, size_below_min=21, in_position=2

equity $10,023.24 (peak $10,023.24, drawdown 0.000%), closed PnL $+23.24, fees $17.03; hurdle 1.00 bps, edge-credit 1.00, mode auto, size×1.00, halted=False (-), quarantined=['LINKUSDC', 'LINKUSDT', 'gate:LTC_USDT', 'hyperliquid:LTC', 'hyperliquid:AVAX', 'hyperliquid:DOGE', 'coinbase:DOGE-USD', 'hyperliquid:SOL', 'kraken:SOL/USD', 'hyperliquid:ETH', 'pm:btc-updown-15m-1792439100:updown_15m', 'pm:bitcoin-price-on-october-21-2026:range-80000-82000', 'pm:bitcoin-up-or-down-october-19-2026-3pm-et:updown_1h', 'AVAXUSDC', 'XRPUSDC', 'gate:SOL_USDT', 'hyperliquid:BTC', 'pm:bitcoin-price-on-october-21-2026:range-82000-84000']

## 6. Realised markout curves (t+1s … t+30s)

**All detected gaps (incl. CFO-rejected shadow cohort)** — does the gap actually close?

| horizon | n | gross bps | net bps (taker, after spread+fees) | net s.e. | hit gross | hit net | gap closure |
|---|---|---|---|---|---|---|---|
| t+1s | 527 | +81.75 | -249.06 | 103.61 | 48% | 4% | 0.61 |
| t+3s | 527 | +84.65 | -244.84 | 124.75 | 51% | 5% | 0.61 |
| t+5s | 527 | +114.15 | -219.34 | 131.58 | 56% | 7% | 0.74 |
| t+10s | 527 | +138.80 | -190.92 | 131.76 | 55% | 8% | 0.81 |
| t+30s | 487 | +235.62 | -119.79 | 199.92 | 60% | 11% | 0.60 |

**CFO-approved cohort**

| horizon | n | gross bps | net bps (taker, after spread+fees) | net s.e. | hit gross | hit net | gap closure |
|---|---|---|---|---|---|---|---|
| t+1s | 24 | +624.60 | -217.24 | 348.93 | 50% | 38% | 0.62 |
| t+3s | 24 | +935.58 | +121.06 | 398.43 | 71% | 42% | 0.77 |
| t+5s | 24 | +1208.63 | +399.26 | 409.66 | 75% | 50% | 0.97 |
| t+10s | 24 | +1721.22 | +914.24 | 393.40 | 71% | 50% | 1.28 |
| t+30s | 23 | +2490.99 | +1690.07 | 735.76 | 83% | 74% | 2.12 |

**CFO-rejected: net edge below hurdle**

| horizon | n | gross bps | net bps (taker, after spread+fees) | net s.e. | hit gross | hit net | gap closure |
|---|---|---|---|---|---|---|---|
| t+1s | 135 | +30.22 | -391.98 | 138.31 | 53% | 2% | 0.67 |
| t+3s | 135 | +35.83 | -378.33 | 132.53 | 56% | 2% | 0.68 |
| t+5s | 135 | +44.76 | -369.07 | 130.41 | 62% | 2% | 0.76 |
| t+10s | 135 | +48.01 | -357.89 | 120.60 | 64% | 2% | 0.81 |
| t+30s | 132 | +58.13 | -367.94 | 138.99 | 63% | 2% | 0.94 |

_gross = mid→mid after fill (latency-adjusted entry); net = cross the spread on entry and exit + round-trip taker fees; gap closure = share of the signalled gap that has closed._

## 7. Per-market profitability @ t+5s

| market | n | gross bps | net bps | hit net | status |
|---|---|---|---|---|---|
| pm:btc-updown-5m-1792438800:updown_5m | 5 | +2503.28 | +1829.91 | 80% |  |
| pm:btc-updown-5m-1792439400:updown_5m | 2 | +3524.48 | +1303.00 | 50% |  |
| pm:btc-updown-5m-1792439700:updown_5m | 2 | +1239.14 | +674.42 | 100% |  |
| pm:btc-updown-5m-1792438500:updown_5m | 3 | +780.53 | +318.71 | 100% |  |
| BTCFDUSD | 4 | +0.69 | +0.69 | 75% |  |
| ETHFDUSD | 3 | +0.18 | +0.14 | 33% |  |
| BNBFDUSD | 3 | -0.02 | -0.41 | 0% |  |
| XRPFDUSD | 5 | +0.15 | -0.77 | 40% |  |
| ETHUSDC | 3 | -1.00 | -1.04 | 33% |  |
| DOGEFDUSD | 5 | -0.76 | -2.02 | 20% |  |

worst:

| market | n | gross bps | net bps | hit net | status |
|---|---|---|---|---|---|
| pm:btc-updown-4h-1792425600:updown_4h | 5 | -183.83 | -1207.19 | 20% |  |
| pm:bitcoin-price-on-october-20-2026:range-82000-84000 | 2 | +121.95 | -1352.82 | 0% |  |
| pm:bitcoin-price-on-october-21-2026:range-80000-82000 | 10 | +160.75 | -1475.85 | 0% | QUARANTINED |
| pm:bitcoin-price-on-october-21-2026:range-82000-84000 | 18 | +129.25 | -1687.38 | 0% | QUARANTINED |
| pm:bitcoin-price-on-october-21-2026:range-78000-80000 | 6 | +231.19 | -2802.80 | 0% |  |

## 8. Paper execution

orders submitted 24, filled 13 (partial 1), closed 40, open 0; dropped: {'maker_ttl_expired': 9, 'below_min_notional': 2, 'ioc_price_moved': 1, 'ioc_no_liquidity': 1}

closed trades 40: win rate 75%, net PnL $+23.24, fees $17.03, expectancy +113.80 bps / +0.30 R, gross +215.20 bps, entry slippage -5.50 bps, mean spread at entry 40.97 bps

exit reasons: take_profit=8, locked=22, adverse_stop=2, leg_risk=5, time_stop=3

| market | side | mode | hold s | entry | exit | gross bps | net bps | R | exit |
|---|---|---|---|---|---|---|---|---|---|
| BTCFDUSD>BTCUSDC | L | arb | 0.0 | 0 | 0 | +1.2 | +1.2 | +0.24 | locked |
| ETHFDUSD>ETHUSDC | L | arb | 0.0 | 0 | 0 | +1.7 | +1.7 | +0.34 | locked |
| ETHFDUSD>ETHUSDC | L | arb | 0.0 | 0 | 0 | +1.4 | +1.4 | +0.27 | locked |
| BTCFDUSD>BTCUSDC | L | arb | 0.0 | 0 | 0 | +1.4 | +1.4 | +0.28 | locked |
| BTCFDUSD>BTCUSDC | L | arb | 0.0 | 0 | 0 | +1.4 | +1.4 | +0.28 | locked |
| BTCFDUSD>BTCUSDC | L | arb | 0.0 | 0 | 0 | +1.1 | +1.1 | +0.23 | locked |
| BTCFDUSD>BTCUSDC | L | arb | 0.0 | 0 | 0 | +1.5 | +1.5 | +0.30 | locked |
| BTCFDUSD>BTCUSDC | L | arb | 0.0 | 0 | 0 | +1.1 | +1.1 | +0.22 | locked |
| BTCFDUSD>BTCUSDC | L | arb | 0.0 | 0 | 0 | +1.1 | +1.1 | +0.22 | locked |
| ETHFDUSD>ETHUSDC | L | arb | 0.0 | 0 | 0 | +1.1 | +1.1 | +0.22 | locked |
| ETHUSDC>ETHFDUSD | L | arb | 0.0 | 0 | 0 | -0.0 | -0.0 | -0.01 | leg_risk |
| pm:btc-updown-5m-1792439700:updown_5m | L | taker | 4.9 | 0.62 | 0.67 | +806.5 | +290.8 | +0.88 | take_profit |

sample prepared payload (never transmitted):

```json
{
 "oid": 24,
 "sid": 10000116,
 "market": "pm:btc-updown-5m-1792439700:updown_5m",
 "symbol": "45803575559191913970645154322843345204131045979103804994417498192458059781380",
 "venue": "polymarket",
 "side": "BUY",
 "order_type": "LIMIT",
 "time_in_force": "IOC",
 "price": 0.62,
 "qty": 16.8,
 "notional": 10.416,
 "mode": "taker",
 "tp_price": 0.6706176071508752,
 "stop_price": 0.585,
 "time_stop_s": 30.0,
 "maker_ttl_s": 3.0,
 "expected_net_bps": 800.4577347175668,
 "gap_bps": 1549.4122113547878,
 "t_signal": 6632.291695125,
 "t_prepared": 6632.291695125,
 "prep_latency_us": 310.98500039661303,
 "sig_quote_px": 0.61,
 "sig_mid": 0.605,
 "beta": 1.0,
 "stop_bps": 330.5785123966945,
 "exchange_params": {
  "symbol": "45803575559191913970645154322843345204131045979103804994417498192458059781380",
  "side": "BUY",
  "type": "LIMIT",
  "quantity": "16.8",
  "price": "0.62",
  "newClientOrderId": "qa24",
  "timeInForce": "IOC"
 }
}
```

## 9. CEO → CFO/Hunter interventions

CEO state: **NORMAL**, reviews: 40, interventions: **31**

| t | state | verdict | signals | gross5 | net5 | false-gap | trades | exp bps | realization | reasons |
|---|---|---|---|---|---|---|---|---|---|---|
| 871s | NORMAL | OK | 241 | 143.069 | -242.146 | 40% | 21 | 146.024 | 0.672 |  |
| 901s | NORMAL | GOOD | 262 | 172.195 | -219.005 | 37% | 20 | 235.66 | 2.898 |  |
| 931s | NORMAL | GOOD | 252 | 153.355 | -226.235 | 36% | 21 | 224.536 | 2.898 |  |
| 961s | NORMAL | GOOD | 254 | 159.824 | -234.089 | 36% | 19 | 248.059 | 4.71 |  |
| 991s | NORMAL | GOOD | 328 | 121.744 | -215.217 | 47% | 21 | 224.345 | 4.705 |  |
| 1021s | NORMAL | OK | 212 | 127.356 | -350.275 | 51% | 19 | 45.558 | None |  |
| 1051s | NORMAL | GOOD | 212 | 127.356 | -350.275 | 51% | 18 | 90.34 | None |  |
| 1081s | NORMAL | GOOD | 212 | 127.356 | -350.275 | 51% | 21 | 77.632 | None |  |
| 1111s | NORMAL | GOOD | 212 | 127.356 | -350.275 | 51% | 22 | 74.156 | None |  |
| 1141s | NORMAL | GOOD | 219 | 125.566 | -360.733 | 51% | 22 | 74.175 | None |  |
| 1171s | NORMAL | GOOD | 219 | 125.566 | -360.733 | 51% | 24 | 68.084 | None |  |
| 1199s | NORMAL | GOOD | 211 | 121.598 | -328.714 | 51% | 27 | 71.33 | None |  |

audit trail:

```
#1 [20:03:59] QUARANTINE_MARKET      pm:bitcoin-up-or-down-october-19-2026-3pm-et:updown_1h NORMAL->NORMAL | negative_markouts: n=6 gross@1s=+256.65 gross@5s=+280.27 net@5s=-353.03bps hit=17%; blacklisted 600s | {} -> {'until': 6321.7}
#2 [20:03:59] QUARANTINE_MARKET      pm:btc-updown-15m-1792438200:updown_15m NORMAL->NORMAL | negative_markouts: n=7 gross@1s=+494.90 gross@5s=+623.32 net@5s=-53.89bps hit=29%; blacklisted 600s | {} -> {'until': 6321.7}
#3 [20:05:59] RETUNE_IMPULSE         hunter     NORMAL->NORMAL | false-gap 47% over 144 fresh signals, regime normal-vol (vol ratio 0.93) | {'z_thr': 3.0, 'window_mult': 2.0} -> {'z_thr': 3.0, 'window_mult': 2.25}
#4 [20:06:29] QUARANTINE_MARKET      hyperliquid:LINK NORMAL->NORMAL | negative_markouts: n=6 gross@1s=+0.98 gross@5s=+1.54 net@5s=-8.86bps hit=0%; blacklisted 600s | {} -> {'until': 6471.8}
#5 [20:06:29] RETUNE_IMPULSE         hunter     NORMAL->NORMAL | false-gap 45% over 253 fresh signals, regime normal-vol (vol ratio 1.10) | {'z_thr': 3.0, 'window_mult': 2.25} -> {'z_thr': 3.0, 'window_mult': 1.75}
#6 [20:06:59] RETUNE_IMPULSE         hunter     NORMAL->NORMAL | false-gap 44% over 264 fresh signals, regime normal-vol (vol ratio 1.05) | {'z_thr': 3.0, 'window_mult': 1.75} -> {'z_thr': 3.0, 'window_mult': 2.0}
#7 [20:08:30] QUARANTINE_MARKET      pm:bitcoin-price-on-october-21-2026:range-82000-84000 NORMAL->NORMAL | negative_markouts: n=7 gross@1s=+58.46 gross@5s=+156.33 net@5s=-1553.25bps hit=0%; blacklisted 600s | {} -> {'until': 6591.9}
#8 [20:10:00] QUARANTINE_MARKET      LINKUSDC   NORMAL->NORMAL | negative_markouts: n=6 gross@1s=+0.00 gross@5s=+0.21 net@5s=-15.98bps hit=0%; blacklisted 600s | {} -> {'until': 6681.9}
#9 [20:10:00] QUARANTINE_MARKET      LINKUSDT   NORMAL->NORMAL | negative_markouts: n=6 gross@1s=+0.28 gross@5s=+0.84 net@5s=-15.00bps hit=0%; blacklisted 600s | {} -> {'until': 6681.9}
#10 [20:10:00] QUARANTINE_MARKET      gate:LTC_USDT NORMAL->NORMAL | negative_markouts: n=6 gross@1s=+0.14 gross@5s=+0.56 net@5s=-41.95bps hit=0%; blacklisted 600s | {} -> {'until': 6681.9}
#11 [20:10:00] QUARANTINE_MARKET      hyperliquid:LTC NORMAL->NORMAL | negative_markouts: n=6 gross@1s=+1.43 gross@5s=+1.63 net@5s=-8.08bps hit=0%; blacklisted 600s | {} -> {'until': 6681.9}
#12 [20:10:00] QUARANTINE_MARKET      hyperliquid:AVAX NORMAL->NORMAL | negative_markouts: n=6 gross@1s=+1.14 gross@5s=+1.95 net@5s=-7.90bps hit=0%; blacklisted 600s | {} -> {'until': 6681.9}
#13 [20:10:00] QUARANTINE_MARKET      hyperliquid:DOGE NORMAL->NORMAL | negative_markouts: n=6 gross@1s=+1.85 gross@5s=+2.00 net@5s=-7.23bps hit=0%; blacklisted 600s | {} -> {'until': 6681.9}
#14 [20:10:00] QUARANTINE_MARKET      coinbase:DOGE-USD NORMAL->NORMAL | negative_markouts: n=6 gross@1s=-0.42 gross@5s=-0.74 net@5s=-123.78bps hit=0%; blacklisted 600s | {} -> {'until': 6681.9}
#15 [20:10:00] QUARANTINE_MARKET      hyperliquid:SOL NORMAL->NORMAL | negative_markouts: n=6 gross@1s=+1.60 gross@5s=+1.76 net@5s=-8.20bps hit=0%; blacklisted 600s | {} -> {'until': 6681.9}
#16 [20:10:00] QUARANTINE_MARKET      kraken:SOL/USD NORMAL->NORMAL | negative_markouts: n=6 gross@1s=+0.08 gross@5s=+0.72 net@5s=-80.32bps hit=0%; blacklisted 600s | {} -> {'until': 6681.9}
#17 [20:10:30] QUARANTINE_MARKET      hyperliquid:ETH NORMAL->NORMAL | negative_markouts: n=6 gross@1s=+1.35 gross@5s=+1.77 net@5s=-7.75bps hit=0%; blacklisted 600s | {} -> {'until': 6712.0}
#18 [20:10:30] QUARANTINE_MARKET      pm:btc-updown-15m-1792439100:updown_15m NORMAL->NORMAL | negative_markouts: n=6 gross@1s=+379.70 gross@5s=+689.27 net@5s=-563.13bps hit=17%; blacklisted 600s | {} -> {'until': 6712.0}
#19 [20:11:00] QUARANTINE_MARKET      pm:bitcoin-price-on-october-21-2026:range-80000-82000 NORMAL->NORMAL | negative_markouts: n=6 gross@1s=-0.01 gross@5s=+113.22 net@5s=-1578.52bps hit=0%; blacklisted 600s | {} -> {'until': 6742.0}
#20 [20:12:30] RETUNE_IMPULSE         hunter     NORMAL->NORMAL | false-gap 37% over 284 fresh signals, regime normal-vol (vol ratio 0.91) | {'z_thr': 3.0, 'window_mult': 2.0} -> {'z_thr': 3.0, 'window_mult': 2.25}
#21 [20:14:30] RETUNE_IMPULSE         hunter     NORMAL->NORMAL | false-gap 37% over 262 fresh signals, regime normal-vol (vol ratio 1.23) | {'z_thr': 3.0, 'window_mult': 2.25} -> {'z_thr': 3.0, 'window_mult': 1.5}
#22 [20:15:00] QUARANTINE_MARKET      pm:bitcoin-up-or-down-october-19-2026-3pm-et:updown_1h NORMAL->NORMAL | negative_markouts: n=15 gross@1s=+516.42 gross@5s=+543.43 net@5s=-321.03bps hit=33%; blacklisted 1200s | {} -> {'until': 7582.2}
#23 [20:15:00] RETUNE_IMPULSE         hunter     NORMAL->NORMAL | false-gap 37% over 252 fresh signals, regime normal-vol (vol ratio 1.16) | {'z_thr': 3.0, 'window_mult': 1.5} -> {'z_thr': 3.0, 'window_mult': 1.75}
#24 [20:16:00] QUARANTINE_MARKET      AVAXUSDC   NORMAL->NORMAL | negative_markouts: n=7 gross@1s=+1.12 gross@5s=+1.57 net@5s=-16.35bps hit=0%; blacklisted 600s | {} -> {'until': 7042.3}
#25 [20:16:00] QUARANTINE_MARKET      XRPUSDC    NORMAL->NORMAL | negative_markouts: n=6 gross@1s=+0.13 gross@5s=-0.39 net@5s=-16.15bps hit=0%; blacklisted 600s | {} -> {'until': 7042.3}
#26 [20:16:00] QUARANTINE_MARKET      gate:SOL_USDT NORMAL->NORMAL | negative_markouts: n=6 gross@1s=-0.16 gross@5s=-0.64 net@5s=-41.60bps hit=0%; blacklisted 600s | {} -> {'until': 7042.3}
#27 [20:16:00] QUARANTINE_MARKET      hyperliquid:BTC NORMAL->NORMAL | negative_markouts: n=6 gross@1s=+1.20 gross@5s=+2.46 net@5s=-6.72bps hit=0%; blacklisted 600s | {} -> {'until': 7042.3}
#28 [20:17:00] RETUNE_IMPULSE         hunter     NORMAL->NORMAL | false-gap 51% over 212 fresh signals, regime normal-vol (vol ratio 1.06) | {'z_thr': 3.0, 'window_mult': 1.75} -> {'z_thr': 3.0, 'window_mult': 2.0}
#29 [20:18:30] QUARANTINE_MARKET      pm:bitcoin-price-on-october-21-2026:range-82000-84000 NORMAL->NORMAL | negative_markouts: n=11 gross@1s=+35.25 gross@5s=+112.01 net@5s=-1772.74bps hit=0%; blacklisted 1200s | {} -> {'until': 7792.4}
#30 [20:19:00] RETUNE_IMPULSE         hunter     NORMAL->NORMAL | false-gap 51% over 219 fresh signals, regime normal-vol (vol ratio 0.92) | {'z_thr': 3.0, 'window_mult': 2.0} -> {'z_thr': 3.0, 'window_mult': 2.25}
#31 [20:19:29] RETUNE_IMPULSE         hunter     NORMAL->NORMAL | false-gap 51% over 211 fresh signals, regime normal-vol (vol ratio 1.06) | {'z_thr': 3.0, 'window_mult': 2.25} -> {'z_thr': 3.0, 'window_mult': 2.0}
```

## 10. Caveats

* Quotes are timestamped at *our* gateway (cloud container → proxy → venue). Lead-lag below ~100 ms here is measured through that path; a co-located engine would see different lags.
* Paper fills use as-of quotes after an assumed order latency; maker fills require the market to trade *through* the resting price (no queue-position credit).
* Short sales are simulated (perp-style); on spot they would be unavailable.
