# Phase 7 — synthetic quiet world, exit policies (3 seeds x 600 s; MECHANISM CHECK, not market evidence)

Tapes: quiet_s1.npz, quiet_s2.npz, quiet_s3.npz — total **1800 s**. Pure Architecture B (Architecture A is not instantiated), floor 1.5× (spread + taker-in + maker-out fee) tagged on every shadow row with a *fixed* reference; HL fees 1.5 / 4.5 bps assumed. Every exit policy below ran on **identical entries** (same signals, same IOC taker fill), so differences are the exit alone. t = mean / cluster-robust s.e. (clusters = BTC impulses).

Exit policies: `fixed0.7` = Phase 6 reference (maker TP at 0.7× the credited gap, 8–10 s window) · `fixed1.0` = maker TP at 1.0× · `wide1.5`/`wide2.0` = maker TP at 1.5×/2.0× with a 20–25 s horizon · `adaptive` = start 1.0×, widen to 1.5× then 2.0× each time Binance extends the impulse by another 20 % beyond the signal level (cancel latency charged, re-post only after the cancel lands) · `trail` = no resting TP, stay while Binance velocity is supportive, exit passively at the touch when the venue has done the credited gap and Binance 1 s velocity has faded (or on a 40 % give-back of peak progress / a stall); reversal, adverse and time stops apply to all.

*Metric note:* `net / fill` shows the mean in ¢ per share and in bps of notional. Shadow rows use a fixed notional, so bps of notional (and the $ column) is the sizing-consistent measure; ¢/share weights high-priced contracts more and bps weights cheap contracts more, so on small samples the two can disagree in sign — both t-statistics are shown and neither is a substitute for more fills.

## polymarket

421 signals; **0 (0%) clear the 1.5× floor**.

No signal clears the floor: B abstains here. The 'all signals' rows show what the refused signals would have done.

**fill model `strict`**

| subset | exit | fills | net / fill | cluster s.e. (bps) | t (bps of notional) | t (¢/share) | hit | net $ | gross bps | passive exit | hold s | top exits |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| all signals | fixed0.7 | 342 | -1.81¢ (-384 bps) | ±42 | -9.08 | -9.29 | 29% | -646.25 | +86 | 66% | 5.1 | passive_fill=224, work_expired=65, reversal_stop=51 |
| all signals | fixed1.0 | 342 | -2.04¢ (-430 bps) | ±51 | -8.37 | -8.41 | 51% | -727.43 | +85 | 53% | 6.2 | passive_fill=181, work_expired=90, reversal_stop=69 |
| all signals | wide1.5 | 342 | -1.67¢ (-353 bps) | ±62 | -5.72 | -5.84 | 54% | -599.67 | +148 | 57% | 9.0 | passive_fill=195, reversal_stop=96, work_expired=48 |
| all signals | wide2.0 | 342 | -1.85¢ (-405 bps) | ±70 | -5.78 | -5.80 | 45% | -689.38 | +133 | 47% | 11.1 | passive_fill=161, reversal_stop=111, work_expired=67 |
| all signals | adaptive | 342 | -1.81¢ (-399 bps) | ±69 | -5.75 | -5.78 | 46% | -677.55 | +137 | 48% | 10.9 | passive_fill=163, reversal_stop=109, work_expired=67 |
| all signals | trail | 342 | -2.26¢ (-486 bps) | ±34 | -14.40 | -15.13 | 14% | -818.23 | +53 | 46% | 3.5 | trail_capture=169, trail_retrace=166, reversal_stop=4 |
| all signals | taker/taker | 342 | -3.62¢ (-783 bps) | ±23 | -34.18 | -41.34 | 0% | -1312.99 | -79 | 0% | 1.5 | take_profit=335, adverse_stop=5, end_of_run=2 |

**fill model `depletion`**

| subset | exit | fills | net / fill | cluster s.e. (bps) | t (bps of notional) | t (¢/share) | hit | net $ | gross bps | passive exit | hold s | top exits |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| all signals | fixed0.7 | 342 | -0.75¢ (-159 bps) | ±32 | -5.02 | -5.23 | 43% | -267.21 | +231 | 89% | 2.7 | passive_fill=303, reversal_stop=22, work_expired=15 |
| all signals | fixed1.0 | 342 | -0.86¢ (-179 bps) | ±43 | -4.15 | -4.35 | 70% | -302.95 | +254 | 76% | 4.2 | passive_fill=260, reversal_stop=40, work_expired=40 |
| all signals | wide1.5 | 342 | -0.75¢ (-153 bps) | ±53 | -2.92 | -3.10 | 65% | -261.51 | +281 | 76% | 6.5 | passive_fill=259, reversal_stop=68, work_expired=13 |
| all signals | wide2.0 | 342 | -0.76¢ (-154 bps) | ±64 | -2.40 | -2.56 | 57% | -266.92 | +306 | 68% | 8.2 | passive_fill=232, reversal_stop=87, work_expired=20 |
| all signals | adaptive | 342 | -0.69¢ (-138 bps) | ±59 | -2.33 | -2.52 | 62% | -237.57 | +309 | 72% | 7.2 | passive_fill=245, reversal_stop=75, work_expired=19 |
| all signals | trail | 342 | -1.23¢ (-263 bps) | ±31 | -8.50 | -8.90 | 31% | -441.37 | +175 | 75% | 2.5 | trail_capture=169, trail_retrace=166, reversal_stop=4 |
| all signals | taker/taker | 342 | -3.62¢ (-783 bps) | ±23 | -34.18 | -41.34 | 0% | -1312.99 | -79 | 0% | 1.5 | take_profit=335, adverse_stop=5, end_of_run=2 |

