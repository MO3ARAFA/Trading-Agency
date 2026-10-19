> **Note:** raw live record. The CFO-accounted PM trades here were sized by notional, which under-sized the risk of a *short* binary (one short of Up at 0.33 lost $367.8, tripping the 2% breaker and the CEO halt). Fixed afterwards (worst-case-loss sizing + 60 s expiry guard); `../phase5_replayB_final/` is the same tape through the fixed code. Shadow-variant tables are unaffected by sizing.

# Quant Agency — Phase 5 report: queue-aware passive maker sniper

* mode **live**, duration **1500s**; markets: Binance BTC oracle, **9 Hyperliquid perps**, **83 Polymarket BTC markets**; trade prints recorded: **8356** (real fills are modelled from prints).
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
| taker/taker | 35 | 31 | 89% | -9.11±0.88 | 0% | -8.06±0.82 | +1.52 | 0 | 0 |
| taker/passive | 35 | 31 | 89% | -6.54±0.85 | 0% | -5.79±0.69 | +1.80 | 0 | 0 |
| join/taker-exit+shield | 35 | 1 | 3% | -6.00±0.00 | 0% | -0.17±0.14 | -0.00 | 0 | 16 |
| join/passive noshield | 35 | 1 | 3% | -7.68±0.00 | 0% | -0.22±0.18 | -0.00 | 0 | 0 |
| join/passive+shield | 35 | 1 | 3% | -7.68±0.00 | 0% | -0.22±0.18 | -0.00 | 0 | 16 |
| penny/passive+shield | 35 | 1 | 3% | -7.68±0.00 | 0% | -0.22±0.18 | -0.00 | 0 | 16 |

**fill model: `depletion`**

| variant | attempts | filled | fill rate | net bps / fill ±s.e. | hit | net bps / attempt ±s.e. | 5s markout after fill (bps) | fills in cancel window | shield cancels |
|---|---|---|---|---|---|---|---|---|---|
| taker/taker | 35 | 31 | 89% | -9.11±0.88 | 0% | -8.06±0.82 | +1.52 | 0 | 0 |
| taker/passive | 35 | 31 | 89% | -6.54±0.85 | 0% | -5.79±0.69 | +1.78 | 0 | 0 |
| join/taker-exit+shield | 35 | 2 | 6% | -7.57±1.57 | 0% | -0.43±0.38 | +0.31 | 0 | 16 |
| join/passive noshield | 35 | 2 | 6% | -6.79±0.89 | 0% | -0.39±0.28 | +0.31 | 0 | 0 |
| join/passive+shield | 35 | 2 | 6% | -6.79±0.89 | 0% | -0.39±0.28 | +0.31 | 0 | 16 |
| penny/passive+shield | 35 | 4 | 11% | -4.55±1.73 | 25% | -0.52±0.27 | +1.57 | 0 | 15 |

**fill model: `trades`**

| variant | attempts | filled | fill rate | net bps / fill ±s.e. | hit | net bps / attempt ±s.e. | 5s markout after fill (bps) | fills in cancel window | shield cancels |
|---|---|---|---|---|---|---|---|---|---|
| taker/taker | 35 | 31 | 89% | -9.11±0.88 | 0% | -8.06±0.82 | +1.52 | 0 | 0 |
| taker/passive | 35 | 31 | 89% | -6.42±0.82 | 0% | -5.69±0.58 | +1.76 | 0 | 0 |
| join/taker-exit+shield | 35 | 1 | 3% | -6.00±0.00 | 0% | -0.17±0.14 | -0.00 | 0 | 16 |
| join/passive noshield | 35 | 1 | 3% | -7.68±0.00 | 0% | -0.22±0.18 | -0.00 | 0 | 0 |
| join/passive+shield | 35 | 1 | 3% | -7.68±0.00 | 0% | -0.22±0.18 | -0.00 | 0 | 16 |
| penny/passive+shield | 35 | 1 | 3% | -7.68±0.00 | 0% | -0.22±0.18 | -0.00 | 0 | 16 |

## Polymarket CLOB (post-only, 0 maker fee)

81 signals; every variant below runs on **exactly these signals** with identical paper size ($50).

**fill model: `strict`**

| variant | attempts | filled | fill rate | net bps / fill ±s.e. | net ¢/share / fill | hit | net bps / attempt ±s.e. | 5s markout after fill (bps) | fills in cancel window | shield cancels |
|---|---|---|---|---|---|---|---|---|---|---|
| taker/taker | 81 | 54 | 67% | -674.70±215.59 | -2.85 | 13% | -449.80±123.53 | +117.44 | 0 | 0 |
| taker/passive | 81 | 54 | 67% | -648.27±170.19 | -2.83 | 19% | -432.18±116.92 | +110.49 | 0 | 0 |
| join/taker-exit+shield | 81 | 7 | 9% | -2347.68±1151.04 | -9.50 | 14% | -202.89±77.54 | -1610.88 | 0 | 51 |
| join/passive noshield | 81 | 9 | 11% | -1941.94±948.14 | -8.34 | 0% | -215.77±76.43 | -1272.29 | 0 | 0 |
| join/passive+shield | 81 | 7 | 9% | -2441.92±1082.39 | -10.25 | 0% | -211.03±76.04 | -1610.88 | 0 | 51 |
| penny/passive+shield | 81 | 6 | 7% | -2627.10±1095.11 | -10.07 | 0% | -194.60±75.07 | -1693.09 | 0 | 50 |

