> **Note:** this live run executed *before* the CEO evidence-gating fix (it re-raised `z_thr` on stale signals up to 5.0). Kept as recorded; see replayA_* for the same tape through the final code.

# Quant Agency — live telemetry report

* mode: **live**  | duration: **1200s**  | markets watched: **67** (61 Binance + 6 cross-venue)
* fees: taker 1.0 bps / maker 1.0 bps per side | assumed order latency 150 ms | capital $10,000 (paper)
* execution is **paper only** — no credentials, no live orders.

## 1. Feed health & internal latency

| feed | msgs | quotes | rate | reconnects | errors | up | last error |
|---|---|---|---|---|---|---|---|
| binance | 944331 | 939373 | 787/s | 0 | 0 | yes | - |
| gate | 13280 | 13278 | 11/s | 1 | 1 | yes | ConnectionClosedError: no close frame received or sent |
| kraken | 28911 | 27710 | 24/s | 0 | 0 | yes | - |

* hunter scan (all 66 markets, numba): n=98800  p50=1µs  p90=184µs  p99=512µs  max=19.20ms
* BTC tick received → CFO-approved executable payload ready: n=7  p50=619µs  p90=1044µs  p99=1242µs  max=1.26ms
* BTC quotes processed: 98800  | trades(agg): 4958  | book rejects: 0

## 2. BTC oracle (master reference)

BTCUSDT bid/ask 81964.00/81964.01, micro 81964.003, OBI -0.31, spread 0.001 bps, vol 0.25 bps/√s (slow 0.24, ratio 1.04), tick-vol 0.00

BTC impulses detected (|Z|≥3.00 at report time): **12**; hunter scans: 32003

## 3. Lead-lag map (Hayashi-Yoshida peak lag, Kalman β) — top markets by ρ

calibrated: 64/66 markets

| market | β (Kalman) | t(β) | ρ (3s, at lag) | HY ρ peak | HY ρ(0) | lag s | decay s | σ_res 3s bps | spread bps | tick Hz | regime |
|---|---|---|---|---|---|---|---|---|---|---|---|
| kraken:BTC/USD | 0.98 | 17.9 | 0.80 | 0.06 | 0.01 | 0.1 | 0.0 | 0.41 | 0.01 | 8.7 | tight |
| gate:BTC_USDT | 0.94 | 17.7 | 0.80 | 0.72 | 0.72 | 0.0 | 0.0 | 0.42 | 0.01 | 4.7 | normal |
| SOLUSDT | 1.79 | 13.5 | 0.71 | 0.08 | 0.04 | -0.1 | 0.1 | 0.95 | 0.96 | 21.1 | normal |
| ETHUSDT | 1.36 | 7.6 | 0.69 | 0.03 | 0.01 | -0.3 | 0.2 | 0.71 | 0.04 | 28.0 | normal |
| XRPUSDT | 1.71 | 12.5 | 0.68 | 0.18 | 0.18 | 0.0 | 0.0 | 0.85 | 0.77 | 26.1 | normal |
| PENGUUSDT | 2.72 | 11.1 | 0.64 | 0.37 | 0.21 | -0.2 | 0.2 | 1.61 | 2.67 | 15.7 | normal |
| gate:ETH_USDT | 1.58 | 11.1 | 0.64 | 0.27 | 0.27 | 0.0 | 0.2 | 0.81 | 0.04 | 9.1 | normal |
| AVAXUSDT | 2.06 | 10.1 | 0.60 | 0.31 | 0.16 | -0.3 | 0.3 | 1.28 | 1.05 | 7.8 | normal |
| gate:SOL_USDT | 1.82 | 9.9 | 0.60 | 0.40 | 0.40 | 0.0 | 0.0 | 1.07 | 0.96 | 3.2 | normal |
| kraken:ETH/USD | 1.35 | 9.3 | 0.57 | 0.09 | 0.07 | -0.1 | 0.1 | 0.84 | 0.04 | 23.2 | normal |
| HYPEUSDT | 1.44 | 9.1 | 0.57 | 0.19 | 0.19 | 0.0 | 0.1 | 1.06 | 1.28 | 9.0 | normal |
| kraken:SOL/USD | 1.76 | 9.0 | 0.56 | 0.22 | 0.06 | -0.4 | 0.3 | 1.25 | 0.96 | 9.4 | normal |
| SUIUSDT | 2.30 | 8.7 | 0.55 | 0.21 | 0.11 | -0.2 | 0.2 | 1.46 | 1.01 | 54.8 | normal |
| ADAUSDT | 1.91 | 8.4 | 0.54 | 0.34 | 0.06 | -0.5 | 0.3 | 1.74 | 4.60 | 7.7 | normal |
| PYTHUSDT | 2.97 | 8.3 | 0.53 | 0.19 | 0.18 | -0.2 | 0.8 | 2.44 | 1.37 | 7.5 | normal |

