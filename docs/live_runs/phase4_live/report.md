# Quant Agency — Phase 4 report: venue & microstructure specialization

* mode **live**, duration **1200s**, **151** markets: binance/spot: 29, coinbase/spot: 9, deribit/perp: 2, gate/spot: 9, hyperliquid/perp: 9, kraken/spot: 9, polymarket/prediction: 84
* hard microstructure gate: directional trades require live spread ≤ **0.5 bps** (CFO rule; wider signals are shadow-tracked, `rejected_gate` cohort). Prediction markets use their own cost model (spread + price-dependent taker fee).
* order latency assumed **150 ms**; shadow trackers re-score every signal at 0 ms, 500 ms.

> **FEE ASSUMPTIONS (not verifiable from public data):** zero fee on Binance `*FDUSD`, `BTCUSDC`, `ETHUSDC` (per the operator brief; promotions change), 7.5 bps elsewhere on Binance; public retail taker fees Gate 20 / Kraken 40 / Coinbase 60 / Hyperliquid 4.5 / Deribit 5 bps; Polymarket taker `0.07·p·(1−p)` per share (≈ 350 bps at p = 0.5), makers free. Every table below also shows **zero-fee net** (`net0`) so conclusions do not depend on them.

## 1. Feed health & internal latency

| feed | msgs | quotes | rate | reconnects | errors | up | last error |
|---|---|---|---|---|---|---|---|
| binance | 557743 | 552252 | 465/s | 1 | 1 | yes | ConnectionClosedError: no close frame received or sent |
| gate | 50509 | 50508 | 42/s | 0 | 0 | yes | - |
| kraken | 99257 | 98042 | 83/s | 1 | 1 | yes | ConnectionClosedError: no close frame received or sent |
| coinbase | 117119 | 117117 | 98/s | 1 | 1 | yes | ConnectionClosedError: no close frame received or sent |
| hyperliquid | 42565 | 42556 | 35/s | 0 | 0 | yes | - |
| deribit | 26443 | 26441 | 22/s | 1 | 1 | yes | ConnectionClosedError: no close frame received or sent |
| polymarket | 1279819 | 303660 | 1066/s | 3 | 3 | yes | ConnectionClosedError: received 1013 (try again later) slow consumer: send buffer full; then sent 1013 (try again later) slow consumer: send bu |

* scan→gate (all 150 markets + arb + prediction): n=153437 p50=41µs p90=252µs p99=689µs max=14.1ms
* BTC tick → approved executable payload: n=24 p50=628µs p99=1252µs
* markets that never ticked: 10 (pm:bitcoin-above-on-october-20-2026:above-74000, pm:bitcoin-above-on-october-20-2026:above-90000, pm:bitcoin-above-on-october-20-2026:above-92000, pm:bitcoin-above-on-october-20-2026:above-94000, pm:bitcoin-price-on-october-20-2026:below-74000, pm:bitcoin-price-on-october-20-2026:range-74000-76000, pm:bitcoin-price-on-october-20-2026:range-88000-90000, pm:bitcoin-price-on-october-20-2026:range-90000-92000, pm:bitcoin-price-on-october-20-2026:above-92000, pm:bitcoin-price-on-october-21-2026:range-72000-74000)

## 2. Battleground 1 — the `< 0.5 bps` hypothesis, tested out-of-sample

*Pre-registered claim (from Run 1, n = 35, **zero latency, zero fee**): signals in markets with live spread < 0.5 bps have net@5s > 0 and hit-rate > 60 %. Here it is re-tested on a fresh live session at **realistic latency**. `net0` = spread-crossing net with zero fees; cluster-robust s.e. over BTC impulses.*

| spread bucket (all directional signals, t+5s) | n | gross bps | net0 bps ±s.e. | net (assumed fees) | hit gross | hit net0 |
|---|---|---|---|---|---|---|
| 0–0.5 bps | 127 | +0.89 | +0.62±0.40 | -33.27 | 62% | 58% |
| 0.5–1 bps | 125 | +0.71 | -0.25±0.63 | -30.51 | 48% | 29% |
| 1–3 bps | 133 | +0.51 | -1.21±0.64 | -54.22 | 45% | 17% |
| ≥3 bps | 29 | +1.27 | -2.12±0.72 | -76.94 | 66% | 14% |

**Latency sensitivity of the tight-spread cohort (same signals re-scored at different order latencies; t+5s):**

| order latency | n | gross bps | net0 bps ±s.e. | net (assumed fees) | hit gross | hit net0 |
|---|---|---|---|---|---|---|
| 0 ms | 127 | +1.37 | +1.18±0.37 | -32.72 | 77% | 74% |
| 150 ms | 127 | +0.89 | +0.62±0.40 | -33.27 | 62% | 58% |
| 500 ms | 127 | +0.76 | +0.51±0.46 | -33.39 | 56% | 49% |


