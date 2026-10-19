# Phase 7 — exit policies of Pure Architecture B, pooled replay of the recorded tapes

Tapes: p4_tape_1.npz, p5_tape_1.npz, p6_tape_1.npz — total **4197 s**. Pure Architecture B (Architecture A is not instantiated), floor 1.5× (spread + taker-in + maker-out fee) tagged on every shadow row with a *fixed* reference; HL fees 1.5 / 4.5 bps assumed. Every exit policy below ran on **identical entries** (same signals, same IOC taker fill), so differences are the exit alone. t = mean / cluster-robust s.e. (clusters = BTC impulses).

Exit policies: `fixed0.7` = Phase 6 reference (maker TP at 0.7× the credited gap, 8–10 s window) · `fixed1.0` = maker TP at 1.0× · `wide1.5`/`wide2.0` = maker TP at 1.5×/2.0× with a 20–25 s horizon · `adaptive` = start 1.0×, widen to 1.5× then 2.0× each time Binance extends the impulse by another 20 % beyond the signal level (cancel latency charged, re-post only after the cancel lands) · `trail` = no resting TP, stay while Binance velocity is supportive, exit passively at the touch when the venue has done the credited gap and Binance 1 s velocity has faded (or on a 40 % give-back of peak progress / a stall); reversal, adverse and time stops apply to all.

*Metric note:* `net / fill` shows the mean in ¢ per share and in bps of notional. Shadow rows use a fixed notional, so bps of notional (and the $ column) is the sizing-consistent measure; ¢/share weights high-priced contracts more and bps weights cheap contracts more, so on small samples the two can disagree in sign — both t-statistics are shown and neither is a substitute for more fills.

## polymarket

280 signals; **70 (25%) clear the 1.5× floor**.

**fill model `strict`**

| subset | exit | fills | net / fill | cluster s.e. (bps) | t (bps of notional) | t (¢/share) | hit | net $ | gross bps | passive exit | hold s | top exits |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| floor-passed | fixed0.7 | 36 | +1.04¢ (+240 bps) | ±175 | +1.37 | +1.34 | 64% | +50.31 | +603 | 58% | 4.1 | passive_fill=21, adverse_stop=8, work_expired=7 |
| floor-passed | fixed1.0 | 36 | +2.09¢ (+477 bps) | ±221 | +2.16 | +2.19 | 61% | +90.34 | +858 | 53% | 4.8 | passive_fill=19, work_expired=9, adverse_stop=8 |
| floor-passed | wide1.5 | 36 | +3.08¢ (+749 bps) | ±300 | +2.49 | +2.32 | 58% | +135.75 | +1132 | 50% | 9.7 | passive_fill=18, adverse_stop=12, work_expired=5 |
| floor-passed | wide2.0 | 36 | +3.86¢ (+948 bps) | ±386 | +2.46 | +2.33 | 56% | +172.30 | +1367 | 39% | 12.9 | passive_fill=14, adverse_stop=13, work_expired=8 |
| floor-passed | adaptive | 36 | +3.27¢ (+853 bps) | ±349 | +2.45 | +2.32 | 61% | +155.18 | +1246 | 47% | 10.3 | passive_fill=17, adverse_stop=11, work_expired=7 |
| floor-passed | trail | 36 | +3.96¢ (+851 bps) | ±267 | +3.18 | +3.05 | 64% | +151.67 | +1250 | 47% | 8.2 | trail_capture=21, adverse_stop=8, trail_retrace=6 |
| floor-passed | taker/taker | 36 | +0.55¢ (+121 bps) | ±186 | +0.65 | +0.63 | 61% | +28.71 | +667 | 0% | 5.6 | take_profit=25, adverse_stop=10, time_stop=1 |
| all signals | fixed0.7 | 172 | -2.54¢ (-711 bps) | ±91 | -7.81 | -7.85 | 27% | -600.24 | -136 | 28% | 7.3 | work_expired=106, passive_fill=49, adverse_stop=12 |
| all signals | fixed1.0 | 172 | -2.22¢ (-642 bps) | ±101 | -6.33 | -5.91 | 28% | -545.73 | -61 | 27% | 7.6 | work_expired=110, passive_fill=46, adverse_stop=12 |
| all signals | wide1.5 | 172 | -2.06¢ (-589 bps) | ±116 | -5.07 | -4.42 | 27% | -505.58 | -2 | 24% | 17.6 | work_expired=103, passive_fill=41, adverse_stop=20 |
| all signals | wide2.0 | 172 | -1.82¢ (-533 bps) | ±133 | -4.01 | -3.35 | 26% | -455.84 | +66 | 20% | 18.6 | work_expired=107, passive_fill=35, adverse_stop=21 |
| all signals | adaptive | 172 | -1.94¢ (-556 bps) | ±125 | -4.45 | -3.92 | 29% | -476.69 | +30 | 24% | 17.6 | work_expired=104, passive_fill=42, adverse_stop=19 |
| all signals | trail | 172 | -1.69¢ (-559 bps) | ±119 | -4.70 | -3.40 | 28% | -481.97 | +38 | 22% | 10.9 | trail_capture=77, trail_retrace=60, time_stop=19 |
| all signals | taker/taker | 172 | -2.91¢ (-821 bps) | ±85 | -9.63 | -9.32 | 15% | -686.57 | -161 | 0% | 7.6 | take_profit=135, time_stop=22, adverse_stop=15 |