## 4. Detected micro-gaps (hunter signals): **155**

per market (top 10): kraken:ETH/USD:6, HYPEUSDT:5, ONDOUSDT:5, HBARUSDT:5, kraken:SOL/USD:5, gate:ETH_USDT:5, ETHUSDT:5, TRUMPUSDT:4, UNIUSDT:4, SANDUSDT:4

| t | market | side | BTC Δ | Z | β | lag | gap bps | gap Z | spread | CFO | pred net | gross@1s | gross@5s | net@5s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
|  282.3s | NILUSDT | BUY | +2.4@1s | 12.2 | 3.92 | -0.4 | +9.0 | 1.5 | 5.7 | net_edge_below_hurdle | -1.0 | +8.5 | +9.1 | +2.5 |
|  344.4s | NILUSDT | SELL | -1.6@1s | -6.8 | 3.86 | 0.9 | -8.0 | 1.6 | 6.8 | ok (maker) | +2.8 | -2.3 | +8.5 | +1.4 |
|  282.5s | DOTUSDT | BUY | +3.1@1s | 14.3 | 2.58 | -0.5 | +7.9 | 3.3 | 8.8 | net_edge_below_hurdle | -5.1 | +0.0 | +0.0 | -10.7 |
|  112.6s | MARSCOINUSDT | BUY | +1.7@3s | 3.8 | 3.98 | -0.1 | +6.8 | 2.5 | 13.1 | net_edge_below_hurdle | -11.1 | +0.0 | +0.0 | -15.1 |
| 1171.3s | STRKUSDT | SELL | -1.7@1s | -7.4 | 3.70 | -0.5 | -6.4 | 2.3 | 1.7 | ok (taker) | +1.2 | -0.0 | +8.6 | +4.9 |
| 1171.4s | ZROUSDT | SELL | -1.7@1s | -7.4 | 3.59 | 0.5 | -6.3 | 1.8 | 5.3 | net_edge_below_hurdle | -3.0 | -0.0 | -10.5 | -17.8 |
|   51.9s | ENAUSDT | SELL | -1.5@1s | -6.6 | 4.00 | 0.0 | -6.1 | 2.6 | 5.4 | net_edge_below_hurdle | -3.2 | -0.0 | +5.4 | -2.0 |
|   51.9s | MARSCOINUSDT | SELL | -1.5@1s | -6.6 | 4.00 | -0.5 | -6.1 | 2.4 | 13.1 | net_edge_below_hurdle | -11.9 | -0.0 | -0.0 | -15.1 |
|  112.6s | ENAUSDT | BUY | +1.7@3s | 3.8 | 3.43 | 0.0 | +5.8 | 2.2 | 5.4 | net_edge_below_hurdle | -3.3 | +0.0 | +5.4 | -2.0 |
|  344.4s | MARSCOINUSDT | SELL | -1.5@1s | -6.4 | 3.30 | 0.0 | -5.1 | 3.1 | 13.1 | net_edge_below_hurdle | -12.8 | -0.0 | -0.0 | -15.1 |
|  282.7s | QNTUSDT | BUY | +2.8@1s | 11.9 | 3.18 | 0.0 | +4.9 | 3.2 | 1.5 | size_below_min | +0.1 | -1.0 | -1.3 | -5.1 |
|  924.4s | ONDOUSDT | SELL | -1.5@5s | -2.5 | 1.57 | 2.1 | -4.6 | 2.1 | 2.3 | ok (maker) | +0.9 | -0.0 | -0.0 | -4.3 |
|  345.8s | ONDOUSDT | SELL | -2.6@1s | -9.7 | 2.20 | 0.3 | -4.6 | 4.9 | 4.6 | net_edge_below_hurdle | -3.7 | -0.0 | -0.0 | -4.3 |
| 1171.3s | CRVUSDT | SELL | -1.7@1s | -7.4 | 2.68 | -0.3 | -4.6 | 2.3 | 2.7 | net_edge_below_hurdle | -1.7 | -0.0 | -0.0 | -4.7 |

