# Quant Agency — Phase 5 report: queue-aware passive maker sniper

* mode **replay of p4_tape_1.npz**, duration **1199s**; markets: Binance BTC oracle, **9 Hyperliquid perps**, **84 Polymarket BTC markets**; trade prints recorded: **0** (NO trade tape → fills are bounded, not observed).
* order latency **150 ms**, cancel latency **150 ms**; shield: cancel when < 40% of the impulse is intact, on a 0.3 bps reversal, or when the venue already did 80% of the gap; TTL {'hyperliquid': 6.0, 'polymarket': 12.0}; passive-exit work window {'hyperliquid': 8.0, 'polymarket': 10.0} then taker fallback.
* **fees (assumptions):** Hyperliquid maker 1.5 bps / taker 4.5 bps per side (public base tier; the brief says ~1 bp maker — every table is linear in that: Δnet = −2·Δfee); Polymarket maker 0, taker `0.07·p·(1−p)` per share.

**Fill models** (an order sits behind the visible size at its price, or at the front if it penny-jumps inside the spread):
`strict` — fill only when the opposite touch crosses our price (certain, lower bound) ·
`depletion` — displayed-size depletion at our level counts as trades (optimistic upper bound; the only other option when no trade tape exists) ·
`trades` — real trade prints consume the queue ahead of us and sweep through on prints beyond our price (live only).
Cancels take effect after the cancel latency; fills inside that window are real and counted.

## Hyperliquid perps (ALO maker, 1 tick spread)

92 signals; every variant below runs on **exactly these signals** with identical paper size ($200).

**fill model: `strict`**

| variant | attempts | filled | fill rate | net bps / fill ±s.e. | hit | net bps / attempt ±s.e. | 5s markout after fill (bps) | fills in cancel window | shield cancels |
|---|---|---|---|---|---|---|---|---|---|
| taker/taker | 92 | 73 | 79% | -7.87±0.17 | 0% | -6.24±0.56 | +1.51 | 0 | 0 |
| taker/passive | 92 | 73 | 79% | -6.52±0.48 | 0% | -5.18±0.61 | +1.58 | 0 | 0 |
| join/taker-exit+shield | 92 | 6 | 7% | -5.94±1.05 | 0% | -0.39±0.29 | -0.68 | 0 | 75 |
| join/passive noshield | 92 | 8 | 9% | -6.64±0.62 | 0% | -0.58±0.33 | -0.77 | 0 | 0 |
| join/passive+shield | 92 | 6 | 7% | -6.37±0.76 | 0% | -0.42±0.32 | -0.68 | 0 | 75 |
| penny/passive+shield | 92 | 7 | 8% | -6.58±0.85 | 0% | -0.50±0.37 | -0.78 | 0 | 75 |

**fill model: `depletion`**

| variant | attempts | filled | fill rate | net bps / fill ±s.e. | hit | net bps / attempt ±s.e. | 5s markout after fill (bps) | fills in cancel window | shield cancels |
|---|---|---|---|---|---|---|---|---|---|
| taker/taker | 92 | 73 | 79% | -7.87±0.17 | 0% | -6.24±0.56 | +1.51 | 0 | 0 |
| taker/passive | 92 | 73 | 79% | -6.31±0.49 | 0% | -5.01±0.62 | +1.55 | 0 | 0 |
| join/taker-exit+shield | 92 | 10 | 11% | -5.28±0.40 | 0% | -0.57±0.37 | -0.11 | 0 | 73 |
| join/passive noshield | 92 | 13 | 14% | -5.39±1.32 | 0% | -0.76±0.41 | -0.28 | 0 | 0 |
| join/passive+shield | 92 | 10 | 11% | -4.97±1.44 | 0% | -0.54±0.40 | -0.11 | 0 | 73 |
| penny/passive+shield | 92 | 15 | 16% | -4.18±0.91 | 7% | -0.68±0.40 | +1.06 | 0 | 69 |

## Polymarket CLOB (post-only, 0 maker fee)

117 signals; every variant below runs on **exactly these signals** with identical paper size ($50).

**fill model: `strict`**

