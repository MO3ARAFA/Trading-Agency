# Quant Agency — live telemetry report

* mode: **replay of live_tape_1.npz**  | duration: **899s**  | markets watched: **67** (61 Binance + 6 cross-venue)
* fees: taker 7.5 bps / maker 7.5 bps per side | assumed order latency 150 ms | capital $10,000 (paper)
* execution is **paper only** — no credentials, no live orders.

## 1. Feed health & internal latency

_(none)_

* hunter scan (all 66 markets, numba): n=78075  p50=0µs  p90=41µs  p99=192µs  max=334.65ms
* BTC quotes processed: 78075  | trades(agg): 4682  | book rejects: 0

## 2. BTC oracle (master reference)

BTCUSDT bid/ask 81918.96/81918.97, micro 81918.961, OBI -0.90, spread 0.001 bps, vol 0.28 bps/√s (slow 0.31, ratio 0.92), tick-vol 0.00

BTC impulses detected (|Z|≥4.25 at report time): **14**; hunter scans: 21766

## 3. Lead-lag map (Hayashi-Yoshida peak lag, Kalman β) — top markets by ρ

calibrated: 65/66 markets

| market | β (Kalman) | t(β) | ρ (3s, at lag) | HY ρ peak | HY ρ(0) | lag s | decay s | σ_res 3s bps | spread bps | tick Hz | regime |
|---|---|---|---|---|---|---|---|---|---|---|---|
| gate:BTC_USDT | 0.89 | 20.5 | 0.84 | 0.42 | 0.42 | 0.0 | 0.1 | 0.31 | 0.01 | 2.1 | normal |
| BNBUSDT | 0.69 | 14.9 | 0.75 | 0.05 | 0.04 | 0.4 | 0.0 | 0.36 | 0.14 | 5.6 | normal |
| gate:ETH_USDT | 1.19 | 13.7 | 0.72 | 0.32 | 0.32 | 0.0 | 0.0 | 0.63 | 0.04 | 4.0 | normal |
| LINKUSDT | 1.65 | 12.8 | 0.69 | 0.10 | 0.10 | 0.2 | 0.4 | 1.14 | 0.84 | 3.9 | normal |
| AVAXUSDT | 1.96 | 12.7 | 0.69 | 0.17 | 0.17 | 0.0 | 0.4 | 1.24 | 1.05 | 4.5 | normal |
| gate:SOL_USDT | 1.66 | 11.5 | 0.65 | 0.42 | 0.42 | 0.0 | 0.0 | 1.01 | 0.96 | 3.2 | normal |
| DOGEUSDT | 1.56 | 11.3 | 0.65 | 0.15 | 0.05 | 0.1 | 0.0 | 0.98 | 1.26 | 11.5 | normal |
| SOLUSDT | 1.63 | 11.1 | 0.64 | 0.11 | 0.10 | -0.2 | 0.3 | 0.95 | 0.96 | 38.0 | normal |
| UNIUSDT | 2.06 | 10.2 | 0.61 | 0.21 | 0.20 | -0.1 | 0.1 | 1.39 | 1.38 | 3.8 | normal |
| AAVEUSDT | 1.92 | 10.0 | 0.60 | 0.28 | 0.20 | -0.1 | 0.1 | 1.35 | 0.68 | 1.5 | normal |
| SUIUSDT | 2.06 | 9.9 | 0.60 | 0.31 | 0.21 | -0.2 | 0.2 | 1.39 | 1.01 | 58.6 | normal |
| XRPUSDT | 1.49 | 9.9 | 0.60 | 0.10 | 0.10 | -0.2 | 0.4 | 0.98 | 0.77 | 5.0 | normal |
| NEARUSDT | 3.32 | 9.7 | 0.59 | 0.08 | 0.08 | 0.0 | 0.0 | 2.81 | 2.02 | 22.2 | normal |
| HBARUSDT | 1.82 | 9.5 | 0.58 | 0.19 | 0.16 | -0.1 | 0.3 | 1.63 | 1.21 | 6.0 | normal |
| HYPEUSDT | 1.56 | 9.4 | 0.58 | 0.41 | 0.20 | -0.3 | 0.2 | 1.23 | 1.28 | 1.6 | normal |

