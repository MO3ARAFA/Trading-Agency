# Phase 7 — exit policies of Pure Architecture B, pooled replay of all four recorded sessions

Tapes: p4_tape_1.npz, p5_tape_1.npz, p6_tape_1.npz, p7_tape_1.npz — total **7196 s**. Pure Architecture B (Architecture A is not instantiated), floor 1.5× (spread + taker-in + maker-out fee) tagged on every shadow row with a *fixed* reference; HL fees 1.5 / 4.5 bps assumed. Every exit policy below ran on **identical entries** (same signals, same IOC taker fill), so differences are the exit alone. t = mean / cluster-robust s.e. (clusters = BTC impulses).

Exit policies: `fixed0.7` = Phase 6 reference (maker TP at 0.7× the credited gap, 8–10 s window) · `fixed1.0` = maker TP at 1.0× · `wide1.5`/`wide2.0` = maker TP at 1.5×/2.0× with a 20–25 s horizon · `adaptive` = start 1.0×, widen to 1.5× then 2.0× each time Binance extends the impulse by another 20 % beyond the signal level (cancel latency charged, re-post only after the cancel lands) · `trail` = no resting TP, stay while Binance velocity is supportive, exit passively at the touch when the venue has done the credited gap and Binance 1 s velocity has faded (or on a 40 % give-back of peak progress / a stall); reversal, adverse and time stops apply to all.

*Metric note:* `net / fill` shows the mean in ¢ per share and in bps of notional. Shadow rows use a fixed notional, so bps of notional (and the $ column) is the sizing-consistent measure; ¢/share weights high-priced contracts more and bps weights cheap contracts more, so on small samples the two can disagree in sign — both t-statistics are shown and neither is a substitute for more fills.

## polymarket

398 signals; **111 (28%) clear the 1.5× floor**.

**fill model `strict`**

| subset | exit | fills | net / fill | cluster s.e. (bps) | t (bps of notional) | t (¢/share) | hit | net $ | gross bps | passive exit | hold s | top exits |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| floor-passed | fixed0.7 | 48 | +0.58¢ (+195 bps) | ±177 | +1.10 | +0.67 | 62% | +54.06 | +587 | 58% | 4.6 | passive_fill=27, work_expired=11, adverse_stop=10 |
| floor-passed | fixed1.0 | 48 | +1.50¢ (+407 bps) | ±212 | +1.92 | +1.52 | 60% | +100.23 | +827 | 50% | 5.1 | passive_fill=24, work_expired=14, adverse_stop=10 |
| floor-passed | wide1.5 | 48 | +1.87¢ (+487 bps) | ±302 | +1.62 | +1.35 | 54% | +112.78 | +919 | 48% | 9.8 | passive_fill=23, adverse_stop=19, work_expired=5 |
| floor-passed | wide2.0 | 48 | +2.53¢ (+680 bps) | ±372 | +1.83 | +1.55 | 52% | +156.18 | +1143 | 38% | 12.6 | adverse_stop=20, passive_fill=18, work_expired=9 |
| floor-passed | adaptive | 48 | +2.24¢ (+634 bps) | ±329 | +1.93 | +1.57 | 58% | +148.46 | +1063 | 48% | 10.0 | passive_fill=23, adverse_stop=17, work_expired=7 |
| floor-passed | trail | 48 | +2.90¢ (+680 bps) | ±306 | +2.22 | +2.13 | 60% | +151.67 | +1127 | 44% | 8.3 | trail_capture=26, trail_retrace=11, adverse_stop=10 |
| floor-passed | taker/taker | 48 | +0.14¢ (+152 bps) | ±169 | +0.90 | +0.17 | 65% | +39.23 | +735 | 0% | 5.7 | take_profit=35, adverse_stop=12, time_stop=1 |
| all signals | fixed0.7 | 228 | -2.70¢ (-802 bps) | ±90 | -8.93 | -8.90 | 25% | -896.44 | -206 | 27% | 7.5 | work_expired=141, passive_fill=61, adverse_stop=19 |
| all signals | fixed1.0 | 228 | -2.42¢ (-741 bps) | ±98 | -7.58 | -7.06 | 27% | -834.02 | -137 | 25% | 7.7 | work_expired=147, passive_fill=56, adverse_stop=19 |
| all signals | wide1.5 | 228 | -2.34¢ (-720 bps) | ±117 | -6.14 | -5.40 | 25% | -818.81 | -110 | 23% | 17.6 | work_expired=132, passive_fill=52, adverse_stop=35 |
| all signals | wide2.0 | 228 | -2.15¢ (-669 bps) | ±131 | -5.10 | -4.35 | 24% | -762.32 | -47 | 19% | 18.6 | work_expired=139, passive_fill=43, adverse_stop=36 |
| all signals | adaptive | 228 | -2.20¢ (-680 bps) | ±121 | -5.60 | -4.88 | 27% | -771.88 | -72 | 24% | 17.4 | work_expired=132, passive_fill=54, adverse_stop=33 |
| all signals | trail | 228 | -1.97¢ (-666 bps) | ±119 | -5.58 | -4.43 | 26% | -763.60 | -46 | 20% | 10.7 | trail_capture=98, trail_retrace=83, time_stop=23 |
| all signals | taker/taker | 228 | -3.02¢ (-872 bps) | ±83 | -10.45 | -10.63 | 15% | -972.20 | -195 | 0% | 7.3 | take_profit=178, time_stop=26, adverse_stop=24 |

