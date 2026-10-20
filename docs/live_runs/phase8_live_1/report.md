# Quant Agency — Phase 7 report: Pure Architecture B (live, 2616 s)

Tapes: live — total **2616 s**. Pure Architecture B (Architecture A is not instantiated), floor 1.5× (spread + taker-in + maker-out fee) tagged on every shadow row with a *fixed* reference; HL fees 1.5 / 4.5 bps assumed. Every exit policy below ran on **identical entries** (same signals, same IOC taker fill), so differences are the exit alone. t = mean / cluster-robust s.e. (clusters = BTC impulses).

Exit policies: `fixed0.7` = Phase 6 reference (maker TP at 0.7× the credited gap, 8–10 s window) · `fixed1.0` = maker TP at 1.0× · `wide1.5`/`wide2.0` = maker TP at 1.5×/2.0× with a 20–25 s horizon · `adaptive` = start 1.0×, widen to 1.5× then 2.0× each time Binance extends the impulse by another 20 % beyond the signal level (cancel latency charged, re-post only after the cancel lands) · `trail` = no resting TP, stay while Binance velocity is supportive, exit passively at the touch when the venue has done the credited gap and Binance 1 s velocity has faded (or on a 40 % give-back of peak progress / a stall); reversal, adverse and time stops apply to all.

*Metric note:* `net / fill` shows the mean in ¢ per share and in bps of notional. Shadow rows use a fixed notional, so bps of notional (and the $ column) is the sizing-consistent measure; ¢/share weights high-priced contracts more and bps weights cheap contracts more, so on small samples the two can disagree in sign — both t-statistics are shown and neither is a substitute for more fills.

## polymarket

272 signals; **48 (18%) clear the 1.5× floor**.

**fill model `strict`**

| subset | exit | fills | net / fill | cluster s.e. (bps) | t (bps of notional) | t (¢/share) | hit | net $ | gross bps | passive exit | hold s | top exits |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| floor-passed | fixed0.7 | 22 | -0.57¢ (+134 bps) | ±261 | +0.52 | -0.46 | 50% | +12.27 | +604 | 45% | 4.6 | passive_fill=10, adverse_stop=6, work_expired=4 |
| floor-passed | fixed1.0 | 22 | +0.45¢ (+387 bps) | ±335 | +1.16 | +0.29 | 50% | +37.72 | +878 | 41% | 5.2 | passive_fill=9, adverse_stop=6, work_expired=5 |
| floor-passed | wide1.5 | 22 | +0.09¢ (+154 bps) | ±540 | +0.29 | +0.04 | 41% | +20.88 | +677 | 36% | 10.1 | adverse_stop=10, passive_fill=8, work_expired=2 |
| floor-passed | wide2.0 | 22 | +0.99¢ (+351 bps) | ±595 | +0.59 | +0.40 | 41% | +41.79 | +926 | 23% | 12.4 | adverse_stop=10, work_expired=5, passive_fill=5 |
| floor-passed | adaptive | 22 | +0.35¢ (+185 bps) | ±569 | +0.32 | +0.15 | 41% | +25.14 | +742 | 27% | 10.0 | adverse_stop=10, passive_fill=6, work_expired=4 |
| floor-passed | trail | 22 | -0.54¢ (+18 bps) | ±448 | +0.04 | -0.29 | 45% | +3.81 | +596 | 23% | 7.4 | trail_capture=9, adverse_stop=7, trail_retrace=4 |
| floor-passed | taker/taker | 22 | -1.14¢ (-74 bps) | ±207 | -0.36 | -1.07 | 45% | -8.38 | +581 | 0% | 5.3 | take_profit=12, adverse_stop=9, time_stop=1 |
| all signals | fixed0.7 | 103 | -3.02¢ (-882 bps) | ±113 | -7.83 | -7.97 | 17% | -440.74 | -163 | 21% | 7.7 | work_expired=66, passive_fill=22, reversal_stop=8 |
| all signals | fixed1.0 | 103 | -2.79¢ (-821 bps) | ±126 | -6.54 | -6.33 | 19% | -411.94 | -85 | 17% | 8.1 | work_expired=70, passive_fill=18, reversal_stop=8 |
| all signals | wide1.5 | 103 | -2.76¢ (-808 bps) | ±153 | -5.30 | -4.87 | 17% | -398.77 | -63 | 16% | 17.5 | work_expired=62, passive_fill=16, adverse_stop=13 |
| all signals | wide2.0 | 103 | -2.53¢ (-752 bps) | ±162 | -4.64 | -4.07 | 17% | -370.50 | +9 | 12% | 18.3 | work_expired=66, adverse_stop=13, passive_fill=12 |
| all signals | adaptive | 103 | -2.69¢ (-800 bps) | ±159 | -5.04 | -4.46 | 17% | -393.35 | -42 | 13% | 17.8 | work_expired=65, passive_fill=13, adverse_stop=13 |
| all signals | trail | 103 | -2.96¢ (-863 bps) | ±142 | -6.08 | -6.15 | 15% | -426.36 | -95 | 11% | 11.5 | trail_capture=34, trail_retrace=34, time_stop=11 |
| all signals | taker/taker | 103 | -3.38¢ (-955 bps) | ±100 | -9.59 | -10.14 | 12% | -476.92 | -147 | 0% | 9.0 | take_profit=74, time_stop=15, adverse_stop=12 |

