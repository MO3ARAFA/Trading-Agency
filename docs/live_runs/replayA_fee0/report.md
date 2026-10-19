# Quant Agency — live telemetry report

* mode: **replay of live_tape_1.npz**  | duration: **899s**  | markets watched: **67** (61 Binance + 6 cross-venue)
* fees: taker 0.0 bps / maker 0.0 bps per side | assumed order latency 150 ms | capital $10,000 (paper)
* execution is **paper only** — no credentials, no live orders.

## 1. Feed health & internal latency

_(none)_

* hunter scan (all 66 markets, numba): n=78075  p50=0µs  p90=43µs  p99=202µs  max=215.71ms
* BTC tick received → CFO-approved executable payload ready: n=62  p50=1094µs  p90=3070µs  p99=5600µs  max=5.74ms
* BTC quotes processed: 78075  | trades(agg): 4682  | book rejects: 0

## 2. BTC oracle (master reference)

BTCUSDT bid/ask 81918.96/81918.97, micro 81918.961, OBI -0.90, spread 0.001 bps, vol 0.28 bps/√s (slow 0.31, ratio 0.92), tick-vol 0.00

BTC impulses detected (|Z|≥4.50 at report time): **14**; hunter scans: 21766

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
|  598.6s | TAOUSDT | BUY | +2.2@1s | 7.7 | 2.28 | 0.0 | +8.8 | 6.3 | 3.8 | ok (maker) | +5.2 | -3.8 | -3.8 | -7.5 |
|  238.0s | STRKUSDT | BUY | +1.8@3s | 3.4 | 3.39 | 0.0 | +8.7 | 2.2 | 3.5 | ok (taker) | +3.6 | +2.6 | -2.6 | -6.9 |
|  598.6s | NEARUSDT | BUY | +2.2@1s | 7.7 | 3.86 | -0.5 | +8.5 | 4.4 | 2.0 | ok (maker) | +5.3 | +0.0 | -6.1 | -8.1 |
|  386.3s | SANDUSDT | SELL | -1.8@1s | -4.9 | 2.01 | -0.2 | -8.0 | 4.8 | 6.8 | net_edge_below_hurdle | -1.4 | -0.0 | -0.0 | -6.8 |
|  598.6s | ONDOUSDT | BUY | +2.2@1s | 7.7 | 2.17 | -0.2 | +7.1 | 6.1 | 2.3 | ok (maker) | +3.9 | +0.0 | -2.3 | -4.7 |
|  268.2s | MARSCOINUSDT | BUY | +3.2@1s | 9.7 | 2.21 | -0.5 | +7.1 | 3.0 | 13.1 | net_edge_below_hurdle | -8.9 | +0.0 | +0.0 | -13.1 |
|   80.4s | ZROUSDT | BUY | +1.5@1s | 7.2 | 2.73 | 2.4 | +6.9 | 2.7 | 10.6 | ok (maker) | +3.0 | +0.0 | +0.0 | -5.3 |
|  598.6s | SEIUSDT | BUY | +2.2@1s | 7.7 | 2.67 | -0.1 | +5.9 | 4.2 | 1.7 | ok (maker) | +2.8 | +0.0 | -5.0 | -6.7 |
|  377.0s | ZROUSDT | SELL | -2.7@1s | -8.2 | 2.18 | -0.2 | -5.9 | 2.1 | 5.3 | net_edge_below_hurdle | -1.8 | +5.3 | +5.3 | -0.0 |
|  598.6s | SANDUSDT | BUY | +2.2@1s | 7.7 | 1.11 | -0.1 | +5.8 | 4.6 | 3.4 | ok (maker) | +2.4 | -0.9 | -2.6 | -5.1 |
|  377.5s | PUMPUSDT | SELL | -2.7@1s | -7.4 | 3.01 | -0.3 | -5.8 | 1.7 | 2.3 | ok (taker) | +1.4 | -0.0 | -4.6 | -6.9 |
|  138.1s | APTUSDT | BUY | +2.7@5s | 3.4 | 3.09 | 1.2 | +5.8 | 1.6 | 1.3 | ok (taker) | +3.1 | -2.6 | -2.6 | -4.0 |
|   80.4s | APTUSDT | BUY | +1.5@1s | 7.2 | 3.69 | 0.1 | +5.7 | 3.2 | 1.3 | ok (taker) | +3.1 | +0.0 | +2.6 | +1.3 |
|  386.3s | MARSCOINUSDT | SELL | -1.8@1s | -4.9 | 3.08 | 0.0 | -5.7 | 2.3 | 13.2 | net_edge_below_hurdle | -10.9 | -0.0 | -0.0 | -13.2 |

