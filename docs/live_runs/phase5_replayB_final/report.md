# Quant Agency — Phase 5 report: queue-aware passive maker sniper

* mode **replay of p5_tape_1.npz**, duration **1499s**; markets: Binance BTC oracle, **9 Hyperliquid perps**, **83 Polymarket BTC markets**; trade prints recorded: **8356** (real fills are modelled from prints).
* order latency **150 ms**, cancel latency **150 ms**; shield: cancel when < 40% of the impulse is intact, on a 0.3 bps reversal, or when the venue already did 80% of the gap; TTL {'hyperliquid': 6.0, 'polymarket': 12.0}; passive-exit work window {'hyperliquid': 8.0, 'polymarket': 10.0} then taker fallback.
* **fees (assumptions):** Hyperliquid maker 1.5 bps / taker 4.5 bps per side (public base tier; the brief says ~1 bp maker — every table is linear in that: Δnet = −2·Δfee); Polymarket maker 0, taker `0.07·p·(1−p)` per share.

**Fill models** (an order sits behind the visible size at its price, or at the front if it penny-jumps inside the spread):
`strict` — fill only when the opposite touch crosses our price (certain, lower bound) ·
`depletion` — displayed-size depletion at our level counts as trades (optimistic upper bound; the only other option when no trade tape exists) ·
`trades` — real trade prints consume the queue ahead of us and sweep through on prints beyond our price (live only).
Cancels take effect after the cancel latency; fills inside that window are real and counted.

## Hyperliquid perps (ALO maker, 1 tick spread)

35 signals; every variant below runs on **exactly these signals** with identical paper size ($200).

**fill model: `strict`**

| variant | attempts | filled | fill rate | net bps / fill ±s.e. | hit | net bps / attempt ±s.e. | 5s markout after fill (bps) | fills in cancel window | shield cancels |
|---|---|---|---|---|---|---|---|---|---|
| taker/taker | 35 | 31 | 89% | -9.11±0.88 | 0% | -8.06±0.82 | +1.53 | 0 | 0 |
| taker/passive | 35 | 31 | 89% | -6.54±0.85 | 0% | -5.79±0.69 | +1.80 | 0 | 0 |
| join/taker-exit+shield | 35 | 1 | 3% | -6.00±0.00 | 0% | -0.17±0.14 | -0.00 | 0 | 16 |
| join/passive noshield | 35 | 1 | 3% | -7.68±0.00 | 0% | -0.22±0.18 | -0.00 | 0 | 0 |
| join/passive+shield | 35 | 1 | 3% | -7.68±0.00 | 0% | -0.22±0.18 | -0.00 | 0 | 16 |
| penny/passive+shield | 35 | 1 | 3% | -7.68±0.00 | 0% | -0.22±0.18 | -0.00 | 0 | 16 |

**fill model: `depletion`**

| variant | attempts | filled | fill rate | net bps / fill ±s.e. | hit | net bps / attempt ±s.e. | 5s markout after fill (bps) | fills in cancel window | shield cancels |
|---|---|---|---|---|---|---|---|---|---|
| taker/taker | 35 | 31 | 89% | -9.11±0.88 | 0% | -8.06±0.82 | +1.53 | 0 | 0 |
| taker/passive | 35 | 31 | 89% | -6.54±0.85 | 0% | -5.79±0.69 | +1.78 | 0 | 0 |
| join/taker-exit+shield | 35 | 2 | 6% | -7.57±1.57 | 0% | -0.43±0.38 | +0.31 | 0 | 16 |
| join/passive noshield | 35 | 2 | 6% | -6.79±0.89 | 0% | -0.39±0.28 | +0.31 | 0 | 0 |
| join/passive+shield | 35 | 2 | 6% | -6.79±0.89 | 0% | -0.39±0.28 | +0.31 | 0 | 16 |
| penny/passive+shield | 35 | 4 | 11% | -4.55±1.73 | 25% | -0.52±0.27 | +1.57 | 0 | 15 |

**fill model: `trades`**