**fill model `depletion`**

| subset | exit | fills | net / fill | cluster s.e. (bps) | t (bps of notional) | t (¢/share) | hit | net $ | gross bps | passive exit | hold s | top exits |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| floor-passed | fixed0.7 | 36 | +1.08¢ (+245 bps) | ±175 | +1.40 | +1.38 | 64% | +51.07 | +606 | 61% | 3.9 | passive_fill=22, adverse_stop=8, work_expired=6 |
| floor-passed | fixed1.0 | 36 | +2.09¢ (+477 bps) | ±221 | +2.16 | +2.19 | 61% | +90.34 | +858 | 53% | 4.7 | passive_fill=19, work_expired=9, adverse_stop=8 |
| floor-passed | wide1.5 | 36 | +3.08¢ (+749 bps) | ±300 | +2.49 | +2.32 | 58% | +135.75 | +1132 | 50% | 9.5 | passive_fill=18, adverse_stop=12, work_expired=5 |
| floor-passed | wide2.0 | 36 | +3.93¢ (+965 bps) | ±388 | +2.49 | +2.35 | 56% | +175.47 | +1374 | 42% | 12.7 | passive_fill=14, adverse_stop=13, work_expired=8 |
| floor-passed | adaptive | 36 | +3.28¢ (+864 bps) | ±352 | +2.46 | +2.32 | 61% | +157.15 | +1246 | 50% | 10.0 | passive_fill=17, adverse_stop=11, work_expired=7 |
| floor-passed | trail | 36 | +4.24¢ (+931 bps) | ±276 | +3.37 | +3.22 | 67% | +165.51 | +1283 | 58% | 7.8 | trail_capture=21, adverse_stop=8, trail_retrace=6 |
| floor-passed | taker/taker | 36 | +0.55¢ (+121 bps) | ±186 | +0.65 | +0.63 | 61% | +28.71 | +667 | 0% | 5.6 | take_profit=25, adverse_stop=10, time_stop=1 |
| all signals | fixed0.7 | 172 | -1.95¢ (-573 bps) | ±87 | -6.58 | -6.02 | 30% | -483.32 | -44 | 41% | 6.6 | work_expired=86, passive_fill=71, adverse_stop=11 |
| all signals | fixed1.0 | 172 | -2.04¢ (-596 bps) | ±96 | -6.21 | -5.58 | 32% | -506.70 | -29 | 31% | 7.3 | work_expired=103, passive_fill=53, adverse_stop=12 |
| all signals | wide1.5 | 172 | -1.57¢ (-456 bps) | ±115 | -3.98 | -3.36 | 34% | -396.64 | +98 | 33% | 16.4 | work_expired=89, passive_fill=56, adverse_stop=20 |
| all signals | wide2.0 | 172 | -1.68¢ (-485 bps) | ±134 | -3.61 | -3.10 | 27% | -421.96 | +100 | 23% | 18.1 | work_expired=103, passive_fill=39, adverse_stop=21 |
| all signals | adaptive | 172 | -1.60¢ (-461 bps) | ±124 | -3.71 | -3.30 | 34% | -398.42 | +96 | 32% | 16.5 | work_expired=93, passive_fill=54, adverse_stop=18 |
| all signals | trail | 172 | -1.38¢ (-484 bps) | ±119 | -4.07 | -2.78 | 31% | -419.53 | +82 | 30% | 10.7 | trail_capture=77, trail_retrace=60, time_stop=19 |
| all signals | taker/taker | 172 | -2.91¢ (-821 bps) | ±85 | -9.63 | -9.32 | 15% | -686.57 | -161 | 0% | 7.6 | take_profit=135, time_stop=22, adverse_stop=15 |