## 4. Detected micro-gaps (hunter signals): **243**

per market (top 10): XLMUSDT:8, LTCUSDT:7, APTUSDT:7, SEIUSDT:7, ENAUSDT:7, kraken:SOL/USD:7, ADAUSDT:6, FILUSDT:6, TAOUSDT:6, PENGUUSDT:6

| t | market | side | BTC Δ | Z | β | lag | gap bps | gap Z | spread | CFO | pred net | gross@1s | gross@5s | net@5s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
|  598.6s | TAOUSDT | BUY | +2.2@1s | 7.7 | 2.28 | 0.0 | +8.8 | 6.3 | 3.8 | net_edge_below_hurdle | -11.6 | -3.8 | -3.8 | -22.5 |
|  238.0s | STRKUSDT | BUY | +1.8@3s | 3.4 | 3.39 | 0.0 | +8.7 | 2.2 | 3.5 | net_edge_below_hurdle | -11.4 | +2.6 | -2.6 | -21.9 |
|  598.6s | NEARUSDT | BUY | +2.2@1s | 7.7 | 3.86 | -0.5 | +8.5 | 4.4 | 2.0 | net_edge_below_hurdle | -10.0 | +0.0 | -6.1 | -23.1 |
|  386.3s | SANDUSDT | SELL | -1.8@1s | -4.9 | 2.01 | -0.2 | -8.0 | 4.8 | 6.8 | net_edge_below_hurdle | -15.9 | -0.0 | -0.0 | -21.8 |
|  598.6s | ONDOUSDT | BUY | +2.2@1s | 7.7 | 2.17 | -0.2 | +7.1 | 6.1 | 2.3 | net_edge_below_hurdle | -11.6 | +0.0 | -2.3 | -19.7 |
|  268.2s | MARSCOINUSDT | BUY | +3.2@1s | 9.7 | 2.21 | -0.5 | +7.1 | 3.0 | 13.1 | net_edge_below_hurdle | -23.9 | +0.0 | +0.0 | -28.1 |
|   80.4s | ZROUSDT | BUY | +1.5@1s | 7.2 | 2.73 | 2.4 | +6.9 | 2.7 | 10.6 | net_edge_below_hurdle | -12.0 | +0.0 | +0.0 | -20.3 |
|  598.6s | SEIUSDT | BUY | +2.2@1s | 7.7 | 2.67 | -0.1 | +5.9 | 4.2 | 1.7 | net_edge_below_hurdle | -12.2 | +0.0 | -5.0 | -21.7 |
|  377.0s | ZROUSDT | SELL | -2.7@1s | -8.2 | 2.18 | -0.2 | -5.9 | 2.1 | 5.3 | net_edge_below_hurdle | -16.3 | +5.3 | +5.3 | -15.0 |
|  598.6s | SANDUSDT | BUY | +2.2@1s | 7.7 | 1.11 | -0.1 | +5.8 | 4.6 | 3.4 | net_edge_below_hurdle | -14.1 | -0.9 | -2.6 | -20.1 |
|  377.5s | PUMPUSDT | SELL | -2.7@1s | -7.4 | 3.01 | -0.3 | -5.8 | 1.7 | 2.3 | net_edge_below_hurdle | -13.1 | -0.0 | -4.6 | -21.9 |
|  138.1s | APTUSDT | BUY | +2.7@5s | 3.4 | 3.09 | 1.2 | +5.8 | 1.6 | 1.3 | net_edge_below_hurdle | -10.7 | -2.6 | -2.6 | -19.0 |
|   80.4s | APTUSDT | BUY | +1.5@1s | 7.2 | 3.69 | 0.1 | +5.7 | 3.2 | 1.3 | net_edge_below_hurdle | -11.9 | +0.0 | +2.6 | -13.7 |
|  386.3s | MARSCOINUSDT | SELL | -1.8@1s | -4.9 | 3.08 | 0.0 | -5.7 | 2.3 | 13.2 | net_edge_below_hurdle | -25.4 | -0.0 | -0.0 | -28.2 |

## 5. CFO gating & accounting

evaluated 243, approved 0; reasons: net_edge_below_hurdle=238, quarantined=5

