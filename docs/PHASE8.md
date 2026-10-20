# Phase 8 — single pre-registered exit validation: `trail` vs `fixed0.7` (2026-10-19/20)

**Result: the pre-registered hypothesis is NOT supported.** On fresh data `trail` did not beat `fixed0.7` (paired difference −175 bps, t = −0.63) and was not positive on its own (−77 bps, t = −0.19). The cumulative pooled test reached the target sample (N = 72) but `trail` did **not** clear even the raw bar (t = +1.67 < 2.0, let alone the adjusted 2.63). No post-hoc re-tuning was done, and by the pre-registration the sample is **not** extended.

What this does and does not tell us:
* The Phase 7 impression that uncapping the exit helps was an in-sample artefact (selection of the best of six on the same entries) or at least did not replicate. It was concentrated in the first three recorded sessions (trail − fixed0.7: +617, +721, +511 bps) and faded in the last two (+108, **−175**).
* It does **not** show that B is dead: `fixed0.7` is still slightly positive over 72 entries (+162 ± 144 bps, t = +1.13) — an unproven lead, not a confirmed edge, exactly as in Phase 6/7. The fresh sample (N = 24, s.e. 413 bps) could not have confirmed an effect of the size we were looking for (+680 bps would have given t ≈ 1.6 at that variance) and cannot rule it out either (95 % CI [−841, +801]).
* No wallet should be connected on this evidence (docs/OPERATOR_GUIDE.md §6).

## 1. Pre-registration (committed before any Phase 8 data)

`docs/PREREG_PHASE8.md` + `docs/PREREG_PHASE8.json` (SHA-256 of 17 files: sniper, sleeves, config, CFO, fill model, watchers, oracle, agency, runner, `p7_pool`, `p8_eval`) were committed and pushed at 2026-10-19 ≈ 23:41 UTC; the first Phase 8 tape was started at 23:42. The evaluation report states its own frozen-code check: **PASS** (nothing changed). One hypothesis; unit = one floor-passed IOC-filled Polymarket entry, `trail` and `fixed0.7` paired on the identical fill; metric = net bps of notional; t = mean / cluster-robust s.e. (clusters = BTC impulse id); `strict` primary, `trades` secondary.

* **Test 1 (fresh only):** supported iff trail mean and paired difference both have one-sided t > 1.645.
* **Test 2 (pooled, N ≥ 70):** trail t > 2.0 raw / > 2.63 (6-way Bonferroni).
* **Collector:** Pure B (`--phase7 --b-exit trail`), sleeves active, A never built; count-only stop at 48 prior + live floor-passed `trail` fills ≥ 70, 90-minute cap, part 2 only if the replayed cumulative count < 70.

## 2. Collection

One session, 2,616 s (43.6 min): the count rule fired (48 + 22 live floor-passed fills ≥ 70). The replay of the saved tape (the analysis input) gives **24** fresh fills, so the cumulative N is **72 ≥ 70** and part 2 was not needed. 272 Polymarket signals, 48 (18 %) cleared the floor; 0 Hyperliquid signals did. Oracle volatility (status line, bps/√s): 0.20–0.26 for the first 20 min, 0.29–0.42 to ≈ 36 min, **0.56–0.75 in the last ≈ 8 min** (the first time the agency saw the "volatile" band); one Polymarket feed drop was visible in the status log. All of this is in the tape and was analysed as recorded (no fills dropped).

## 3. Confirmatory results (`docs/live_runs/phase8_eval.md`, `.json`)

### Test 1 — fresh out-of-sample only (p8_tape_1; `strict` = primary)

| quantity | N | clusters | mean net bps | s.e. | t | one-sided p | cluster-bootstrap 95 % CI (report only) |
|---|---|---|---|---|---|---|---|
| trail | 24 | 18 | −77 | 413 | −0.19 | 0.57 | [−841, +801] |
| fixed0.7 | 24 | 18 | +97 | 243 | +0.40 | 0.34 | [−355, +625] |
| **trail − fixed0.7** | 24 | 18 | **−175** | 275 | **−0.63** | 0.74 | [−721, +345] |

Rule: supported iff both t > 1.645 → **NOT supported** (`trades` fills give the same verdict: −77, difference −194, t = −0.72). ¢/share cross-check: trail −0.95¢, fixed0.7 −0.65¢.

### Test 2 — cumulative pooled, tapes p4–p8 (N = 72 ≥ 70)

| quantity | N | clusters | mean net bps | s.e. | t | one-sided p | cluster-bootstrap 95 % CI |
|---|---|---|---|---|---|---|---|
| trail | 72 | 56 | +427 | 256 | **+1.67** | 0.047 | [−56, +958] |
| fixed0.7 | 72 | 56 | +162 | 144 | +1.13 | 0.13 | [−128, +461] |
| trail − fixed0.7 | 72 | 56 | +265 | 176 | +1.51 | 0.07 | [−81, +602] |