**fill model `trades`**

| subset | exit | fills | net / fill | cluster s.e. (bps) | t (bps of notional) | t (¢/share) | hit | net $ | gross bps | passive exit | hold s | top exits |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| floor-passed | fixed0.7 | 22 | +1.73¢ (+493 bps) | ±192 | +2.56 | +1.76 | 77% | +50.19 | +795 | 73% | 3.1 | passive_fill=16, adverse_stop=4, work_expired=2 |
| floor-passed | fixed1.0 | 22 | +2.93¢ (+774 bps) | ±269 | +2.88 | +2.41 | 73% | +78.79 | +1107 | 64% | 4.1 | passive_fill=14, adverse_stop=4, work_expired=4 |
| floor-passed | wide1.5 | 22 | +2.65¢ (+782 bps) | ±398 | +1.97 | +1.49 | 55% | +76.30 | +1143 | 55% | 8.4 | passive_fill=12, adverse_stop=8, work_expired=1 |
| floor-passed | wide2.0 | 22 | +3.31¢ (+944 bps) | ±520 | +1.82 | +1.46 | 50% | +95.07 | +1340 | 45% | 11.4 | passive_fill=10, adverse_stop=9, work_expired=2 |
| floor-passed | adaptive | 22 | +2.75¢ (+846 bps) | ±434 | +1.95 | +1.66 | 59% | +83.48 | +1199 | 59% | 7.5 | passive_fill=13, adverse_stop=7, work_expired=1 |
| floor-passed | trail | 22 | +4.83¢ (+1099 bps) | ±335 | +3.28 | +2.77 | 68% | +108.61 | +1483 | 50% | 5.8 | trail_capture=14, adverse_stop=5, trail_retrace=3 |
| floor-passed | taker/taker | 36 | +0.55¢ (+121 bps) | ±186 | +0.65 | +0.63 | 61% | +28.71 | +667 | 0% | 5.6 | take_profit=25, adverse_stop=10, time_stop=1 |
| all signals | fixed0.7 | 102 | -1.97¢ (-489 bps) | ±113 | -4.33 | -4.52 | 31% | -250.11 | -11 | 35% | 6.7 | work_expired=56, passive_fill=36, adverse_stop=6 |
| all signals | fixed1.0 | 102 | -1.61¢ (-414 bps) | ±130 | -3.18 | -3.11 | 33% | -215.08 | +76 | 31% | 7.2 | work_expired=60, passive_fill=32, adverse_stop=6 |
| all signals | wide1.5 | 102 | -1.67¢ (-421 bps) | ±156 | -2.69 | -2.56 | 30% | -223.24 | +76 | 28% | 16.2 | work_expired=53, passive_fill=29, adverse_stop=12 |
| all signals | wide2.0 | 102 | -1.46¢ (-379 bps) | ±180 | -2.10 | -1.90 | 28% | -198.96 | +133 | 25% | 17.2 | work_expired=55, passive_fill=25, adverse_stop=13 |
| all signals | adaptive | 102 | -1.53¢ (-394 bps) | ±165 | -2.39 | -2.29 | 32% | -208.95 | +101 | 30% | 15.9 | work_expired=53, passive_fill=31, adverse_stop=11 |
| all signals | trail | 102 | -0.93¢ (-328 bps) | ±157 | -2.09 | -1.33 | 33% | -179.67 | +183 | 25% | 11.3 | trail_capture=49, trail_retrace=28, time_stop=14 |
| all signals | taker/taker | 172 | -2.91¢ (-821 bps) | ±85 | -9.63 | -9.32 | 15% | -686.57 | -161 | 0% | 7.6 | take_profit=135, time_stop=22, adverse_stop=15 |