## 5. CFO gating & accounting

evaluated 155, approved 7; reasons: net_edge_below_hurdle=145, ok=7, size_below_min=3

equity $10,000.02 (peak $10,000.02, drawdown 0.000%), closed PnL $+0.02, fees $0.01; hurdle 1.00 bps, edge-credit 1.00, mode auto, size×1.00, halted=False (-), quarantined=-

## 6. Realised markout curves (t+1s … t+30s)

**All detected gaps (incl. CFO-rejected shadow cohort)** — does the gap actually close?

| horizon | n | gross bps | net bps (taker, after spread+fees) | net s.e. | hit gross | hit net | gap closure |
|---|---|---|---|---|---|---|---|
| t+1s | 155 | +0.36 | -3.94 | 0.34 | 26% | 1% | 0.43 |
| t+3s | 155 | +0.94 | -3.37 | 0.33 | 52% | 6% | 0.67 |
| t+5s | 155 | +0.96 | -3.33 | 0.46 | 52% | 9% | 0.65 |
| t+10s | 155 | -0.04 | -4.36 | 0.52 | 41% | 6% | 0.23 |
| t+30s | 119 | +0.52 | -3.84 | 1.03 | 54% | 24% | 0.38 |

**CFO-approved cohort**

| horizon | n | gross bps | net bps (taker, after spread+fees) | net s.e. | hit gross | hit net | gap closure |
|---|---|---|---|---|---|---|---|
| t+1s | 7 | +0.13 | -3.87 | 0.63 | 29% | 0% | 0.11 |
| t+3s | 7 | +0.13 | -3.71 | 0.59 | 29% | 0% | 0.11 |
| t+5s | 7 | +3.22 | -0.70 | 1.59 | 57% | 43% | 0.57 |
| t+10s | 7 | +1.44 | -2.68 | 1.62 | 57% | 14% | 0.25 |
| t+30s | 6 | +0.01 | -3.84 | 2.36 | 33% | 17% | -0.03 |

**CFO-rejected: net edge below hurdle**

| horizon | n | gross bps | net bps (taker, after spread+fees) | net s.e. | hit gross | hit net | gap closure |
|---|---|---|---|---|---|---|---|
| t+1s | 145 | +0.38 | -3.97 | 0.43 | 26% | 1% | 0.45 |
| t+3s | 145 | +1.00 | -3.35 | 0.36 | 54% | 7% | 0.71 |
| t+5s | 145 | +0.91 | -3.43 | 0.49 | 53% | 8% | 0.68 |
| t+10s | 145 | -0.05 | -4.41 | 0.55 | 41% | 6% | 0.25 |
| t+30s | 111 | +0.57 | -3.85 | 1.02 | 55% | 25% | 0.41 |

_gross = mid→mid after fill (latency-adjusted entry); net = cross the spread on entry and exit + round-trip taker fees; gap closure = share of the signalled gap that has closed._

## 7. Per-market profitability @ t+5s