**fill model: `depletion`**

| variant | attempts | filled | fill rate | net bps / fill ±s.e. | net ¢/share / fill | hit | net bps / attempt ±s.e. | 5s markout after fill (bps) | fills in cancel window | shield cancels |
|---|---|---|---|---|---|---|---|---|---|---|
| taker/taker | 81 | 54 | 67% | -674.70±215.59 | -2.85 | 13% | -449.80±123.53 | +117.44 | 0 | 0 |
| taker/passive | 81 | 54 | 67% | -575.12±169.47 | -2.47 | 22% | -383.42±117.92 | +71.39 | 0 | 0 |
| join/taker-exit+shield | 81 | 17 | 21% | -829.09±400.52 | -2.92 | 41% | -174.01±89.36 | -139.02 | 8 | 45 |
| join/passive noshield | 81 | 22 | 27% | -571.47±304.48 | -2.23 | 41% | -155.22±91.43 | -152.38 | 10 | 0 |
| join/passive+shield | 81 | 17 | 21% | -814.54±388.18 | -3.09 | 41% | -170.95±89.98 | -248.98 | 8 | 45 |
| penny/passive+shield | 81 | 30 | 37% | -568.23±232.87 | -2.02 | 27% | -210.45±92.80 | -14.56 | 7 | 35 |

**fill model: `trades`**

| variant | attempts | filled | fill rate | net bps / fill ±s.e. | net ¢/share / fill | hit | net bps / attempt ±s.e. | 5s markout after fill (bps) | fills in cancel window | shield cancels |
|---|---|---|---|---|---|---|---|---|---|---|
| taker/taker | 81 | 54 | 67% | -674.70±215.59 | -2.85 | 13% | -449.80±123.53 | +117.44 | 0 | 0 |
| taker/passive | 81 | 54 | 67% | -648.27±170.19 | -2.83 | 19% | -432.18±116.92 | +110.49 | 0 | 0 |
| join/taker-exit+shield | 81 | 8 | 10% | -1815.77±1131.06 | -6.53 | 25% | -179.34±88.82 | -1051.19 | 0 | 50 |
| join/passive noshield | 81 | 10 | 12% | -1654.41±881.25 | -6.81 | 10% | -204.25±80.02 | -1005.06 | 0 | 0 |
| join/passive+shield | 81 | 8 | 10% | -2020.02±1010.00 | -8.09 | 12% | -199.51±79.61 | -1234.52 | 0 | 50 |
| penny/passive+shield | 81 | 7 | 9% | -2118.46±1014.88 | -7.63 | 14% | -183.08±78.58 | -1251.22 | 0 | 49 |

## Mechanics: why orders do or don't fill, and where the edge goes

**Signalled gap vs the price grid** — if the whole gap is smaller than one tick, a resting order cannot capture it: it only fills after the book has already moved a tick.

| venue | signals | median |gap| bps | median spread bps | median gap / tick | signals with gap < 1 tick |
|---|---|---|---|---|---|
| hyperliquid | 35 | 3.1 | 0.50 | 8.91 | 0% |
| polymarket | 81 | 287.4 | 215.05 | 1.43 | 0% |

**`join/passive+shield`: no-fill reasons, exit mix, gross and fees per fill (bps of notional):**

| venue | model | attempts | not filled because | exit mix of fills | gross bps / fill | fees bps / fill |
|---|---|---|---|---|---|---|
| hyperliquid | strict | 35 | ttl=18, converged=16 | taker=1 | -1.68 | 6.00 |
| hyperliquid | depletion | 35 | ttl=17, converged=16 | taker=2 | -0.79 | 6.00 |
| hyperliquid | trades | 35 | ttl=18, converged=16 | taker=1 | -1.68 | 6.00 |
| polymarket | strict | 81 | converged=48, ttl=23, shield=3 | taker=7 | -2194.36 | 247.55 |
| polymarket | depletion | 81 | converged=42, ttl=19, shield=3 | taker=12, passive=5 | -617.26 | 185.35 |
| polymarket | trades | 81 | converged=47, ttl=23, shield=3 | taker=7, passive=1 | -1803.40 | 216.61 |

## Does the oracle cancel shield earn its keep?