**fill model `depletion`**

| subset | exit | fills | net / fill | cluster s.e. (bps) | t (bps of notional) | t (¢/share) | hit | net $ | gross bps | passive exit | hold s | top exits |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| floor-passed | fixed0.7 | 22 | +0.11¢ (+232 bps) | ±262 | +0.89 | +0.09 | 59% | +23.03 | +684 | 55% | 4.2 | passive_fill=12, adverse_stop=6, work_expired=4 |
| floor-passed | fixed1.0 | 22 | +0.76¢ (+466 bps) | ±349 | +1.34 | +0.49 | 55% | +46.82 | +930 | 50% | 4.9 | passive_fill=11, adverse_stop=6, work_expired=4 |
| floor-passed | wide1.5 | 22 | +0.32¢ (+182 bps) | ±541 | +0.34 | +0.14 | 45% | +23.97 | +699 | 41% | 9.5 | adverse_stop=10, passive_fill=9, work_expired=2 |
| floor-passed | wide2.0 | 22 | +1.35¢ (+402 bps) | ±603 | +0.67 | +0.53 | 45% | +47.39 | +957 | 32% | 12.2 | adverse_stop=10, passive_fill=7, work_expired=4 |
| floor-passed | adaptive | 22 | +0.56¢ (+273 bps) | ±578 | +0.47 | +0.24 | 45% | +35.74 | +785 | 41% | 8.3 | adverse_stop=10, passive_fill=9, work_expired=2 |
| floor-passed | trail | 22 | +0.06¢ (+160 bps) | ±479 | +0.33 | +0.03 | 50% | +19.81 | +678 | 41% | 7.0 | trail_capture=9, adverse_stop=7, trail_retrace=4 |
| floor-passed | taker/taker | 22 | -1.14¢ (-74 bps) | ±207 | -0.36 | -1.07 | 45% | -8.38 | +581 | 0% | 5.3 | take_profit=12, adverse_stop=9, time_stop=1 |
| all signals | fixed0.7 | 103 | -2.63¢ (-765 bps) | ±111 | -6.90 | -6.94 | 19% | -383.74 | -83 | 30% | 7.3 | work_expired=60, passive_fill=31, adverse_stop=6 |
| all signals | fixed1.0 | 103 | -2.60¢ (-775 bps) | ±127 | -6.08 | -5.82 | 23% | -387.83 | -61 | 23% | 7.8 | work_expired=65, passive_fill=24, reversal_stop=7 |
| all signals | wide1.5 | 103 | -2.47¢ (-741 bps) | ±155 | -4.78 | -4.29 | 23% | -364.78 | -23 | 21% | 16.3 | work_expired=57, passive_fill=22, adverse_stop=13 |
| all signals | wide2.0 | 103 | -2.39¢ (-726 bps) | ±165 | -4.41 | -3.75 | 18% | -357.10 | +23 | 16% | 17.8 | work_expired=63, passive_fill=16, adverse_stop=13 |
| all signals | adaptive | 103 | -2.53¢ (-734 bps) | ±164 | -4.49 | -4.14 | 20% | -361.54 | -8 | 18% | 16.8 | work_expired=60, passive_fill=19, adverse_stop=13 |
| all signals | trail | 103 | -2.72¢ (-795 bps) | ±145 | -5.50 | -5.52 | 17% | -390.96 | -60 | 18% | 11.3 | trail_capture=34, trail_retrace=34, time_stop=11 |
| all signals | taker/taker | 103 | -3.38¢ (-955 bps) | ±100 | -9.59 | -10.14 | 12% | -476.92 | -147 | 0% | 9.0 | take_profit=74, time_stop=15, adverse_stop=12 |

