# Phase 9 — `fixed0.7` by BTC volatility regime, and the power calculation

Entries: floor-passed (1.5×) Polymarket entries on tapes p4_tape_1.npz, p5_tape_1.npz, p6_tape_1.npz, p7_tape_1.npz, p8_tape_1.npz, `strict` fills, exit `fixed0.7` (the Phase 6/7 reference, parameters untouched), metric net bps of notional, clusters = BTC impulse id. Each entry is labelled with **sigma60 at its signal time** (RMS of the last 60 one-second Binance BTCUSDT mid log-returns, bps/√s; causal; `quant_agency/regime.py`, the same estimator the daemon triggers on). Active = sigma60 ≥ 0.5. Entries with < 60 s of BTC history are excluded from this table (none expected).

All entries: N = 71 (55 clusters), mean **+155.7** bps, cluster-robust s.e. **145.5**, t = +1.07; raw per-entry SD 1273 bps; design effect (cluster) 0.93; effective per-entry SD σ_eff = s.e.·√N = **1226** bps.

## 1. Time spent in each regime and signal/fill supply

| regime | tape-hours | PM signals | signals / h | pass floor | floor pass rate | floor-passed `fixed0.7` fills | fills / h |
|---|---|---|---|---|---|---|---|
| quiet | 2.45 | 505 | 206 | 134 | 27% | 55 | 22.5 |
| active | 0.18 | 157 | 856 | 30 | 19% | 16 | 87.3 |

Hyperliquid (the secondary arm): signals by regime quiet 474 / active 104; clearing the 1.5× floor: quiet 0 / active 0. With zero floor-passed Hyperliquid entries in any regime there is no variance to plan from, so the Hyperliquid arm cannot be powered (see PREREG_PHASE9).

## 2. `fixed0.7` net expectancy by regime (descriptive; no regime was ever used to choose or drop anything)

| regime | N | mean net bps | cluster s.e. | t | per-entry SD | hit | net $ (fixed $50 clips) |
|---|---|---|---|---|---|---|---|
| quiet | 55 | +248 | 166 | +1.49 | 1193 | 62% | +63.7 |
| active | 16 | -161 | 271 | -0.59 | 1517 | 44% | -3.7 |

Active − quiet difference: -409 bps, s.e. 318, t = -1.29 (descriptive; N_active = 16).

**Variance decomposition (entries, bps²):** total 1621294; between-regime share η² = 1.8% , within-regime share 98.2%. Per-entry SD: quiet 1193, active 1517 bps.

**By σ60 tercile (descriptive):**

| tercile | N | mean net bps | cluster s.e. | t |
|---|---|---|---|---|
| low (σ60 0.12–0.28) | 24 | +398 | 247 | +1.61 |
| mid (σ60 0.28–0.41) | 24 | +64 | 245 | +0.26 |
| high (σ60 0.43–1.12) | 23 | -2 | 244 | -0.01 |

Regression of net bps on σ60 (cluster-robust): slope -1222 bps per 1 bps/√s (s.e. 674, t = -1.81). Descriptive: it is estimated from 71 entries of which 16 are in the active regime.

**Per tape:**

| tape | hours | quiet h | active h | entries | excluded (no 60 s history) |
|---|---|---|---|---|---|
| p4_tape_1.npz | 0.33 | 0.30 | 0.01 | 14 | 0 |
| p5_tape_1.npz | 0.42 | 0.40 | 0.00 | 10 | 0 |
| p6_tape_1.npz | 0.42 | 0.37 | 0.03 | 12 | 0 |
| p7_tape_1.npz | 0.83 | 0.81 | 0.00 | 11 | 1 |
| p8_tape_1.npz | 0.73 | 0.57 | 0.14 | 24 | 0 |

## 3. Power calculation: smallest N for a one-sided test of mean > 0

One-sided cluster-robust t-test, α = 0.05, power 0.8; non-central t with df = (clusters − 1), clusters = 0.77·N (observed ratio 55/71); σ_eff = 1226 bps (observed, cluster-inflated). N depends only on μ/σ_eff:

| planning effect μ | μ (bps) | required N* |
|---|---|---|
| observed mean | +156 | 386 |
| observed lower 80 % one-sided bound | +33 | 8405 |
| half the observed mean (shrinkage / winner's-curse allowance) | +78 | 1535 |
| +100 bps (≈ 1 % of notional per entry) | +100 | 931 |
| +250 bps | +250 | 151 |
| upper 95 % bound of the observed mean | +395 | 62 |

**Locked planning value (Phase 9 pre-registration): μ = observed mean +156 bps ⇒ N\* = 386 floor-passed Polymarket entries.** Achieved power at N\*: 0.80. If the true mean is only half the observed one, the power of a test with N = N\* is 0.34; the minimum detectable true mean at N\* with power 0.8 is +156 bps by construction. A non-significant result at N\* therefore means 'no evidence of an effect as large as the one observed', not 'no effect'.

**Capture time implied** (floor-passed fills per hour from §1; the active rate rests on very few entries):

| scenario | floor-passed fills / h | hours to N* = 386 |
|---|---|---|
| all-quiet capture | 22.5 | 17.2 |
| all-active capture | 87.3 | 4.4 |
