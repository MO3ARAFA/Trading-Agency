# Phase 9 pre-registration (locked before any confirmatory data exists)

Code hashes in `docs/PREREG_PHASE9.json` (checked by `python -m quant_agency.p9_eval --check-frozen`; the evaluation report prints the result). This file and the JSON are committed and pushed before the daemon is ever started in confirmatory mode. The confirmatory collection has **not** been started at the time of writing.

## Hypothesis (one, confirmatory)
**H1.** On floor-passed (1.5×) Polymarket entries, the Phase 6/7 reference exit **`fixed0.7`** has net expectancy **> 0** (bps of notional after fees).

* Test: one-sided, α = 0.05, t = mean / cluster-robust s.e. (clusters = BTC impulse id), Student-t reference with (clusters − 1) df, fill model `strict` (primary; `trades` reported as secondary).
* Unit: one floor-passed IOC-filled Polymarket entry; exit `fixed0.7` exactly as in Phase 7 (`BConfig` untouched; the ACCOUNT exit is also `fixed0.7`; `--b-exit fixed0.7` is hard-wired in the daemon).
* **Data: fresh only.** Confirmatory tapes are the daemon's `p9_seg*.npz`. Tapes from Phases 4–8 generated this hypothesis and are **excluded** from the test. `p9v_seg*` (validation) tapes are refused by `p9_eval`.
* **Population:** the floor-passed entries recorded during daemon-triggered sessions (a scheduled high-liquidity window or sustained σ60 ≥ 0.45) — i.e. whatever mixture of regimes the trigger delivers. H1 is about that population, not about quiet hours.
* **Sample size: N\* = 386** floor-passed Polymarket entries (from `docs/live_runs/phase9_regime_power.md`): non-central-t power 0.80 at α = 0.05 (one-sided) for a true mean of **+155.7 bps** (the observed mean of the 71 labelled Phase 4–8 entries), with σ_eff = 1225.8 bps (observed cluster-robust s.e. 145.5 × √71) and clusters = 0.775·N. 
  The sensitivity table is part of the pre-registration: a true mean of half the observed value (+78) would give power 0.34 at N\*; +100 bps would need N = 931; +250 bps N = 151. **A non-rejection at N\* means "no evidence of an effect as large as +156 bps", not "no effect".**
* Stopping rule (count-only, never looks at P&L): the daemon stops when the cumulative live floor-passed fill counter ≥ N\* **or** total capture time reaches **24 hours**, whichever first. The analysis N is the replay count; if the replay count of the finished tapes is < N\* while time remains under the cap, collection resumes with the replay count as `--prior-fills`. At the cap the result is reported as is (inconclusive if N < N\*). No extension.

## Secondary (reported, no decision rule)
* **S1 – regime split:** same entries split at σ60(signal time) ≥ 0.50 (active) vs < 0.50 (quiet): N, mean, cluster s.e., t, each reported; no test of difference is a decision.
* **S2 – Hyperliquid arm (conditional):** analysed iff ≥ 30 floor-passed Hyperliquid entries accrue (Phase 4–8: **0 of 578 signals ever cleared the floor, in either regime**, so there is no variance to plan from and no power calculation exists). If analysed, it is exploratory.

## The regime trigger (daemon), exactly as frozen
* Estimator: σ60 = RMS of the last 60 one-second Binance BTCUSDT mid log-returns in bps/√s (`quant_agency/regime.py`), from a single `btcusdt@bookTicker` websocket.
* Start capture when **any** of: (a) inside a scheduled window — London 07:00–10:00 UTC or US 13:30–16:30 UTC, **Monday–Friday only**; (b) σ60 ≥ **0.45** continuously for ≥ **30 s**.
* Stop capture (graceful, tape saved) only when **all** of: outside every window; σ60 < **0.35** continuously for ≥ **300 s**; session age ≥ **600 s**. Between 0.35 and 0.45 nothing changes (hysteresis). Unknown σ60 (feed stale > 10 s) never starts or stops.
* Each capture segment is at most 2,700 s (the child ends by itself; the daemon may start the next segment on its next 5 s tick if the trigger still holds).
* Open positions at a segment end are finalised at the last quote as a taker exit (`end_of_run`) and **kept** in the analysis.
* The triggers are chosen from the calendar and σ60 only — never from realised P&L.

## Not allowed
Changing any threshold, window, estimator, exit, floor, fill model, metric or clustering after this commit; dropping or re-weighting entries; analysing a subset to rescue a non-rejection; using Phase 4–8 data in the confirmatory test; re-running with different seeds; extending past the cap.

## Disclosures
* **Validation pass (excluded):** on 2026-10-20 04:21–04:26 UTC the daemon was run live with deliberately loosened thresholds (`--start-thr 0 --stop-thr 99 --calm-s 20 …`) to exercise the real start → graceful stop → restart → SIGINT shutdown path; two short segments (`p9v_seg1/2`, 128 s and 66 s) were recorded. They are labelled `validation` in the log, use a different prefix, and are never analysed.
* **Evidence that the regime assumption may be wrong (pre-stated):** among the 71 labelled Phase 4–8 entries, `fixed0.7` was **+248 bps (quiet, N = 55)** vs **−161 bps (active σ60 ≥ 0.5, N = 16)**; difference −409 ± 318 (t = −1.29); a regression on σ60 gives slope −1,222 ± 674 (t = −1.81). Not significant, but the prior direction is *against* an active-regime advantage, and the trigger collects an active-heavy mixture. N\* was computed from the pooled variance, which is dominated by within-regime variation (between-regime share of variance 1.8 %); the active-regime per-entry SD (1,517) is larger than the quiet one (1,193), so an active-heavy sample is somewhat less well powered than N\* assumes.
* `regime_daemon.py` was re-frozen twice after the validation pass for cosmetic shutdown fixes (await/unwind the websocket tasks on exit); no confirmatory data existed at either point, and the final hashes are those in the JSON.
* Even a rejection of H1 at N\* would **not** be a trading recommendation (docs/OPERATOR_GUIDE.md §6).