**fill model `trades`**

| subset | exit | fills | net / fill | cluster s.e. (bps) | t (bps of notional) | t (¢/share) | hit | net $ | gross bps | passive exit | hold s | top exits |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| all signals | fixed0.7 | 342 | -1.51¢ (-320 bps) | ±40 | -8.02 | -8.24 | 33% | -537.12 | +127 | 72% | 4.6 | passive_fill=245, work_expired=51, reversal_stop=44 |
| all signals | fixed1.0 | 342 | -1.72¢ (-366 bps) | ±48 | -7.69 | -7.74 | 56% | -618.75 | +127 | 59% | 5.8 | passive_fill=201, work_expired=77, reversal_stop=62 |
| all signals | wide1.5 | 342 | -1.48¢ (-318 bps) | ±60 | -5.29 | -5.34 | 57% | -540.46 | +170 | 61% | 8.5 | passive_fill=208, reversal_stop=91, work_expired=41 |
| all signals | wide2.0 | 342 | -1.62¢ (-359 bps) | ±69 | -5.19 | -5.17 | 48% | -610.93 | +162 | 52% | 10.5 | passive_fill=175, reversal_stop=107, work_expired=57 |
| all signals | adaptive | 342 | -1.59¢ (-351 bps) | ±68 | -5.19 | -5.18 | 49% | -597.00 | +166 | 52% | 10.2 | passive_fill=178, reversal_stop=105, work_expired=56 |
| all signals | trail | 342 | -2.04¢ (-440 bps) | ±33 | -13.52 | -14.23 | 16% | -741.74 | +76 | 52% | 3.4 | trail_capture=169, trail_retrace=166, reversal_stop=4 |
| all signals | taker/taker | 342 | -3.62¢ (-783 bps) | ±23 | -34.18 | -41.34 | 0% | -1312.99 | -79 | 0% | 1.5 | take_profit=335, adverse_stop=5, end_of_run=2 |

## hyperliquid

202 signals; **0 (0%) clear the 1.5× floor**.

No signal clears the floor: B abstains here. The 'all signals' rows show what the refused signals would have done.

**fill model `strict`**

| subset | exit | fills | net / fill | cluster s.e. (bps) | t (bps of notional) | t (¢/share) | hit | net $ | gross bps | passive exit | hold s | top exits |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| all signals | fixed0.7 | 175 | -3.71 bps | ±0.16 | -23.70 | -19.53 | 0% | -12.98 | +2.5 | 93% | 1.0 | passive_fill=162, target_passed=8, reversal_stop=5 |
| all signals | fixed1.0 | 175 | -3.34 bps | ±0.29 | -11.36 | -10.69 | 1% | -11.70 | +3.2 | 83% | 2.7 | passive_fill=146, reversal_stop=13, work_expired=10 |
| all signals | wide1.5 | 175 | -3.43 bps | ±0.50 | -6.81 | -6.37 | 21% | -12.02 | +3.5 | 68% | 6.4 | passive_fill=118, reversal_stop=33, target_passed=13 |
| all signals | wide2.0 | 175 | -3.69 bps | ±0.59 | -6.26 | -5.58 | 26% | -12.90 | +3.8 | 51% | 9.8 | passive_fill=87, reversal_stop=39, work_expired=31 |
| all signals | adaptive | 175 | -3.55 bps | ±0.50 | -7.10 | -5.79 | 24% | -12.41 | +3.7 | 59% | 7.9 | passive_fill=101, reversal_stop=28, work_expired=26 |
| all signals | trail | 175 | -3.89 bps | ±0.34 | -11.40 | -10.06 | 7% | -13.61 | +3.6 | 52% | 2.7 | trail_capture=128, trail_retrace=45, reversal_stop=2 |
| all signals | taker/taker | 175 | -5.77 bps | ±0.11 | -53.87 | -50.21 | 0% | -20.21 | +3.2 | 0% | 0.8 | take_profit=175 |

**fill model `depletion`**