**fill model `depletion`**

| subset | exit | fills | net / fill | cluster s.e. (bps) | t (bps of notional) | t (¢/share) | hit | net $ | gross bps | passive exit | hold s | top exits |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| floor-passed | fixed0.7 | 48 | +0.61¢ (+198 bps) | ±178 | +1.12 | +0.70 | 62% | +54.81 | +590 | 60% | 4.4 | passive_fill=28, work_expired=10, adverse_stop=10 |
| floor-passed | fixed1.0 | 48 | +1.55¢ (+414 bps) | ±212 | +1.96 | +1.56 | 60% | +102.06 | +830 | 52% | 5.1 | passive_fill=25, work_expired=13, adverse_stop=10 |
| floor-passed | wide1.5 | 48 | +2.04¢ (+531 bps) | ±298 | +1.78 | +1.48 | 56% | +123.32 | +957 | 48% | 9.5 | passive_fill=23, adverse_stop=19, work_expired=5 |
| floor-passed | wide2.0 | 48 | +2.86¢ (+732 bps) | ±374 | +1.96 | +1.73 | 52% | +168.88 | +1183 | 42% | 12.1 | adverse_stop=20, passive_fill=19, work_expired=8 |
| floor-passed | adaptive | 48 | +2.25¢ (+642 bps) | ±330 | +1.94 | +1.58 | 58% | +150.43 | +1064 | 50% | 9.8 | passive_fill=23, adverse_stop=17, work_expired=7 |
| floor-passed | trail | 48 | +3.18¢ (+752 bps) | ±306 | +2.46 | +2.39 | 65% | +168.26 | +1159 | 54% | 7.9 | trail_capture=26, trail_retrace=11, adverse_stop=10 |
| floor-passed | taker/taker | 48 | +0.14¢ (+152 bps) | ±169 | +0.90 | +0.17 | 65% | +39.23 | +735 | 0% | 5.7 | take_profit=35, adverse_stop=12, time_stop=1 |
| all signals | fixed0.7 | 228 | -2.14¢ (-651 bps) | ±82 | -7.90 | -7.12 | 29% | -727.13 | -100 | 39% | 6.8 | work_expired=117, passive_fill=87, adverse_stop=18 |
| all signals | fixed1.0 | 228 | -2.26¢ (-704 bps) | ±95 | -7.37 | -6.66 | 30% | -791.30 | -111 | 29% | 7.4 | work_expired=138, passive_fill=65, adverse_stop=19 |
| all signals | wide1.5 | 228 | -1.89¢ (-598 bps) | ±115 | -5.21 | -4.35 | 32% | -685.47 | -17 | 30% | 16.6 | work_expired=117, passive_fill=68, adverse_stop=35 |
| all signals | wide2.0 | 228 | -1.96¢ (-621 bps) | ±133 | -4.66 | -3.91 | 25% | -714.77 | -12 | 22% | 18.2 | work_expired=133, passive_fill=49, adverse_stop=36 |
| all signals | adaptive | 228 | -1.94¢ (-606 bps) | ±121 | -4.99 | -4.33 | 31% | -691.17 | -20 | 29% | 16.6 | work_expired=121, passive_fill=66, adverse_stop=32 |
| all signals | trail | 228 | -1.61¢ (-578 bps) | ±117 | -4.92 | -3.69 | 29% | -666.44 | +5 | 29% | 10.5 | trail_capture=98, trail_retrace=83, time_stop=23 |
| all signals | taker/taker | 228 | -3.02¢ (-872 bps) | ±83 | -10.45 | -10.63 | 15% | -972.20 | -195 | 0% | 7.3 | take_profit=178, time_stop=26, adverse_stop=24 |

