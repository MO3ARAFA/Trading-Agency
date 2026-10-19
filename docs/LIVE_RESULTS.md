# Phase 3 — live validation results (2026-10-19)

All numbers below come from **real streaming data** (Binance Vision combined stream + Gate + Kraken BBO), 67 markets:
BTCUSDT oracle + 60 top-volume Binance USDT alts + 6 cross-venue BTC/ETH/SOL books. Execution is paper only.
Full reports, JSON summaries and CEO audit trails are in `docs/live_runs/`.

## Bottom line (read this first)

**On this data, in this environment, the BTC→alt lead-lag dislocations are real but far too small to trade after costs.**
The system found, measured and correctly *refused* to trade them; the CEO/CFO governance loop did its job.
Nothing here is evidence of a profitable strategy.

* Same-venue alts show **no measurable lag behind BTC at ≥100 ms resolution** (peak HY lags 0–0.3 s, many ≤0; an independent 1-second-grid regression on the raw tape agrees: best lag ≈ 0 s). A 150 ms order latency alone halves what gross edge there is.
* Mean **gross** markout of detected gaps is ≈ **0 to +1 bps** at t+1 s…t+30 s (hit rate 23–55 %) versus **~2 bps average spread** and **15 bps round-trip fees** at Binance VIP0-with-BNB rates.
* Even with **zero fees and zero latency** the all-signal taker net markout is **−1.0 bps** (gross +1.2 − spread). Only the tightest-spread markets (<0.5 bps: ETH/BNB/ZEC-type) show a positive net (+0.98 bps, 77 % hit) — from **n = 35 signals** clustered in a handful of BTC impulses on one 15-minute tape; treat as a hypothesis, not a result.

## The runs

| run | data | fee/side | detected gaps | CFO-approved | closed paper trades | paper PnL | CEO |
|---|---|---|---|---|---|---|---|
| **A** live, 900 s | live | 7.5 bps | 197 | **0** (all `net_edge_below_hurdle`) | 0 | $0.00 | 11 interventions (see note) |
| **B** live, 1200 s | live | 1.0 bps | 155 | 7 | 1 (maker TTL expired ×4, post-only-would-cross ×1, IOC no liquidity ×1) | +$0.02 | 9 interventions |
| A′ replay of A's tape, final code | recorded live tape | 7.5 bps | 243 | 0 | 0 | $0.00 | 20 |
| A″ replay of A's tape, final code | recorded live tape | **0 bps** | 243 | 62 | 17 | −$0.53 | **17 → state HALTED** |
| B′ replay of B's tape | recorded live tape | 1.0 bps | 155 | 7 | 1 | +$0.02 | identical to live B (determinism check ✔) |

(Run A executed before the CEO evidence-gating fix, so it ratcheted `z_thr` to 5.0 on stale signals; A′/A″ are the same tape through the final code. Signal counts differ (197 vs 243) for exactly that reason.)

### Feed & latency telemetry (live)
* Binance combined stream **≈ 790–1,000 msgs/s** (BTC book+aggTrade + 60 books) on one connection, plus Gate ≈ 12/s, Kraken ≈ 26/s; **zero book rejects**.
* Reconnects were exercised live (Binance ×1 in run A, Gate ×1 in B, Kraken ×2 in A) and handled by the feed-reset guard (no fake impulses — verified against the tape).
* Hunter scan over all 66 markets: **p50 ≈ 1 µs (early-exit, no impulse), p90 ≈ 170–185 µs, p99 ≈ 510 µs**, max ≈ 19–115 ms (rare GIL contention with the calibration thread).
* BTC tick received → **CFO-approved, fully-formed executable payload: p50 619 µs, p90 1.0 ms, p99 1.2 ms** (n = 7, run B).

### Lead-lag map (run A, final model state) — highest-ρ markets
`gate:BTC_USDT β0.89 ρ0.84` · `BNBUSDT β0.69 ρ0.75 lag 0.4s` · `gate:ETH β1.19 ρ0.72` · `LINKUSDT β1.65 ρ0.69` · `AVAXUSDT β1.96 ρ0.69` · `DOGEUSDT β1.56 ρ0.65` · `SOLUSDT β1.63 ρ0.64`.
Independent check on the raw tape (1 s grid, 3 s windows): SOL β 1.65, XRP 1.56, ETH 1.36, Gate-BTC 0.87 vs the agency's Kalman 1.63 / 1.49 / – / 0.89 → **estimator validated on real data**.

### Markout performance table — all detected gaps (incl. CFO-rejected shadow cohort)
Gross = mid→mid after the latency-delayed fill; net = cross the spread both ways + round-trip taker fees.

