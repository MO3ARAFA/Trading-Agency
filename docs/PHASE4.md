# Phase 4 — Venue & microstructure specialization (live, 2026-10-19)

One 20-minute **live** session (19:35–19:55 UTC) on **151 markets over 7 feeds**: 29 Binance Vision (BTCUSDT oracle + tight-spread USDT/USDC/FDUSD majors +
triangle components), 38 cross-venue books (Gate, Kraken, Coinbase `level2_batch`, Hyperliquid perps `bbo`, Deribit perps `quote.*`) and **84 Polymarket CLOB
markets** (threshold, bracket, hourly Binance-candle Up/Down, 5m/15m/4h Chainlink-TWAP Up/Down). Execution is paper only. Raw report:
`docs/live_runs/phase4_live/report.md`; the **deterministic replay of the same recorded tape through the final code** (adds the momentum control, fee-class and
cents-per-share tables) is `docs/live_runs/phase4_replay/report.md`. The replay reproduces the live session (117 Polymarket signals, 24 CFO approvals, identical markout tables).

## 0. Audit of the premises (what the data does and doesn't say)

| Premise in the brief | What was measured |
|---|---|
| "Alts failed because Binance market makers update in <5 ms" | Not measured and not measurable here: our timestamps are taken at a cloud gateway behind an egress proxy. What *is* measured is a **decay of the same-venue edge over 0 → 150 → 500 ms** (below). That is consistent with fast quote updating, not proof of a <5 ms mechanism. |
| "Golden Lead: <0.5 bps spread ⇒ +0.98 bps net, 77 % hit rate" | Run 1's number came from **n = 35 signals, zero latency, zero fee**. Treated as a pre-registered hypothesis and re-tested out-of-sample (n = 124, 19 BTC impulses): it **replicates at zero latency** (+1.19 ± 0.37 bps, 74 % hit) and **does not survive 150 ms** (+0.63 ± 0.40, 58 %; "not supported at 2σ"). In the specific zero-fee Binance FDUSD/USDC class it is **−0.09 ± 0.26 bps (n = 13) at 150 ms**. |
| "Zero-fee FDUSD/USDC pairs" | **Assumption, not fact.** Public data cannot verify any account's fee. The report prints it as an assumption and every table also shows zero-fee `net0`. |
| "A 1 s Binance oracle exploits slower venues/prediction markets" | **Partly true.** Hyperliquid perps lag Binance by ~0.7–0.9 s and show a latency-robust gross lead; Polymarket's CLOB converges to BTC-implied fair value beyond what BTC drift explains. **Neither is profitable after taker costs at public retail fee schedules.** |

## 1. What was built (all unit-tested, 113 tests)