**fill model `trades`**

| subset | exit | fills | net / fill | cluster s.e. (bps) | t (bps of notional) | t (¢/share) | hit | net $ | gross bps | passive exit | hold s | top exits |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| floor-passed | fixed0.7 | 22 | -0.43¢ (+156 bps) | ±259 | +0.60 | -0.35 | 50% | +14.62 | +622 | 45% | 4.6 | passive_fill=10, adverse_stop=6, work_expired=4 |
| floor-passed | fixed1.0 | 22 | +0.45¢ (+387 bps) | ±335 | +1.16 | +0.29 | 50% | +37.72 | +878 | 41% | 5.2 | passive_fill=9, adverse_stop=6, work_expired=5 |
| floor-passed | wide1.5 | 22 | +0.09¢ (+154 bps) | ±540 | +0.29 | +0.04 | 41% | +20.88 | +677 | 36% | 10.0 | adverse_stop=10, passive_fill=8, work_expired=2 |
| floor-passed | wide2.0 | 22 | +0.99¢ (+351 bps) | ±595 | +0.59 | +0.40 | 41% | +41.79 | +926 | 23% | 12.4 | adverse_stop=10, work_expired=5, passive_fill=5 |
| floor-passed | adaptive | 22 | +0.35¢ (+185 bps) | ±569 | +0.32 | +0.15 | 41% | +25.14 | +742 | 27% | 10.0 | adverse_stop=10, passive_fill=6, work_expired=4 |
| floor-passed | trail | 22 | -0.54¢ (+18 bps) | ±448 | +0.04 | -0.29 | 45% | +3.81 | +596 | 23% | 7.4 | trail_capture=9, adverse_stop=7, trail_retrace=4 |
| floor-passed | taker/taker | 22 | -1.14¢ (-74 bps) | ±207 | -0.36 | -1.07 | 45% | -8.38 | +581 | 0% | 5.3 | take_profit=12, adverse_stop=9, time_stop=1 |
| all signals | fixed0.7 | 103 | -3.00¢ (-877 bps) | ±113 | -7.79 | -7.92 | 17% | -438.40 | -159 | 21% | 7.7 | work_expired=66, passive_fill=22, reversal_stop=8 |
| all signals | fixed1.0 | 103 | -2.79¢ (-821 bps) | ±126 | -6.54 | -6.33 | 19% | -411.94 | -85 | 17% | 8.1 | work_expired=70, passive_fill=18, reversal_stop=8 |
| all signals | wide1.5 | 103 | -2.75¢ (-805 bps) | ±153 | -5.27 | -4.85 | 17% | -397.01 | -61 | 16% | 17.4 | work_expired=62, passive_fill=16, adverse_stop=13 |
| all signals | wide2.0 | 103 | -2.53¢ (-752 bps) | ±162 | -4.64 | -4.07 | 17% | -370.50 | +9 | 12% | 18.3 | work_expired=66, adverse_stop=13, passive_fill=12 |
| all signals | adaptive | 103 | -2.69¢ (-800 bps) | ±159 | -5.04 | -4.46 | 17% | -393.35 | -42 | 13% | 17.8 | work_expired=65, passive_fill=13, adverse_stop=13 |
| all signals | trail | 103 | -2.96¢ (-863 bps) | ±142 | -6.08 | -6.15 | 15% | -426.36 | -95 | 11% | 11.5 | trail_capture=34, trail_retrace=34, time_stop=11 |
| all signals | taker/taker | 103 | -3.38¢ (-955 bps) | ±100 | -9.59 | -10.14 | 12% | -476.92 | -147 | 0% | 9.0 | take_profit=74, time_stop=15, adverse_stop=12 |