Rule: N ≥ 70 and trail t > 2.0 (raw) / > 2.63 (adjusted) → **does NOT clear the raw bar** (t = 1.67). Under `trades` fills (58 entries, tapes with prints only) N < 70 and the result is "inconclusive": trail +419 (t 1.39), fixed0.7 +247 (t 1.53), difference +172 (t 0.82). ¢/share cross-check (strict): trail +1.61¢ (t 1.45), fixed0.7 +0.17¢, difference t +2.23 — the one cross-check metric that favours trail, and not a pre-registered one (cents weight dear contracts more; the decision metric was bps of notional).

Per-tape (descriptive): trail mean bps +461, +1186, +1027, +166, **−77** across p4…p8 vs fixed0.7 −156, +465, +516, +59, +97. The candidate's advantage decays across sessions; the sessions in which it was selected carry it.

Caveat that no statistic removes: the four prior tapes are the data on which `trail` was picked as best of six, so the pooled test is biased towards the candidate; that it still falls short of 2.0 reinforces the conclusion.

## 4. Exploratory, descriptive only (not part of the confirmatory analysis; no test, no conclusion)

* Within the fresh session by time: first 36 min (vol ≤ 0.42): 16 entries, trail −179 vs fixed0.7 +1 bps; last 7.6 min (vol 0.56–0.75): 8 entries, trail +125 vs fixed0.7 +289 bps. Eight entries in the faster regime say nothing either way. The pre-registration forbade a regime subset analysis; this is shown only so nobody has to wonder, and it should not be used to justify one.
* The other four exits (shadows, same fresh entries, `strict`): fixed1.0 +387, wide2.0 +351, adaptive +185, wide1.5 +154, fixed0.7 +134 (non-paired cell means in the live report, N = 22 live-counted fills), trail +18 bps — all within noise (s.e. 260–600).
* Account sleeve (`trail`, CFO-sized, binary worst-case sizing): `polymarket_b` 23 round trips, −$5.35, state `NORMAL`, no governor event; `hyperliquid_b` $10,000, no activity. Isolation was not stressed (no halt occurred).

## 5. Interpretation, with the limits stated

* The honest summary of Phases 6–8 for Polymarket floor-passed entries: **positive-looking point estimates in four of five sessions for either exit, never significant, and the apparent improvement from uncapping did not survive a clean test.** With the Phase 6 reference exit, 72 entries give +162 ± 144 bps.
* Power: with N = 24 and s.e. ≈ 275–413 bps the fresh test could only detect effects of ≳ 700 bps. A true `trail` advantage of, say, +250 bps (the pooled paired estimate) would need roughly 200+ paired entries to reach t = 2.6 — about nine more sessions like this one, and only if the effect is real.
* Regime: every recorded session except the last 8 minutes of this one was quiet (0.20–0.40 bps/√s). B's design case — a large continuing impulse — is still essentially unobserved, so these results are about B in quiet markets.

## 6. What happens next (no extension of this test)

1. Close the exit question at "no evidence that uncapping helps"; keep `fixed0.7` as the reference exit in any future work (it is also the simplest).
2. Any further test is a **new** pre-registration. The most valuable one is regime-conditional and specified *in advance by the calendar or `regime_check`*, e.g. ≥ 3 sessions in the US-open/macro windows, B (`fixed0.7`) vs its own null of zero, N set by a power calculation on the pooled s.e., stop rule count-only (OPERATOR_GUIDE §5).
3. Do not connect a wallet. The bar in OPERATOR_GUIDE §6 (fresh-data significance, an independent replication, a volatile-regime session, measured latency/fees, shadow-live reconciliation) is not met — the first item has now been tested and failed for the exit comparison, and not been met for B itself.

## 7. Reproduce

```bash
python -m quant_agency.p8_eval --check-frozen
python -m quant_agency.run_live --phase7 --b-exit trail --duration 2700 --stop-fills 70 --prior-fills 48 --record tapes/p8_tape_1.npz --tag phase8_live_1
python -m quant_agency.p8_eval --prior tapes/p4_tape_1.npz tapes/p5_tape_1.npz tapes/p6_tape_1.npz tapes/p7_tape_1.npz --fresh tapes/p8_tape_1.npz \
       --out docs/live_runs/phase8_eval.md --json docs/live_runs/phase8_eval.json
python -m quant_agency.inspect_run runs/phase8_live_1_<timestamp>
python -m pytest tests -q        # 194 tests
```