## 5. CFO gating & accounting

evaluated 243, approved 62; reasons: net_edge_below_hurdle=113, ok=62, halted=37, size_below_min=29, in_position=2

equity $9,999.47 (peak $10,000.25, drawdown 0.008%), closed PnL $-0.53, fees $0.00; hurdle 2.50 bps, edge-credit 0.85, mode maker_only, size×0.40, halted=True (ceo_halt), quarantined=['XLMUSDT', 'ADAUSDT', 'ENAUSDT', 'TRUMPUSDT']

## 6. Realised markout curves (t+1s … t+30s)

**All detected gaps (incl. CFO-rejected shadow cohort)** — does the gap actually close?

| horizon | n | gross bps | net bps (taker, after spread+fees) | net s.e. | hit gross | hit net | gap closure |
|---|---|---|---|---|---|---|---|
| t+1s | 243 | +0.23 | -2.03 | 0.31 | 21% | 9% | 0.34 |
| t+3s | 243 | +0.68 | -1.59 | 0.30 | 40% | 20% | 0.50 |
| t+5s | 243 | +0.60 | -1.67 | 0.49 | 43% | 26% | 0.53 |
| t+10s | 243 | +0.54 | -1.72 | 0.99 | 43% | 28% | 0.46 |
| t+30s | 243 | +1.06 | -1.21 | 1.61 | 56% | 42% | 0.51 |

**CFO-approved cohort**

| horizon | n | gross bps | net bps (taker, after spread+fees) | net s.e. | hit gross | hit net | gap closure |
|---|---|---|---|---|---|---|---|
| t+1s | 62 | +0.03 | -1.95 | 0.35 | 21% | 10% | 0.22 |
| t+3s | 62 | +0.11 | -1.86 | 0.44 | 34% | 19% | 0.23 |
| t+5s | 62 | -0.78 | -2.73 | 0.67 | 31% | 21% | 0.07 |
| t+10s | 62 | -0.13 | -2.15 | 1.34 | 40% | 26% | 0.18 |
| t+30s | 62 | +2.98 | +1.02 | 2.06 | 76% | 61% | 0.94 |

**CFO-rejected: net edge below hurdle**

| horizon | n | gross bps | net bps (taker, after spread+fees) | net s.e. | hit gross | hit net | gap closure |
|---|---|---|---|---|---|---|---|
| t+1s | 113 | +0.36 | -2.23 | 0.35 | 19% | 7% | 0.36 |
| t+3s | 113 | +1.14 | -1.44 | 0.54 | 45% | 19% | 0.66 |
| t+5s | 113 | +1.51 | -1.08 | 0.78 | 51% | 27% | 0.85 |
| t+10s | 113 | +1.33 | -1.23 | 1.78 | 51% | 32% | 0.74 |
| t+30s | 113 | +1.38 | -1.20 | 2.30 | 61% | 41% | 0.71 |

_gross = mid→mid after fill (latency-adjusted entry); net = cross the spread on entry and exit + round-trip taker fees; gap closure = share of the signalled gap that has closed._

## 7. Per-market profitability @ t+5s

| market | n | gross bps | net bps | hit net | status |
|---|---|---|---|---|---|
| ETHUSDT | 3 | +1.38 | +1.33 | 100% |  |
| kraken:BTC/USD | 5 | +1.33 | +1.30 | 100% |  |
| SUIUSDT | 5 | +2.03 | +1.02 | 40% |  |
| gate:ETH_USDT | 5 | +0.68 | +0.63 | 80% |  |
| BNBUSDT | 4 | +0.76 | +0.62 | 75% |  |
| LINKUSDT | 5 | +1.35 | +0.50 | 60% |  |
| gate:BTC_USDT | 4 | +0.52 | +0.50 | 75% |  |
| kraken:ETH/USD | 5 | +0.55 | +0.49 | 80% |  |
| UNIUSDT | 6 | +1.38 | +0.00 | 33% |  |
| TIAUSDT | 4 | +2.07 | +0.00 | 25% |  |