| subset | exit | fills | net / fill | cluster s.e. (bps) | t (bps of notional) | t (¢/share) | hit | net $ | gross bps | passive exit | hold s | top exits |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| all signals | fixed0.7 | 175 | -3.71 bps | ±0.16 | -23.70 | -19.53 | 0% | -12.98 | +2.5 | 93% | 1.0 | passive_fill=162, target_passed=8, reversal_stop=5 |
| all signals | fixed1.0 | 175 | -3.34 bps | ±0.29 | -11.36 | -10.69 | 1% | -11.70 | +3.2 | 83% | 2.7 | passive_fill=146, reversal_stop=13, work_expired=10 |
| all signals | wide1.5 | 175 | -3.43 bps | ±0.50 | -6.81 | -6.37 | 21% | -12.02 | +3.5 | 68% | 6.4 | passive_fill=118, reversal_stop=33, target_passed=13 |
| all signals | wide2.0 | 175 | -3.69 bps | ±0.59 | -6.26 | -5.58 | 26% | -12.90 | +3.8 | 51% | 9.8 | passive_fill=87, reversal_stop=39, work_expired=31 |
| all signals | adaptive | 175 | -3.55 bps | ±0.50 | -7.10 | -5.79 | 24% | -12.41 | +3.7 | 59% | 7.9 | passive_fill=101, reversal_stop=28, work_expired=26 |
| all signals | trail | 175 | -3.86 bps | ±0.34 | -11.46 | -10.06 | 7% | -13.52 | +3.6 | 53% | 2.6 | trail_capture=128, trail_retrace=45, reversal_stop=2 |
| all signals | taker/taker | 175 | -5.77 bps | ±0.11 | -53.87 | -50.21 | 0% | -20.21 | +3.2 | 0% | 0.8 | take_profit=175 |

**fill model `trades`**

| subset | exit | fills | net / fill | cluster s.e. (bps) | t (bps of notional) | t (¢/share) | hit | net $ | gross bps | passive exit | hold s | top exits |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| all signals | fixed0.7 | 175 | -3.66 bps | ±0.16 | -23.59 | -19.50 | 0% | -12.80 | +2.5 | 93% | 1.0 | passive_fill=163, target_passed=8, reversal_stop=4 |
| all signals | fixed1.0 | 175 | -3.27 bps | ±0.29 | -11.20 | -10.69 | 1% | -11.44 | +3.2 | 85% | 2.6 | passive_fill=148, reversal_stop=12, work_expired=9 |
| all signals | wide1.5 | 175 | -3.32 bps | ±0.51 | -6.54 | -6.37 | 22% | -11.63 | +3.6 | 70% | 6.1 | passive_fill=121, reversal_stop=33, target_passed=12 |
| all signals | wide2.0 | 175 | -3.66 bps | ±0.59 | -6.17 | -5.58 | 27% | -12.80 | +3.8 | 51% | 9.6 | passive_fill=88, reversal_stop=39, work_expired=30 |
| all signals | adaptive | 175 | -3.37 bps | ±0.50 | -6.78 | -5.78 | 24% | -11.81 | +3.8 | 62% | 7.4 | passive_fill=106, reversal_stop=26, work_expired=23 |
| all signals | trail | 175 | -3.86 bps | ±0.34 | -11.46 | -10.06 | 7% | -13.52 | +3.6 | 53% | 2.6 | trail_capture=128, trail_retrace=45, reversal_stop=2 |
| all signals | taker/taker | 175 | -5.77 bps | ±0.11 | -53.87 | -50.21 | 0% | -20.21 | +3.2 | 0% | 0.8 | take_profit=175 |

## Exit ranking by the pre-registered rule

(The binding pick was made on the first three tapes, before the Phase 7 live session; any later tape only re-ranks and does not change the pick.)

Rule: among the six exits, take the one with the highest pooled **Polymarket floor-passed net bps per fill under `strict`** (the one fill model all tapes support) with n ≥ 30. Ties/near-ties are not adjudicated: a difference smaller than its standard error is noise.

| exit | floor-passed fills | net bps / fill | cluster s.e. | t |
|---|---|---|---|---|
| fixed0.7 | 0 | +nan | nan | +nan |
| fixed1.0 | 0 | +nan | nan | +nan |
| wide1.5 | 0 | +nan | nan | +nan |
| wide2.0 | 0 | +nan | nan | +nan |
| adaptive | 0 | +nan | nan | +nan |
| trail | 0 | +nan | nan | +nan |

**Pick under this data: `None`**


# Phase 7 — synthetic volatile world, exit policies (3 seeds x 600 s; MECHANISM CHECK, not market evidence)

Tapes: volatile_s1.npz, volatile_s2.npz, volatile_s3.npz — total **1800 s**. Pure Architecture B (Architecture A is not instantiated), floor 1.5× (spread + taker-in + maker-out fee) tagged on every shadow row with a *fixed* reference; HL fees 1.5 / 4.5 bps assumed. Every exit policy below ran on **identical entries** (same signals, same IOC taker fill), so differences are the exit alone. t = mean / cluster-robust s.e. (clusters = BTC impulses).

