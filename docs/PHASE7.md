# Phase 7 — Pure Architecture B on isolated risk sleeves, and the exit-overshoot question (2026-10-19)

**Bottom line.** The two structural fixes are done and tested. The exit question is *promising in-sample and unresolved out of sample*. B is **not** yet shown to have positive expectancy.

* **Isolation works (unit-tested; live only partly exercised).** Each venue has its own `CFOAgent` (equity, exposure, blacklist, breakers, config copy) and its own four-state governor fed only by that sleeve's round trips. A drawdown/halt in `polymarket_b` cannot touch `hyperliquid_b`, the legacy book or the global CEO. Architecture A is not instantiated in Phase 7. Live, the Hyperliquid sleeve had no activity (B abstains there), so the *live* run did not exercise cross-sleeve non-interference — the tests do.
* **Uncapping the exit looks better in-sample, but the evidence is thin.** Over four real sessions (Polymarket, floor-passed, 48 fills, strict fills) every wider/uncapped exit beats the Phase 6 reference (`fixed0.7`: +195 ± 177 bps, t = 1.10): `trail` +680 ± 306 (t = 2.22), `adaptive` +634 (1.93), `wide2.0` +680 ± 372 (1.83), `fixed1.0` +407 (1.92). **No exit passes the correction for having tried six** (≈ t > 2.6), and on the one fresh session — 12 floor-passed fills — the in-sample favourite did not replicate (`wide2.0` −125 ± 931 bps; every exit was within ±300 bps of zero with s.e. 480–930). That session cannot distinguish "works" from "doesn't".
* **The "breakthrough" in the brief should be read with those numbers.** Phase 6's `fixed0.7` was +1.04¢ (t ≈ 1.4) on 36 fills; with the new session it is +0.58¢ (t = 1.10) on 48. Floor-passed, positive point estimates are consistent across four sessions, but the Phase 6 reference exit is still not significant, and the "+9 vs +14 bp overshoot" claim was a *synthetic-world* result, not an observation of real Hyperliquid (where B never fires: 0 of 317 real signals clear the floor).
* t > 2.0 on a pre-registered exit was **not** reached. Projected cost of getting there is in §5.

## 0. Audit of the premises