**fill model `trades`**

| subset | exit | fills | net / fill | cluster s.e. (bps) | t (bps of notional) | t (¢/share) | hit | net $ | gross bps | passive exit | hold s | top exits |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| floor-passed | fixed0.7 | 34 | +0.83¢ (+340 bps) | ±212 | +1.60 | +0.75 | 71% | +53.93 | +705 | 68% | 4.1 | passive_fill=22, adverse_stop=6, work_expired=6 |
| floor-passed | fixed1.0 | 34 | +1.80¢ (+570 bps) | ±257 | +2.22 | +1.43 | 68% | +88.68 | +975 | 56% | 4.8 | passive_fill=19, work_expired=9, adverse_stop=6 |
| floor-passed | wide1.5 | 34 | +1.09¢ (+402 bps) | ±385 | +1.04 | +0.62 | 50% | +53.33 | +838 | 50% | 8.8 | passive_fill=17, adverse_stop=15, work_expired=1 |
| floor-passed | wide2.0 | 34 | +1.62¢ (+567 bps) | ±473 | +1.20 | +0.78 | 47% | +78.96 | +1033 | 41% | 11.5 | adverse_stop=16, passive_fill=14, work_expired=3 |
| floor-passed | adaptive | 34 | +1.48¢ (+539 bps) | ±399 | +1.35 | +0.86 | 56% | +76.75 | +958 | 56% | 8.1 | passive_fill=19, adverse_stop=13, work_expired=1 |
| floor-passed | trail | 34 | +3.02¢ (+770 bps) | ±393 | +1.96 | +1.71 | 62% | +108.62 | +1227 | 44% | 6.8 | trail_capture=19, trail_retrace=8, adverse_stop=7 |
| floor-passed | taker/taker | 48 | +0.14¢ (+152 bps) | ±169 | +0.90 | +0.17 | 65% | +39.23 | +735 | 0% | 5.7 | take_profit=35, adverse_stop=12, time_stop=1 |
| all signals | fixed0.7 | 158 | -2.40¢ (-699 bps) | ±114 | -6.13 | -6.16 | 28% | -546.31 | -156 | 31% | 7.1 | work_expired=91, passive_fill=48, adverse_stop=13 |
| all signals | fixed1.0 | 158 | -2.12¢ (-638 bps) | ±125 | -5.11 | -4.78 | 29% | -503.37 | -82 | 27% | 7.5 | work_expired=97, passive_fill=42, adverse_stop=13 |
| all signals | wide1.5 | 158 | -2.22¢ (-670 bps) | ±154 | -4.35 | -3.93 | 27% | -536.48 | -107 | 25% | 16.6 | work_expired=82, passive_fill=40, adverse_stop=27 |
| all signals | wide2.0 | 158 | -2.06¢ (-630 bps) | ±171 | -3.68 | -3.20 | 25% | -505.16 | -53 | 21% | 17.7 | work_expired=87, passive_fill=33, adverse_stop=28 |
| all signals | adaptive | 158 | -2.05¢ (-629 bps) | ±156 | -4.03 | -3.58 | 28% | -504.14 | -71 | 27% | 16.2 | work_expired=81, passive_fill=43, adverse_stop=25 |
| all signals | trail | 158 | -1.60¢ (-564 bps) | ±155 | -3.63 | -2.77 | 28% | -461.30 | +10 | 22% | 10.9 | trail_capture=70, trail_retrace=51, time_stop=18 |
| all signals | taker/taker | 228 | -3.02¢ (-872 bps) | ±83 | -10.45 | -10.63 | 15% | -972.20 | -195 | 0% | 7.3 | take_profit=178, time_stop=26, adverse_stop=24 |