Exit policies: `fixed0.7` = Phase 6 reference (maker TP at 0.7× the credited gap, 8–10 s window) · `fixed1.0` = maker TP at 1.0× · `wide1.5`/`wide2.0` = maker TP at 1.5×/2.0× with a 20–25 s horizon · `adaptive` = start 1.0×, widen to 1.5× then 2.0× each time Binance extends the impulse by another 20 % beyond the signal level (cancel latency charged, re-post only after the cancel lands) · `trail` = no resting TP, stay while Binance velocity is supportive, exit passively at the touch when the venue has done the credited gap and Binance 1 s velocity has faded (or on a 40 % give-back of peak progress / a stall); reversal, adverse and time stops apply to all.

*Metric note:* `net / fill` shows the mean in ¢ per share and in bps of notional. Shadow rows use a fixed notional, so bps of notional (and the $ column) is the sizing-consistent measure; ¢/share weights high-priced contracts more and bps weights cheap contracts more, so on small samples the two can disagree in sign — both t-statistics are shown and neither is a substitute for more fills.

## polymarket

183 signals; **6 (3%) clear the 1.5× floor**.

**fill model `strict`**

| subset | exit | fills | net / fill | cluster s.e. (bps) | t (bps of notional) | t (¢/share) | hit | net $ | gross bps | passive exit | hold s | top exits |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| floor-passed | fixed0.7 | 4 | +10.54¢ (+1436 bps) | ±254 | +5.66 | +6.72 | 100% | +31.01 | +1599 | 100% | 2.9 | passive_fill=4 |
| floor-passed | fixed1.0 | 4 | +7.72¢ (+1003 bps) | ±17 | +57.75 | +55.82 | 100% | +21.07 | +1285 | 50% | 7.5 | passive_fill=2, work_expired=2 |
| floor-passed | wide1.5 | 4 | +3.23¢ (+381 bps) | ±319 | +1.19 | +1.19 | 75% | +7.61 | +660 | 25% | 18.2 | work_expired=3, passive_fill=1 |
| floor-passed | wide2.0 | 4 | +3.23¢ (+381 bps) | ±319 | +1.19 | +1.19 | 75% | +7.61 | +660 | 25% | 18.2 | work_expired=3, passive_fill=1 |
| floor-passed | adaptive | 4 | +5.23¢ (+624 bps) | ±233 | +2.68 | +2.60 | 75% | +12.49 | +904 | 25% | 14.3 | work_expired=3, passive_fill=1 |
| floor-passed | trail | 4 | +11.49¢ (+1534 bps) | ±133 | +11.52 | +19.64 | 100% | +32.71 | +1874 | 0% | 4.7 | trail_capture=4 |
| floor-passed | taker/taker | 4 | +10.65¢ (+1452 bps) | ±369 | +3.94 | +4.20 | 100% | +31.29 | +1802 | 0% | 0.9 | take_profit=4 |
| all signals | fixed0.7 | 119 | +1.17¢ (+325 bps) | ±73 | +4.47 | +3.57 | 87% | +187.06 | +671 | 97% | 1.4 | passive_fill=115, reversal_stop=3, work_expired=1 |
| all signals | fixed1.0 | 119 | +1.71¢ (+506 bps) | ±80 | +6.34 | +6.93 | 97% | +281.31 | +856 | 93% | 1.7 | passive_fill=110, work_expired=6, reversal_stop=3 |
| all signals | wide1.5 | 119 | +1.94¢ (+679 bps) | ±111 | +6.11 | +6.89 | 92% | +377.96 | +1031 | 88% | 2.8 | passive_fill=104, reversal_stop=9, work_expired=6 |
| all signals | wide2.0 | 119 | +2.55¢ (+928 bps) | ±142 | +6.54 | +8.02 | 90% | +512.74 | +1283 | 86% | 3.3 | passive_fill=100, reversal_stop=12, work_expired=7 |
| all signals | adaptive | 119 | +1.72¢ (+568 bps) | ±100 | +5.69 | +6.35 | 92% | +317.61 | +924 | 87% | 2.7 | passive_fill=103, reversal_stop=8, work_expired=6 |
| all signals | trail | 119 | +0.80¢ (+384 bps) | ±177 | +2.17 | +1.62 | 37% | +211.26 | +778 | 77% | 1.6 | trail_retrace=86, trail_capture=32, reversal_stop=1 |
| all signals | taker/taker | 119 | -1.84¢ (-654 bps) | ±194 | -3.37 | -3.00 | 26% | -351.90 | -10 | 0% | 0.6 | take_profit=119 |

**fill model `depletion`**