* `venues.py` — venue catalogue, **assumed** public retail fee table, Binance scalp-universe discovery (spread ≤ 3 bps watch set; the **0.5 bps hard gate is enforced in the CFO**, wider signals become shadow `rejected_gate` cohorts so the gate's effect is measurable).
* `market_watchers.py` — per-market fee schedules (incl. Polymarket's price-dependent `0.07·p·(1−p)`), per-market spread gates, market kinds (spot / perp / prediction).
* `feeds.py` — adapters: Coinbase `level2_batch` (true top of book), Hyperliquid `bbo`, Deribit `quote.*`; fixed Polymarket "slow consumer" disconnects (O(1) top-of-book, dedupe unchanged tops).
* `cross_venue_arb.py` — basis-adjusted locked cross-venue gaps (168 pairs) and triangles (18), **two/three-leg IOC paper execution with leg risk**, persistence-after-latency shadow tracking, CFO gating (`gap > fee_A + fee_B + slippage + hurdle`), CEO pair quarantine.
* `polymarket_watcher.py` — Gamma discovery, CLOB WS, analytic fair probabilities (threshold / bracket / terminal Up-Down / TWAP Up-Down), the same lead-lag signal definition as the Hunter, and a **momentum control**.
* CFO/CEO: per-market fees and gates, latency-sensitivity shadow trackers (0 / 150 / 500 ms), arb accounting, symmetric significance guards (a noisy winner no longer counts as a GOOD review).

## 2. Before / after vs Run 1 (15-min live, 60 same-venue USDT alts, 7.5 bps/side)

| metric | Run 1 | Phase 4 (replay of live tape) |
|---|---|---|
| directional signals detected | 197 | 410 (+117 Polymarket) |
| **CFO approval rate** | **0 / 197 (0 %)** | **24 / 527 (4.6 %)** — 9 directional/Polymarket + arb; rejects: spread gate 257, net-edge 135, quarantined 88 |
| gross markout @1s / @5s / @30s (directional) | +0.25 / −0.09 / +0.45 bps | +0.51 / **+0.74** / +0.25 bps |
| hit rate (gross > 0) @5s | 34 % | **52 %** |
| zero-fee net0 @5s, crosses spread | −2.31 bps | −0.43 bps |
| tight-spread (<0.5 bps) net0 @5s | +0.98 [n=35, 77 %, **0 ms**] | +1.19±0.37 [n=124, 74 %, **0 ms**] · **+0.63±0.40 [58 %, 150 ms]** · +0.51±0.46 [48 %, 500 ms] |
| closed paper trades / PnL | 0 / $0 | 40 / +$23.24 (**see §6: not a result**) |

The universe change did what the brief predicted *qualitatively* — higher gross markouts and hit rates, and the CFO finally approves trades — but the improvement is **mostly the removal of wide-spread markets**, and what remains is ≲1 bp gross.

## 3. Battleground 1

**Tight-spread cohort (<0.5 bps), t+5s, net0 = zero-fee net ± cluster-robust s.e.:**

| class | n | 150 ms | 0 ms |
|---|---|---|---|
| **Hyperliquid perps** | 39 | **+2.03 ± 0.48 (87 % hit)** | +2.12 ± 0.45 (87 %) |
| Kraken spot | 27 | +0.32 ± 0.41 | +1.15 ± 0.37 |
| Binance, 7.5 bps pairs | 13 | +0.27 ± 0.24 | +0.81 ± 0.25 |
| **Binance, assumed zero-fee (FDUSD/USDC)** | 13 | **−0.09 ± 0.26** | +0.52 ± 0.28 |
| Gate / Coinbase / Deribit | 14 / 7 / 11 | −0.38 / +0.16 / −0.76 | +0.49 / +1.08 / +0.25 |

* The same-venue Binance tight-spread edge **exists only at ~0 ms and decays with order latency** (all tight: +1.19 → +0.63 → +0.51 bps). It is not capturable from a cloud gateway with a 150 ms path.
* **Hyperliquid is the only latency-robust lead**: HY lag ≈ 0.7–0.9 s behind Binance, gross +2.45 bps at t+5s, 84–90 % hit, identical at 0 ms and 150 ms. But taker fees are 4.5 bps/side → **net −7.35 bps**. Even maker-both-sides (1.5 bps × 2) leaves ~0, before adverse selection. It needs a fee tier ≲ 1 bp/side — an *account* property this project cannot establish.
* **Cross-venue arbitrage: nothing real.** 26,328 basis-adjusted gross gap episodes (p50 0.55 bps, p90 1.09, max 9.45; median lifetime 0.52 s) — the best real gaps (Hyperliquid AVAX/LTC vs Binance, 7–9 bps) cost 12 bps in fees. **All 27 executed arb trades were Binance FDUSD↔USDC stable-basis trades under the assumed 0 bps fee, earning $0.25 in total** ($0.009 per trade), and that profit assumes the stable-coin basis reverts. 6 of 33 filled with leg risk.
* **Triangles:** 18 scanned; none net-positive. `FDUSDUSDT` never quoted, so the FDUSD triangles could not run.

## 4. Battleground 2 — Polymarket (84 markets, 117 signals, 39 BTC impulses)

* **The CLOB is not just tracking BTC.** Momentum control (t+5s): signed gap +2.80 ¢; fair value drifted +1.25 ¢ (BTC kept moving); the CLOB mid moved +2.48 ¢ → **CLOB − fair = +1.23 ± 0.33 ¢ (3.7σ), ~44 % of the gap closed beyond drift**. Strongest on hourly Binance-candle markets (closure 0.75, +1.46 ± 0.36 ¢); weakest on TWAP Up/Down at t+30s (closure ≈ 0).
* **But it is not tradable as a taker.** Live-priced contracts (0.10 ≤ p ≤ 0.90, n = 105): gross **+2.33 ¢/share**, spread **2.17 ¢**, net0 **+0.48 ± 0.63 ¢** (not significant), **taker fees 2.87 ¢** for the round trip → **−2.39 ¢ net**. (Polymarket taker fee `0.07·p·(1−p)` ≈ 350 bps of notional at p = 0.5; makers pay 0.) bps-of-notional metrics are distorted by near-decided contracts (p < 0.1 or > 0.9), so cents per share is the honest unit.
* The CEO's maker-only lever is exactly the relevant one here (no maker fee), but maker fills require the CLOB to trade *through* a resting order — i.e. adverse selection against the very lag we're hunting — and this paper exchange gives no queue credit. **Maker economics on Polymarket remain untested.**
* Quarantined by the CEO for negative net markouts: the daily bracket markets `range-80000-82000` / `range-82000-84000` (net@5s ≈ −1,500 bps, 0 % hit) and several Up/Down windows.

## 5. CEO ↔ CFO in the new universe (34 interventions, `ceo_audit.jsonl`)

* 27 `QUARANTINE_MARKET` (12 of them in one review at 19:45:50: Hyperliquid LINK/LTC/AVAX/DOGE/SOL/ETH, Kraken/Gate/Coinbase books — all **gross positive but net −7…−124 bps because of fees**, i.e. the CEO is judging on net economics, as designed), 7 `RETUNE_IMPULSE` (lag-window regime changes, evidence-gated).
* Verdict was GOOD throughout because eight Polymarket trades carried the P&L; **this exposed that GOOD had no significance guard** (POOR did). Fixed after the run (`exp − s.e. > threshold`, with a test); the replay used the fixed code and shows the same market-level interventions.

## 6. What the +$23 paper PnL really is

| source | trades | PnL | note |
|---|---|---|---|
| Polymarket | 8 | **+$22.96** | **one trade = +$13.19** (BUY Up 5m at 0.39 → 0.55 in 0.7 s); two stops −$2; n = 8, median +$1.21 |
| arb (FDUSD↔USDC, assumed 0 fee) | 27 | +$0.25 | $0.009/trade; assumes basis reversion |
| other directional | 5 | +$0.03 | |

This is **a sample of 8 trades dominated by one outlier**, not evidence of an edge.

## 7. Limits and next steps
* One 20-minute session in a quiet regime (BTC vol ≈ 0.25 bps/√s, 19 impulses with |Z| ≥ 3 for the directional cohort, 39 for Polymarket). Cluster-robust s.e. are shown but power is low.
* All timing is measured at a cloud gateway; paper fills assume 150 ms order latency and no queue priority; fees are public retail schedules; Chainlink TWAP is approximated with Binance prices; shorts/perp mechanics are simulated.
* Prediction-market trading is geo-restricted for some users; this project only reads public data and simulates.
* Worth testing next (not claimed): Hyperliquid **maker/rebate** economics with a queue model; Polymarket **maker-side** quoting around BTC impulses; several multi-hour sessions across volatility regimes; a gateway nearer the venues to separate the 0 ms vs 150 ms effect.

## Reproduce
```bash
python -m quant_agency.run_live --phase4 --duration 1200 --fee-bps 7.5 --record tapes/p4.npz   # live
python -m quant_agency.run_live --replay tapes/p4.npz --phase4 --fee-bps 7.5                 # deterministic replay (adds controls)
```