| variant | attempts | filled | fill rate | net bps / fill ±s.e. | hit | net bps / attempt ±s.e. | 5s markout after fill (bps) | fills in cancel window | shield cancels |
|---|---|---|---|---|---|---|---|---|---|
| taker/taker | 35 | 31 | 89% | -9.11±0.88 | 0% | -8.06±0.82 | +1.53 | 0 | 0 |
| taker/passive | 35 | 31 | 89% | -6.42±0.82 | 0% | -5.69±0.58 | +1.76 | 0 | 0 |
| join/taker-exit+shield | 35 | 1 | 3% | -6.00±0.00 | 0% | -0.17±0.14 | -0.00 | 0 | 16 |
| join/passive noshield | 35 | 1 | 3% | -7.68±0.00 | 0% | -0.22±0.18 | -0.00 | 0 | 0 |
| join/passive+shield | 35 | 1 | 3% | -7.68±0.00 | 0% | -0.22±0.18 | -0.00 | 0 | 16 |
| penny/passive+shield | 35 | 1 | 3% | -7.68±0.00 | 0% | -0.22±0.18 | -0.00 | 0 | 16 |

## Polymarket CLOB (post-only, 0 maker fee)

80 signals; every variant below runs on **exactly these signals** with identical paper size ($50).

**fill model: `strict`**

| variant | attempts | filled | fill rate | net bps / fill ±s.e. | net ¢/share / fill | hit | net bps / attempt ±s.e. | 5s markout after fill (bps) | fills in cancel window | shield cancels |
|---|---|---|---|---|---|---|---|---|---|---|
| taker/taker | 80 | 53 | 66% | -669.55±215.42 | -2.75 | 13% | -443.57±123.65 | +135.88 | 0 | 0 |
| taker/passive | 80 | 53 | 66% | -642.62±170.08 | -2.74 | 19% | -425.74±117.06 | +126.38 | 0 | 0 |
| join/taker-exit+shield | 80 | 6 | 8% | -2623.71±2163.95 | -10.13 | 17% | -196.78±83.49 | -1789.00 | 0 | 51 |
| join/passive noshield | 80 | 8 | 10% | -2098.24±1803.49 | -8.67 | 0% | -209.82±82.43 | -1363.55 | 0 | 0 |
| join/passive+shield | 80 | 6 | 8% | -2733.67±2111.63 | -11.00 | 0% | -205.02±82.10 | -1789.00 | 0 | 51 |
| penny/passive+shield | 80 | 5 | 6% | -3014.22±2124.86 | -10.94 | 0% | -188.39±81.24 | -1923.27 | 0 | 50 |

**fill model: `depletion`**

| variant | attempts | filled | fill rate | net bps / fill ±s.e. | net ¢/share / fill | hit | net bps / attempt ±s.e. | 5s markout after fill (bps) | fills in cancel window | shield cancels |
|---|---|---|---|---|---|---|---|---|---|---|
| taker/taker | 80 | 53 | 66% | -669.55±215.42 | -2.75 | 13% | -443.57±123.65 | +135.88 | 0 | 0 |
| taker/passive | 80 | 53 | 66% | -568.09±169.26 | -2.37 | 23% | -376.36±118.01 | +86.54 | 0 | 0 |
| join/taker-exit+shield | 80 | 16 | 20% | -837.70±444.79 | -2.74 | 44% | -167.54±94.12 | -110.06 | 7 | 45 |
| join/passive noshield | 80 | 21 | 26% | -565.76±339.96 | -2.06 | 43% | -148.51±96.52 | -130.95 | 9 | 0 |
| join/passive+shield | 80 | 16 | 20% | -822.23±437.06 | -2.93 | 44% | -164.45±95.12 | -226.89 | 7 | 45 |
| penny/passive+shield | 80 | 29 | 36% | -563.98±264.36 | -1.89 | 28% | -204.44±97.94 | +5.71 | 6 | 35 |

**fill model: `trades`**

| variant | attempts | filled | fill rate | net bps / fill ±s.e. | net ¢/share / fill | hit | net bps / attempt ±s.e. | 5s markout after fill (bps) | fills in cancel window | shield cancels |
|---|---|---|---|---|---|---|---|---|---|---|
| taker/taker | 80 | 53 | 66% | -669.55±215.42 | -2.75 | 13% | -443.57±123.65 | +135.88 | 0 | 0 |
| taker/passive | 80 | 53 | 66% | -642.62±170.08 | -2.74 | 19% | -425.74±117.06 | +126.38 | 0 | 0 |
| join/taker-exit+shield | 80 | 7 | 9% | -1976.39±1942.50 | -6.64 | 29% | -172.93±94.17 | -1123.91 | 0 | 50 |
| join/passive noshield | 80 | 9 | 11% | -1761.40±1602.21 | -6.93 | 11% | -198.16±85.84 | -1056.49 | 0 | 0 |
| join/passive+shield | 80 | 7 | 9% | -2209.81±1848.58 | -8.43 | 14% | -193.36±85.47 | -1333.43 | 0 | 50 |
| penny/passive+shield | 80 | 6 | 8% | -2356.30±1855.50 | -7.95 | 17% | -176.72±84.55 | -1369.39 | 0 | 49 |