| subset | exit | fills | net / fill | cluster s.e. (bps) | t (bps of notional) | t (¢/share) | hit | net $ | gross bps | passive exit | hold s | top exits |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| floor-passed | fixed0.7 | 4 | +10.54¢ (+1436 bps) | ±254 | +5.66 | +6.72 | 100% | +31.01 | +1599 | 100% | 0.9 | passive_fill=4 |
| floor-passed | fixed1.0 | 4 | +10.61¢ (+1389 bps) | ±154 | +9.03 | +11.99 | 100% | +29.70 | +1618 | 75% | 5.5 | passive_fill=3, work_expired=1 |
| floor-passed | wide1.5 | 4 | +7.74¢ (+1032 bps) | ±89 | +11.64 | +6.92 | 100% | +22.07 | +1201 | 75% | 16.5 | passive_fill=3, work_expired=1 |
| floor-passed | wide2.0 | 4 | +7.74¢ (+1032 bps) | ±89 | +11.64 | +6.92 | 100% | +22.07 | +1201 | 75% | 16.5 | passive_fill=3, work_expired=1 |
| floor-passed | adaptive | 4 | +11.99¢ (+1576 bps) | ±104 | +15.20 | +31.18 | 100% | +33.66 | +1745 | 75% | 10.1 | passive_fill=3, work_expired=1 |
| floor-passed | trail | 4 | +12.91¢ (+1724 bps) | ±200 | +8.61 | +11.88 | 100% | +36.95 | +2007 | 25% | 4.2 | trail_capture=4 |
| floor-passed | taker/taker | 4 | +10.65¢ (+1452 bps) | ±369 | +3.94 | +4.20 | 100% | +31.29 | +1802 | 0% | 0.9 | take_profit=4 |
| all signals | fixed0.7 | 119 | +1.19¢ (+352 bps) | ±81 | +4.36 | +3.63 | 87% | +199.70 | +692 | 98% | 1.2 | passive_fill=116, reversal_stop=3 |
| all signals | fixed1.0 | 119 | +1.84¢ (+523 bps) | ±83 | +6.31 | +5.82 | 97% | +291.85 | +870 | 97% | 1.5 | passive_fill=114, reversal_stop=3, work_expired=2 |
| all signals | wide1.5 | 119 | +2.37¢ (+732 bps) | ±107 | +6.83 | +8.27 | 96% | +410.66 | +1077 | 95% | 2.4 | passive_fill=112, reversal_stop=4, work_expired=3 |
| all signals | wide2.0 | 119 | +2.89¢ (+969 bps) | ±139 | +6.98 | +9.21 | 93% | +538.81 | +1318 | 92% | 2.6 | passive_fill=108, reversal_stop=8, work_expired=3 |
| all signals | adaptive | 119 | +2.27¢ (+678 bps) | ±109 | +6.24 | +6.31 | 97% | +379.25 | +1022 | 94% | 1.9 | passive_fill=111, reversal_stop=4, target_passed=2 |
| all signals | trail | 119 | +0.93¢ (+426 bps) | ±189 | +2.25 | +1.78 | 38% | +237.63 | +809 | 82% | 1.3 | trail_retrace=86, trail_capture=32, reversal_stop=1 |
| all signals | taker/taker | 119 | -1.84¢ (-654 bps) | ±194 | -3.37 | -3.00 | 26% | -351.90 | -10 | 0% | 0.6 | take_profit=119 |

**fill model `trades`**