## hyperliquid

255 signals; **0 (0%) clear the 1.5× floor**.

No signal clears the floor: B abstains here. The 'all signals' rows show what the refused signals would have done.

**fill model `strict`**

| subset | exit | fills | net / fill | cluster s.e. (bps) | t (bps of notional) | t (¢/share) | hit | net $ | gross bps | passive exit | hold s | top exits |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| all signals | fixed0.7 | 208 | -6.08 bps | ±0.26 | -23.43 | -9.01 | 0% | -24.75 | +0.9 | 67% | 3.5 | passive_fill=139, work_expired=54, reversal_stop=13 |
| all signals | fixed1.0 | 208 | -6.23 bps | ±0.32 | -19.47 | -8.43 | 0% | -25.37 | +1.1 | 57% | 4.2 | passive_fill=116, work_expired=75, reversal_stop=16 |
| all signals | wide1.5 | 208 | -6.07 bps | ±0.44 | -13.93 | -7.64 | 0% | -24.77 | +1.3 | 55% | 9.5 | passive_fill=114, work_expired=58, reversal_stop=35 |
| all signals | wide2.0 | 208 | -6.42 bps | ±0.51 | -12.53 | -7.00 | 1% | -26.16 | +1.3 | 42% | 11.8 | passive_fill=87, work_expired=75, reversal_stop=44 |
| all signals | adaptive | 208 | -6.20 bps | ±0.42 | -14.78 | -7.32 | 1% | -25.20 | +1.2 | 54% | 9.0 | passive_fill=112, work_expired=59, reversal_stop=34 |
| all signals | trail | 208 | -6.45 bps | ±0.40 | -16.12 | -8.34 | 1% | -26.29 | +1.6 | 33% | 6.5 | trail_capture=163, trail_retrace=27, reversal_stop=7 |
| all signals | taker/taker | 208 | -8.51 bps | ±0.15 | -55.34 | -10.15 | 0% | -34.64 | +0.5 | 0% | 4.0 | take_profit=185, adverse_stop=12, time_stop=11 |

**fill model `depletion`**

| subset | exit | fills | net / fill | cluster s.e. (bps) | t (bps of notional) | t (¢/share) | hit | net $ | gross bps | passive exit | hold s | top exits |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| all signals | fixed0.7 | 208 | -5.94 bps | ±0.22 | -26.70 | -9.01 | 0% | -24.19 | +1.0 | 70% | 3.4 | passive_fill=144, work_expired=52, reversal_stop=10 |
| all signals | fixed1.0 | 208 | -6.07 bps | ±0.29 | -21.21 | -8.56 | 0% | -24.76 | +1.1 | 60% | 4.1 | passive_fill=123, work_expired=70, reversal_stop=14 |
| all signals | wide1.5 | 208 | -5.89 bps | ±0.43 | -13.82 | -7.64 | 0% | -24.02 | +1.4 | 59% | 9.0 | passive_fill=122, work_expired=52, reversal_stop=33 |
| all signals | wide2.0 | 208 | -6.26 bps | ±0.50 | -12.61 | -6.93 | 1% | -25.48 | +1.4 | 45% | 11.4 | passive_fill=94, work_expired=71, reversal_stop=41 |
| all signals | adaptive | 208 | -6.05 bps | ±0.40 | -15.08 | -7.23 | 1% | -24.57 | +1.2 | 58% | 8.5 | passive_fill=120, work_expired=52, reversal_stop=33 |
| all signals | trail | 208 | -5.60 bps | ±0.38 | -14.63 | -7.55 | 1% | -22.81 | +1.7 | 55% | 5.9 | trail_capture=163, trail_retrace=27, reversal_stop=7 |
| all signals | taker/taker | 208 | -8.51 bps | ±0.15 | -55.34 | -10.15 | 0% | -34.64 | +0.5 | 0% | 4.0 | take_profit=185, adverse_stop=12, time_stop=11 |