worst:

| market | n | gross bps | net bps | hit net | status |
|---|---|---|---|---|---|
| FETUSDT | 4 | +0.00 | -5.34 | 0% |  |
| ENAUSDT | 7 | -0.77 | -6.15 | 0% | QUARANTINED |
| OPUSDT | 2 | +0.00 | -8.08 | 0% |  |
| ARBUSDT | 2 | -5.15 | -10.30 | 0% |  |
| MARSCOINUSDT | 2 | +0.00 | -13.16 | 0% |  |

## 8. Paper execution

orders submitted 53, filled 17 (partial 0), closed 17, open 0; dropped: {'maker_ttl_expired': 28, 'ioc_price_moved': 5, 'ioc_no_liquidity': 3, 'max_open': 9}

closed trades 17: win rate 47%, net PnL $-0.53, fees $0.00, expectancy -1.69 bps / -0.31 R, gross -1.69 bps, entry slippage +0.47 bps, mean spread at entry 1.47 bps

exit reasons: take_profit=8, adverse_stop=4, time_stop=5

| market | side | mode | hold s | entry | exit | gross bps | net bps | R | exit |
|---|---|---|---|---|---|---|---|---|---|
| APTUSDT | L | taker | 13.4 | 0.7583 | 0.7582 | -1.3 | -1.3 | -0.18 | time_stop |
| XPLUSDT | L | taker | 10.2 | 0.0756 | 0.07555 | -6.6 | -6.6 | -1.46 | time_stop |
| SOLUSDT | L | taker | 10.2 | 103.95 | 103.96 | +1.0 | +1.0 | +0.24 | time_stop |
| STRKUSDT | L | taker | 10.2 | 0.05762 | 0.05761 | -1.7 | -1.7 | -0.22 | time_stop |
| PUMPUSDT | L | taker | 0.2 | 0.004384 | 0.004384 | +0.0 | +0.0 | +0.00 | take_profit |
| INJUSDT | L | taker | 3.0 | 8.564 | 8.558 | -7.0 | -7.0 | -1.75 | adverse_stop |
| NEARUSDT | L | taker | 9.7 | 4.94 | 4.936 | -8.1 | -8.1 | -1.95 | adverse_stop |
| PUMPUSDT | S | taker | 5.5 | 0.004353 | 0.004358 | -11.5 | -11.5 | -1.65 | adverse_stop |
| FILUSDT | S | taker | 10.2 | 1.0081 | 1.0083 | -2.0 | -2.0 | -0.50 | time_stop |
| SOLUSDT | S | taker | 1.5 | 103.94 | 103.93 | +1.0 | +1.0 | +0.24 | take_profit |
| INJUSDT | S | taker | 2.0 | 8.547 | 8.544 | +3.5 | +3.5 | +0.88 | take_profit |
| XRPUSDT | S | taker | 2.4 | 1.3002 | 1.3 | +1.5 | +1.5 | +0.38 | take_profit |

sample prepared payload (never transmitted):

```json
{
 "oid": 53,
 "sid": 190,
 "market": "ONDOUSDT",
 "symbol": "ONDOUSDT",
 "venue": "binance",
 "side": "BUY",
 "order_type": "LIMIT_MAKER",
 "time_in_force": "GTC",
 "price": 0.4297,
 "qty": 465.40000000000003,
 "notional": 199.98238000000003,
 "mode": "maker",
 "tp_price": 0.429963505945763,
 "stop_price": 0.4295781,
 "time_stop_s": 10.0,
 "maker_ttl_s": 3.0,
 "expected_net_bps": 3.9020934650252537,
 "gap_bps": 7.097347154090988,
 "t_signal": 2033.148895097,
 "t_prepared": 2033.148895097,
 "prep_latency_us": 2567.0409995655064,
 "sig_quote_px": 0.4298,
 "sig_mid": 0.42975,
 "beta": 2.1748592654387164,
 "stop_bps": 4.0,
 "exchange_params": {
  "symbol": "ONDOUSDT",
  "side": "BUY",
  "type": "LIMIT_MAKER",
  "quantity": "465.4",
  "price": "0.4297",
  "newClientOrderId": "qa53"
 }
}
```