## hyperliquid

317 signals; **0 (0%) clear the 1.5× floor**.

No signal clears the floor: B abstains here. The 'all signals' rows show what the refused signals would have done.

**fill model `strict`**

| subset | exit | fills | net / fill | cluster s.e. (bps) | t (bps of notional) | t (¢/share) | hit | net $ | gross bps | passive exit | hold s | top exits |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| all signals | fixed0.7 | 268 | -6.01 bps | ±0.26 | -22.73 | -11.31 | 0% | -31.70 | +1.1 | 63% | 3.9 | passive_fill=169, work_expired=95, target_passed=3 |
| all signals | fixed1.0 | 268 | -6.05 bps | ±0.32 | -18.99 | -11.21 | 0% | -31.89 | +1.4 | 53% | 4.9 | passive_fill=140, work_expired=127, reversal_stop=1 |
| all signals | wide1.5 | 268 | -6.16 bps | ±0.47 | -13.03 | -9.63 | 1% | -32.48 | +1.6 | 42% | 13.0 | work_expired=127, passive_fill=112, reversal_stop=23 |
| all signals | wide2.0 | 268 | -6.24 bps | ±0.50 | -12.50 | -9.87 | 4% | -32.91 | +1.8 | 31% | 14.9 | work_expired=149, passive_fill=84, reversal_stop=25 |
| all signals | adaptive | 268 | -5.98 bps | ±0.42 | -14.41 | -10.19 | 2% | -31.56 | +1.6 | 47% | 11.4 | passive_fill=126, work_expired=110, reversal_stop=22 |
| all signals | trail | 268 | -6.63 bps | ±0.35 | -19.00 | -11.28 | 1% | -35.01 | +1.6 | 26% | 8.3 | trail_capture=193, trail_retrace=49, time_stop=18 |
| all signals | taker/taker | 268 | -8.17 bps | ±0.18 | -45.51 | -12.33 | 0% | -43.15 | +0.8 | 0% | 5.6 | take_profit=232, time_stop=31, adverse_stop=5 |

**fill model `depletion`**

| subset | exit | fills | net / fill | cluster s.e. (bps) | t (bps of notional) | t (¢/share) | hit | net $ | gross bps | passive exit | hold s | top exits |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| all signals | fixed0.7 | 268 | -5.86 bps | ±0.26 | -22.96 | -11.19 | 0% | -30.88 | +1.1 | 67% | 3.7 | passive_fill=179, work_expired=85, target_passed=3 |
| all signals | fixed1.0 | 268 | -5.91 bps | ±0.32 | -18.69 | -11.55 | 0% | -31.16 | +1.4 | 56% | 4.7 | passive_fill=149, work_expired=118, reversal_stop=1 |
| all signals | wide1.5 | 268 | -5.97 bps | ±0.45 | -13.17 | -9.55 | 1% | -31.52 | +1.7 | 46% | 12.6 | passive_fill=122, work_expired=118, reversal_stop=22 |
| all signals | wide2.0 | 268 | -6.19 bps | ±0.49 | -12.74 | -9.82 | 4% | -32.63 | +1.8 | 32% | 14.8 | work_expired=147, passive_fill=87, reversal_stop=24 |
| all signals | adaptive | 268 | -5.84 bps | ±0.41 | -14.32 | -10.22 | 2% | -30.80 | +1.7 | 50% | 11.0 | passive_fill=134, work_expired=105, reversal_stop=20 |
| all signals | trail | 268 | -5.78 bps | ±0.38 | -15.10 | -9.88 | 3% | -30.50 | +1.8 | 47% | 7.7 | trail_capture=193, trail_retrace=49, time_stop=18 |
| all signals | taker/taker | 268 | -8.17 bps | ±0.18 | -45.51 | -12.33 | 0% | -43.15 | +0.8 | 0% | 5.6 | take_profit=232, time_stop=31, adverse_stop=5 |

**fill model `trades`**