| variant | attempts | filled | fill rate | net bps / fill ±s.e. | net ¢/share / fill | hit | net bps / attempt ±s.e. | 5s markout after fill (bps) | fills in cancel window | shield cancels |
|---|---|---|---|---|---|---|---|---|---|---|
| taker/taker | 117 | 70 | 60% | -1133.45±189.66 | -3.58 | 11% | -678.13±112.11 | -39.31 | 0 | 0 |
| taker/passive | 117 | 70 | 60% | -1033.07±173.89 | -3.38 | 20% | -618.07±104.20 | -31.04 | 0 | 0 |
| join/taker-exit+shield | 117 | 15 | 13% | -1132.69±933.99 | -2.43 | 27% | -145.22±123.19 | -84.78 | 1 | 88 |
| join/passive noshield | 117 | 19 | 16% | -499.28±341.65 | -1.13 | 37% | -81.08±42.13 | +6.79 | 0 | 0 |
| join/passive+shield | 117 | 15 | 13% | -609.28±402.72 | -1.23 | 33% | -78.11±42.03 | -54.48 | 1 | 88 |
| penny/passive+shield | 117 | 15 | 13% | -633.90±403.15 | -1.43 | 33% | -81.27±42.48 | -88.47 | 1 | 88 |

**fill model: `depletion`**

| variant | attempts | filled | fill rate | net bps / fill ±s.e. | net ¢/share / fill | hit | net bps / attempt ±s.e. | 5s markout after fill (bps) | fills in cancel window | shield cancels |
|---|---|---|---|---|---|---|---|---|---|---|
| taker/taker | 117 | 70 | 60% | -1133.45±189.66 | -3.58 | 11% | -678.13±112.11 | -39.31 | 0 | 0 |
| taker/passive | 117 | 70 | 60% | -805.20±171.08 | -2.49 | 23% | -481.74±93.66 | -37.53 | 0 | 0 |
| join/taker-exit+shield | 117 | 27 | 23% | -356.38±320.87 | -1.56 | 41% | -82.24±60.13 | +245.28 | 9 | 81 |
| join/passive noshield | 117 | 34 | 29% | -119.36±218.94 | -0.44 | 50% | -34.69±50.08 | +227.05 | 12 | 0 |
| join/passive+shield | 117 | 27 | 23% | -169.43±239.47 | -0.55 | 48% | -39.10±45.66 | +244.73 | 9 | 81 |
| penny/passive+shield | 117 | 48 | 41% | +58.09±176.49 | +0.08 | 46% | +23.83±68.94 | +394.15 | 9 | 62 |

## Mechanics: why orders do or don't fill, and where the edge goes

**Signalled gap vs the price grid** — if the whole gap is smaller than one tick, a resting order cannot capture it: it only fills after the book has already moved a tick.

| venue | signals | median |gap| bps | median spread bps | median gap / tick | signals with gap < 1 tick |
|---|---|---|---|---|---|
| hyperliquid | 92 | 2.2 | 0.77 | 5.31 | 0% |
| polymarket | 117 | 413.1 | 500.00 | 1.58 | 0% |

**`join/passive+shield`: no-fill reasons, exit mix, gross and fees per fill (bps of notional):**

| venue | model | attempts | not filled because | exit mix of fills | gross bps / fill | fees bps / fill |
|---|---|---|---|---|---|---|
| hyperliquid | strict | 92 | converged=74, ttl=11, shield=1 | taker=6 | -0.37 | 6.00 |
| hyperliquid | depletion | 92 | converged=72, ttl=9, shield=1 | taker=7, passive=3 | +0.13 | 5.10 |
| polymarket | strict | 117 | converged=86, ttl=14, shield=1, post_only_cross=1 | taker=12, passive=3 | -358.10 | 251.18 |
| polymarket | depletion | 117 | converged=80, ttl=8, shield=1, post_only_cross=1 | taker=20, passive=7 | +89.65 | 199.38 |

## Does the oracle cancel shield earn its keep?

| venue | fill model | fill rate (shield vs none) | net bps/fill | net bps/attempt | 5s markout after fill | orders pulled |
|---|---|---|---|---|---|---|
| hyperliquid | strict | 7% vs 9% | -6.37 vs -6.64 | -0.42 vs -0.58 | -0.68 vs -0.77 | 75 |
| hyperliquid | depletion | 11% vs 14% | -4.97 vs -5.39 | -0.54 vs -0.76 | -0.11 vs -0.28 | 73 |
| polymarket | strict | 13% vs 16% | -609.28 vs -499.28 | -78.11 vs -81.08 | -54.48 vs +6.79 | 88 |
| polymarket | depletion | 23% vs 29% | -169.43 vs -119.36 | -39.10 vs -34.69 | +244.73 vs +227.05 | 81 |

## Adverse selection: filled orders vs the same signals' unconditional markout

`unconditional` = mid-to-mid gross markout at t+5s of *all* signals on that venue (what a taker captures before costs); `conditional` = markout after a passive fill. A negative gap is the adverse-selection tax on maker fills.