**Claim check (150 ms): n=127 over 19 BTC impulses, net0 +0.62±0.40 bps, hit 58% → NOT SUPPORTED at 2σ.** (Run 1: n=35, +0.98 bps, 77 % at zero latency.)

**Fee sensitivity (tight cohort, t+5s): net = net0 − 2·fee** → fee 0 bps: +0.62, fee 1 bps: -1.38, fee 4.5 bps: -8.38, fee 7.5 bps: -14.38

## 3. CFO gating (this run) vs Run 1

evaluated 531, approved **24** (4.5%); reasons: spread_too_wide=253, net_edge_below_hurdle=136, quarantined=94, ok=24, size_below_min=22, in_position=2

## 4. Cross-venue lead-lag (BTC oracle → other venues' books, same assets)

| venue (t+5s) | n | gross bps | net0 bps ±s.e. | net (assumed fees) | hit gross | hit net0 |
|---|---|---|---|---|---|---|
| gate | 56 | -0.19 | -1.33±0.61 | -41.33 | 32% | 11% |
| kraken | 71 | +1.14 | -0.26±0.51 | -80.26 | 66% | 41% |
| coinbase | 59 | -0.11 | -2.02±0.38 | -122.02 | 37% | 14% |
| hyperliquid | 93 | +2.43 | +1.64±0.57 | -7.36 | 84% | 73% |
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

168 same-asset pairs + 18 triangles scanned (43594 scans). **Episodes with a positive basis-adjusted gross gap: 26353** (gap p50 0.55, p90 1.09, max 9.43 bps; lifetime p50 0.52s, p90 5.01s).

| metric | count |
|---|---|
| gross gap ≥ record threshold | 26353 |
| net of fees+slippage+hurdle > 0 at detection | 63 |
| net > 0 still true after order latency (persistence) | 77 |
| executed (both/any legs) | 30 |
| paper PnL $ | +0.26 |
| mean gap at fill time (bps) | +0.41 |

reasons: gap_below_cost=26290, size_below_min=33, ok=30

| name | kind | gap bps | fees | slip | net@detect | gap@fill | status | approved/reason |
|---|---|---|---|---|---|---|---|---|
| hyperliquid:AVAX>AVAXUSDT | xvenue | 9.43 | 12.00 | 0.14 | -3.70 | 9.43 | shadow | False/gap_below_cost |
| hyperliquid:AVAX>coinbase:AVAX-USD | xvenue | 8.06 | 64.50 | 0.17 | -57.62 | 8.06 | shadow | False/gap_below_cost |
| hyperliquid:LTC>LTCUSDT | xvenue | 7.60 | 12.00 | 0.02 | -5.42 | 3.25 | shadow | False/gap_below_cost |
| hyperliquid:AVAX>AVAXUSDC | xvenue | 7.42 | 12.00 | 0.45 | -6.03 | 7.42 | shadow | False/gap_below_cost |
| hyperliquid:AVAX>gate:AVAX_USDT | xvenue | 7.39 | 24.50 | 0.23 | -18.34 | 9.50 | shadow | False/gap_below_cost |
| coinbase:AVAX-USD>AVAXUSDT | xvenue | 6.63 | 67.50 | 0.52 | -62.39 | -0.73 | shadow | False/gap_below_cost |
| kraken:AVAX/USD>AVAXUSDT | xvenue | 5.64 | 47.50 | 0.27 | -43.13 | -3.82 | shadow | False/gap_below_cost |
| SOLUSDC>hyperliquid:SOL | xvenue | 5.33 | 12.00 | 0.12 | -7.79 | 7.25 | shadow | False/gap_below_cost |
| hyperliquid:LTC>coinbase:LTC-USD | xvenue | 5.11 | 64.50 | 0.04 | -60.43 | 1.26 | shadow | False/gap_below_cost |
| hyperliquid:LTC>gate:LTC_USDT | xvenue | 5.09 | 24.50 | 0.03 | -20.45 | 2.41 | shadow | False/gap_below_cost |

## 6. Battleground 2 — Polymarket CLOB (50+ BTC markets) driven by the Binance oracle

84 BTC markets watched (Counter({'above': 36, 'range': 27, 'updown_twap': 15, 'updown_terminal': 3, 'below': 3})), CLOB quotes processed: 303660, scans 35283, **signals 117**.

