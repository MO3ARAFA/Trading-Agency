# Phase 6 Step 1 + live tape — pooled replay of all three recorded sessions

Tapes: p4_tape_1.npz, p5_tape_1.npz, p6_tape_1.npz — total **4197 s**; BTC impulses 142; calm fraction 84%, 93%, 89%. HL maker fee assumed **1.5 bps** (taker 4.5). Cluster s.e. is by BTC impulse across tapes. Trade prints on tape: False, True, True.

## Architecture A — pre-positioned quote maker

### hyperliquid

| variant | round trips | net / trip | hit | net $ | passive exit | fills in shield-cancel window / any cancel window | quotes | shield cancels | shield flattens |
|---|---|---|---|---|---|---|---|---|---|
| shield/strict | 0 | - | - | - | - | - | 2 | 0 | 0 |
| noshield/strict | 0 | - | - | - | - | - | 2 | 0 | 0 |
| shield/depletion | 0 | - | - | - | - | - | 2 | 0 | 0 |
| noshield/depletion | 0 | - | - | - | - | - | 2 | 0 | 0 |
| shield/trades | 0 | - | - | - | - | - | 0 | 0 | 0 |
| noshield/trades | 0 | - | - | - | - | - | 0 | 0 | 0 |

### polymarket

| variant | round trips | net / trip | hit | net $ | passive exit | fills in shield-cancel window / any cancel window | quotes | shield cancels | shield flattens |
|---|---|---|---|---|---|---|---|---|---|
| shield/strict | 521 | -2.97¢ (-647±42 bps) | 25% | -824.78 | 26% | 33 / 303 | 5629 | 2420 | 123 |
| noshield/strict | 743 | -3.47¢ (-746±36 bps) | 27% | -1350.24 | 32% | 0 / 300 | 4345 | 0 | 0 |
| shield/depletion | 2163 | -0.28¢ (-45±23 bps) | 54% | -355.41 | 53% | 57 / 702 | 6080 | 2499 | 378 |
| noshield/depletion | 2644 | -0.37¢ (+65±116 bps) | 57% | -409.78 | 57% | 0 / 754 | 5372 | 0 | 0 |
| shield/trades | 369 | -2.83¢ (-597±47 bps) | 26% | -528.83 | 29% | 20 / 202 | 3442 | 1495 | 70 |
| noshield/trades | 500 | -3.37¢ (-697±41 bps) | 27% | -845.33 | 32% | 0 / 201 | 2547 | 0 | 0 |

ACCOUNT (CFO-gated, adaptive buffer): 40 trips, -3.13¢ (-726±121 bps), net $-71.54.

## Architecture B — high-conviction taker sniper

### hyperliquid

208 signals, **0 pass the absolute floor (0%)**, 208 abstained.

| fill model | variant | attempts | filled | net / fill | hit | net $ | passive exit | scratched | stopped |
|---|---|---|---|---|---|---|---|---|---|
| strict | B all signals (no floor) | 208 | 172 | -6.04±0.33 bps | 0% | -20.46 | 64% | 1 | 1 |
| strict | B floor-failed | 208 | 172 | -6.04±0.33 bps | 0% | -20.46 | 64% | 1 | 1 |
| depletion | B all signals (no floor) | 208 | 172 | -5.95±0.32 bps | 0% | -20.16 | 66% | 1 | 1 |
| depletion | B floor-failed | 208 | 172 | -5.95±0.32 bps | 0% | -20.16 | 66% | 1 | 1 |
| trades | B all signals (no floor) | 116 | 99 | -5.54±0.37 bps | 0% | -10.85 | 74% | 1 | 1 |
| trades | B floor-failed | 116 | 99 | -5.54±0.37 bps | 0% | -10.85 | 74% | 1 | 1 |
| - | taker/taker (all) | 208 | 172 | -8.13±0.17 bps | 0% | -27.57 | 0% | 0 | 0 |

### polymarket

280 signals, **70 pass the absolute floor (25%)**, 210 abstained.

| fill model | variant | attempts | filled | net / fill | hit | net $ | passive exit | scratched | stopped |
|---|---|---|---|---|---|---|---|---|---|
| strict | B all signals (no floor) | 280 | 172 | -2.54¢ (-711±91 bps) | 27% | -600.24 | 28% | 2 | 16 |
| strict | B floor-passed | 70 | 36 | +1.04¢ (+240±175 bps) | 64% | +50.31 | 58% | 0 | 8 |
| strict | B floor-failed | 210 | 136 | -3.49¢ (-962±80 bps) | 17% | -650.55 | 21% | 2 | 8 |
| depletion | B all signals (no floor) | 280 | 172 | -1.95¢ (-573±87 bps) | 30% | -483.32 | 41% | 0 | 14 |
| depletion | B floor-passed | 70 | 36 | +1.08¢ (+245±175 bps) | 64% | +51.07 | 61% | 0 | 8 |
| depletion | B floor-failed | 210 | 136 | -2.75¢ (-790±81 bps) | 21% | -534.39 | 36% | 0 | 6 |
| trades | B all signals (no floor) | 163 | 102 | -1.97¢ (-489±113 bps) | 31% | -250.11 | 35% | 1 | 10 |
| trades | B floor-passed | 42 | 22 | +1.73¢ (+493±192 bps) | 77% | +50.19 | 73% | 0 | 4 |
| trades | B floor-failed | 121 | 80 | -2.99¢ (-759±95 bps) | 19% | -300.30 | 25% | 1 | 6 |
| - | taker/taker (all) | 280 | 172 | -2.91¢ (-821±85 bps) | 15% | -686.57 | 0% | 0 | 0 |
| - | taker/taker (floor-passed) | 70 | 36 | +0.55¢ (+121±186 bps) | 61% | +28.71 | 0% | 0 | 0 |

