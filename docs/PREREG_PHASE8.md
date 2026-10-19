# Phase 8 pre-registration (locked before any Phase 8 data exists)

Committed with the SHA-256 of every file that decides entries, exits, fills and the test statistic (`docs/PREREG_PHASE8.json`; checked by `python -m quant_agency.p8_eval --check-frozen`, and the evaluation report states whether the check passed). Git history timestamps this file before the first Phase 8 tape is recorded.

## Hypothesis (one, planned)
On **floor-passed (1.5×) Polymarket entries**, the oracle-guided **`trail`** exit has higher net expectancy than the **`fixed0.7`** exit, and `trail`'s expectancy is positive. Nothing else is tested. No other exit, venue, floor multiple, fill model or subset is part of the confirmatory analysis.

* Candidate `trail`, baseline `fixed0.7`: exactly the Phase 7 implementations and parameters (`BConfig`, `high_conviction_sniper.py`, unchanged).
* Unit of observation: one floor-passed, IOC-filled Polymarket entry (the entry is identical for both exits, so the comparison is **paired**).
* Metric: net bps of notional after fees on the fixed-notional shadow (¢/share and $ are reported as cross-checks only).
* Statistic: t = mean / cluster-robust s.e. (clusters = BTC impulse id; entries on different markets reacting to the same impulse are one cluster). One-sided p from the normal approximation.
* Fill models: `strict` (primary, available on every tape) and `trades` (secondary, tapes with trade prints) are reported side by side. Decisions use `strict`.

## The two tests
1. **Fresh out-of-sample only (Phase 8 tapes alone).** `trail` mean > 0 **and** paired difference `trail − fixed0.7` > 0. "Supported" iff **both** one-sided t > 1.645. Reported at whatever N results; no minimum N is required to report it, and an N this small is expected to be underpowered (stated in advance).
2. **Cumulative pooled** (tapes p4, p5, p6, p7 + Phase 8). Requires N ≥ 70 floor-passed entries. `trail` mean t must exceed **2.0** (raw) and **2.63** (adjusted for the six Phase 7 exits, two-sided Bonferroni 5 %). If N < 70 the result is "inconclusive", not "fail". The pooled sample contains the data on which `trail` was selected as best of six, so it is biased in favour of the candidate; the 2.63 bar corrects for the six-way choice only. The fresh-only test is the clean one.

## Data collection and stopping rule (count-only; never looks at P&L)
* Pure Architecture B, `sleeves.py` active, Architecture A never built (`--phase7`). Account exit for the sleeves = `trail` (the account is not part of the hypothesis; shadows are independent of it).
* Part 1: `python -m quant_agency.run_live --phase7 --b-exit trail --duration 2700 --stop-fills 70 --prior-fills 48 --record tapes/p8_tape_1.npz --tag phase8_live_1`. Stops early the moment 48 + live floor-passed strict `trail` fills ≥ 70.
* Part 2 only if the cumulative count (48 + part-1 count from the replayed tape) is < 70: `--duration` = 5400 − elapsed part-1 seconds (≤ 2700), `--prior-fills` = that cumulative count, `--record tapes/p8_tape_2.npz`.
* Hard cap: 5,400 s (90 min) of live capture in total. If N < 70 at the cap, the analysis is run and reported as inconclusive; **no extension**.
* A session that crashes without saving its tape contributes nothing and is repeated once within the remaining time budget.
* Analysis input = deterministic replay of the recorded tapes through the frozen code (`p8_eval`), not the live counters (those are only the stopping signal and may differ by a few fills).

## Explicitly not allowed
Changing any parameter, the floor, either exit, the fill models, the metric or the clustering; dropping or re-weighting fills; analysing a regime subset; running more sessions than the cap; choosing the stopping time from outcomes.

## Disclosures made in advance
* Collection starts around 23:45 UTC on 2026-10-19 — **outside** the US-open / macro high-volatility window. The test is regime-agnostic by design; a quiet-regime result says nothing about a volatile regime.
* Prior sessions (Phase 7 table, strict, 48 fills): `trail` +680 ± 306 bps (t = 2.22), `fixed0.7` +195 ± 177 (t = 1.10), paired difference t = 2.35 — the effect we are trying to replicate.
* Even if both tests pass, that is **not** a trading recommendation: see docs/OPERATOR_GUIDE.md for what else must hold before a wallet is connected.
