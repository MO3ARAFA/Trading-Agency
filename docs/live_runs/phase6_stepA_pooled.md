# Phase 6 Step 1 — pooled tape replay

Tapes: p4_tape_1.npz, p5_tape_1.npz — total **2698 s**; BTC impulses 96; calm fraction 84%, 93%. HL maker fee assumed **1.5 bps** (taker 4.5). Cluster s.e. is by BTC impulse across tapes. Trade prints on tape: False, True.

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
| shield/strict | 367 | -3.01¢ (-629±50 bps) | 26% | -564.90 | 28% | 23 / 217 | 3912 | 1592 | 84 |
| noshield/strict | 506 | -3.42¢ (-730±44 bps) | 30% | -893.88 | 35% | 0 / 209 | 3095 | 0 | 0 |
| shield/depletion | 1480 | -0.19¢ (-14±31 bps) | 55% | -127.95 | 54% | 34 / 465 | 4086 | 1584 | 254 |
| noshield/depletion | 1799 | -0.18¢ (+173±170 bps) | 58% | -60.12 | 58% | 0 / 505 | 3709 | 0 | 0 |
| shield/trades | 206 | -2.98¢ (-563±61 bps) | 27% | -278.83 | 30% | 9 / 115 | 1726 | 667 | 30 |
| noshield/trades | 254 | -3.36¢ (-656±56 bps) | 30% | -406.44 | 35% | 0 / 112 | 1295 | 0 | 0 |

ACCOUNT (CFO-gated, adaptive buffer): 24 trips, -3.13¢ (-645±142 bps), net $-46.19.

## Architecture B — high-conviction taker sniper

### hyperliquid

127 signals, **0 pass the absolute floor (0%)**, 127 abstained.

| fill model | variant | attempts | filled | net / fill | hit | net $ | passive exit | scratched | stopped |
|---|---|---|---|---|---|---|---|---|---|
| strict | B all signals (no floor) | 127 | 104 | -6.53±0.44 bps | 0% | -13.27 | 52% | 0 | 0 |
| strict | B floor-failed | 127 | 104 | -6.53±0.44 bps | 0% | -13.27 | 52% | 0 | 0 |
| depletion | B all signals (no floor) | 127 | 104 | -6.38±0.44 bps | 0% | -12.96 | 56% | 0 | 0 |
| depletion | B floor-failed | 127 | 104 | -6.38±0.44 bps | 0% | -12.96 | 56% | 0 | 0 |
| trades | B all signals (no floor) | 35 | 31 | -6.42±0.85 bps | 0% | -3.87 | 48% | 0 | 0 |
| trades | B floor-failed | 35 | 31 | -6.42±0.85 bps | 0% | -3.87 | 48% | 0 | 0 |
| - | taker/taker (all) | 127 | 104 | -8.24±0.25 bps | 0% | -16.76 | 0% | 0 | 0 |

### polymarket

197 signals, **47 pass the absolute floor (24%)**, 150 abstained.

| fill model | variant | attempts | filled | net / fill | hit | net $ | passive exit | scratched | stopped |
|---|---|---|---|---|---|---|---|---|---|
| strict | B all signals (no floor) | 197 | 123 | -3.09¢ (-863±98 bps) | 20% | -517.58 | 19% | 1 | 11 |
| strict | B floor-passed | 47 | 24 | +0.76¢ (+103±213 bps) | 58% | +21.36 | 54% | 0 | 6 |
| strict | B floor-failed | 150 | 99 | -4.02¢ (-1097±87 bps) | 10% | -538.94 | 10% | 1 | 5 |
| depletion | B all signals (no floor) | 197 | 123 | -2.42¢ (-701±97 bps) | 23% | -419.06 | 33% | 0 | 10 |
| depletion | B floor-passed | 47 | 24 | +0.76¢ (+103±213 bps) | 58% | +21.36 | 54% | 0 | 6 |
| depletion | B floor-failed | 150 | 99 | -3.19¢ (-896±93 bps) | 14% | -440.42 | 27% | 0 | 4 |
| trades | B all signals (no floor) | 80 | 53 | -2.70¢ (-638±149 bps) | 19% | -167.44 | 19% | 0 | 5 |
| trades | B floor-passed | 19 | 10 | +1.87¢ (+465±229 bps) | 80% | +21.24 | 80% | 0 | 2 |
| trades | B floor-failed | 61 | 43 | -3.76¢ (-894±114 bps) | 5% | -188.69 | 5% | 0 | 3 |
| - | taker/taker (all) | 197 | 123 | -3.22¢ (-934±100 bps) | 12% | -555.99 | 0% | 0 | 0 |
| - | taker/taker (floor-passed) | 47 | 24 | +0.95¢ (+144±258 bps) | 58% | +23.90 | 0% | 0 | 0 |