ACCOUNT: 20 fills, -0.87¢ (-287±657 bps), net $+7.49.

## CEO Phase 6 interventions in these replays

```
22:10:28 MM_DISABLE_VENUE         polymarket   quote-maker net -657.0±246.2bps per round trip after 3 corrections; pulling all quotes on this venue
22:17:03 MM_RAISE_ADVERSE_BUFFER  polymarket   quote-maker net -456.5±225.3bps per round trip < tolerance: CFO adverse buffer 367.199→400bps (quotes only on wider spreads)
22:17:33 B_RAISE_FLOOR            polymarket   fired snipes net -2420.4±2283.3bps per fill < tolerance: absolute floor 1.5x→2x (spread+fees)
22:17:13 MM_EXTEND_SHIELD         polymarket   4/8 round trips were filled inside a *shield* cancel-latency window (net -290.1bps): staying off the vulnerable side 6→7.5s after an impulse
22:25:14 MM_DISABLE_VENUE         polymarket   quote-maker net -921.1±371.4bps per round trip after 3 corrections; pulling all quotes on this venue
```

## Sweep 2 — B's absolute floor multiple (post-hoc on the same shadow rows; the predicted move / floor ratio is stored at 1.5x)

| venue | floor | signals passing | fills | net / fill | hit | net $ |
|---|---|---|---|---|---|---|
| hyperliquid | none | 208 | 172 | -5.96±0.31 bps | 0% | -20.18 |
| hyperliquid | 1x | 0 | 0 | - | - | - |
| hyperliquid | 1.5x | 0 | 0 | - | - | - |
| hyperliquid | 2x | 0 | 0 | - | - | - |
| hyperliquid | 3x | 0 | 0 | - | - | - |
| polymarket | none | 280 | 172 | -2.54¢ (-711±91 bps) | 27% | -600.24 |
| polymarket | 1x | 102 | 53 | +0.34¢ (+109±124 bps) | 60% | +34.39 |
| polymarket | 1.5x | 70 | 36 | +1.04¢ (+240±175 bps) | 64% | +50.31 |
| polymarket | 2x | 52 | 27 | +1.39¢ (+474±208 bps) | 67% | +61.70 |
| polymarket | 3x | 25 | 14 | +2.76¢ (+842±287 bps) | 71% | +57.57 |

## Sweep 1 — cancel latency (Polymarket, the last tape; shield vs identical policy without shield)

The order latency stays 150 ms; only the cancel latency changes. This answers whether the shield fails because the *cancel is too slow* (a latency problem we could engineer away) or because quoting on a lagging venue is adverse even when cancels are instant.

| cancel latency | fill model | trips (shield / none) | net/trip (shield / none) | net $ (shield / none) | shield trips filled inside the cancel window |
|---|---|---|---|---|---|
| 0 ms | strict | 99 / 195 | -3.71¢ (-884±97 bps) / -4.20¢ (-880±67 bps) | -212.6 / -422.4 | 0 |
| 0 ms | trades | 110 / 208 | -3.22¢ (-776±84 bps) / -3.83¢ (-808±63 bps) | -204.1 / -406.6 | 0 |
| 50 ms | strict | 143 / 231 | -2.77¢ (-690±81 bps) / -3.68¢ (-806±62 bps) | -232.9 / -448.0 | 4 |
| 50 ms | trades | 146 / 238 | -2.62¢ (-658±80 bps) / -3.50¢ (-770±61 bps) | -231.1 / -441.2 | 4 |
| 150 ms | strict | 154 / 237 | -2.88¢ (-689±74 bps) / -3.59¢ (-780±61 bps) | -259.9 / -456.4 | 10 |
| 150 ms | trades | 163 / 246 | -2.65¢ (-639±72 bps) / -3.38¢ (-740±60 bps) | -250.0 / -438.9 | 11 |
| 300 ms | strict | 162 / 238 | -2.96¢ (-704±75 bps) / -3.64¢ (-796±62 bps) | -278.6 / -465.1 | 15 |
| 300 ms | trades | 169 / 247 | -2.76¢ (-661±73 bps) / -3.41¢ (-749±61 bps) | -277.6 / -454.3 | 15 |