| horizon | A live (7.5 bps): n=197 gross / net | B live (1 bp): n=155 gross / net | tape A, 0 fee, 0 latency (n=243) gross / net |
|---|---|---|---|
| t+1 s  | +0.25 / −16.96 | +0.36 / −3.94 | +0.81 / – |
| t+3 s  | +0.36 / −16.86 | +0.94 / −3.37 | – |
| t+5 s  | −0.09 / −17.31 | +0.96 / −3.33 | +1.23 / −1.03 |
| t+10 s | +0.04 / −17.18 | −0.04 / −4.36 | – |
| t+30 s | +0.45 / −16.76 | +0.52 / −3.84 | +1.60 / – |

Net-vs-spread at zero fee/latency (tape A, t+5 s): `<0.5 bps: +0.98 (n35, 77% hit)` · `0.5–1: +0.35` · `1–2: −0.52` · `2–5: −1.65` · `5–20: −4.40`.

### Fee × latency sweep (same live tape, final code) — `docs/live_runs/sweep_fee_latency.md`
| fee/side | latency | approved | closed | paper PnL | gross@5s | net@5s (all, taker) | CEO end state |
|---|---|---|---|---|---|---|---|
| 7.5 | 0 / 150 / 500 ms | 0 / 0 / 0 | 0 | $0 | +1.23 / +0.60 / +0.53 | −16.0 / −16.7 / −16.7 | NORMAL |
| 1.0 | 0 / 150 / 500 ms | 18 / 22 / 22 | 15 / 11 / 14 | −1.43 / −1.45 / −1.55 | same | −3.0 / −3.7 / −3.7 | DEFENSIVE / TIGHTENED / TIGHTENED |
| 0.0 | 0 / 150 / 500 ms | 64 / 62 / 75 | 44 / 17 / 41 | −0.96 / −0.53 / −1.93 | same | −1.0 / −1.7 / −1.7 | DEFENSIVE / HALTED / TIGHTENED |

## CEO ↔ CFO interventions on real data

**What the CEO did when the CFO was allowed to trade (A″, zero fees, tape A)** — full trail in `docs/live_runs/replayA_fee0/ceo_audit.jsonl`:

```
#1  RETUNE_IMPULSE        hunter  false-gap 58% over 12 fresh signals            z_thr 3.0 → 3.25
#3  TIGHTEN_CFO           cfo     trade expectancy −2.57 bps over 6 trades < −1  NORMAL→TIGHTENED  hurdle 1.0→1.5, size×0.8
#5  DEFENSIVE_MAKER_ONLY  cfo     trade expectancy −3.22 bps over 7; fee bleed: gross +1.34 vs net −0.76 bps
                                  TIGHTENED→DEFENSIVE  hurdle 1.5→2.5, size×0.4, taker → maker-only
#8,#9 QUARANTINE_MARKET   XLMUSDT, ADAUSDT  negative_markouts: n=6 net@5s −4.7 / −3.1 bps, hit 0%; blacklisted 600 s
#10 CFO_EDGE_RECALIBRATION cfo    CFO predicted +0.21 bps but realised −4.37 bps (ratio −20.8): edge credit 1.00→0.85
#12 HALT_TRADING          cfo     approved net markout −4.37 bps over 29 < −1.0; DEFENSIVE→HALTED; stand down 300 s
#13,#16 QUARANTINE_MARKET ENAUSDT, TRUMPUSDT  …
```
This is the CEO *auditing the CFO's own numbers* (predicted vs realised edge), diagnosing fee bleed (gross>0 but net<0), switching taker→maker-only, quarantining losing markets, tightening Hunter impulse thresholds, and finally halting — each with its KPI evidence in the audit record.

**At realistic fees (A, B)** the CFO's gating already blocks nearly everything, so the CEO's job is mostly Hunter quality control (retune Z / lag window to the vol regime and false-gap rate) and per-market quarantine (e.g. APTUSDT: n=6, net@5s −16.1 bps, 0 % hit).

## What this does and doesn't show
* ✔ The full stack runs 24/7-style on live data at ~1k msgs/s with sub-ms internal decision latency, deterministic replay, and an auditable governance loop.
* ✔ The lead-lag estimators recover planted lags/betas (synthetic tests) and match an independent regression on real data.
* ✘ No profitable configuration was found. Edge candidates for further research (not claimed): tight-spread large caps only; maker execution with real queue-position modelling; very low/zero fee tiers; co-located latency; longer tapes (these are 15–20-minute samples in a quiet regime: BTC vol ≈ 0.3 bps/√s).
* Caveats: timestamps are taken at *our* gateway (cloud → proxy → venue); paper fills assume 150 ms order latency and no queue priority; shorts are perp-style; one quiet-regime session per tape → wide confidence intervals (cluster-robust s.e. are reported in each table).