| Premise in the brief | Finding |
|---|---|
| "B achieved positive post-cost expectancy … across pooled replay and fresh live OOS" | Point estimates positive; **not significant** (Phase 6: t ≈ 1.3–1.4; now t = 1.10 for the same exit). "OOS +1.61¢" was 12 fills with s.e. ±382 bps. |
| "Correctly standing aside on all 208 HL signals that lost 6–8 bps each" | True, and now 317/317. Standing aside *avoids* a loss; it earns nothing. HL needs a move ≫ 10 bps (a volatile regime) to ever pass the floor; no real session has had one (BTC vol 0.20–0.25 bps/√s in all four). |
| "Fixed maker TP truncates volatile winners (+9 vs +14 bps on volatile HL)" | Reproduced **only in the synthetic world** (§3). It is a mechanism check, not evidence about the venue. |
| "Isolate risk books" | Done (§1). The Phase 6 contamination was real (122 B decisions refused after A's drawdown). |

## 1. Isolated risk sleeves (`sleeves.py`, 187 tests)

* `Sleeve` = own `CFOAgent` on a **deep-copied** `CFOConfig` + own governor + own results list. `SleeveSet` builds one sleeve per venue (`hyperliquid_b`, `polymarket_b`), each its own $10,000 paper bankroll. The only shared object is the read-only `MarketBook`.
* Governor (per sleeve, every 30 s, ≥ 6 fresh round trips, cluster-robust by BTC impulse): net + s.e. below −tolerance → `TIGHTENED` (floor +0.5, size ×0.5) → `DEFENSIVE` (floor ≥ 3×, size ×0.25) → `HALTED` (10 min) → probation at ×0.25 size from the current equity; significantly good → step back one notch. A CFO breaker (drawdown / daily loss) tripping *inside* the sleeve also puts only that sleeve into `HALTED`.
* Routing: `Agency._handle_signal` evaluates a B signal with the sleeve of the signal's venue (`hc.cfo_for(idx)`); results, exposure, breakers and P&L book into that sleeve only; the global CEO's `_b_review` is detached (`attach_hc(..., govern=False)`). Architecture A (`pre_positioned_mm.py`) is shelved: `--phase7` never builds it (asserted in the replay runner and in a test); `--phase6` still works for reproduction.
* Tests (`tests/test_sleeves_and_exits.py`): separate config/equity/blacklist objects; a halted Polymarket sleeve leaves Hyperliquid approving and trading; losses move only their own governor; full TIGHTEN → DEFENSIVE → HALT → probation ladder; sleeve breaker halts only its sleeve; account P&L lands in the venue sleeve and not in the global CFO; A is absent.
* Live (3,000 s): the Polymarket sleeve went `NORMAL → TIGHTENED` after 6 round trips at −1,025 ± 596 bps (floor 1.5× → 2.0×, size ×0.5) and finished +$3.71 (10 round trips); the Hyperliquid sleeve stayed `NORMAL` at $10,000 with zero trades, and nothing the Polymarket governor did reached it.

## 2. Exit policies (`high_conviction_sniper.py`)

All six run as shadows on **identical entries** (same signal, same IOC taker fill — the entry is not what differs), in all three fill models; the ACCOUNT uses one.

| exit | rule |
|---|---|
| `fixed0.7` | Phase 6 reference: maker TP at 0.7× the credited gap, 8–10 s window |
| `fixed1.0` | (a) maker TP at 1.0× the gap, same window |
| `wide1.5`, `wide2.0` | (b) maker TP at 1.5× / 2.0×, **horizon hold** 20 s (HL) / 25 s (PM) |
| `adaptive` | (b) start at 1.0×; each time Binance extends the impulse by another 20 % of its size beyond the signal level, cancel (150 ms charged; the old TP can still fill) and re-post one step wider (1.5×, then 2.0×) — re-post only after the cancel has landed, so the position cannot be over-sold |
| `trail` | (c) no resting TP. Stay while Binance velocity is supportive; exit passively at the touch when the venue has done ≥ 100 % of the credited gap **and** Binance's 1 s velocity in our direction has fallen ≤ 0.2 bps, or when the venue gives back 40 % of its peak progress (peak ≥ 50 %), or on a stall. Reversal stop, CFO adverse stop and the 30 s time stop apply to all |

## 3. Results

Files: `docs/live_runs/phase7_pooled_3tapes.md`, `phase7_pooled_4tapes.md`, `phase7_synthetic_exits.md`, `phase7_live/`. t = mean / cluster-robust s.e. (clusters = BTC impulses). `net / fill` is given in ¢/share and bps of notional; shadows use a fixed notional so **bps of notional is the sizing-consistent measure** — on small samples ¢/share and bps can differ in sign (the live n = 12 rows do), because cheap contracts dominate bps and dear ones dominate ¢. Both t-statistics are reported.

### 3.1 Real data, Polymarket, floor-passed (1.5× floor), strict fills, pooled over p4 + p5 + p6 + the new 3,000 s live session

| exit | fills | net / fill | s.e. (bps) | t (bps) | t (¢/share) | hit | net $ (fixed $50 clips) |
|---|---|---|---|---|---|---|---|
| fixed0.7 (Phase 6) | 48 | +0.58¢ (+195 bps) | 177 | +1.10 | +0.67 | 62 % | +54.1 |
| fixed1.0 | 48 | +1.50¢ (+407) | 212 | +1.92 | +1.52 | 60 % | +100.2 |
| wide1.5 | 48 | +1.87¢ (+487) | 302 | +1.62 | +1.35 | 54 % | +112.8 |
| wide2.0 | 48 | +2.53¢ (+680) | 372 | +1.83 | +1.55 | 52 % | +156.2 |
| adaptive | 48 | +2.24¢ (+634) | 329 | +1.93 | +1.57 | 58 % | +148.5 |
| trail | 48 | +2.90¢ (+680) | 306 | +2.22 | +2.13 | 60 % | +151.7 |
| taker/taker | 48 | +0.14¢ (+152) | 169 | +0.90 | +0.17 | 65 % | +39.2 |

Under `trades` fills (p5 + p6 + live only; 34 fills) the ordering is the same except the wide TPs weaken: fixed0.7 +340 (t 1.60), fixed1.0 +570 (2.22), wide2.0 +567 (1.20), trail +770 (1.96).
Without the floor, **every exit loses** (all signals, strict: −2.0 to −2.7 ¢/fill, t between −5 and −9), and taker/taker loses −3.0 ¢. The floor is doing most of the work; the exit decides how much of the remaining edge is kept.

Cost of the wider exits, visible in the same table: the share of fills that exit passively falls (58 % → 38–48 %) and adverse stops rise (10 of 48 for `fixed0.7`, 17–20 of 48 for the wide/adaptive exits) — holding longer buys the right tail by taking more of the left.

### 3.2 The one genuinely out-of-sample slice: the new live session alone (BTC vol 0.20–0.22 bps/√s, quiet)

118 PM signals, 41 (35 %) clear the floor, **12 filled** (strict). Net bps/fill (s.e.): fixed0.7 +59 (479), fixed1.0 +195 (528), wide1.5 −296 (790), wide2.0 **−125 (931)**, adaptive −23 (792), trail +202 (927), taker/taker +242 (373). Nothing here is distinguishable from zero or from each other. ACCOUNT (`wide2.0`, pre-registered): 10 round trips, +$3.71 (exits: passive fills +$12.7, +$11.4, +$5.4, +$3.2; five adverse stops −$2.0 … −$11.9).

### 3.3 Pre-registered exit selection

Rule written into the runner before the live session: highest pooled PM floor-passed **strict** net bps/fill over the first three tapes with n ≥ 30. Result (3 tapes, 36 fills): `wide2.0` (+948 bps, s.e. 386) over `trail` (+851), `adaptive` (+853), `wide1.5` (+749), `fixed1.0` (+477), `fixed0.7` (+240) — differences among the top four are far inside one s.e., so this pick is close to arbitrary. It was used for the live ACCOUNT as pre-registered. With the fourth tape the ranking by mean is a tie between `wide2.0` and `trail` (+680 each); `trail` has the lower s.e. and the best t. **I would not conclude that `wide2.0` is better than `fixed1.0` or `trail` from this data.**

### 3.4 Hyperliquid

317 real signals, **0 clear the floor** (median predicted move ≈ 2.3 bps vs a floor ≈ 10 bps). B abstains; the refused signals lose −6.0 to −6.6 bps/fill (strict, 268 fills) under every exit (taker/taker −8.2). Uncapping does not rescue them (best: `adaptive` −6.0). HL can only matter in a volatile regime that we have not observed.

### 3.5 Synthetic worlds — mechanism check only (3 seeds × 600 s, my construction)

Volatile world (10–30 bp impulses), Hyperliquid-like, `trades` fills, floor-passed 170 fills: `trail` **+21.0 bps** > `adaptive` +17.8 > `fixed1.0` +17.0 > taker/taker +16.6 > `wide2.0` +16.3 > `wide1.5` +14.9 > `fixed0.7` **+11.7**. This reproduces the Phase 6 observation (a fixed 0.7× maker TP caps the overshoot; a taker exit beats it) and shows the oracle-guided trail beats both. The 1.5×/2.0× fixed TPs do worse than 1.0× because the longer hold runs into reversal stops (43–46 of 170). In the quiet synthetic world no signal clears the floor on either venue (B abstains), and uncapping does not help the refused signals. Volatile PM-like: only 4 floor-passed fills (inconclusive).

## 4. What changed in the code (tests: 187, all pass)

`sleeves.py` (new); `high_conviction_sniper.py` (exit policies, per-venue sleeve routing, Binance velocity history); `config.py` (`BConfig` exit knobs, `b_tp_mult`); `cfo_agent.py` (`b_tp_mult` in the B net-edge gate); `agency.py` (`attach_sleeves`, governor review, per-sleeve evaluation); `run_live.py` (`--phase7`, `--b-exit`, `--sleeve-capital`); `p7_pool.py`; `telemetry.build_report_p7`; `tests/test_sleeves_and_exits.py` (13 tests). `maker_sniper.py` / Phase 6 paths are unchanged in behaviour (Phase 6 reproduces with `exit_variants=("fixed0.7",)`).

## 5. How far is t > 2, honestly

* At the observed means and s.e., the **pre-registered** exit (`wide2.0`, t = 1.83 on 48 fills) would need ≈ 58 floor-passed fills for |t| > 2; `fixed0.7` would need ≈ 160. `trail` is already at t = 2.2 but that is the best of six, so the multiplicity-adjusted bar (t ≈ 2.6) needs ≈ 70.
* Fill supply: the live session produced **12 floor-passed strict fills in 3,000 s** (41 floor-passed signals → 12 fills; the rest hit `ioc_price_moved` / `ioc_no_liquidity`). At that rate: ≈ 2 more 50-minute sessions to ≈ 70 fills (if the `trail` effect is real), ≈ 9 sessions to 160 (if `fixed0.7` is the truth). These are projections from one quiet regime; fill rates and effect sizes in a volatile regime could be very different.
* Everything is in a quiet BTC regime (0.20–0.25 bps/√s in all four sessions). B's design case — a large, continuing impulse — has never occurred in the real data.

## 6. Recommended next step

Keep collecting Pure-B sessions with all six exits as shadows and **do not change the pre-registered account exit until a single exit passes a multiplicity-adjusted test on data not used to choose it**. A reasonable pre-registration for the next batch: report `trail` vs `fixed0.7` as the single planned comparison (paired on identical entries), stop at n ≥ 70 floor-passed fills or a volatile session, whichever is first.

## 7. Production commands

```bash
# Pure Architecture B, isolated sleeves, pre-registered account exit, longer session (A is never built)
python -m quant_agency.run_live --phase7 --b-exit wide2.0 --duration 3000 --record tapes/p7.npz --tag phase7_live
# pooled comparison of all exits over every recorded tape
python -m quant_agency.p7_pool tapes/p4_tape_1.npz tapes/p5_tape_1.npz tapes/p6_tape_1.npz tapes/p7_tape_1.npz --out docs/live_runs/phase7_pooled_4tapes.md
# synthetic mechanism check
python -m quant_agency.p7_pool --synthetic --seeds 3 --duration 600 --out docs/live_runs/phase7_synthetic_exits.md
python -m pytest tests -q          # 187 tests
```
Paper only: no credentials, no code path that transmits an order.