## Mechanics: why orders do or don't fill, and where the edge goes

**Signalled gap vs the price grid** — if the whole gap is smaller than one tick, a resting order cannot capture it: it only fills after the book has already moved a tick.

| venue | signals | median |gap| bps | median spread bps | median gap / tick | signals with gap < 1 tick |
|---|---|---|---|---|---|
| hyperliquid | 35 | 3.1 | 0.50 | 8.91 | 0% |
| polymarket | 80 | 286.9 | 215.05 | 1.42 | 0% |

**`join/passive+shield`: no-fill reasons, exit mix, gross and fees per fill (bps of notional):**

| venue | model | attempts | not filled because | exit mix of fills | gross bps / fill | fees bps / fill |
|---|---|---|---|---|---|---|
| hyperliquid | strict | 35 | ttl=18, converged=16 | taker=1 | -1.68 | 6.00 |
| hyperliquid | depletion | 35 | ttl=17, converged=16 | taker=2 | -0.79 | 6.00 |
| hyperliquid | trades | 35 | ttl=18, converged=16 | taker=1 | -1.68 | 6.00 |
| polymarket | strict | 80 | converged=48, ttl=23, shield=3 | taker=6 | -2459.69 | 273.97 |
| polymarket | depletion | 80 | converged=42, ttl=19, shield=3 | taker=11, passive=5 | -618.19 | 194.22 |
| polymarket | trades | 80 | converged=47, ttl=23, shield=3 | taker=6, passive=1 | -1974.97 | 234.83 |

## Does the oracle cancel shield earn its keep?

| venue | fill model | fill rate (shield vs none) | net bps/fill | net bps/attempt | 5s markout after fill | orders pulled |
|---|---|---|---|---|---|---|
| hyperliquid | strict | 3% vs 3% | -7.68 vs -7.68 | -0.22 vs -0.22 | -0.00 vs -0.00 | 16 |
| hyperliquid | depletion | 6% vs 6% | -6.79 vs -6.79 | -0.39 vs -0.39 | +0.31 vs +0.31 | 16 |
| hyperliquid | trades | 3% vs 3% | -7.68 vs -7.68 | -0.22 vs -0.22 | -0.00 vs -0.00 | 16 |
| polymarket | strict | 8% vs 10% | -2733.67 vs -2098.24 | -205.02 vs -209.82 | -1789.00 vs -1363.55 | 51 |
| polymarket | depletion | 20% vs 26% | -822.23 vs -565.76 | -164.45 vs -148.51 | -226.89 vs -130.95 | 45 |
| polymarket | trades | 9% vs 11% | -2209.81 vs -1761.40 | -193.36 vs -198.16 | -1333.43 vs -1056.49 | 50 |

## Adverse selection: filled orders vs the same signals' unconditional markout

`unconditional` = mid-to-mid gross markout at t+5s of *all* signals on that venue (what a taker captures before costs); `conditional` = markout after a passive fill. A negative gap is the adverse-selection tax on maker fills.

| venue | fill model | n signals | unconditional gross bps | n fills | conditional markout bps | adverse-selection gap |
|---|---|---|---|---|---|---|
| hyperliquid | strict | 35 | +2.30 | 1 | -0.00 | -2.30 |
| hyperliquid | depletion | 35 | +2.30 | 2 | +0.31 | -1.99 |
| hyperliquid | trades | 35 | +2.30 | 1 | -0.00 | -2.30 |
| polymarket | strict | 80 | +267.83 | 6 | -1789.00 | -2056.83 |
| polymarket | depletion | 80 | +267.83 | 16 | -226.89 | -494.72 |
| polymarket | trades | 80 | +267.83 | 7 | -1333.43 | -1601.26 |

## Cancel-latency adverse fills