| venue | fill model | fill rate (shield vs none) | net bps/fill | net bps/attempt | 5s markout after fill | orders pulled |
|---|---|---|---|---|---|---|
| hyperliquid | strict | 3% vs 3% | -7.68 vs -7.68 | -0.22 vs -0.22 | -0.00 vs -0.00 | 16 |
| hyperliquid | depletion | 6% vs 6% | -6.79 vs -6.79 | -0.39 vs -0.39 | +0.31 vs +0.31 | 16 |
| hyperliquid | trades | 3% vs 3% | -7.68 vs -7.68 | -0.22 vs -0.22 | -0.00 vs -0.00 | 16 |
| polymarket | strict | 9% vs 11% | -2441.92 vs -1941.94 | -211.03 vs -215.77 | -1610.88 vs -1272.29 | 51 |
| polymarket | depletion | 21% vs 27% | -814.54 vs -571.47 | -170.95 vs -155.22 | -248.98 vs -152.38 | 45 |
| polymarket | trades | 10% vs 12% | -2020.02 vs -1654.41 | -199.51 vs -204.25 | -1234.52 vs -1005.06 | 50 |

## Adverse selection: filled orders vs the same signals' unconditional markout

`unconditional` = mid-to-mid gross markout at t+5s of *all* signals on that venue (what a taker captures before costs); `conditional` = markout after a passive fill. A negative gap is the adverse-selection tax on maker fills.

| venue | fill model | n signals | unconditional gross bps | n fills | conditional markout bps | adverse-selection gap |
|---|---|---|---|---|---|---|
| hyperliquid | strict | 35 | +2.30 | 1 | -0.00 | -2.30 |
| hyperliquid | depletion | 35 | +2.30 | 2 | +0.31 | -1.99 |
| hyperliquid | trades | 35 | +2.30 | 1 | -0.00 | -2.30 |
| polymarket | strict | 81 | +252.55 | 7 | -1610.88 | -1863.43 |
| polymarket | depletion | 81 | +252.55 | 17 | -248.98 | -501.53 |
| polymarket | trades | 81 | +252.55 | 8 | -1234.52 | -1487.07 |

## Cancel-latency adverse fills

| venue | fill model | shield-variant fills | of which inside the cancel window | mean net bps (inside) | mean net bps (other fills) |
|---|---|---|---|---|---|
| hyperliquid | strict | 3 | 0 | - | -7.12 |
| hyperliquid | depletion | 8 | 0 | - | -5.86 |
| hyperliquid | trades | 3 | 0 | - | -7.12 |
| polymarket | strict | 20 | 0 | - | -2464.49 |
| polymarket | depletion | 64 | 23 | -518.50 | -806.42 |
| polymarket | trades | 23 | 0 | - | -1978.94 |

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
| Phase 5 `taker/taker` baseline | 81 | 100% | -2.85 | - |
| Phase 5 join/passive+shield, strict | 81 | 9% | -10.25 | -0.89 |
| Phase 5 penny/passive+shield, strict | 81 | 7% | -10.07 | -0.75 |
| Phase 5 join/passive+shield, depletion | 81 | 21% | -3.09 | -0.65 |
| Phase 5 penny/passive+shield, depletion | 81 | 37% | -2.02 | -0.75 |
| Phase 5 join/passive+shield, trades | 81 | 10% | -8.09 | -0.80 |
| Phase 5 penny/passive+shield, trades | 81 | 9% | -7.63 | -0.66 |

## CFO-accounted maker attempts and CEO monitoring

account attempts 13, filled 3 (23%), net PnL $-396.59, equity $9,603.41; learned P(fill) 0.29, P(passive exit) 0.46, adverse buffers {'hyperliquid': 0.3, 'polymarket': 400.0}, CFO reasons: net_edge_below_hurdle=45, halted=43, quarantined=14, ok=13, breaker_market=2, in_position=1

| market | side | entry | mode | wait s | entry px | exit px | exit | net bps | net $ | in cancel window |
|---|---|---|---|---|---|---|---|---|---|---|
| pm:btc-updown-5m-1792441500:updown_5m | L | join | trades | 1.3 | 0.88 | 0.82 | taker | -799.2 | -39.961 | False |
| pm:btc-updown-5m-1792441800:updown_5m | S | join | trades | 0.8 | 0.33 | 0.69 | taker | -11362.8 | -367.815 | False |
| pm:btc-updown-5m-1792442700:updown_5m | S | join | trades | 0.2 | 0.75 | 0.68 | passive | +933.3 | +11.191 | False |

**CEO sniper interventions:**

```
(none triggered)
```

CEO state HALTED; all interventions 12.

## Caveats

* Real trade prints were recorded for Hyperliquid and Polymarket in this session; Polymarket aggressor side is inferred from price vs mid. A real queue also has cancellations ahead of us, hidden/iceberg size and other makers' adverse-selection management, none of which can be observed here.
* Shadow variants use a fixed small paper size and do not move the book; the account attempt is CFO-sized. Hyperliquid is 1 tick wide so penny-jumping applies to Polymarket only.
* One quiet-regime session; cluster-robust s.e. over BTC impulses are shown and power is low.