| venue | fill model | n signals | unconditional gross bps | n fills | conditional markout bps | adverse-selection gap |
|---|---|---|---|---|---|---|
| hyperliquid | strict | 92 | +2.45 | 6 | -0.68 | -3.13 |
| hyperliquid | depletion | 92 | +2.45 | 10 | -0.11 | -2.56 |
| polymarket | strict | 117 | +511.60 | 15 | -54.48 | -566.08 |
| polymarket | depletion | 117 | +511.60 | 27 | +244.73 | -266.86 |

## Cancel-latency adverse fills

| venue | fill model | shield-variant fills | of which inside the cancel window | mean net bps (inside) | mean net bps (other fills) |
|---|---|---|---|---|---|
| hyperliquid | strict | 19 | 0 | - | -6.31 |
| hyperliquid | depletion | 35 | 0 | - | -4.72 |
| polymarket | strict | 45 | 3 | -4775.94 | -507.39 |
| polymarket | depletion | 102 | 27 | +413.49 | -300.97 |

## Before / after: Phase 4 taker vs Phase 5 maker (same venues, same assumptions)

**Hyperliquid, net bps (after fees):**

| configuration | signals/attempts | fill rate | net bps / fill | net bps / attempt (unfilled = 0) |
|---|---|---|---|---|
| Phase 4 report (taker, 150 ms, all HL signals) | 92 | 100% | -7.35 | - |
| Phase 5 `taker/taker` (same engine, same signals as below) | 92 | 100% | -7.87 | -6.24 |
| Phase 5 join/passive+shield, strict (lower bound) | 92 | 7% | -6.37 | -0.42 |
| Phase 5 join/passive+shield, depletion (upper bound) | 92 | 11% | -4.97 | -0.54 |

**Polymarket, net ¢ per share (after fees):**

| configuration | signals/attempts | fill rate | net ¢ / fill | net ¢ / attempt (unfilled = 0) |
|---|---|---|---|---|
| Phase 4 report (taker, live-priced contracts) | 105 | 100% | -2.39 | - |
| Phase 5 `taker/taker` baseline | 117 | 100% | -3.58 | - |
| Phase 5 join/passive+shield, strict | 117 | 13% | -1.23 | -0.16 |
| Phase 5 penny/passive+shield, strict | 117 | 13% | -1.43 | -0.18 |
| Phase 5 join/passive+shield, depletion | 117 | 23% | -0.55 | -0.13 |
| Phase 5 penny/passive+shield, depletion | 117 | 41% | +0.08 | +0.03 |

## CFO-accounted maker attempts and CEO monitoring

account attempts 29, filled 6 (21%), net PnL $-1.10, equity $9,999.19; learned P(fill) 0.32, P(passive exit) 0.54, adverse buffers {'hyperliquid': 0.3, 'polymarket': 400.0}, CFO reasons: spread_too_wide=218, net_edge_below_hurdle=175, quarantined=88, ok=35, size_below_min=9, in_position=2

| market | side | entry | mode | wait s | entry px | exit px | exit | net bps | net $ | in cancel window |
|---|---|---|---|---|---|---|---|---|---|---|
| pm:btc-updown-15m-1792438200:updown_15m | L | join | strict | 0.9 | 0.83 | 0.8 | taker | -496.4 | -1.985 | False |
| pm:btc-updown-15m-1792438200:updown_15m | L | join | strict | 1.0 | 0.79 | 0.82 | taker | +249.0 | +0.996 | False |
| pm:btc-updown-5m-1792438800:updown_5m | L | join | strict | 9.8 | 0.81 | 0.88 | passive | +864.2 | +3.456 | False |
| pm:btc-updown-15m-1792439100:updown_15m | S | join | strict | 1.7 | 0.27 | 0.24 | passive | +1111.1 | +1.644 | False |
| pm:btc-updown-4h-1792425600:updown_4h | L | penny | strict | 0.3 | 0.55 | 0.43 | taker | -2493.8 | -9.978 | False |
| pm:btc-updown-5m-1792439400:updown_5m | S | join | strict | 0.3 | 0.33 | 0.25 | passive | +2424.2 | +4.773 | False |

**CEO sniper interventions:**

```
(none triggered)
```

CEO state NORMAL; all interventions 31.

## Caveats

* **This tape has no trade prints**, so queue consumption is unobservable: `strict`/`depletion` bracket the truth. A real queue also has cancellations ahead of us, hidden/iceberg size and other makers' adverse-selection management, none of which can be observed here.
* Shadow variants use a fixed small paper size and do not move the book; the account attempt is CFO-sized. Hyperliquid is 1 tick wide so penny-jumping applies to Polymarket only.
* One quiet-regime session; cluster-robust s.e. over BTC impulses are shown and power is low.
