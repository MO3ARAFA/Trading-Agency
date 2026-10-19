# Phase 6 Step 1b — synthetic lag-world stress test

Open-loop synthetic worlds in the live-tape format (Binance BTC oracle + Hyperliquid-like perps + Polymarket-like digitals + trade prints), 3 seeds x 600 s per cell, replayed through the *unchanged* agency (hunter, PM watcher, CFO, CEO, both engines). `quiet` = 1.5–4 bp impulses every ~12 s; `volatile` = 10–30 bp impulses every ~9 s and 3x the diffusion. The lagging venue's makers reprice 0.8 s (HL) / 1.5 s (PM) after Binance; **informed takers** hit the stale quotes `D_inf` seconds after the Binance move completes (80 % of qualifying impulses) — the cancel-vs-taker race. Our order and cancel latencies are fixed at 150 ms each, so the shield can only protect a quote when (detection + 150 ms) < D_inf. Uninformed flow is Poisson at the touch. Fill model shown: `trades` (queue-aware, prints) unless stated.

## Architecture A on Polymarket-like digitals (net ¢ per round trip, shield vs the identical policy without the shield)

| regime | D_inf (s) | BTC impulses | calm | trips (shield / none) | net/trip (shield / none) | shield value | net $ (shield / none) | strict-model net/trip (shield / none) | shield trips filled inside the shield's cancel window |
|---|---|---|---|---|---|---|---|---|---|
| quiet | 0.05 | 432 | 49% | 83 / 367 | -0.42¢ / -1.80¢ | +1.38¢ | -16.0 / -284.0 | -1.34¢ / -3.02¢ | 3 of 83 |
| quiet | 0.15 | 412 | 49% | 89 / 372 | -1.41¢ / -1.93¢ | +0.52¢ | -67.7 / -424.2 | -2.14¢ / -3.04¢ | 2 of 89 |
| quiet | 0.5 | 360 | 49% | 92 / 377 | -0.42¢ / -1.73¢ | +1.31¢ | -22.2 / -344.7 | -1.80¢ / -3.20¢ | 3 of 92 |
| quiet | 1.0 | 342 | 52% | 115 / 404 | -0.61¢ / -1.70¢ | +1.09¢ | -48.5 / -380.2 | -1.77¢ / -2.76¢ | 2 of 115 |
| volatile | 0.05 | 165 | 72% | 419 / 880 | -1.40¢ / -2.64¢ | +1.24¢ | -398.9 / -1281.7 | -0.83¢ / -3.05¢ | 30 of 419 |
| volatile | 0.15 | 164 | 74% | 190 / 411 | -0.72¢ / -3.29¢ | +2.58¢ | -165.4 / -1355.2 | -0.75¢ / -3.77¢ | 4 of 190 |
| volatile | 0.5 | 192 | 72% | 271 / 566 | -1.25¢ / -2.72¢ | +1.47¢ | -223.5 / -891.0 | -1.79¢ / -3.28¢ | 5 of 271 |
| volatile | 1.0 | 181 | 73% | 497 / 871 | -0.82¢ / -2.79¢ | +1.97¢ | -197.3 / -1357.7 | -1.31¢ / -3.41¢ | 1 of 497 |

## Architecture A on Hyperliquid-like perps (4-tick-wide book, D_inf 0.5 s; the real HL book is 1 tick = 0.04–1.7 bp and is gated out)

| regime | HL maker fee (bp) | trips (shield / none) | net/trip (shield / none) | net $ | passive exit |
|---|---|---|---|---|---|
| quiet | 0.0 | 86 / 111 | -0.8bp / -0.8bp | -1.41 / -1.77 | 45% / 70% |
| quiet | 1.0 | 0 / 0 | - / - | +0.00 / +0.00 | - |
| volatile | 0.0 | 150 / 256 | -1.1bp / -4.4bp | -3.35 / -22.49 | 45% / 57% |
| volatile | 1.0 | 0 / 0 | - / - | +0.00 / +0.00 | - |

## Architecture B on Polymarket-like digitals (net per fill; `trades` model)