| subset | exit | fills | net / fill | cluster s.e. (bps) | t (bps of notional) | t (¢/share) | hit | net $ | gross bps | passive exit | hold s | top exits |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| floor-passed | fixed0.7 | 4 | +10.54¢ (+1436 bps) | ±254 | +5.66 | +6.72 | 100% | +31.01 | +1599 | 100% | 2.9 | passive_fill=4 |
| floor-passed | fixed1.0 | 4 | +7.72¢ (+1003 bps) | ±17 | +57.75 | +55.82 | 100% | +21.07 | +1285 | 50% | 7.5 | passive_fill=2, work_expired=2 |
| floor-passed | wide1.5 | 4 | +3.23¢ (+381 bps) | ±319 | +1.19 | +1.19 | 75% | +7.61 | +660 | 25% | 18.2 | work_expired=3, passive_fill=1 |
| floor-passed | wide2.0 | 4 | +3.23¢ (+381 bps) | ±319 | +1.19 | +1.19 | 75% | +7.61 | +660 | 25% | 18.2 | work_expired=3, passive_fill=1 |
| floor-passed | adaptive | 4 | +5.23¢ (+624 bps) | ±233 | +2.68 | +2.60 | 75% | +12.49 | +904 | 25% | 14.3 | work_expired=3, passive_fill=1 |
| floor-passed | trail | 4 | +11.49¢ (+1534 bps) | ±133 | +11.52 | +19.64 | 100% | +32.71 | +1874 | 0% | 4.7 | trail_capture=4 |
| floor-passed | taker/taker | 4 | +10.65¢ (+1452 bps) | ±369 | +3.94 | +4.20 | 100% | +31.29 | +1802 | 0% | 0.9 | take_profit=4 |
| all signals | fixed0.7 | 119 | +1.19¢ (+352 bps) | ±81 | +4.36 | +3.63 | 87% | +199.70 | +692 | 98% | 1.3 | passive_fill=116, reversal_stop=3 |
| all signals | fixed1.0 | 119 | +1.73¢ (+508 bps) | ±80 | +6.37 | +7.01 | 97% | +282.57 | +858 | 95% | 1.6 | passive_fill=112, work_expired=4, reversal_stop=3 |
| all signals | wide1.5 | 119 | +2.00¢ (+685 bps) | ±111 | +6.19 | +7.15 | 93% | +381.46 | +1037 | 90% | 2.6 | passive_fill=106, reversal_stop=8, work_expired=5 |
| all signals | wide2.0 | 119 | +2.72¢ (+945 bps) | ±141 | +6.72 | +8.86 | 92% | +523.07 | +1299 | 89% | 2.8 | passive_fill=105, reversal_stop=9, work_expired=5 |
| all signals | adaptive | 119 | +1.83¢ (+580 bps) | ±99 | +5.84 | +6.90 | 94% | +324.51 | +934 | 90% | 2.4 | passive_fill=106, reversal_stop=6, work_expired=5 |
| all signals | trail | 119 | +0.80¢ (+384 bps) | ±177 | +2.17 | +1.62 | 37% | +211.26 | +778 | 77% | 1.5 | trail_retrace=86, trail_capture=32, reversal_stop=1 |
| all signals | taker/taker | 119 | -1.84¢ (-654 bps) | ±194 | -3.37 | -3.00 | 26% | -351.90 | -10 | 0% | 0.6 | take_profit=119 |

## hyperliquid

234 signals; **228 (97%) clear the 1.5× floor**.

**fill model `strict`**

| subset | exit | fills | net / fill | cluster s.e. (bps) | t (bps of notional) | t (¢/share) | hit | net $ | gross bps | passive exit | hold s | top exits |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| floor-passed | fixed0.7 | 170 | +11.71 bps | ±0.60 | +19.67 | +18.43 | 97% | +39.83 | +17.9 | 95% | 0.8 | passive_fill=162, adverse_stop=3, reversal_stop=3 |
| floor-passed | fixed1.0 | 170 | +16.96 bps | ±1.17 | +14.46 | +14.57 | 93% | +57.68 | +23.2 | 91% | 1.3 | passive_fill=153, reversal_stop=10, adverse_stop=3 |
| floor-passed | wide1.5 | 170 | +14.94 bps | ±2.61 | +5.71 | +5.78 | 68% | +50.78 | +22.2 | 59% | 7.4 | passive_fill=100, reversal_stop=43, work_expired=15 |
| floor-passed | wide2.0 | 170 | +16.33 bps | ±3.26 | +5.00 | +5.10 | 65% | +55.51 | +24.0 | 43% | 10.4 | passive_fill=72, reversal_stop=46, work_expired=34 |
| floor-passed | adaptive | 170 | +17.80 bps | ±2.00 | +8.89 | +8.95 | 86% | +60.50 | +24.5 | 78% | 4.5 | passive_fill=131, reversal_stop=19, work_expired=13 |
| floor-passed | trail | 170 | +20.98 bps | ±2.11 | +9.96 | +9.65 | 89% | +71.33 | +28.6 | 45% | 2.6 | trail_capture=148, trail_retrace=19, adverse_stop=3 |
| floor-passed | taker/taker | 170 | +16.58 bps | ±1.04 | +15.88 | +15.71 | 97% | +56.37 | +25.6 | 0% | 0.9 | take_profit=164, adverse_stop=6 |
| all signals | fixed0.7 | 176 | +11.85 bps | ±0.58 | +20.28 | +19.05 | 97% | +41.72 | +18.0 | 94% | 0.7 | passive_fill=166, target_passed=4, adverse_stop=3 |
| all signals | fixed1.0 | 176 | +17.04 bps | ±1.14 | +14.97 | +14.84 | 93% | +59.97 | +23.3 | 90% | 1.4 | passive_fill=158, reversal_stop=10, work_expired=4 |
| all signals | wide1.5 | 176 | +14.94 bps | ±2.55 | +5.85 | +5.98 | 69% | +52.57 | +22.1 | 60% | 7.3 | passive_fill=105, reversal_stop=44, work_expired=15 |
| all signals | wide2.0 | 176 | +16.44 bps | ±3.19 | +5.16 | +5.30 | 65% | +57.88 | +24.1 | 44% | 10.2 | passive_fill=77, reversal_stop=47, work_expired=34 |
| all signals | adaptive | 176 | +17.85 bps | ±1.96 | +9.11 | +9.16 | 86% | +62.85 | +24.5 | 78% | 4.4 | passive_fill=136, reversal_stop=20, work_expired=13 |
| all signals | trail | 176 | +20.64 bps | ±2.05 | +10.08 | +9.68 | 90% | +72.67 | +28.3 | 44% | 2.6 | trail_capture=151, trail_retrace=22, adverse_stop=3 |
| all signals | taker/taker | 176 | +16.34 bps | ±1.02 | +15.97 | +15.65 | 97% | +57.51 | +25.3 | 0% | 0.9 | take_profit=170, adverse_stop=6 |