| market | n | gross bps | net bps | hit net | status |
|---|---|---|---|---|---|
| STRKUSDT | 1 | +8.57 | +4.86 | 100% |  |
| NILUSDT | 2 | +8.82 | +1.98 | 100% |  |
| ICPUSDT | 1 | +7.04 | +1.52 | 100% |  |
| CRVUSDT | 4 | +5.12 | +0.05 | 25% |  |
| gate:BTC_USDT | 3 | +1.33 | -0.68 | 33% |  |
| kraken:BTC/USD | 4 | +1.12 | -0.92 | 0% |  |
| LINKUSDT | 4 | +1.68 | -1.16 | 25% |  |
| gate:ETH_USDT | 5 | +0.81 | -1.23 | 20% |  |
| MUBUSDT | 2 | +2.01 | -1.28 | 50% |  |
| kraken:ETH/USD | 6 | +0.84 | -1.49 | 17% |  |

worst:

| market | n | gross bps | net bps | hit net | status |
|---|---|---|---|---|---|
| TRUMPUSDT | 4 | +0.00 | -7.86 | 0% |  |
| GRAMUSDT | 1 | +0.00 | -9.40 | 0% |  |
| DOTUSDT | 3 | +0.00 | -10.76 | 0% |  |
| MARSCOINUSDT | 3 | +0.00 | -15.09 | 0% |  |
| ZROUSDT | 1 | -10.50 | -17.76 | 0% |  |

## 8. Paper execution

orders submitted 7, filled 1 (partial 0), closed 1, open 0; dropped: {'maker_ttl_expired': 4, 'post_only_would_cross': 1, 'ioc_no_liquidity': 1}

closed trades 1: win rate 100%, net PnL $+0.02, fees $0.01, expectancy +3.15 bps / +0.58 R, gross +5.14 bps, entry slippage +0.00 bps, mean spread at entry 1.71 bps

exit reasons: take_profit=1

| market | side | mode | hold s | entry | exit | gross bps | net bps | R | exit |
|---|---|---|---|---|---|---|---|---|---|
| STRKUSDT | S | taker | 3.9 | 0.05831 | 0.05828 | +5.1 | +3.1 | +0.58 | take_profit |

sample prepared payload (never transmitted):

```json
{
 "oid": 7,
 "sid": 136,
 "market": "STRKUSDT",
 "symbol": "STRKUSDT",
 "venue": "binance",
 "side": "SELL",
 "order_type": "LIMIT",
 "time_in_force": "IOC",
 "price": 0.058300000000000005,
 "qty": 1091.43,
 "notional": 63.63036900000001,
 "mode": "taker",
 "tp_price": 0.058289029058404135,
 "stop_price": 0.05834666446229582,
 "time_stop_s": 10.0,
 "maker_ttl_s": 3.0,
 "expected_net_bps": 1.1701785042818598,
 "gap_bps": -6.362230152952803,
 "t_signal": 3654.833272597,
 "t_prepared": 3654.833272597,
 "prep_latency_us": 1264.4680000448716,
 "sig_quote_px": 0.05831,
 "sig_mid": 0.058315,
 "beta": 3.7037453057980807,
 "stop_bps": 5.42990007645003,
 "exchange_params": {
  "symbol": "STRKUSDT",
  "side": "SELL",
  "type": "LIMIT",
  "quantity": "1091.43",
  "price": "0.0583",
  "newClientOrderId": "qa7",
  "timeInForce": "IOC"
 }
}
```

## 9. CEO → CFO/Hunter interventions

CEO state: **NORMAL**, reviews: 40, interventions: **9**

| t | state | verdict | signals | gross5 | net5 | false-gap | trades | exp bps | realization | reasons |
|---|---|---|---|---|---|---|---|---|---|---|
| 871s | NORMAL | OK | 56 | 1.629 | -2.808 | 41% | 0 | 0.0 | None |  |
| 901s | NORMAL | OK | 24 | 1.795 | -3.215 | 46% | 0 | 0.0 | None |  |
| 931s | NORMAL | OK | 39 | 1.299 | -2.881 | 46% | 0 | 0.0 | None |  |
| 961s | NORMAL | OK | 39 | 1.429 | -1.869 | 26% | 0 | 0.0 | None |  |
| 991s | NORMAL | OK | 39 | 1.429 | -1.869 | 26% | 0 | 0.0 | None |  |
| 1021s | NORMAL | OK | 44 | 1.64 | -1.898 | 25% | 0 | 0.0 | None |  |
| 1051s | NORMAL | OK | 44 | 1.64 | -1.898 | 25% | 0 | 0.0 | None |  |
| 1081s | NORMAL | OK | 44 | 1.64 | -1.898 | 25% | 0 | 0.0 | None |  |
| 1111s | NORMAL | OK | 44 | 1.64 | -1.898 | 25% | 0 | 0.0 | None |  |
| 1141s | NORMAL | OK | 44 | 1.64 | -1.898 | 25% | 0 | 0.0 | None |  |
| 1171s | NORMAL | OK | 44 | 1.64 | -1.898 | 25% | 0 | 0.0 | None |  |
| 1200s | NORMAL | OK | 80 | 0.336 | -3.457 | 55% | 1 | 3.145 | -0.687 |  |