| Polymarket markouts | n | gross bps | net0 bps ±s.e. | net (taker fee schedule) | hit gross | hit net0 |
|---|---|---|---|---|---|---|
| t+1s | 117 | +366.44 | -231.86±103.17 | -972.25 | 53% | 30% |
| t+3s | 117 | +379.36 | -212.29±136.87 | -953.45 | 62% | 30% |
| t+5s | 117 | +511.60 | -97.64±155.85 | -839.28 | 68% | 36% |
| t+10s | 117 | +622.15 | +28.92±162.86 | -711.76 | 70% | 44% |
| t+30s | 115 | +996.98 | +387.53±277.53 | -366.83 | 77% | 43% |

mean signalled gap 818 bps vs mean spread 696 bps; mean taker fee drag 742 bps round-trip.

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
| directional signals detected | 197 | 414 |
| CFO-approved (all signal types) | 0 | 24 (4.5%) |
| gross markout @1s (directional) | +0.25 | +0.51 |
| gross markout @5s (directional) | -0.09 | +0.74 |
| gross markout @30s (directional) | +0.45 | +0.28 |
| hit rate gross @5s | 34% | 53% |
| net0 (zero-fee, crosses spread) @5s | -2.31 | -0.42 |
| tight-spread (<0.5 bps) net0 @5s [n, hit] | +0.98 [35, 77%; zero latency] | +0.62±0.40 [127, 58%; 150 ms] |
| closed paper trades / PnL | 0 / $0.00 | 44 / $+26.76 |
| arb episodes net>0 after fees | n/a | 63 |
| Polymarket signals | n/a | 117 |


---
# Appendix: generic agency telemetry (CFO, markouts, execution, CEO)

## (generic) Feed health

| feed | msgs | quotes | rate | reconnects | errors | up | last error |
|---|---|---|---|---|---|---|---|
| binance | 557743 | 552252 | 465/s | 1 | 1 | yes | ConnectionClosedError: no close frame received or sent |
| gate | 50509 | 50508 | 42/s | 0 | 0 | yes | - |
| kraken | 99257 | 98042 | 83/s | 1 | 1 | yes | ConnectionClosedError: no close frame received or sent |
| coinbase | 117119 | 117117 | 98/s | 1 | 1 | yes | ConnectionClosedError: no close frame received or sent |
| hyperliquid | 42565 | 42556 | 35/s | 0 | 0 | yes | - |
| deribit | 26443 | 26441 | 22/s | 1 | 1 | yes | ConnectionClosedError: no close frame received or sent |
| polymarket | 1279819 | 303660 | 1066/s | 3 | 3 | yes | ConnectionClosedError: received 1013 (try again later) slow consumer: send buffer full; then sent 1013 (try again later) slow consumer: send bu |

* hunter scan (all 150 markets, numba): n=153437  p50=41µs  p90=252µs  p99=689µs  max=14.14ms
* BTC tick received → CFO-approved executable payload ready: n=24  p50=628µs  p90=1015µs  p99=1252µs  max=1.30ms
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
| SOLUSDT | 2.28 | 8.2 | 0.75 | 0.02 | 0.02 | 0.0 | 0.0 | 1.46 | 0.96 | 15.6 | normal |
| hyperliquid:BTC | 0.94 | 14.8 | 0.74 | 0.44 | 0.08 | 0.7 | 0.2 | 0.41 | 0.12 | 8.9 | normal |
| kraken:BTC/USD | 0.93 | 14.7 | 0.74 | 0.08 | 0.00 | -0.1 | 0.0 | 0.46 | 0.01 | 8.5 | tight |
| DOGEUSDT | 1.43 | 14.6 | 0.74 | 0.13 | 0.08 | -0.2 | 0.0 | 0.99 | 1.26 | 8.9 | normal |
| coinbase:BTC-USD | 0.96 | 14.6 | 0.74 | 0.59 | 0.59 | 0.0 | 0.0 | 0.50 | 0.00 | 16.3 | tight |
| ETHFDUSD | 1.03 | 14.2 | 0.73 | 0.12 | 0.09 | 0.2 | 0.0 | 0.88 | 0.04 | 13.8 | normal |
| deribit:ETH-PERP | 0.98 | 13.9 | 0.72 | 0.36 | 0.03 | 0.1 | 0.2 | 1.20 | 0.21 | 9.0 | normal |
| DOGEUSDC | 1.62 | 13.4 | 0.71 | 0.14 | 0.12 | -0.5 | 0.5 | 1.03 | 1.26 | 2.6 | normal |
| hyperliquid:DOGE | 1.41 | 13.3 | 0.71 | 0.54 | 0.23 | 0.9 | 0.1 | 1.07 | 0.25 | 3.0 | normal |

## 4. Detected micro-gaps (hunter signals): **414**

per market (top 10): pm:bitcoin-up-or-down-october-19-2026-3pm-et:updown_1h:26, pm:bitcoin-price-on-october-21-2026:range-82000-84000:18, pm:btc-updown-15m-1792438200:updown_15m:14, hyperliquid:ETH:13, hyperliquid:SOL:11, hyperliquid:DOGE:11, kraken:LINK/USD:11, hyperliquid:LINK:11, AVAXUSDC:10, kraken:SOL/USD:10