ACCOUNT: 16 fills, -0.85¢ (-334±820 bps), net $+8.13.

## CEO Phase 6 interventions in these replays

```
21:38:29 MM_DISABLE_VENUE         polymarket   quote-maker net -657.0±246.2bps per round trip after 3 corrections; pulling all quotes on this venue
21:45:09 MM_RAISE_ADVERSE_BUFFER  polymarket   quote-maker net -456.5±225.3bps per round trip < tolerance: CFO adverse buffer 367.199→400bps (quotes only on wider spreads)
21:45:39 B_RAISE_FLOOR            polymarket   fired snipes net -2420.4±2283.3bps per fill < tolerance: absolute floor 1.5x→2x (spread+fees)
```

## Sweep 2 — B's absolute floor multiple (post-hoc on the same shadow rows; the predicted move / floor ratio is stored at 1.5x)

| venue | floor | signals passing | fills | net / fill | hit | net $ |
|---|---|---|---|---|---|---|
| hyperliquid | none | 127 | 104 | -6.49±0.43 bps | 0% | -13.20 |
| hyperliquid | 1x | 0 | 0 | - | - | - |
| hyperliquid | 1.5x | 0 | 0 | - | - | - |
| hyperliquid | 2x | 0 | 0 | - | - | - |
| hyperliquid | 3x | 0 | 0 | - | - | - |
| polymarket | none | 197 | 123 | -3.09¢ (-863±98 bps) | 20% | -517.58 |
| polymarket | 1x | 68 | 33 | +0.39¢ (+39±159 bps) | 58% | +14.08 |
| polymarket | 1.5x | 47 | 24 | +0.76¢ (+103±213 bps) | 58% | +21.36 |
| polymarket | 2x | 33 | 17 | +1.29¢ (+417±254 bps) | 65% | +35.12 |
| polymarket | 3x | 16 | 10 | +2.43¢ (+700±341 bps) | 70% | +35.07 |

## Sweep 1 — cancel latency (Polymarket, the last tape; shield vs identical policy without shield)

The order latency stays 150 ms; only the cancel latency changes. This answers whether the shield fails because the *cancel is too slow* (a latency problem we could engineer away) or because quoting on a lagging venue is adverse even when cancels are instant.

| cancel latency | fill model | trips (shield / none) | net/trip (shield / none) | net $ (shield / none) | shield trips filled inside the cancel window |
|---|---|---|---|---|---|
| 0 ms | strict | 131 / 194 | -3.23¢ (-593±76 bps) / -4.07¢ (-788±67 bps) | -190.3 / -371.8 | 0 |
| 0 ms | trades | 139 / 205 | -2.95¢ (-544±75 bps) / -3.86¢ (-769±64 bps) | -170.0 / -369.9 | 0 |
| 50 ms | strict | 194 / 243 | -3.19¢ (-605±64 bps) / -3.71¢ (-726±59 bps) | -283.4 / -427.0 | 3 |
| 50 ms | trades | 194 / 250 | -3.01¢ (-575±65 bps) / -3.48¢ (-682±57 bps) | -263.6 / -412.7 | 3 |
| 150 ms | strict | 201 / 245 | -3.17¢ (-604±62 bps) / -3.53¢ (-694±58 bps) | -295.6 / -412.9 | 8 |
| 150 ms | trades | 206 / 254 | -2.98¢ (-563±61 bps) / -3.36¢ (-656±56 bps) | -278.8 / -406.4 | 9 |
| 300 ms | strict | 210 / 248 | -3.15¢ (-601±57 bps) / -3.56¢ (-694±56 bps) | -314.8 / -422.8 | 21 |
| 300 ms | trades | 216 / 257 | -3.08¢ (-588±57 bps) / -3.41¢ (-666±56 bps) | -311.9 / -419.9 | 22 |