**fill model `trades`**

| subset | exit | fills | net / fill | cluster s.e. (bps) | t (bps of notional) | t (¢/share) | hit | net $ | gross bps | passive exit | hold s | top exits |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| all signals | fixed0.7 | 208 | -5.98 bps | ±0.25 | -23.46 | -9.01 | 0% | -24.34 | +0.9 | 70% | 3.4 | passive_fill=144, work_expired=50, reversal_stop=12 |
| all signals | fixed1.0 | 208 | -6.10 bps | ±0.30 | -20.14 | -8.53 | 0% | -24.89 | +1.1 | 60% | 4.0 | passive_fill=123, work_expired=68, reversal_stop=16 |
| all signals | wide1.5 | 208 | -5.91 bps | ±0.43 | -13.82 | -7.64 | 0% | -24.13 | +1.4 | 57% | 9.1 | passive_fill=119, work_expired=55, reversal_stop=33 |
| all signals | wide2.0 | 208 | -6.18 bps | ±0.51 | -12.22 | -7.07 | 1% | -25.18 | +1.5 | 45% | 11.2 | passive_fill=94, work_expired=72, reversal_stop=40 |
| all signals | adaptive | 208 | -5.94 bps | ±0.40 | -14.83 | -7.50 | 1% | -24.17 | +1.3 | 59% | 8.2 | passive_fill=123, work_expired=49, reversal_stop=33 |
| all signals | trail | 208 | -6.40 bps | ±0.40 | -16.10 | -8.37 | 1% | -26.10 | +1.6 | 35% | 6.4 | trail_capture=163, trail_retrace=27, reversal_stop=7 |
| all signals | taker/taker | 208 | -8.51 bps | ±0.15 | -55.34 | -10.15 | 0% | -34.64 | +0.5 | 0% | 4.0 | take_profit=185, adverse_stop=12, time_stop=11 |

## Exit ranking by the pre-registered rule

(The binding pick was made on the first three tapes, before the Phase 7 live session; any later tape only re-ranks and does not change the pick.)

Rule: among the six exits, take the one with the highest pooled **Polymarket floor-passed net bps per fill under `strict`** (the one fill model all tapes support) with n ≥ 30. Ties/near-ties are not adjudicated: a difference smaller than its standard error is noise.

| exit | floor-passed fills | net bps / fill | cluster s.e. | t |
|---|---|---|---|---|
| fixed0.7 | 22 | +134 | 261 | +0.52 |
| fixed1.0 | 22 | +387 | 335 | +1.16 |
| wide1.5 | 22 | +154 | 540 | +0.29 |
| wide2.0 | 22 | +351 | 595 | +0.59 |
| adaptive | 22 | +185 | 569 | +0.32 |
| trail | 22 | +18 | 448 | +0.04 |

**Pick under this data: `None`**

## Isolated risk sleeves

| tape | sleeve | final state | equity | account round trips | closed P&L $ | halts | governor events |
|---|---|---|---|---|---|---|---|
| live | hyperliquid_b | NORMAL | $10,000.00 | 0 | 0.0 | 0 | 0 |
| live | polymarket_b | NORMAL | $9,994.65 | 23 | -5.35 | 0 | 0 |


