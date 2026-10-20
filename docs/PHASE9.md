# Phase 9 — power-calculated `fixed0.7` protocol and the regime-triggered collector (2026-10-20)

**Status: protocol locked, tools built and validated; the confirmatory collection has NOT been run.** This phase produces no test result about `fixed0.7`. It produces (a) the sample size the test needs, (b) a description of how `fixed0.7` behaved by BTC volatility in the data we already have, and (c) a daemon that collects the data when the pre-registered conditions hold.

## 0. Audit of the premises

| Premise in the brief | Finding |
|---|---|
| "Phase 8 settled the exit question … impulses do not follow through in quiet hours, so waiting gives back the convergence" | Phase 8 showed `trail` was **not better** than `fixed0.7` on 24 fresh entries (paired −175 bps, t = −0.63) and not significant on 72 pooled. It did not establish a mechanism: the fresh sample cannot rule out a +680 bps effect (95 % CI of `trail` [−841, +801]). "Quiet hours" is also not clean — the last ~8 minutes of that session were at 0.56–0.75 bps/√s. |
| "`fixed0.7` +97 bps fresh, +162 ± 144 pooled" | Correct as numbers, but neither is distinguishable from zero (t = 0.40 and 1.13). With the 60-second regime label, 71 of the 72 entries are usable (one has < 60 s of BTC history): mean +155.7 ± 145.5 bps, t = 1.07. |
| "Active windows are where B's design case lives" | The theory says so; **the existing data lean the other way**: `fixed0.7` was +248 bps in quiet (N = 55) and −161 bps in the active regime (σ60 ≥ 0.5; N = 16); a regression on σ60 has slope −1,222 ± 674 (t = −1.81). Not significant, but it is the only evidence we have and the daemon will collect an active-heavy mixture. This is stated in the pre-registration so it cannot be forgotten later. |
| "Hyperliquid when impulses clear the floor" | In **578** Hyperliquid signals over five sessions, in both regimes (474 quiet, 104 active), **0** cleared the 1.5× floor. No variance exists to plan from, so that arm is conditional and cannot be powered. |

## 1. `fixed0.7` by real-time BTC volatility (tapes 4–8; `docs/live_runs/phase9_regime_power.md`)

σ60 = RMS of the last 60 one-second Binance BTCUSDT mid returns (bps/√s), causal, evaluated at each signal time; the same function (`regime.py`) is what the daemon triggers on. No parameter was touched.

| regime | tape-hours | PM signals/h | floor pass rate | floor-passed fills | fills/h | mean net bps (strict) | cluster s.e. | t | per-entry SD | hit |
|---|---|---|---|---|---|---|---|---|---|---|
| quiet σ60 < 0.50 | 2.45 | 206 | 27 % | 55 | 22.5 | **+248** | 166 | +1.49 | 1,193 | 62 % |
| active σ60 ≥ 0.50 | 0.18 | 856 | 19 % | 16 | 87.3 | **−161** | 271 | −0.59 | 1,517 | 44 % |
| all | 2.63 | – | – | 71 | – | +155.7 | 145.5 | +1.07 | 1,273 | – |

* Active − quiet: −409 ± 318 bps (t = −1.29), descriptive. By σ60 tercile: low (0.12–0.28) +398 (t 1.61), mid +64, high (0.43–1.12) −2.
* **Variance decomposition:** the between-regime share of entry variance is only η² = **1.8 %**; 98.2 % is within-regime. Regime explains almost none of the dispersion of single outcomes, so the pooled σ_eff is the right planning scale; the active regime is noisier (SD 1,517 vs 1,193) and yields ~4× more floor-passed fills per hour (87 vs 22.5 — resting on 0.18 h of data and 16 fills).
* Design effect of clustering by BTC impulse: 0.93 (clusters = 55 for 71 entries).

## 2. Power calculation

One-sided cluster-robust t-test of mean > 0, α = 0.05, power 0.80; non-central t with (clusters − 1) df, clusters = 0.775·N; σ_eff = s.e.·√N = **1,226 bps**.