## hyperliquid

208 signals; **0 (0%) clear the 1.5× floor**.

No signal clears the floor: B abstains here. The 'all signals' rows show what the refused signals would have done.

**fill model `strict`**

| subset | exit | fills | net / fill | cluster s.e. (bps) | t (bps of notional) | t (¢/share) | hit | net $ | gross bps | passive exit | hold s | top exits |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| all signals | fixed0.7 | 172 | -6.04 bps | ±0.33 | -18.57 | -8.77 | 0% | -20.46 | +1.0 | 64% | 3.7 | passive_fill=110, work_expired=58, target_passed=3 |
| all signals | fixed1.0 | 172 | -6.00 bps | ±0.41 | -14.71 | -8.81 | 0% | -20.33 | +1.3 | 56% | 4.7 | passive_fill=96, work_expired=75, reversal_stop=1 |
| all signals | wide1.5 | 172 | -5.83 bps | ±0.53 | -11.10 | -7.80 | 1% | -19.72 | +1.8 | 47% | 12.4 | work_expired=82, passive_fill=80, reversal_stop=4 |
| all signals | wide2.0 | 172 | -5.74 bps | ±0.57 | -9.99 | -8.06 | 5% | -19.39 | +2.1 | 39% | 13.9 | work_expired=89, passive_fill=67, end_of_run=7 |
| all signals | adaptive | 172 | -5.68 bps | ±0.49 | -11.65 | -8.67 | 3% | -19.21 | +1.7 | 53% | 10.6 | passive_fill=91, work_expired=66, end_of_run=6 |
| all signals | trail | 172 | -6.63 bps | ±0.44 | -15.04 | -8.36 | 1% | -22.44 | +1.6 | 24% | 8.3 | trail_capture=128, trail_retrace=28, time_stop=12 |
| all signals | taker/taker | 172 | -8.13 bps | ±0.17 | -46.54 | -9.34 | 0% | -27.57 | +0.9 | 0% | 5.3 | take_profit=152, time_stop=18, adverse_stop=2 |

**fill model `depletion`**

| subset | exit | fills | net / fill | cluster s.e. (bps) | t (bps of notional) | t (¢/share) | hit | net $ | gross bps | passive exit | hold s | top exits |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| all signals | fixed0.7 | 172 | -5.95 bps | ±0.32 | -18.41 | -8.77 | 0% | -20.16 | +1.1 | 66% | 3.6 | passive_fill=114, work_expired=54, target_passed=3 |
| all signals | fixed1.0 | 172 | -5.87 bps | ±0.40 | -14.52 | -9.28 | 0% | -19.88 | +1.3 | 59% | 4.5 | passive_fill=102, work_expired=69, reversal_stop=1 |
| all signals | wide1.5 | 172 | -5.70 bps | ±0.52 | -10.99 | -7.57 | 1% | -19.27 | +1.8 | 49% | 12.1 | passive_fill=85, work_expired=77, reversal_stop=4 |
| all signals | wide2.0 | 172 | -5.74 bps | ±0.57 | -9.99 | -8.06 | 5% | -19.39 | +2.1 | 39% | 13.9 | work_expired=89, passive_fill=67, end_of_run=7 |
| all signals | adaptive | 172 | -5.57 bps | ±0.48 | -11.53 | -8.67 | 3% | -18.82 | +1.8 | 55% | 10.2 | passive_fill=95, work_expired=64, end_of_run=5 |
| all signals | trail | 172 | -5.71 bps | ±0.47 | -12.06 | -7.80 | 3% | -19.28 | +1.9 | 47% | 7.7 | trail_capture=128, trail_retrace=28, time_stop=12 |
| all signals | taker/taker | 172 | -8.13 bps | ±0.17 | -46.54 | -9.34 | 0% | -27.57 | +0.9 | 0% | 5.3 | take_profit=152, time_stop=18, adverse_stop=2 |