## 9. CEO → CFO/Hunter interventions

CEO state: **HALTED**, reviews: 30, interventions: **17**

| t | state | verdict | signals | gross5 | net5 | false-gap | trades | exp bps | realization | reasons |
|---|---|---|---|---|---|---|---|---|---|---|
| 571s | DEFENSIVE | OK | 25 | -0.136 | -2.403 | 80% | 0 | 0.0 | None |  |
| 601s | DEFENSIVE | OK | 0 | 0.0 | 0.0 | 0% | 0 | 0.0 | None |  |
| 631s | DEFENSIVE | POOR | 42 | -2.122 | -4.065 | 93% | 0 | 0.0 | -20.814 | approved net markout -4.37bps over 29 < -1.0; CFO edge realization -20.81 < 0.5 |
| 661s | HALTED | OK | 0 | 0.0 | 0.0 | 0% | 0 | 0.0 | None |  |
| 691s | HALTED | OK | 0 | 0.0 | 0.0 | 0% | 0 | 0.0 | None |  |
| 721s | HALTED | OK | 12 | 0.104 | -4.448 | 67% | 0 | 0.0 | None |  |
| 751s | HALTED | OK | 0 | 0.0 | 0.0 | 0% | 0 | 0.0 | None |  |
| 781s | HALTED | OK | 0 | 0.0 | 0.0 | 0% | 0 | 0.0 | None |  |
| 811s | HALTED | OK | 0 | 0.0 | 0.0 | 0% | 0 | 0.0 | None |  |
| 841s | HALTED | OK | 0 | 0.0 | 0.0 | 0% | 0 | 0.0 | None |  |
| 871s | HALTED | OK | 24 | -0.206 | -2.144 | 79% | 0 | 0.0 | None |  |
| 899s | HALTED | OK | 0 | 0.0 | 0.0 | 0% | 0 | 0.0 | None |  |

audit trail:

```
#1 [19:08:32] RETUNE_IMPULSE         hunter     NORMAL->NORMAL | false-gap 58% over 12 signals, regime normal-vol (vol ratio 1.00) | {'z_thr': 3.0, 'window_mult': 2.0} -> {'z_thr': 3.25, 'window_mult': 2.0}
#2 [19:11:32] RETUNE_IMPULSE         hunter     NORMAL->NORMAL | false-gap 71% over 14 signals, regime normal-vol (vol ratio 1.06) | {'z_thr': 3.25, 'window_mult': 2.0} -> {'z_thr': 3.5, 'window_mult': 2.0}
#3 [19:11:32] TIGHTEN_CFO            cfo        NORMAL->TIGHTENED | trade expectancy -2.57bps over 6 trades < -1.0 | {'hurdle': 1.0, 'size_mult': 1.0, 'mode': 'auto'} -> {'hurdle': 1.5, 'size_mult': 0.8, 'mode': 'auto'}
#4 [19:13:32] RETUNE_IMPULSE         hunter     TIGHTENED->TIGHTENED | false-gap 34% over 41 signals, regime normal-vol (vol ratio 1.12) | {'z_thr': 3.5, 'window_mult': 2.0} -> {'z_thr': 3.5, 'window_mult': 1.75}
#5 [19:13:32] DEFENSIVE_MAKER_ONLY   cfo        TIGHTENED->DEFENSIVE | trade expectancy -3.22bps over 7 trades < -1.0; fee bleed: gross +1.34 vs net -0.76bps | {'hurdle': 1.5, 'size_mult': 0.8, 'mode': 'auto'} -> {'hurdle': 2.5, 'size_mult': 0.4, 'mode': 'maker_only'}
#6 [19:14:32] RETUNE_IMPULSE         hunter     DEFENSIVE->DEFENSIVE | false-gap 0% over 0 signals, regime normal-vol (vol ratio 1.05) | {'z_thr': 3.5, 'window_mult': 1.75} -> {'z_thr': 3.5, 'window_mult': 2.0}
#7 [19:16:32] RETUNE_IMPULSE         hunter     DEFENSIVE->DEFENSIVE | false-gap 80% over 25 signals, regime normal-vol (vol ratio 0.97) | {'z_thr': 3.5, 'window_mult': 2.0} -> {'z_thr': 3.75, 'window_mult': 2.0}
#8 [19:17:32] QUARANTINE_MARKET      XLMUSDT    DEFENSIVE->DEFENSIVE | negative_markouts: n=6 gross@1s=+0.00 gross@5s=+0.95 net@5s=-4.74bps hit=0%; blacklisted 600s | {} -> {'until': 2665.5}
#9 [19:17:32] QUARANTINE_MARKET      ADAUSDT    DEFENSIVE->DEFENSIVE | negative_markouts: n=6 gross@1s=+0.00 gross@5s=+1.54 net@5s=-3.08bps hit=0%; blacklisted 600s | {} -> {'until': 2665.5}
#10 [19:17:32] CFO_EDGE_RECALIBRATION cfo        DEFENSIVE->DEFENSIVE | CFO predicted net +0.21bps but realised -4.37bps (ratio -20.81): haircutting gap credit | {'edge_credit': 1.0} -> {'edge_credit': 0.85}
#11 [19:17:32] RETUNE_IMPULSE         hunter     DEFENSIVE->DEFENSIVE | false-gap 93% over 42 signals, regime normal-vol (vol ratio 1.00) | {'z_thr': 3.75, 'window_mult': 2.0} -> {'z_thr': 4.0, 'window_mult': 2.0}
#12 [19:17:32] HALT_TRADING           cfo        DEFENSIVE->HALTED | approved net markout -4.37bps over 29 < -1.0; CFO edge realization -20.81 < 0.5; standing down 300s then probation | {'hurdle': 2.5, 'size_mult': 0.4, 'mode': 'maker_only'} -> {'hurdle': 2.5, 'size_mult': 0.4, 'mode': 'maker_only'}
#13 [19:19:03] QUARANTINE_MARKET      ENAUSDT    HALTED->HALTED | negative_markouts: n=6 gross@1s=+0.90 gross@5s=-0.89 net@5s=-6.28bps hit=0%; blacklisted 600s | {} -> {'until': 2755.6}
#14 [19:19:03] RETUNE_IMPULSE         hunter     HALTED->HALTED | false-gap 67% over 12 signals, regime normal-vol (vol ratio 0.98) | {'z_thr': 4.0, 'window_mult': 2.0} -> {'z_thr': 4.25, 'window_mult': 2.0}
#15 [19:19:33] RETUNE_IMPULSE         hunter     HALTED->HALTED | false-gap 0% over 0 signals, regime normal-vol (vol ratio 0.94) | {'z_thr': 4.25, 'window_mult': 2.0} -> {'z_thr': 4.25, 'window_mult': 2.25}
#16 [19:21:33] QUARANTINE_MARKET      TRUMPUSDT  HALTED->HALTED | negative_markouts: n=6 gross@1s=+0.98 gross@5s=+1.96 net@5s=-3.92bps hit=0%; blacklisted 600s | {} -> {'until': 2905.7}
#17 [19:21:33] RETUNE_IMPULSE         hunter     HALTED->HALTED | false-gap 79% over 24 signals, regime normal-vol (vol ratio 0.89) | {'z_thr': 4.25, 'window_mult': 2.25} -> {'z_thr': 4.5, 'window_mult': 2.25}
```

## 10. Caveats

* Quotes are timestamped at *our* gateway (cloud container → proxy → venue). Lead-lag below ~100 ms here is measured through that path; a co-located engine would see different lags.
* Paper fills use as-of quotes after an assumed order latency; maker fills require the market to trade *through* the resting price (no queue-position credit).
* Short sales are simulated (perp-style); on spot they would be unavailable.