| planning effect | μ (bps) | required N\* |
|---|---|---|
| **observed mean (locked)** | **+156** | **386** |
| observed 80 % one-sided lower bound | +33 | 8,405 |
| half the observed mean (winner's-curse allowance) | +78 | 1,535 |
| +100 bps ( ≈ 1 % of notional per entry) | +100 | 931 |
| +250 bps | +250 | 151 |
| observed 95 % upper bound | +395 | 62 |

N\* = 386 as instructed (observed mean and cluster-robust SD). The honest reading of the table: power at N\* is 0.80 **only if the true mean is at least what we observed**; at half of it, power is 0.34. The point estimate is itself uncertain (its 80 % lower bound is +33), so a null at N\* will not say the edge is zero — it will say it is not as large as +156 bps.
**Time:** at the in-sample supply rates that is ≈ 17 h of quiet capture or ≈ 4.4 h of active capture; the daemon's scheduled windows cover 6 h per weekday, so the realistic horizon is one to a few weekdays plus any volatility triggers. The cap is 24 capture-hours.

## 3. `regime_daemon.py` (one command: `python -m quant_agency.regime_daemon`)

* **Standby:** one Binance Vision `btcusdt@bookTicker` websocket, a 60-sample ring, a 5 s decision tick. Measured: **1.4 % CPU, 43 MB RSS** (95 s run); no engine, numba or Polymarket/Hyperliquid feeds.
* **Rules (frozen):** start on a scheduled window (London 07:00–10:00 UTC, US 13:30–16:30 UTC, Mon–Fri) **or** σ60 ≥ 0.45 for 30 s; stop only outside windows with σ60 < 0.35 for 300 s after ≥ 600 s of session (hysteresis band 0.35–0.45; unknown σ60 never changes state); segments ≤ 2,700 s. Account exit hard-wired to `fixed0.7`, Pure B, sleeves active, Architecture A never built.
* **Plumbing:** `run_live` gained `--stop-file` (graceful end: tape saved, positions finalised) and `--count-file` (live floor-passed fill counter); the daemon passes `--stop-fills N* --prior-fills cum`, so a segment also ends by itself at the count target; everything the daemon decides is appended to `runs/p9_daemon/daemon_log.jsonl` (60 s σ60 trace, starts/stops with the reason, segment fill counts).
* **Tests (23 new; 210 total pass):** estimator (RMS on a constant-drift series = 1.0, NaN before 60 s, carry-forward, batch = streaming), UTC/weekday/half-open windows, spike shorter than the confirm time does not start, hysteresis, calm timer reset, window blocks the calm stop, NaN holds state, segment-end restart, overrides mark a run `validation`, a dry-run daemon cycle with an injected clock, `p9_eval` refuses validation tapes.
* **Live validation pass (2026-10-20 04:21–04:26 UTC; `docs/live_runs/phase9_validation/`):** with loosened thresholds the real daemon read σ60 from the live feed (0.52–0.59 at the first trigger), launched a real `run_live` segment, requested a stop after the calm timer (`stop_requested`), the child saved its tape and exited rc = 0 (128 s, 1 live floor-passed fill), restarted a second segment on the next tick, and on SIGINT stopped it gracefully (66 s, tape saved, no orphan process). Those two tapes (`p9v_seg1/2`) are validation-only and refused by `p9_eval`.
* **Not validated:** the *real* thresholds have not triggered live (a 95 s dry run read σ60 = 0.14); the scheduled windows were exercised by unit tests only (it is 04:30 UTC now); behaviour over a multi-hour run, a feed outage inside a segment, and the cost of restarts are untested. Each new segment loses the hunter's warm-up (≈ 45 s to the first lead-lag calibration, a 180 s calibration window) — about 5–10 % of a 600 s minimum session.
* **Practical caveat:** this cloud container is ephemeral; a multi-hour collection must run on a persistent host (the tapes are git-ignored, so keep `tapes/p9_seg*.npz` and `runs/p9_daemon/daemon_log.jsonl`).

## 4. Pre-registration (`docs/PREREG_PHASE9.md/.json`, committed before any confirmatory data)

H1: floor-passed Polymarket `fixed0.7` net expectancy > 0, one-sided α = 0.05, fresh daemon data only (Phase 4–8 excluded), `strict` primary, N\* = 386, count-only stop or 24 capture-hours, no extension; secondary regime split and a conditional (≥ 30 entries) Hyperliquid arm. 21 files are SHA-256-pinned; `python -m quant_agency.p9_eval --check-frozen` and the evaluation report both state whether anything changed. (`regime_daemon.py` was re-frozen twice after the validation pass for cosmetic shutdown fixes, before any confirmatory data.)

## 5. How to run it, and what to expect

```bash
python -m quant_agency.regime_daemon --dry-run                 # watch σ60 and the decisions, launch nothing
python -m quant_agency.regime_daemon                            # confirmatory: runs until N* live fills or 24 capture-hours
python -m quant_agency.p9_eval --tapes tapes/p9_seg*.npz --out docs/live_runs/phase9_eval.md
```
Expect: a null result is the more probable outcome on the evidence so far (pooled t = 1.07; the active regime, which the trigger over-samples, is currently the worse one). Whichever way it comes out, it will be a clean answer about `fixed0.7` on fresh data — which is what none of Phases 6–8 had.

## 6. Open items

1. Run the collection on a persistent host through at least one London and one US window (and any volatility trigger); report the result with the pre-registered test only.
2. If N\* is reached and H1 is rejected, that is still not a trading recommendation: OPERATOR_GUIDE §6 (independent replication, a genuinely volatile-regime session analysed on its own, measured latency/fees, shadow-live reconciliation) is untouched.
3. If the regime split in the fresh data confirms a negative active-regime effect, the right follow-up is a *new* pre-registration restricted to quiet-regime or scheduled-window entries, not an amendment of this one.
