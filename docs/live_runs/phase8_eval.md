# Phase 8 — evaluation of the single pre-registered comparison

**Frozen-code check:** PASS — every strategy/analysis file matches the SHA-256 recorded in docs/PREREG_PHASE8.json.

Tapes — prior: p4_tape_1.npz, p5_tape_1.npz, p6_tape_1.npz, p7_tape_1.npz; fresh (Phase 8): p8_tape_1.npz. Unit: one floor-passed (1.5×) Polymarket entry; its `trail` and `fixed0.7` exits ran on the identical IOC taker fill. Metric: net bps of notional after fees (fixed-notional shadows). Clusters: BTC impulse id. One-sided p from the normal approximation of t.

## Fill model `strict` (primary)

### Test 1 — fresh out-of-sample only (Phase 8 tapes)

| quantity | paired entries N | BTC-impulse clusters | mean net bps/fill | cluster s.e. | t | one-sided p | cluster-bootstrap 95 % CI (report only) |
|---|---|---|---|---|---|---|---|
| trail (candidate) | 24 | 18 | -77 | 413 | -0.19 | 0.574 | [-841, +801] |
| fixed0.7 (baseline) | 24 | 18 | +97 | 243 | +0.40 | 0.344 | [-355, +625] |
| paired diff  trail − fixed0.7 | 24 | 18 | -175 | 275 | -0.63 | 0.737 | [-721, +345] |

Rule: supported iff **both** one-sided t > 1.645. Result: **NOT supported** at N = 24 (trail t = -0.19, paired difference t = -0.63).

¢/share cross-check: trail -0.95¢ (t -0.56), fixed0.7 -0.65¢, difference t -0.30.

### Test 2 — cumulative pooled (all tapes)

| quantity | paired entries N | BTC-impulse clusters | mean net bps/fill | cluster s.e. | t | one-sided p | cluster-bootstrap 95 % CI (report only) |
|---|---|---|---|---|---|---|---|
| trail (candidate) | 72 | 56 | +427 | 256 | +1.67 | 0.047 | [-56, +958] |
| fixed0.7 (baseline) | 72 | 56 | +162 | 144 | +1.13 | 0.129 | [-128, +461] |
| paired diff  trail − fixed0.7 | 72 | 56 | +265 | 176 | +1.51 | 0.066 | [-81, +602] |

Rule: N ≥ 70 **and** trail t > 2.0 (raw) / > 2.63 (adjusted for the six Phase 7 exits). N = 72 (met); trail t = +1.67. Verdict: **does NOT clear the raw bar**. Paired difference vs fixed0.7: t = +1.51.

¢/share cross-check: trail +1.61¢ (t +1.45), fixed0.7 +0.17¢, difference t +2.23.

Per-tape breakdown (descriptive only, no test):

| tape | role | paired entries | trail mean bps | fixed0.7 mean bps | diff mean bps |
|---|---|---|---|---|---|
| p4_tape_1.npz | prior | 14 | +461 | -156 | +617 |
| p5_tape_1.npz | prior | 10 | +1186 | +465 | +721 |
| p6_tape_1.npz | prior | 12 | +1027 | +516 | +511 |
| p7_tape_1.npz | prior | 12 | +166 | +59 | +108 |
| p8_tape_1.npz | fresh | 24 | -77 | +97 | -175 |

## Fill model `trades` (secondary: only tapes with trade prints)

### Test 1 — fresh out-of-sample only (Phase 8 tapes)

| quantity | paired entries N | BTC-impulse clusters | mean net bps/fill | cluster s.e. | t | one-sided p | cluster-bootstrap 95 % CI (report only) |
|---|---|---|---|---|---|---|---|
| trail (candidate) | 24 | 18 | -77 | 413 | -0.19 | 0.574 | [-841, +801] |
| fixed0.7 (baseline) | 24 | 18 | +117 | 241 | +0.48 | 0.314 | [-328, +643] |
| paired diff  trail − fixed0.7 | 24 | 18 | -194 | 271 | -0.72 | 0.763 | [-733, +314] |

Rule: supported iff **both** one-sided t > 1.645. Result: **NOT supported** at N = 24 (trail t = -0.19, paired difference t = -0.72).

¢/share cross-check: trail -0.95¢ (t -0.56), fixed0.7 -0.53¢, difference t -0.44.

### Test 2 — cumulative pooled (all tapes)

| quantity | paired entries N | BTC-impulse clusters | mean net bps/fill | cluster s.e. | t | one-sided p | cluster-bootstrap 95 % CI (report only) |
|---|---|---|---|---|---|---|---|
| trail (candidate) | 58 | 45 | +419 | 302 | +1.39 | 0.083 | [-157, +1057] |
| fixed0.7 (baseline) | 58 | 45 | +247 | 162 | +1.53 | 0.063 | [-59, +575] |
| paired diff  trail − fixed0.7 | 58 | 45 | +172 | 209 | +0.82 | 0.206 | [-248, +593] |

Rule: N ≥ 70 **and** trail t > 2.0 (raw) / > 2.63 (adjusted for the six Phase 7 exits). N = 58 (NOT met); trail t = +1.39. Verdict: **N below the pre-registered target — inconclusive**. Paired difference vs fixed0.7: t = +0.82.

¢/share cross-check: trail +1.38¢ (t +1.05), fixed0.7 +0.27¢, difference t +1.46.

Per-tape breakdown (descriptive only, no test):

| tape | role | paired entries | trail mean bps | fixed0.7 mean bps | diff mean bps |
|---|---|---|---|---|---|
| p5_tape_1.npz | prior | 10 | +1186 | +465 | +721 |
| p6_tape_1.npz | prior | 12 | +1027 | +516 | +511 |
| p7_tape_1.npz | prior | 12 | +166 | +59 | +108 |
| p8_tape_1.npz | fresh | 24 | -77 | +117 | -194 |

## Caveat that no statistic here removes

The four prior tapes are the data on which `trail` looked best of six, so the pooled test is biased upward by selection (the 2.63 bar corrects for choosing among six exits, not for every other analysis choice); the fresh-only test is the only clean one and it is small. Sessions are in whatever BTC regime the clock delivered — see the per-session volatility in docs/PHASE8.md.
