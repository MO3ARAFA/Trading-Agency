# Phase 10 pre-registration (locked before any confirmatory data exists)

Supersedes `docs/PREREG_PHASE9.md` (never executed: no Phase 9 confirmatory data exist; its code hashes now differ by design). Code hashes: `docs/PREREG_PHASE10.json`, checked by `python -m quant_agency.p10_eval --check-frozen`.

## Hypothesis (one, confirmatory)
**H1.** Among Polymarket entries that clear the 1.5× absolute floor **and** whose *pre-impulse* σ60 is below **0.50 bps/√s**, the Architecture-B `fixed0.7` exit has net expectancy **> 0** (bps of notional after fees).

* Pre-impulse σ60 = RMS of the 1-second Binance BTCUSDT mid log-returns (bps) over the 60 s window that ends **15 s before the signal** (`HighConvictionSniper.regime_tags`; `quant_agency/regime.py`). The gate excludes the triggering impulse by construction. Unknown baseline (< 75 s of BTC history after a process start) = excluded.
* Test: one-sided α = 0.05; t = mean / cluster-robust s.e. (clusters = BTC impulse id **within a run directory**); Student-t reference with (clusters − 1) df; fill model `strict` (primary), `trades` (secondary).
* **Data: fresh only** — the live shadow rows (`b_shadow.jsonl`) of run directories named `p10r*`, written by `regime_daemon --continuous`. Phase 4–8 data generated the hypothesis and are excluded. `p10v*` (validation) runs are refused by `p10_eval`.
* The ACCOUNT also obeys the gate (and `fixed0.7`); shadows are spawned and tagged for every signal, so the analysis population is a filter on rows that exist regardless of the gate.
* **N\* = 608** gated floor-passed Polymarket entries: one-sided non-central-t power 0.80 for a true mean of +127.9 bps, σ_eff = 1,266 bps (cluster-inflated; 62 in-sample gated entries, 48 clusters, ratio 0.774). Sensitivity: half the effect (+64) needs 2,425; +100 bps needs 994; +250 bps needs 161; power at N\* if the truth is half is 0.34. **A non-rejection means "no evidence of an effect as large as +128 bps", not "no effect".**
* Stopping rule (count-only): the collector stops when the live counter of gated, floor-passed, `strict`, Polymarket `fixed0.7` fills reaches 608 **or** after **72 capture-hours**, whichever first; no extension. The analysed N is the count in `b_shadow.jsonl`.
* Operations that are part of the protocol: `--continuous` supervision, tape rotation every 30 min, process cycling every 1.5 h (market set), crash restarts (cold) with back-off. All rows from all processes are used; open positions at a process end are finalised at the last quote as taker exits and kept.

## Secondary (reported, no decision rule)
The same entries without the gate, and the turbulent-baseline bucket (σ_pre ≥ 0.50), both with N/mean/s.e./t; the `trades` model; a conditional Hyperliquid arm (analysed only if ≥ 30 floor-passed Hyperliquid entries accrue — 0 of 578 signals ever cleared the floor in Phases 4–8).

## Not allowed
Changing the gate, lag, threshold, floor, exit, fill model, metric or clustering; dropping or re-weighting rows; analysing a sub-period or regime subset to rescue a non-rejection; using Phase 4–8 data in the test; extending the cap; choosing the stop from P&L.

## Disclosures (made in advance)
* **The gate is post hoc.** Phase 9's split (σ60 at the signal time: quiet +248 ± 166 bps N = 55 vs active −161 ± 271 N = 16) was found by looking at the 71 Phase 4–8 entries. Re-labelled with the *pre-impulse* baseline the same entries give **+128 ± 161 bps (N = 62, t = 0.80) below 0.50 and +347 ± 327 (N = 9) at or above it**: 8 of the 16 "active" entries had a quiet baseline — the Phase 9 label was reacting to the impulse itself. So the in-sample support for the gate is weak, and the spec's honest in-sample number is **+128 bps, not +248**, with t = 0.80. The gate is kept because it was specified as the thing to test, it costs 13 % of entries, and the collection is identical with or without it (the ungated comparison is a pre-registered secondary).
* A turbulent baseline did coincide with wider Polymarket spreads (median 526 vs 282 bps) and a lower floor pass rate (19 % vs 26 %) — consistent with, but not proof of, liquidity providers stepping back.
* Validation runs (excluded): `p10v1/p10v2` on 2026-10-20 ≈ 04:56–05:10 UTC (rotation, tags, session cycling, SIGINT shutdown), plus the Phase 9 validation segments.
* A rejection of H1 would still not be a trading recommendation (docs/OPERATOR_GUIDE.md §6).