| regime | D_inf (s) | signals | pass floor | B floor-passed | B no floor | taker/taker (all) | net $ (floor-passed / no floor) |
|---|---|---|---|---|---|---|---|
| quiet | 0.05 | 474 | 0 (0%) | abstains | -2.27¢ (n=378) | -3.82¢ | +0.0 / -748.9 |
| quiet | 0.15 | 438 | 0 (0%) | abstains | -2.05¢ (n=353) | -3.70¢ | +0.0 / -911.0 |
| quiet | 0.5 | 464 | 0 (0%) | abstains | -2.16¢ (n=383) | -3.61¢ | +0.0 / -828.1 |
| quiet | 1.0 | 435 | 0 (0%) | abstains | -1.40¢ (n=362) | -3.55¢ | +0.0 / -573.7 |
| volatile | 0.05 | 285 | 8 (3%) | -2.50¢ (n=2, hit 50%) | +0.95¢ (n=121) | +3.71¢ | -3.3 / +103.9 |
| volatile | 0.15 | 154 | 8 (5%) | +3.00¢ (n=4, hit 100%) | +0.39¢ (n=78) | +0.84¢ | +19.8 / +95.9 |
| volatile | 0.5 | 194 | 8 (4%) | +4.28¢ (n=5, hit 80%) | +0.84¢ (n=128) | -0.38¢ | +49.5 / +130.5 |
| volatile | 1.0 | 225 | 11 (5%) | -1.55¢ (n=8, hit 50%) | +0.20¢ (n=156) | -1.41¢ | -21.5 / +8.7 |

## Architecture B on Hyperliquid-like perps (1-tick book; net bps per fill)

| regime | D_inf (s) | signals | pass floor | B floor-passed | B no floor | taker/taker (all) |
|---|---|---|---|---|---|---|
| quiet | 0.05 | 195 | 0 (0%) | abstains | -4.2bp (n=167) | -6.3bp |
| quiet | 0.15 | 187 | 0 (0%) | abstains | -4.0bp (n=170) | -6.2bp |
| quiet | 0.5 | 213 | 0 (0%) | abstains | -3.6bp (n=196) | -6.0bp |
| quiet | 1.0 | 221 | 0 (0%) | abstains | -4.1bp (n=209) | -6.1bp |
| volatile | 0.05 | 258 | 255 (99%) | +8.5bp (n=196, hit 96%) | +8.4bp (n=197) | +13.8bp |
| volatile | 0.15 | 225 | 221 (98%) | +8.8bp (n=154, hit 98%) | +8.9bp (n=155) | +14.1bp |
| volatile | 0.5 | 249 | 249 (100%) | +10.0bp (n=187, hit 98%) | +10.0bp (n=187) | +15.3bp |
| volatile | 1.0 | 234 | 234 (100%) | +9.6bp (n=159, hit 96%) | +9.6bp (n=159) | +14.8bp |

## CFO-governed ACCOUNT engines in the same worlds

| world | A-PM trips | A-PM $ | B-PM fills | B-PM $ | A-HL trips | A-HL $ | B-HL fills | B-HL $ |
|---|---|---|---|---|---|---|---|---|
| quiet|D_inf=0.05 | 13 | +8.9 | 0 | +0.0 | 0 | +0.0 | 0 | +0.0 |
| quiet|D_inf=0.15 | 10 | -11.2 | 0 | +0.0 | 0 | +0.0 | 0 | +0.0 |
| quiet|D_inf=0.5 | 14 | -15.6 | 0 | +0.0 | 0 | +0.0 | 0 | +0.0 |
| quiet|D_inf=1.0 | 16 | -1.6 | 0 | +0.0 | 0 | +0.0 | 0 | +0.0 |
| quiet|HLwide|fee=0.0 | 9 | -4.4 | 0 | +0.0 | 16 | -0.0 | 0 | +0.0 |
| quiet|HLwide|fee=1.0 | 9 | -4.5 | 0 | +0.0 | 0 | +0.0 | 0 | +0.0 |
| volatile|D_inf=0.05 | 45 | -84.7 | 2 | -2.4 | 0 | +0.0 | 188 | +66.8 |
| volatile|D_inf=0.15 | 118 | -40.9 | 3 | +12.1 | 0 | +0.0 | 154 | +57.7 |
| volatile|D_inf=0.5 | 42 | -25.9 | 5 | +34.9 | 0 | +0.0 | 181 | +71.7 |
| volatile|D_inf=1.0 | 103 | +1.4 | 5 | -20.2 | 0 | +0.0 | 132 | +59.5 |
| volatile|HLwide|fee=0.0 | 34 | -32.0 | 4 | -0.2 | 6 | -1.1 | 207 | +97.8 |
| volatile|HLwide|fee=1.0 | 34 | -32.0 | 4 | -0.2 | 0 | +0.0 | 206 | +89.1 |