| t | market | side | BTC Δ | Z | β | lag | gap bps | gap Z | spread | CFO | pred net | gross@1s | gross@5s | net@5s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
|  979.6s | pm:bitcoin-up-or-down-october-19-2026-3pm-et:updown_1h | BUY | +2.0@1s | 6.4 | 1.00 | 0.0 | +5038.7 | 3.3 | 1538.5 | quarantined | +1856.0 | +1176.5 | -588.2 | -3510.2 |
|  393.1s | pm:btc-updown-5m-1792438800:updown_5m | BUY | +2.0@1s | 9.1 | 1.00 | 0.0 | +4036.5 | 15.5 | 259.7 | ok (taker) | +2864.1 | +4675.3 | +6493.5 | +5467.8 |
|  956.5s | pm:bitcoin-up-or-down-october-19-2026-3pm-et:updown_1h | SELL | -1.8@3s | -2.8 | 1.00 | 0.0 | -3938.3 | 2.2 | 1818.2 | quarantined | +460.2 | +1818.2 | -0.0 | -3323.0 |
| 1007.3s | pm:bitcoin-up-or-down-october-19-2026-3pm-et:updown_1h | SELL | -2.0@10s | -1.3 | 1.00 | 0.0 | -3689.2 | 2.4 | 1538.5 | quarantined | +594.3 | +833.3 | -833.3 | -5316.0 |
|  649.7s | pm:btc-updown-5m-1792439100:updown_5m | SELL | -1.2@1s | -4.7 | 1.00 | 0.0 | -3678.3 | 2.8 | 1333.3 | size_below_min | +746.2 | +1538.5 | +1538.5 | -1316.0 |
|  891.4s | pm:bitcoin-up-or-down-october-19-2026-3pm-et:updown_1h | SELL | -3.4@10s | -2.0 | 1.00 | 0.0 | -2929.0 | 3.1 | 952.4 | size_below_min | +567.4 | -0.0 | -476.2 | -3246.0 |
|  881.7s | pm:btc-updown-5m-1792439400:updown_5m | SELL | -3.6@1s | -11.6 | 1.00 | 0.0 | -2763.9 | 9.0 | 307.7 | ok (taker) | +1435.0 | +1692.3 | +5230.8 | +3936.0 |
| 1002.3s | pm:bitcoin-up-or-down-october-19-2026-3pm-et:updown_1h | SELL | -1.5@3s | -2.2 | 1.00 | 0.0 | -2529.7 | 1.4 | 1818.2 | quarantined | +1307.5 | -0.0 | -909.1 | -5316.0 |
|  611.6s | pm:btc-updown-5m-1792439100:updown_5m | SELL | -2.3@10s | -2.2 | 1.00 | 0.0 | -2172.4 | 6.0 | 363.6 | ok (taker) | +729.2 | -172.4 | +172.4 | -1358.1 |
|  944.5s | pm:btc-updown-5m-1792439400:updown_5m | SELL | -1.6@3s | -2.5 | 1.00 | 0.0 | -1966.7 | 1.1 | 1818.2 | ok (maker) | +744.5 | -0.0 | +1818.2 | -1330.0 |
|  641.9s | pm:btc-updown-5m-1792439100:updown_5m | SELL | -1.2@10s | -1.1 | 1.00 | 0.0 | -1825.6 | 2.5 | 740.7 | ok (maker) | +1007.7 | -0.0 | +2222.2 | +306.5 |
|  630.1s | pm:btc-updown-5m-1792439100:updown_5m | SELL | -1.1@1s | -4.5 | 1.00 | 0.0 | -1804.4 | 1.5 | 1176.5 | size_below_min | +807.4 | -0.0 | +2424.2 | +678.0 |
|  319.4s | pm:btc-updown-5m-1792438800:updown_5m | SELL | -1.1@1s | -4.5 | 1.00 | 0.0 | -1769.8 | 7.3 | 241.0 | size_below_min | +648.4 | +2650.6 | +4096.4 | +2964.4 |
|  831.2s | pm:btc-updown-4h-1792425600:updown_4h | BUY | -1.5@10s | -1.5 | 1.00 | 0.0 | +1727.3 | 4.8 | 363.6 | size_below_min | +690.0 | +0.0 | -1250.0 | -2561.6 |

## 5. CFO gating & accounting

evaluated 531, approved 24; reasons: spread_too_wide=253, net_edge_below_hurdle=136, quarantined=94, ok=24, size_below_min=22, in_position=2