audit trail:

```
#1 [18:50:52] RETUNE_IMPULSE         hunter     NORMAL->NORMAL | false-gap 38% over 52 signals, regime normal-vol (vol ratio 1.08) | {'z_thr': 3.0, 'window_mult': 2.0} -> {'z_thr': 3.0, 'window_mult': 1.847}
#2 [18:54:22] RETUNE_IMPULSE         hunter     NORMAL->NORMAL | false-gap 40% over 75 signals, regime normal-vol (vol ratio 0.96) | {'z_thr': 3.0, 'window_mult': 1.8465076568037677} -> {'z_thr': 3.0, 'window_mult': 2.082}
#3 [18:55:22] RETUNE_IMPULSE         hunter     NORMAL->NORMAL | false-gap 40% over 75 signals, regime normal-vol (vol ratio 0.88) | {'z_thr': 3.0, 'window_mult': 2.081970424039258} -> {'z_thr': 3.0, 'window_mult': 2.262}
#4 [18:56:52] RETUNE_IMPULSE         hunter     NORMAL->NORMAL | false-gap 42% over 62 signals, regime normal-vol (vol ratio 0.82) | {'z_thr': 3.0, 'window_mult': 2.2621609612579854} -> {'z_thr': 3.0, 'window_mult': 2.437}
#5 [18:59:22] RETUNE_IMPULSE         hunter     NORMAL->NORMAL | false-gap 41% over 56 signals, regime normal-vol (vol ratio 0.88) | {'z_thr': 3.0, 'window_mult': 2.436903373691113} -> {'z_thr': 3.0, 'window_mult': 2.267}
#6 [19:01:23] RETUNE_IMPULSE         hunter     NORMAL->NORMAL | false-gap 46% over 39 signals, regime normal-vol (vol ratio 0.96) | {'z_thr': 3.0, 'window_mult': 2.267144101212615} -> {'z_thr': 3.0, 'window_mult': 2.092}
#7 [19:01:53] RETUNE_IMPULSE         hunter     NORMAL->NORMAL | false-gap 26% over 39 signals, regime normal-vol (vol ratio 1.03) | {'z_thr': 3.0, 'window_mult': 2.0924517479483526} -> {'z_thr': 3.0, 'window_mult': 1.941}
#8 [19:02:53] RETUNE_IMPULSE         hunter     NORMAL->NORMAL | false-gap 25% over 44 signals, regime normal-vol (vol ratio 1.13) | {'z_thr': 3.0, 'window_mult': 1.9406725064433936} -> {'z_thr': 3.0, 'window_mult': 1.774}
#9 [19:05:23] RETUNE_IMPULSE         hunter     NORMAL->NORMAL | false-gap 25% over 44 signals, regime normal-vol (vol ratio 0.98) | {'z_thr': 3.0, 'window_mult': 1.7739196339992562} -> {'z_thr': 3.0, 'window_mult': 2.042}
```

## 10. Caveats

* Quotes are timestamped at *our* gateway (cloud container → proxy → venue). Lead-lag below ~100 ms here is measured through that path; a co-located engine would see different lags.
* Paper fills use as-of quotes after an assumed order latency; maker fills require the market to trade *through* the resting price (no queue-position credit).
* Short sales are simulated (perp-style); on spot they would be unavailable.