equity $10,000.00 (peak $10,000.00, drawdown 0.000%), closed PnL $+0.00, fees $0.00; hurdle 1.00 bps, edge-credit 1.00, mode auto, size×1.00, halted=False (-), quarantined=['PENGUUSDT', 'ASTERUSDT', 'XLMUSDT', 'APTUSDT', 'ADAUSDT', 'TAOUSDT', 'kraken:SOL/USD', 'ENAUSDT', 'SEIUSDT', 'TRUMPUSDT']

## 6. Realised markout curves (t+1s … t+30s)

**All detected gaps (incl. CFO-rejected shadow cohort)** — does the gap actually close?

| horizon | n | gross bps | net bps (taker, after spread+fees) | net s.e. | hit gross | hit net | gap closure |
|---|---|---|---|---|---|---|---|
| t+1s | 243 | +0.23 | -17.03 | 0.31 | 21% | 0% | 0.34 |
| t+3s | 243 | +0.68 | -16.59 | 0.30 | 40% | 0% | 0.50 |
| t+5s | 243 | +0.60 | -16.67 | 0.49 | 43% | 0% | 0.53 |
| t+10s | 243 | +0.54 | -16.72 | 0.99 | 43% | 0% | 0.46 |
| t+30s | 243 | +1.06 | -16.21 | 1.61 | 56% | 3% | 0.51 |

**CFO-approved cohort**

| horizon | n | gross bps | net bps (taker, after spread+fees) | net s.e. | hit gross | hit net | gap closure |
|---|---|---|---|---|---|---|---|
| t+1s | 0 | +0.00 | +0.00 | 0.00 | 0% | 0% | 0.00 |
| t+3s | 0 | +0.00 | +0.00 | 0.00 | 0% | 0% | 0.00 |
| t+5s | 0 | +0.00 | +0.00 | 0.00 | 0% | 0% | 0.00 |
| t+10s | 0 | +0.00 | +0.00 | 0.00 | 0% | 0% | 0.00 |
| t+30s | 0 | +0.00 | +0.00 | 0.00 | 0% | 0% | 0.00 |

**CFO-rejected: net edge below hurdle**

| horizon | n | gross bps | net bps (taker, after spread+fees) | net s.e. | hit gross | hit net | gap closure |
|---|---|---|---|---|---|---|---|
| t+1s | 238 | +0.21 | -17.02 | 0.31 | 21% | 0% | 0.33 |
| t+3s | 238 | +0.68 | -16.56 | 0.30 | 41% | 0% | 0.49 |
| t+5s | 238 | +0.60 | -16.63 | 0.48 | 44% | 0% | 0.53 |
| t+10s | 238 | +0.55 | -16.68 | 0.99 | 44% | 0% | 0.46 |
| t+30s | 238 | +1.18 | -16.05 | 1.60 | 57% | 3% | 0.54 |

_gross = mid→mid after fill (latency-adjusted entry); net = cross the spread on entry and exit + round-trip taker fees; gap closure = share of the signalled gap that has closed._

## 7. Per-market profitability @ t+5s

| market | n | gross bps | net bps | hit net | status |
|---|---|---|---|---|---|
| ETHUSDT | 3 | +1.38 | -13.67 | 0% |  |
| kraken:BTC/USD | 5 | +1.33 | -13.70 | 0% |  |
| SUIUSDT | 5 | +2.03 | -13.98 | 0% |  |
| gate:ETH_USDT | 5 | +0.68 | -14.37 | 0% |  |
| BNBUSDT | 4 | +0.76 | -14.38 | 0% |  |
| LINKUSDT | 5 | +1.35 | -14.50 | 0% |  |
| gate:BTC_USDT | 4 | +0.52 | -14.50 | 0% |  |
| kraken:ETH/USD | 5 | +0.55 | -14.51 | 0% |  |
| UNIUSDT | 6 | +1.38 | -15.00 | 0% |  |
| TIAUSDT | 4 | +2.07 | -15.00 | 0% |  |

worst:

| market | n | gross bps | net bps | hit net | status |
|---|---|---|---|---|---|
| FETUSDT | 4 | +0.00 | -20.34 | 0% |  |
| ENAUSDT | 7 | -0.77 | -21.15 | 0% | QUARANTINED |
| OPUSDT | 2 | +0.00 | -23.08 | 0% |  |
| ARBUSDT | 2 | -5.15 | -25.30 | 0% |  |
| MARSCOINUSDT | 2 | +0.00 | -28.16 | 0% |  |