equity $10,026.76 (peak $10,026.76, drawdown 0.000%), closed PnL $+26.76, fees $19.77; hurdle 1.00 bps, edge-credit 1.00, mode auto, size×1.00, halted=False (-), quarantined=['LINKUSDC', 'LINKUSDT', 'gate:LTC_USDT', 'hyperliquid:LTC', 'kraken:LINK/USD', 'hyperliquid:AVAX', 'hyperliquid:DOGE', 'coinbase:DOGE-USD', 'hyperliquid:SOL', 'kraken:SOL/USD', 'hyperliquid:ETH', 'pm:btc-updown-15m-1792439100:updown_15m', 'pm:bitcoin-price-on-october-21-2026:range-80000-82000', 'pm:bitcoin-up-or-down-october-19-2026-3pm-et:updown_1h', 'AVAXUSDC', 'XRPUSDC', 'gate:SOL_USDT', 'hyperliquid:BTC', 'pm:bitcoin-price-on-october-21-2026:range-82000-84000']

## 6. Realised markout curves (t+1s … t+30s)

**All detected gaps (incl. CFO-rejected shadow cohort)** — does the gap actually close?

| horizon | n | gross bps | net bps (taker, after spread+fees) | net s.e. | hit gross | hit net | gap closure |
|---|---|---|---|---|---|---|---|
| t+1s | 531 | +81.14 | -247.35 | 103.61 | 48% | 4% | 0.61 |
| t+3s | 531 | +84.02 | -243.16 | 124.75 | 51% | 5% | 0.62 |
| t+5s | 531 | +113.30 | -217.85 | 131.58 | 56% | 7% | 0.75 |
| t+10s | 531 | +137.76 | -189.65 | 131.76 | 55% | 8% | 0.81 |
| t+30s | 491 | +233.72 | -118.98 | 199.92 | 60% | 12% | 0.62 |

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
| t+1s | 136 | +29.98 | -389.70 | 138.30 | 53% | 2% | 0.66 |
| t+3s | 136 | +35.56 | -376.15 | 132.52 | 56% | 2% | 0.67 |
| t+5s | 136 | +44.42 | -366.96 | 130.39 | 62% | 2% | 0.75 |
| t+10s | 136 | +47.64 | -355.87 | 120.58 | 63% | 2% | 0.80 |
| t+30s | 133 | +57.69 | -365.78 | 138.97 | 63% | 2% | 0.94 |

_gross = mid→mid after fill (latency-adjusted entry); net = cross the spread on entry and exit + round-trip taker fees; gap closure = share of the signalled gap that has closed._

## 7. Per-market profitability @ t+5s

| market | n | gross bps | net bps | hit net | status |
|---|---|---|---|---|---|
| pm:btc-updown-5m-1792438800:updown_5m | 5 | +2503.28 | +1829.91 | 80% |  |
| pm:btc-updown-5m-1792439400:updown_5m | 2 | +3524.48 | +1303.00 | 50% |  |
| pm:btc-updown-5m-1792439700:updown_5m | 2 | +1239.14 | +674.42 | 100% |  |
| pm:btc-updown-5m-1792438500:updown_5m | 3 | +780.53 | +318.71 | 100% |  |
| BTCFDUSD | 5 | +0.73 | +0.73 | 80% |  |
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

orders submitted 24, filled 14 (partial 1), closed 44, open 0; dropped: {'maker_ttl_expired': 9, 'below_min_notional': 2, 'ioc_price_moved': 1}

closed trades 44: win rate 75%, net PnL $+26.76, fees $19.77, expectancy +131.01 bps / +0.33 R, gross +244.40 bps, entry slippage -13.42 bps, mean spread at entry 45.51 bps

exit reasons: locked=24, take_profit=9, adverse_stop=2, leg_risk=6, time_stop=3