| venue | fill model | shield-variant fills | of which inside the cancel window | mean net bps (inside) | mean net bps (other fills) |
|---|---|---|---|---|---|
| hyperliquid | strict | 3 | 0 | - | -7.12 |
| hyperliquid | depletion | 8 | 0 | - | -5.86 |
| hyperliquid | trades | 3 | 0 | - | -7.12 |
| polymarket | strict | 17 | 0 | - | -2777.37 |
| polymarket | depletion | 61 | 20 | -492.55 | -806.42 |
| polymarket | trades | 20 | 0 | - | -2172.06 |

## Before / after: Phase 4 taker vs Phase 5 maker (same venues, same assumptions)

**Hyperliquid, net bps (after fees):**

| configuration | signals/attempts | fill rate | net bps / fill | net bps / attempt (unfilled = 0) |
|---|---|---|---|---|
| Phase 4 report (taker, 150 ms, all HL signals) | 92 | 100% | -7.35 | - |
| Phase 5 `taker/taker` (same engine, same signals as below) | 35 | 100% | -9.11 | -8.06 |
| Phase 5 join/passive+shield, strict (lower bound) | 35 | 3% | -7.68 | -0.22 |
| Phase 5 join/passive+shield, depletion (upper bound) | 35 | 6% | -6.79 | -0.39 |
| Phase 5 join/passive+shield, trades (observed prints) | 35 | 3% | -7.68 | -0.22 |

**Polymarket, net ¢ per share (after fees):**

| configuration | signals/attempts | fill rate | net ¢ / fill | net ¢ / attempt (unfilled = 0) |
|---|---|---|---|---|
| Phase 4 report (taker, live-priced contracts) | 105 | 100% | -2.39 | - |
| Phase 5 `taker/taker` baseline | 80 | 100% | -2.75 | - |
| Phase 5 join/passive+shield, strict | 80 | 8% | -11.00 | -0.83 |
| Phase 5 penny/passive+shield, strict | 80 | 6% | -10.94 | -0.68 |
| Phase 5 join/passive+shield, depletion | 80 | 20% | -2.93 | -0.59 |
| Phase 5 penny/passive+shield, depletion | 80 | 36% | -1.89 | -0.68 |
| Phase 5 join/passive+shield, trades | 80 | 9% | -8.43 | -0.74 |
| Phase 5 penny/passive+shield, trades | 80 | 8% | -7.95 | -0.60 |

## CFO-accounted maker attempts and CEO monitoring

account attempts 18, filled 4 (22%), net PnL $-17.97, equity $9,982.03; learned P(fill) 0.22, P(passive exit) 0.41, adverse buffers {'hyperliquid': 0.3, 'polymarket': 400.0}, CFO reasons: net_edge_below_hurdle=74, quarantined=21, ok=18, size_below_min=1, in_position=1

| market | side | entry | mode | wait s | entry px | exit px | exit | net bps | net $ | in cancel window |
|---|---|---|---|---|---|---|---|---|---|---|
| pm:btc-updown-5m-1792441500:updown_5m | L | join | trades | 1.3 | 0.88 | 0.82 | taker | -799.2 | -3.197 | False |
| pm:btc-updown-5m-1792441800:updown_5m | S | join | trades | 0.8 | 0.33 | 0.69 | taker | -11362.8 | -22.378 | False |
| pm:btc-updown-15m-1792441800:updown_15m | S | join | trades | 4.6 | 0.27 | 0.32 | taker | -2416.0 | -3.565 | False |
| pm:btc-updown-5m-1792442700:updown_5m | S | join | trades | 0.2 | 0.75 | 0.68 | passive | +933.3 | +11.167 | False |

**CEO sniper interventions:**

```
#10 [21:15:29] SNIPE_RAISE_ADVERSE_BUFFER polymarket NORMAL->NORMAL | maker net -3411.18±2737.33bps per fill < tolerance: CFO adverse-selection buffer 400→400bps | {'buffer': 400.0} -> {'buffer': 400.0}
```

CEO state NORMAL; all interventions 12.

## Caveats

* Real trade prints were recorded for Hyperliquid and Polymarket in this session; Polymarket aggressor side is inferred from price vs mid. A real queue also has cancellations ahead of us, hidden/iceberg size and other makers' adverse-selection management, none of which can be observed here.
* Shadow variants use a fixed small paper size and do not move the book; the account attempt is CFO-sized. Hyperliquid is 1 tick wide so penny-jumping applies to Polymarket only.
* One quiet-regime session; cluster-robust s.e. over BTC impulses are shown and power is low.