## 8. Paper execution

orders submitted 0, filled 0 (partial 0), closed 0, open 0; dropped: {}

## 9. CEO → CFO/Hunter interventions

CEO state: **NORMAL**, reviews: 30, interventions: **20**

| t | state | verdict | signals | gross5 | net5 | false-gap | trades | exp bps | realization | reasons |
|---|---|---|---|---|---|---|---|---|---|---|
| 571s | NORMAL | OK | 25 | -0.136 | -17.403 | 80% | 0 | 0.0 | None |  |
| 601s | NORMAL | OK | 0 | 0.0 | 0.0 | 0% | 0 | 0.0 | None |  |
| 631s | NORMAL | OK | 42 | -2.122 | -19.065 | 93% | 0 | 0.0 | None |  |
| 661s | NORMAL | OK | 0 | 0.0 | 0.0 | 0% | 0 | 0.0 | None |  |
| 691s | NORMAL | OK | 0 | 0.0 | 0.0 | 0% | 0 | 0.0 | None |  |
| 721s | NORMAL | OK | 12 | 0.104 | -19.448 | 67% | 0 | 0.0 | None |  |
| 751s | NORMAL | OK | 0 | 0.0 | 0.0 | 0% | 0 | 0.0 | None |  |
| 781s | NORMAL | OK | 0 | 0.0 | 0.0 | 0% | 0 | 0.0 | None |  |
| 811s | NORMAL | OK | 0 | 0.0 | 0.0 | 0% | 0 | 0.0 | None |  |
| 841s | NORMAL | OK | 0 | 0.0 | 0.0 | 0% | 0 | 0.0 | None |  |
| 871s | NORMAL | OK | 24 | -0.206 | -17.144 | 79% | 0 | 0.0 | None |  |
| 899s | NORMAL | OK | 0 | 0.0 | 0.0 | 0% | 0 | 0.0 | None |  |

audit trail:

```
#1 [19:08:18] RETUNE_IMPULSE         hunter     NORMAL->NORMAL | false-gap 58% over 12 signals, regime normal-vol (vol ratio 1.00) | {'z_thr': 3.0, 'window_mult': 2.0} -> {'z_thr': 3.25, 'window_mult': 2.0}
#2 [19:11:18] RETUNE_IMPULSE         hunter     NORMAL->NORMAL | false-gap 71% over 14 signals, regime normal-vol (vol ratio 1.06) | {'z_thr': 3.25, 'window_mult': 2.0} -> {'z_thr': 3.5, 'window_mult': 2.0}
#3 [19:13:18] RETUNE_IMPULSE         hunter     NORMAL->NORMAL | false-gap 34% over 41 signals, regime normal-vol (vol ratio 1.12) | {'z_thr': 3.5, 'window_mult': 2.0} -> {'z_thr': 3.5, 'window_mult': 1.75}
#4 [19:13:49] RETUNE_IMPULSE         hunter     NORMAL->NORMAL | false-gap 21% over 80 signals, regime normal-vol (vol ratio 1.07) | {'z_thr': 3.5, 'window_mult': 1.75} -> {'z_thr': 3.25, 'window_mult': 1.75}
#5 [19:14:19] RETUNE_IMPULSE         hunter     NORMAL->NORMAL | false-gap 0% over 0 signals, regime normal-vol (vol ratio 1.05) | {'z_thr': 3.25, 'window_mult': 1.75} -> {'z_thr': 3.25, 'window_mult': 2.0}
#6 [19:16:19] RETUNE_IMPULSE         hunter     NORMAL->NORMAL | false-gap 80% over 25 signals, regime normal-vol (vol ratio 0.97) | {'z_thr': 3.25, 'window_mult': 2.0} -> {'z_thr': 3.5, 'window_mult': 2.0}
#7 [19:17:19] QUARANTINE_MARKET      PENGUUSDT  NORMAL->NORMAL | negative_markouts: n=6 gross@1s=-0.34 gross@5s=-0.78 net@5s=-17.23bps hit=0%; blacklisted 600s | {} -> {'until': 2665.5}
#8 [19:17:19] QUARANTINE_MARKET      ASTERUSDT  NORMAL->NORMAL | negative_markouts: n=6 gross@1s=+0.71 gross@5s=+1.19 net@5s=-15.24bps hit=0%; blacklisted 600s | {} -> {'until': 2665.5}
#9 [19:17:19] QUARANTINE_MARKET      XLMUSDT    NORMAL->NORMAL | negative_markouts: n=6 gross@1s=+0.00 gross@5s=+0.95 net@5s=-19.74bps hit=0%; blacklisted 600s | {} -> {'until': 2665.5}
#10 [19:17:19] QUARANTINE_MARKET      APTUSDT    NORMAL->NORMAL | negative_markouts: n=6 gross@1s=-0.44 gross@5s=+0.22 net@5s=-16.10bps hit=0%; blacklisted 600s | {} -> {'until': 2665.5}
#11 [19:17:19] QUARANTINE_MARKET      ADAUSDT    NORMAL->NORMAL | negative_markouts: n=6 gross@1s=+0.00 gross@5s=+1.54 net@5s=-18.08bps hit=0%; blacklisted 600s | {} -> {'until': 2665.5}
#12 [19:17:19] QUARANTINE_MARKET      TAOUSDT    NORMAL->NORMAL | negative_markouts: n=6 gross@1s=+0.00 gross@5s=+1.26 net@5s=-17.51bps hit=0%; blacklisted 600s | {} -> {'until': 2665.5}
#13 [19:17:19] RETUNE_IMPULSE         hunter     NORMAL->NORMAL | false-gap 93% over 42 signals, regime normal-vol (vol ratio 1.00) | {'z_thr': 3.5, 'window_mult': 2.0} -> {'z_thr': 3.75, 'window_mult': 2.0}
#14 [19:18:49] QUARANTINE_MARKET      kraken:SOL/USD NORMAL->NORMAL | negative_markouts: n=6 gross@1s=+0.24 gross@5s=+0.40 net@5s=-15.96bps hit=0%; blacklisted 600s | {} -> {'until': 2755.6}
#15 [19:18:49] QUARANTINE_MARKET      ENAUSDT    NORMAL->NORMAL | negative_markouts: n=6 gross@1s=+0.90 gross@5s=-0.89 net@5s=-21.28bps hit=0%; blacklisted 600s | {} -> {'until': 2755.6}
#16 [19:18:49] RETUNE_IMPULSE         hunter     NORMAL->NORMAL | false-gap 67% over 12 signals, regime normal-vol (vol ratio 0.98) | {'z_thr': 3.75, 'window_mult': 2.0} -> {'z_thr': 4.0, 'window_mult': 2.0}
#17 [19:19:19] RETUNE_IMPULSE         hunter     NORMAL->NORMAL | false-gap 0% over 0 signals, regime normal-vol (vol ratio 0.94) | {'z_thr': 4.0, 'window_mult': 2.0} -> {'z_thr': 4.0, 'window_mult': 2.25}
#18 [19:21:19] QUARANTINE_MARKET      SEIUSDT    NORMAL->NORMAL | negative_markouts: n=6 gross@1s=+0.28 gross@5s=+0.00 net@5s=-16.67bps hit=0%; blacklisted 600s | {} -> {'until': 2905.7}
#19 [19:21:19] QUARANTINE_MARKET      TRUMPUSDT  NORMAL->NORMAL | negative_markouts: n=6 gross@1s=+0.98 gross@5s=+1.96 net@5s=-18.92bps hit=0%; blacklisted 600s | {} -> {'until': 2905.7}
#20 [19:21:19] RETUNE_IMPULSE         hunter     NORMAL->NORMAL | false-gap 79% over 24 signals, regime normal-vol (vol ratio 0.89) | {'z_thr': 4.0, 'window_mult': 2.25} -> {'z_thr': 4.25, 'window_mult': 2.25}
```

## 10. Caveats

* Quotes are timestamped at *our* gateway (cloud container → proxy → venue). Lead-lag below ~100 ms here is measured through that path; a co-located engine would see different lags.
* Paper fills use as-of quotes after an assumed order latency; maker fills require the market to trade *through* the resting price (no queue-position credit).
* Short sales are simulated (perp-style); on spot they would be unavailable.