| subset | exit | fills | net / fill | cluster s.e. (bps) | t (bps of notional) | t (¢/share) | hit | net $ | gross bps | passive exit | hold s | top exits |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| all signals | fixed0.7 | 195 | -5.69 bps | ±0.31 | -18.47 | -10.90 | 0% | -21.87 | +1.2 | 69% | 3.7 | passive_fill=135, work_expired=59, reversal_stop=1 |
| all signals | fixed1.0 | 195 | -5.64 bps | ±0.37 | -15.29 | -10.57 | 1% | -21.69 | +1.6 | 59% | 4.5 | passive_fill=115, work_expired=79, reversal_stop=1 |
| all signals | wide1.5 | 195 | -5.85 bps | ±0.58 | -10.16 | -8.20 | 2% | -22.55 | +1.7 | 48% | 12.3 | passive_fill=92, work_expired=78, reversal_stop=22 |
| all signals | wide2.0 | 195 | -6.09 bps | ±0.61 | -10.03 | -8.51 | 3% | -23.41 | +1.9 | 33% | 14.7 | work_expired=101, passive_fill=65, reversal_stop=24 |
| all signals | adaptive | 195 | -5.84 bps | ±0.49 | -11.95 | -8.88 | 2% | -22.46 | +1.7 | 49% | 10.9 | passive_fill=96, work_expired=73, reversal_stop=21 |
| all signals | trail | 195 | -6.60 bps | ±0.42 | -15.67 | -10.69 | 1% | -25.40 | +1.6 | 28% | 8.2 | trail_capture=137, trail_retrace=34, time_stop=16 |
| all signals | taker/taker | 268 | -8.17 bps | ±0.18 | -45.51 | -12.33 | 0% | -43.15 | +0.8 | 0% | 5.6 | take_profit=232, time_stop=31, adverse_stop=5 |

## Exit ranking by the pre-registered rule

(The binding pick was made on the first three tapes, before the Phase 7 live session; any later tape only re-ranks and does not change the pick.)

Rule: among the six exits, take the one with the highest pooled **Polymarket floor-passed net bps per fill under `strict`** (the one fill model all tapes support) with n ≥ 30. Ties/near-ties are not adjudicated: a difference smaller than its standard error is noise.

| exit | floor-passed fills | net bps / fill | cluster s.e. | t |
|---|---|---|---|---|
| fixed0.7 | 48 | +195 | 177 | +1.10 |
| fixed1.0 | 48 | +407 | 212 | +1.92 |
| wide1.5 | 48 | +487 | 302 | +1.62 |
| wide2.0 | 48 | +680 | 372 | +1.83 |
| adaptive | 48 | +634 | 329 | +1.93 |
| trail | 48 | +680 | 306 | +2.22 |

**Pick under this data: `wide2.0`**

Sample-size check for `wide2.0` (Polymarket, floor-passed, strict): n = 48, mean +680 bps, s.e. 372, t = +1.83. At the same mean and variance, |t| > 2 needs n ≈ **58** floor-passed fills.

## Isolated risk sleeves

| tape | sleeve | final state | equity | account round trips | closed P&L $ | halts | governor events |
|---|---|---|---|---|---|---|---|
| p4_tape_1.npz | hyperliquid_b | NORMAL | $10,000.00 | 0 | 0.0 | 0 | 0 |
| p4_tape_1.npz | polymarket_b | NORMAL | $10,010.87 | 10 | 10.87 | 0 | 0 |
| p5_tape_1.npz | hyperliquid_b | NORMAL | $10,000.00 | 0 | 0.0 | 0 | 0 |
| p5_tape_1.npz | polymarket_b | NORMAL | $10,003.79 | 8 | 3.79 | 0 | 0 |
| p6_tape_1.npz | hyperliquid_b | NORMAL | $10,000.00 | 0 | 0.0 | 0 | 0 |
| p6_tape_1.npz | polymarket_b | NORMAL | $10,018.01 | 10 | 18.01 | 0 | 0 |
| p7_tape_1.npz | hyperliquid_b | NORMAL | $10,000.00 | 0 | 0.0 | 0 | 0 |
| p7_tape_1.npz | polymarket_b | NORMAL | $10,010.54 | 12 | 10.54 | 0 | 0 |
