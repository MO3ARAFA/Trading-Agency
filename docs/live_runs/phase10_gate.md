# Phase 10 — the σ60 split under a pre-impulse definition, and the in-sample size of the gated specification

Entries: floor-passed Polymarket `fixed0.7` (strict), tapes p4_tape_1.npz, p5_tape_1.npz, p6_tape_1.npz, p7_tape_1.npz, p8_tape_1.npz; N = 71. `σ_now` = σ60 at the signal (includes the triggering impulse; the Phase 9 label); `σ_pre` = σ60 on the 60 s window ending 15 s earlier (the baseline the impulse broke out of; the gate). Threshold 0.5 for both. Same entries, same exits, same fees.

## 1. Same entries, two definitions of 'quiet' / 'active'

| bucket | N | mean net bps | cluster s.e. | t | hit | net $ ($50 clips) |
|---|---|---|---|---|---|---|
| σ_now < 0.50  (Phase 9 'quiet') | 55 | +248 | 166 | +1.49 | 62% | +63.7 |
| σ_now ≥ 0.50  (Phase 9 'active') | 16 | -161 | 271 | -0.59 | 44% | -3.7 |
| **σ_pre < 0.50  (the gate: quiet baseline)** | 62 | +128 | 161 | +0.80 | 56% | +44.2 |
| σ_pre ≥ 0.50  (turbulent baseline) | 9 | +347 | 327 | +1.06 | 67% | +15.8 |

Of the 16 entries labelled 'active' at signal time, **8 had a quiet baseline (σ_pre < 0.5)** — the label was reacting to the impulse itself, not to prior turbulence. Entries with a turbulent baseline: 9. Correlation σ_now vs σ_pre across entries: 0.56.

## 2. Does a calm book get 'cleanly sniped', and do providers pull quotes when turbulent? (descriptive, all Polymarket signals)

| bucket | signals | median spread bps | median |gap| bps | floor pass rate |
|---|---|---|---|---|
| σ_pre < 0.50 | 581 | 282 | 416 | 26% |
| σ_pre ≥ 0.50 | 81 | 526 | 585 | 19% |
| σ_now < 0.50 | 505 | 267 | 427 | 27% |
| σ_now ≥ 0.50 | 157 | 426 | 436 | 19% |

If providers pulled quotes in turbulence, spreads would be wider there; read the table, not the story.

## 3. The gated specification, in-sample (post hoc — a planning input, not evidence)

Pure Architecture B + `fixed0.7` + gate σ_pre < 0.5: N = 62, mean **+128** bps, cluster s.e. 161, t = +0.80 (one-sided p ≈ 0.21), hit 56%, σ_eff = 1266 bps. The threshold was not searched: 0.50 was the only value evaluated, but the *split itself* was chosen after Phase 9 looked at these entries, so its in-sample mean is optimistically biased and t is not a valid test statistic.

## 4. Power for the gated specification (one-sided, α = 0.05, power 0.80, non-central t)

| planning effect | μ (bps) | required N\* |
|---|---|---|
| in-sample gated mean | +128 | 608 |
| half of it (selection / winner's-curse allowance) | +64 | 2425 |
| +100 bps | +100 | 994 |
| +250 bps | +250 | 161 |

**N\* (locked in PREREG_PHASE10) = 608** gated entries at the in-sample mean; power at half that effect: 0.34.

By σ_pre tercile (descriptive):

| tercile | N | mean net bps | cluster s.e. | t | hit | net $ |
|---|---|---|---|---|---|---|
| low (σ_pre 0.00–0.18) | 24 | +220 | 219 | +1.00 | 50% | +20.2 |
| mid (σ_pre 0.20–0.32) | 23 | +118 | 327 | +0.36 | 61% | +26.5 |
| high (σ_pre 0.35–0.68) | 24 | +128 | 192 | +0.66 | 62% | +13.3 |