* ACCOUNT exit policy: **trail**; sleeve capital $10,000 each; trade prints 25445; BTC vol (fast) 0.73 bps/√s; Architecture A instantiated: no (shelved); legacy taker CFO closed trades: 0.

**Last ACCOUNT fills:**

| market | side | entry | exit | exit reason | hold s | net bps | net $ |
|---|---|---|---|---|---|---|---|
| btc-updown-5m-1792453800:updown_5m | L | 0.370 | 0.570 | passive_fill | 11.7 | +4964 | +19.854 |
| c-updown-15m-1792454400:updown_15m | L | 0.790 | 0.760 | adverse_stop | 0.5 | -688 | -2.758 |
| btc-updown-5m-1792454400:updown_5m | L | 0.880 | 0.850 | adverse_stop | 1.4 | -526 | -2.108 |
| c-updown-15m-1792454400:updown_15m | L | 0.730 | 0.690 | adverse_stop | 3.2 | -942 | -3.774 |
| btc-updown-5m-1792454400:updown_5m | S | 0.600 | 0.450 | passive_fill | 7.2 | +2220 | +12.701 |
| c-updown-15m-1792454400:updown_15m | S | 0.540 | 0.480 | work_expired | 9.4 | +466 | +2.189 |
| c-updown-15m-1792454400:updown_15m | L | 0.480 | 0.410 | adverse_stop | 3.5 | -2175 | -8.543 |
| c-updown-15m-1792454400:updown_15m | S | 0.410 | 0.440 | adverse_stop | 16.2 | -1565 | -4.359 |
| btc-updown-5m-1792454400:updown_5m | S | 0.290 | 0.360 | adverse_stop | 14.3 | -3467 | -5.519 |
| c-updown-15m-1792454400:updown_15m | S | 0.470 | 0.460 | work_expired | 4.2 | -528 | -1.875 |
| c-updown-15m-1792454400:updown_15m | L | 0.500 | 0.440 | adverse_stop | 12.8 | -1895 | -7.583 |
| btc-updown-5m-1792455000:updown_5m | S | 0.480 | 0.420 | passive_fill | 4.4 | +886 | +3.271 |
| btc-updown-5m-1792455000:updown_5m | S | 0.270 | 0.310 | adverse_stop | 8.2 | -2547 | -3.769 |
| btc-updown-5m-1792455300:updown_5m | L | 0.630 | 0.660 | passive_fill | 2.7 | +217 | +0.868 |
| c-updown-15m-1792455300:updown_15m | S | 0.240 | 0.280 | adverse_stop | 5.2 | -2787 | -3.519 |
| btc-updown-5m-1792455600:updown_5m | S | 0.410 | 0.340 | work_expired | 4.2 | +911 | +2.531 |
| btc-updown-5m-1792455600:updown_5m | S | 0.320 | 0.330 | work_expired | 7.6 | -1272 | -2.394 |
| btc-updown-5m-1792455600:updown_5m | L | 0.330 | 0.390 | work_expired | 4.6 | +845 | +3.376 |
| btc-updown-5m-1792455600:updown_5m | L | 0.400 | 0.370 | adverse_stop | 1.4 | -1578 | -6.310 |
| btc-updown-5m-1792455600:updown_5m | S | 0.470 | 0.370 | target_passed | 1.6 | +1409 | +4.996 |
| btc-updown-5m-1792455600:updown_5m | S | 0.210 | 0.160 | passive_fill | 6.2 | +1828 | +1.943 |
| btc-updown-5m-1792455900:updown_5m | L | 0.830 | 0.800 | reversal_stop | 5.7 | -615 | -2.461 |
| btc-updown-5m-1792455900:updown_5m | L | 0.880 | 0.850 | adverse_stop | 3.8 | -526 | -2.104 |


## Caveats

* Paper only. Floor-passed samples are small; read t, not the point estimate. Fee assumptions (HL 1.5 / 4.5 bps) are inputs. The queue model has no hidden size or other makers' behaviour.