**fill model `trades`**

| subset | exit | fills | net / fill | cluster s.e. (bps) | t (bps of notional) | t (¢/share) | hit | net $ | gross bps | passive exit | hold s | top exits |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| all signals | fixed0.7 | 99 | -5.54 bps | ±0.37 | -14.79 | -8.72 | 0% | -10.85 | +1.2 | 74% | 3.2 | passive_fill=73, work_expired=25, reversal_stop=1 |
| all signals | fixed1.0 | 99 | -5.40 bps | ±0.48 | -11.31 | -8.48 | 0% | -10.58 | +1.6 | 66% | 4.1 | passive_fill=65, work_expired=33, reversal_stop=1 |
| all signals | wide1.5 | 99 | -5.22 bps | ±0.69 | -7.59 | -5.89 | 1% | -10.20 | +2.1 | 58% | 11.2 | passive_fill=55, work_expired=38, reversal_stop=3 |
| all signals | wide2.0 | 99 | -5.30 bps | ±0.72 | -7.31 | -6.43 | 4% | -10.35 | +2.4 | 44% | 13.3 | work_expired=45, passive_fill=44, reversal_stop=5 |
| all signals | adaptive | 99 | -5.24 bps | ±0.59 | -8.81 | -8.03 | 3% | -10.25 | +2.0 | 60% | 9.4 | passive_fill=59, work_expired=31, reversal_stop=4 |
| all signals | trail | 99 | -6.72 bps | ±0.60 | -11.11 | -7.32 | 1% | -13.16 | +1.6 | 23% | 8.2 | trail_capture=72, trail_retrace=13, time_stop=10 |
| all signals | taker/taker | 172 | -8.13 bps | ±0.17 | -46.54 | -9.34 | 0% | -27.57 | +0.9 | 0% | 5.3 | take_profit=152, time_stop=18, adverse_stop=2 |

## Exit ranking by the pre-registered rule

(The binding pick was made on the first three tapes, before the Phase 7 live session; any later tape only re-ranks and does not change the pick.)

Rule: among the six exits, take the one with the highest pooled **Polymarket floor-passed net bps per fill under `strict`** (the one fill model all tapes support) with n ≥ 30. Ties/near-ties are not adjudicated: a difference smaller than its standard error is noise.

| exit | floor-passed fills | net bps / fill | cluster s.e. | t |
|---|---|---|---|---|
| fixed0.7 | 36 | +240 | 175 | +1.37 |
| fixed1.0 | 36 | +477 | 221 | +2.16 |
| wide1.5 | 36 | +749 | 300 | +2.49 |
| wide2.0 | 36 | +948 | 386 | +2.46 |
| adaptive | 36 | +853 | 349 | +2.45 |
| trail | 36 | +851 | 267 | +3.18 |

**Pick under this data: `wide2.0`**

Sample-size check for `wide2.0` (Polymarket, floor-passed, strict): n = 36, mean +948 bps, s.e. 386, t = +2.46. At the same mean and variance, |t| > 2 needs n ≈ **24** floor-passed fills.

## Isolated risk sleeves

| tape | sleeve | final state | equity | account round trips | closed P&L $ | halts | governor events |
|---|---|---|---|---|---|---|---|
| p4_tape_1.npz | hyperliquid_b | NORMAL | $10,000.00 | 0 | 0.0 | 0 | 0 |
| p4_tape_1.npz | polymarket_b | NORMAL | $10,010.87 | 10 | 10.87 | 0 | 0 |
| p5_tape_1.npz | hyperliquid_b | NORMAL | $10,000.00 | 0 | 0.0 | 0 | 0 |
| p5_tape_1.npz | polymarket_b | NORMAL | $10,003.79 | 8 | 3.79 | 0 | 0 |
| p6_tape_1.npz | hyperliquid_b | NORMAL | $10,000.00 | 0 | 0.0 | 0 | 0 |
| p6_tape_1.npz | polymarket_b | NORMAL | $10,018.01 | 10 | 18.01 | 0 | 0 |