**fill model `depletion`**

| subset | exit | fills | net / fill | cluster s.e. (bps) | t (bps of notional) | t (¢/share) | hit | net $ | gross bps | passive exit | hold s | top exits |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| floor-passed | fixed0.7 | 170 | +11.71 bps | ±0.60 | +19.67 | +18.43 | 97% | +39.83 | +17.9 | 95% | 0.8 | passive_fill=162, adverse_stop=3, reversal_stop=3 |
| floor-passed | fixed1.0 | 170 | +16.96 bps | ±1.17 | +14.46 | +14.57 | 93% | +57.68 | +23.2 | 91% | 1.3 | passive_fill=153, reversal_stop=10, adverse_stop=3 |
| floor-passed | wide1.5 | 170 | +14.94 bps | ±2.61 | +5.71 | +5.78 | 68% | +50.78 | +22.2 | 59% | 7.4 | passive_fill=100, reversal_stop=43, work_expired=15 |
| floor-passed | wide2.0 | 170 | +16.33 bps | ±3.26 | +5.00 | +5.10 | 65% | +55.51 | +24.0 | 43% | 10.4 | passive_fill=72, reversal_stop=46, work_expired=34 |
| floor-passed | adaptive | 170 | +17.80 bps | ±2.00 | +8.89 | +8.95 | 86% | +60.50 | +24.5 | 78% | 4.5 | passive_fill=131, reversal_stop=19, work_expired=13 |
| floor-passed | trail | 170 | +20.98 bps | ±2.11 | +9.96 | +9.65 | 89% | +71.33 | +28.6 | 45% | 2.6 | trail_capture=148, trail_retrace=19, adverse_stop=3 |
| floor-passed | taker/taker | 170 | +16.58 bps | ±1.04 | +15.88 | +15.71 | 97% | +56.37 | +25.6 | 0% | 0.9 | take_profit=164, adverse_stop=6 |
| all signals | fixed0.7 | 176 | +11.85 bps | ±0.58 | +20.28 | +19.05 | 97% | +41.72 | +18.0 | 94% | 0.7 | passive_fill=166, target_passed=4, adverse_stop=3 |
| all signals | fixed1.0 | 176 | +17.04 bps | ±1.14 | +14.97 | +14.84 | 93% | +59.97 | +23.3 | 90% | 1.4 | passive_fill=158, reversal_stop=10, work_expired=4 |
| all signals | wide1.5 | 176 | +14.94 bps | ±2.55 | +5.85 | +5.98 | 69% | +52.57 | +22.1 | 60% | 7.3 | passive_fill=105, reversal_stop=44, work_expired=15 |
| all signals | wide2.0 | 176 | +16.44 bps | ±3.19 | +5.16 | +5.30 | 65% | +57.88 | +24.1 | 44% | 10.2 | passive_fill=77, reversal_stop=47, work_expired=34 |
| all signals | adaptive | 176 | +17.85 bps | ±1.96 | +9.11 | +9.16 | 86% | +62.85 | +24.5 | 78% | 4.4 | passive_fill=136, reversal_stop=20, work_expired=13 |
| all signals | trail | 176 | +20.64 bps | ±2.05 | +10.08 | +9.68 | 90% | +72.67 | +28.3 | 44% | 2.6 | trail_capture=151, trail_retrace=22, adverse_stop=3 |
| all signals | taker/taker | 176 | +16.34 bps | ±1.02 | +15.97 | +15.65 | 97% | +57.51 | +25.3 | 0% | 0.9 | take_profit=170, adverse_stop=6 |

**fill model `trades`**