| market | side | mode | hold s | entry | exit | gross bps | net bps | R | exit |
|---|---|---|---|---|---|---|---|---|---|
| ETHFDUSD>ETHUSDC | L | arb | 0.0 | 0 | 0 | +1.4 | +1.4 | +0.27 | locked |
| BTCFDUSD>BTCUSDC | L | arb | 0.0 | 0 | 0 | +1.4 | +1.4 | +0.28 | locked |
| BTCFDUSD>BTCUSDC | L | arb | 0.0 | 0 | 0 | +1.4 | +1.4 | +0.28 | locked |
| ETHFDUSD>ETHUSDC | L | arb | 0.0 | 0 | 0 | +1.7 | +1.7 | +0.34 | locked |
| BTCFDUSD>BTCUSDC | L | arb | 0.0 | 0 | 0 | +1.1 | +1.1 | +0.23 | locked |
| BTCFDUSD>BTCUSDC | L | arb | 0.0 | 0 | 0 | +1.5 | +1.5 | +0.30 | locked |
| BTCFDUSD>BTCUSDC | L | arb | 0.0 | 0 | 0 | +1.1 | +1.1 | +0.22 | locked |
| BTCFDUSD>BTCUSDC | L | arb | 0.0 | 0 | 0 | +1.1 | +1.1 | +0.22 | locked |
| ETHFDUSD>ETHUSDC | L | arb | 0.0 | 0 | 0 | +1.1 | +1.1 | +0.22 | locked |
| ETHUSDC>ETHFDUSD | L | arb | 0.0 | 0 | 0 | -0.0 | -0.0 | -0.01 | leg_risk |
| pm:btc-updown-5m-1792439700:updown_5m | L | taker | 4.9 | 0.62 | 0.67 | +806.5 | +290.8 | +0.88 | take_profit |
| ETHUSDC>ETHFDUSD | L | arb | 0.0 | 0 | 0 | +1.0 | +1.0 | +0.20 | locked |

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
 "tp_price": 0.6706176071647242,
 "stop_price": 0.585,
 "time_stop_s": 30.0,
 "maker_ttl_s": 3.0,
 "expected_net_bps": 800.4577350445763,
 "gap_bps": 1549.4122116817973,
 "t_signal": 6632.291695125,
 "t_prepared": 6632.291695125,
 "prep_latency_us": 962.4499998608371,
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

CEO state: **NORMAL**, reviews: 40, interventions: **34**

| t | state | verdict | signals | gross5 | net5 | false-gap | trades | exp bps | realization | reasons |
|---|---|---|---|---|---|---|---|---|---|---|
| 871s | NORMAL | GOOD | 245 | 140.75 | -238.553 | 40% | 22 | 194.323 | 0.672 |  |
| 901s | NORMAL | GOOD | 266 | 169.621 | -216.043 | 36% | 21 | 281.992 | 2.898 |  |
| 931s | NORMAL | GOOD | 256 | 150.975 | -223.045 | 36% | 22 | 269.267 | 2.898 |  |
| 961s | NORMAL | GOOD | 258 | 157.362 | -230.802 | 36% | 20 | 296.089 | 4.71 |  |
| 991s | NORMAL | GOOD | 332 | 120.289 | -212.89 | 46% | 22 | 269.086 | 4.705 |  |
| 1021s | NORMAL | GOOD | 216 | 125.017 | -344.197 | 50% | 20 | 103.715 | None |  |
| 1051s | NORMAL | GOOD | 216 | 125.017 | -344.197 | 50% | 19 | 149.202 | None |  |
| 1081s | NORMAL | GOOD | 216 | 125.017 | -344.197 | 50% | 23 | 123.509 | None |  |
| 1111s | NORMAL | GOOD | 216 | 125.017 | -344.197 | 50% | 24 | 118.41 | None |  |
| 1141s | NORMAL | GOOD | 223 | 123.332 | -354.658 | 50% | 24 | 118.428 | None |  |
| 1171s | NORMAL | GOOD | 223 | 123.332 | -354.658 | 50% | 26 | 109.401 | None |  |
| 1200s | NORMAL | GOOD | 211 | 121.598 | -328.714 | 51% | 30 | 104.577 | None |  |

audit trail:

```
#1 [19:39:49] QUARANTINE_MARKET      pm:bitcoin-up-or-down-october-19-2026-3pm-et:updown_1h NORMAL->NORMAL | negative_markouts: n=6 gross@1s=+256.65 gross@5s=+280.27 net@5s=-353.03bps hit=17%; blacklisted 600s | {} -> {'until': 6321.0}
#2 [19:39:49] QUARANTINE_MARKET      pm:btc-updown-15m-1792438200:updown_15m NORMAL->NORMAL | negative_markouts: n=7 gross@1s=+494.90 gross@5s=+623.32 net@5s=-53.89bps hit=29%; blacklisted 600s | {} -> {'until': 6321.0}
#3 [19:41:49] RETUNE_IMPULSE         hunter     NORMAL->NORMAL | false-gap 47% over 144 fresh signals, regime normal-vol (vol ratio 0.94) | {'z_thr': 3.0, 'window_mult': 2.0} -> {'z_thr': 3.0, 'window_mult': 2.25}
#4 [19:42:19] QUARANTINE_MARKET      hyperliquid:LINK NORMAL->NORMAL | negative_markouts: n=6 gross@1s=+0.98 gross@5s=+1.54 net@5s=-8.86bps hit=0%; blacklisted 600s | {} -> {'until': 6471.1}
#5 [19:42:19] RETUNE_IMPULSE         hunter     NORMAL->NORMAL | false-gap 45% over 251 fresh signals, regime normal-vol (vol ratio 1.08) | {'z_thr': 3.0, 'window_mult': 2.25} -> {'z_thr': 3.0, 'window_mult': 1.75}
#6 [19:42:49] RETUNE_IMPULSE         hunter     NORMAL->NORMAL | false-gap 44% over 264 fresh signals, regime normal-vol (vol ratio 1.05) | {'z_thr': 3.0, 'window_mult': 1.75} -> {'z_thr': 3.0, 'window_mult': 2.0}
#7 [19:44:19] QUARANTINE_MARKET      pm:bitcoin-price-on-october-21-2026:range-82000-84000 NORMAL->NORMAL | negative_markouts: n=7 gross@1s=+58.46 gross@5s=+156.33 net@5s=-1553.25bps hit=0%; blacklisted 600s | {} -> {'until': 6591.2}
#8 [19:45:50] QUARANTINE_MARKET      LINKUSDC   NORMAL->NORMAL | negative_markouts: n=6 gross@1s=+0.00 gross@5s=+0.21 net@5s=-15.98bps hit=0%; blacklisted 600s | {} -> {'until': 6681.3}
#9 [19:45:50] QUARANTINE_MARKET      LINKUSDT   NORMAL->NORMAL | negative_markouts: n=6 gross@1s=+0.28 gross@5s=+0.84 net@5s=-15.00bps hit=0%; blacklisted 600s | {} -> {'until': 6681.3}
#10 [19:45:50] QUARANTINE_MARKET      gate:LTC_USDT NORMAL->NORMAL | negative_markouts: n=6 gross@1s=+0.14 gross@5s=+0.56 net@5s=-41.95bps hit=0%; blacklisted 600s | {} -> {'until': 6681.3}
#11 [19:45:50] QUARANTINE_MARKET      hyperliquid:LTC NORMAL->NORMAL | negative_markouts: n=6 gross@1s=+1.43 gross@5s=+1.63 net@5s=-8.08bps hit=0%; blacklisted 600s | {} -> {'until': 6681.3}
#12 [19:45:50] QUARANTINE_MARKET      kraken:LINK/USD NORMAL->NORMAL | negative_markouts: n=6 gross@1s=+0.48 gross@5s=+0.13 net@5s=-81.45bps hit=0%; blacklisted 600s | {} -> {'until': 6681.3}
#13 [19:45:50] QUARANTINE_MARKET      hyperliquid:AVAX NORMAL->NORMAL | negative_markouts: n=6 gross@1s=+1.14 gross@5s=+1.95 net@5s=-7.90bps hit=0%; blacklisted 600s | {} -> {'until': 6681.3}
#14 [19:45:50] QUARANTINE_MARKET      hyperliquid:DOGE NORMAL->NORMAL | negative_markouts: n=6 gross@1s=+1.85 gross@5s=+2.00 net@5s=-7.23bps hit=0%; blacklisted 600s | {} -> {'until': 6681.3}
#15 [19:45:50] QUARANTINE_MARKET      coinbase:DOGE-USD NORMAL->NORMAL | negative_markouts: n=6 gross@1s=-0.42 gross@5s=-0.74 net@5s=-123.78bps hit=0%; blacklisted 600s | {} -> {'until': 6681.3}
#16 [19:45:50] QUARANTINE_MARKET      hyperliquid:SOL NORMAL->NORMAL | negative_markouts: n=6 gross@1s=+1.60 gross@5s=+1.76 net@5s=-8.20bps hit=0%; blacklisted 600s | {} -> {'until': 6681.3}
#17 [19:45:50] QUARANTINE_MARKET      kraken:SOL/USD NORMAL->NORMAL | negative_markouts: n=6 gross@1s=+0.08 gross@5s=+0.72 net@5s=-80.32bps hit=0%; blacklisted 600s | {} -> {'until': 6681.3}
#18 [19:45:50] QUARANTINE_MARKET      hyperliquid:ETH NORMAL->NORMAL | negative_markouts: n=6 gross@1s=+1.01 gross@5s=+1.56 net@5s=-7.96bps hit=0%; blacklisted 600s | {} -> {'until': 6681.3}
#19 [19:46:20] QUARANTINE_MARKET      pm:btc-updown-15m-1792439100:updown_15m NORMAL->NORMAL | negative_markouts: n=6 gross@1s=+379.70 gross@5s=+689.27 net@5s=-563.13bps hit=17%; blacklisted 600s | {} -> {'until': 6711.3}
#20 [19:46:50] QUARANTINE_MARKET      pm:bitcoin-price-on-october-21-2026:range-80000-82000 NORMAL->NORMAL | negative_markouts: n=6 gross@1s=-0.01 gross@5s=+113.22 net@5s=-1578.52bps hit=0%; blacklisted 600s | {} -> {'until': 6741.3}
#21 [19:48:20] RETUNE_IMPULSE         hunter     NORMAL->NORMAL | false-gap 36% over 288 fresh signals, regime normal-vol (vol ratio 0.91) | {'z_thr': 3.0, 'window_mult': 2.0} -> {'z_thr': 3.0, 'window_mult': 2.25}
#22 [19:49:20] RETUNE_IMPULSE         hunter     NORMAL->NORMAL | false-gap 33% over 239 fresh signals, regime normal-vol (vol ratio 0.94) | {'z_thr': 3.0, 'window_mult': 2.25} -> {'z_thr': 3.0, 'window_mult': 2.0}
#23 [19:49:50] RETUNE_IMPULSE         hunter     NORMAL->NORMAL | false-gap 40% over 245 fresh signals, regime normal-vol (vol ratio 0.92) | {'z_thr': 3.0, 'window_mult': 2.0} -> {'z_thr': 3.0, 'window_mult': 2.25}
#24 [19:50:20] RETUNE_IMPULSE         hunter     NORMAL->NORMAL | false-gap 36% over 266 fresh signals, regime normal-vol (vol ratio 1.23) | {'z_thr': 3.0, 'window_mult': 2.25} -> {'z_thr': 3.0, 'window_mult': 1.5}
#25 [19:50:50] QUARANTINE_MARKET      pm:bitcoin-up-or-down-october-19-2026-3pm-et:updown_1h NORMAL->NORMAL | negative_markouts: n=15 gross@1s=+516.42 gross@5s=+543.43 net@5s=-321.03bps hit=33%; blacklisted 1200s | {} -> {'until': 7581.5}
#26 [19:50:50] RETUNE_IMPULSE         hunter     NORMAL->NORMAL | false-gap 36% over 256 fresh signals, regime normal-vol (vol ratio 1.16) | {'z_thr': 3.0, 'window_mult': 1.5} -> {'z_thr': 3.0, 'window_mult': 1.75}
#27 [19:51:50] QUARANTINE_MARKET      AVAXUSDC   NORMAL->NORMAL | negative_markouts: n=7 gross@1s=+1.12 gross@5s=+1.57 net@5s=-16.35bps hit=0%; blacklisted 600s | {} -> {'until': 7041.6}
#28 [19:51:50] QUARANTINE_MARKET      XRPUSDC    NORMAL->NORMAL | negative_markouts: n=6 gross@1s=+0.13 gross@5s=-0.39 net@5s=-16.15bps hit=0%; blacklisted 600s | {} -> {'until': 7041.6}
#29 [19:51:50] QUARANTINE_MARKET      gate:SOL_USDT NORMAL->NORMAL | negative_markouts: n=6 gross@1s=-0.16 gross@5s=-0.64 net@5s=-41.60bps hit=0%; blacklisted 600s | {} -> {'until': 7041.6}
#30 [19:51:50] QUARANTINE_MARKET      hyperliquid:BTC NORMAL->NORMAL | negative_markouts: n=6 gross@1s=+1.20 gross@5s=+2.46 net@5s=-6.72bps hit=0%; blacklisted 600s | {} -> {'until': 7041.6}
#31 [19:52:50] RETUNE_IMPULSE         hunter     NORMAL->NORMAL | false-gap 50% over 216 fresh signals, regime normal-vol (vol ratio 1.07) | {'z_thr': 3.0, 'window_mult': 1.75} -> {'z_thr': 3.0, 'window_mult': 2.0}
#32 [19:54:20] QUARANTINE_MARKET      pm:bitcoin-price-on-october-21-2026:range-82000-84000 NORMAL->NORMAL | negative_markouts: n=11 gross@1s=+35.25 gross@5s=+112.01 net@5s=-1772.74bps hit=0%; blacklisted 1200s | {} -> {'until': 7791.8}
#33 [19:54:50] RETUNE_IMPULSE         hunter     NORMAL->NORMAL | false-gap 50% over 223 fresh signals, regime normal-vol (vol ratio 0.92) | {'z_thr': 3.0, 'window_mult': 2.0} -> {'z_thr': 3.0, 'window_mult': 2.25}
#34 [19:55:19] RETUNE_IMPULSE         hunter     NORMAL->NORMAL | false-gap 51% over 211 fresh signals, regime normal-vol (vol ratio 1.06) | {'z_thr': 3.0, 'window_mult': 2.25} -> {'z_thr': 3.0, 'window_mult': 2.0}
```

## 10. Caveats

* Quotes are timestamped at *our* gateway (cloud container → proxy → venue). Lead-lag below ~100 ms here is measured through that path; a co-located engine would see different lags.
* Paper fills use as-of quotes after an assumed order latency; maker fills require the market to trade *through* the resting price (no queue-position credit).
* Short sales are simulated (perp-style); on spot they would be unavailable.