| subset | exit | fills | net / fill | cluster s.e. (bps) | t (bps of notional) | t (¢/share) | hit | net $ | gross bps | passive exit | hold s | top exits |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| floor-passed | fixed0.7 | 170 | +11.71 bps | ±0.60 | +19.67 | +18.43 | 97% | +39.83 | +17.9 | 95% | 0.8 | passive_fill=162, adverse_stop=3, reversal_stop=3 |
| floor-passed | fixed1.0 | 170 | +16.96 bps | ±1.17 | +14.46 | +14.57 | 93% | +57.68 | +23.2 | 91% | 1.3 | passive_fill=153, reversal_stop=10, adverse_stop=3 |
| floor-passed | wide1.5 | 170 | +14.94 bps | ±2.61 | +5.71 | +5.78 | 68% | +50.78 | +22.2 | 59% | 7.4 | passive_fill=100, reversal_stop=43, work_expired=15 |
| floor-passed | wide2.0 | 170 | +16.33 bps | ±3.26 | +5.00 | +5.10 | 65% | +55.51 | +24.0 | 43% | 10.4 | passive_fill=72, reversal_stop=46, work_expired=34 |
| floor-passed | adaptive | 170 | +17.81 bps | ±2.00 | +8.89 | +8.95 | 86% | +60.56 | +24.5 | 78% | 4.4 | passive_fill=132, reversal_stop=19, work_expired=12 |
| floor-passed | trail | 170 | +20.98 bps | ±2.11 | +9.96 | +9.65 | 89% | +71.33 | +28.6 | 45% | 2.6 | trail_capture=148, trail_retrace=19, adverse_stop=3 |
| floor-passed | taker/taker | 170 | +16.58 bps | ±1.04 | +15.88 | +15.71 | 97% | +56.37 | +25.6 | 0% | 0.9 | take_profit=164, adverse_stop=6 |
| all signals | fixed0.7 | 176 | +11.85 bps | ±0.58 | +20.28 | +19.05 | 97% | +41.72 | +18.0 | 94% | 0.7 | passive_fill=166, target_passed=4, adverse_stop=3 |
| all signals | fixed1.0 | 176 | +17.04 bps | ±1.14 | +14.97 | +14.84 | 93% | +59.97 | +23.3 | 90% | 1.4 | passive_fill=158, reversal_stop=10, work_expired=4 |
| all signals | wide1.5 | 176 | +14.94 bps | ±2.55 | +5.85 | +5.98 | 69% | +52.57 | +22.1 | 60% | 7.3 | passive_fill=105, reversal_stop=44, work_expired=15 |
| all signals | wide2.0 | 176 | +16.44 bps | ±3.19 | +5.16 | +5.30 | 65% | +57.88 | +24.1 | 44% | 10.2 | passive_fill=77, reversal_stop=47, work_expired=34 |
| all signals | adaptive | 176 | +17.87 bps | ±1.96 | +9.12 | +9.16 | 86% | +62.91 | +24.5 | 78% | 4.3 | passive_fill=137, reversal_stop=20, work_expired=12 |
| all signals | trail | 176 | +20.64 bps | ±2.05 | +10.08 | +9.68 | 90% | +72.67 | +28.3 | 44% | 2.6 | trail_capture=151, trail_retrace=22, adverse_stop=3 |
| all signals | taker/taker | 176 | +16.34 bps | ±1.02 | +15.97 | +15.65 | 97% | +57.51 | +25.3 | 0% | 0.9 | take_profit=170, adverse_stop=6 |

## Exit ranking by the pre-registered rule

(The binding pick was made on the first three tapes, before the Phase 7 live session; any later tape only re-ranks and does not change the pick.)

Rule: among the six exits, take the one with the highest pooled **Polymarket floor-passed net bps per fill under `strict`** (the one fill model all tapes support) with n ≥ 30. Ties/near-ties are not adjudicated: a difference smaller than its standard error is noise.

| exit | floor-passed fills | net bps / fill | cluster s.e. | t |
|---|---|---|---|---|
| fixed0.7 | 4 | +1436 | 254 | +5.66 |
| fixed1.0 | 4 | +1003 | 17 | +57.75 |
| wide1.5 | 4 | +381 | 319 | +1.19 |
| wide2.0 | 4 | +381 | 319 | +1.19 |
| adaptive | 4 | +624 | 233 | +2.68 |
| trail | 4 | +1534 | 133 | +11.52 |

**Pick under this data: `None`**

## Isolated risk sleeves

| tape | sleeve | final state | equity | account round trips | closed P&L $ | halts | governor events |
|---|---|---|---|---|---|---|---|
| volatile_s1.npz | hyperliquid_b | NORMAL | $10,039.02 | 68 | 39.02 | 0 | 0 |
| volatile_s1.npz | polymarket_b | NORMAL | $10,050.23 | 4 | 50.23 | 0 | 0 |
| volatile_s2.npz | hyperliquid_b | NORMAL | $10,032.01 | 54 | 32.01 | 0 | 0 |
| volatile_s2.npz | polymarket_b | NORMAL | $10,000.00 | 0 | 0.0 | 0 | 0 |
| volatile_s3.npz | hyperliquid_b | NORMAL | $10,026.92 | 45 | 26.92 | 0 | 0 |
| volatile_s3.npz | polymarket_b | NORMAL | $10,000.00 | 0 | 0.0 | 0 | 0 |


