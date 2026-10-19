# Phase 6 — Pre-positioned quote maker (A) vs high-conviction taker sniper (B) (2026-10-19)

**Bottom line: neither architecture shows a tradable edge in this data.**

* **A (rest before the impulse, cancel on the oracle) loses on Polymarket in every fill model that does not hand it free fills, and is uneconomic on Hyperliquid.** The oracle shield consistently *reduces* the loss (≈ 0.4–0.9 ¢/trip on real tapes) but never makes it positive — not with a 0 ms cancel, not in a quiet or a volatile synthetic world, not for any informed-taker delay I tested.
* **B (absolute-magnitude floor, taker in, maker out) does what the floor is for: it abstains.** On Hyperliquid it never fires (0 of 208 real signals clear 1.5× the cost; the median predicted move is 2.3 bps against a ≈ 10 bps floor), and the signals it refuses lose money. On Polymarket 25 % of signals clear the floor and the floor-passed subset is positive (+1.0 ¢/fill strict, +1.7 ¢ trades), but with n = 36 / 22 and a t-statistic ≈ 1.3 — a lead, **not** evidence. The CFO-sized B account fired only 4 live fills (−$0.64).
* Everything is paper. Fees (HL maker 1.5 bps / taker 4.5 bps) are *assumptions*; the synthetic world is *my construction* and shows mechanisms, not market facts.

## 0. Audit of the premises

| Premise in the brief | Finding |
|---|---|
| "0¢ Polymarket / 1 bp Hyperliquid maker" | PM: yes (taker-only schedule). HL public base tier is **1.5 bps** maker; a two-leg quote round trip costs 2×fee = 3 bps vs a BTC book 1 tick (≈ 1.25 bp) wide. **A posted zero HL quotes live (42,874 CFO gate decisions, all negative) and zero on both replays.** At 1.0 bp the gate still closes (spread − 2 bp − buffer − hurdle < 0). A 4-tick-wide synthetic HL book at fee 0 is ≈ −1 bp/trip (shield: −0.8 bp quiet, −1.1 bp volatile), and at 1 bp it is gated. |
| "Resting before the impulse puts us ahead of the wave" | We are ahead in the queue, but fills arrive mainly when the market moves *through* us. Live, 54 % of the un-shielded entry fills happened within 10 s after a BTC impulse, with a −352 bps mean 5 s markout. |
| "Cancel the vulnerable side in 150 ms" | Implemented honestly (cancel lands 150 ms later; fills in the window are real and flagged). The binding problem is **not** the cancel race (§2.3). |
| "Never fire a taker below 1.5×(spread + taker fee + maker-exit fee)" | Implemented exactly (all in bps of entry price; predicted move = CFO-credited |gap|). It is a *regime* filter: HL never passes; PM passes 25 %. |
| Phase 5's "Quiet-regime Z-score trap" | Confirmed from the other side: a 3σ impulse in a calm BTC tape (live vol 0.20–0.41 bps/√s, calm 89 % of the time) is worth ~2 bps on HL and ~1–3 ¢ on PM — below cost. |

## 1. What was built (174 tests)

* `queue_model.py` — shared resting-order model: arrival judged on the as-of quote (post-only cross rejected), queue-ahead, `strict` / `depletion` / `trades` fills, cancel latency (a cancel sent while the order is still in flight lands after it arrives, never before).
* `pre_positioned_mm.py` (**A**) — `FastImpulse` (0.25 / 1 / 3 s horizons, own EW variance) → calm gate (|Z| < 1) and impulse (|Z| ≥ 2, ≥ 0.3 bps). Per market × variant: both quotes at the touch, **one clip of inventory** (the filled side is pulled, the opposite quote is the exit), re-peg after 1 s, taker stop (HL 6 bps, PM **3 ticks** — a % stop is sub-tick at low prices), 30 s time stop, no quotes inside 180 s of expiry, flat by 90 s (CFO guard 60 s). On a bullish impulse the ask is cancelled (bid for bearish; sign flipped for `below` contracts), quotes stay down for a hold (HL 3 s / PM 6 s, CEO-tunable), long inventory into a bearish impulse is flattened by taker, favourable inventory exits at the *converged* price (re-posted after the cancel lands, never alongside it). 7 quoters per market: shield/no-shield × strict/depletion/trades + one CFO-governed `ACCOUNT`.
* `high_conviction_sniper.py` (**B**) — floor in the CFO (`b_floor`, `evaluate_sniper_b`; binary worst-case risk sizing), IOC taker entry, maker take-profit at the converged touch, **scratch** when the impulse stalls (cancel TP with latency charged, re-post at the touch only after the cancel lands — a TP that fills in that window is kept, no over-sell), taker stop only on a genuine reversal (BTC back through the signal level by ≥ ½ the impulse *and* position under water) or the CFO stop. Shadow rows for **every** signal tagged `floor_ok` with a fixed 1.5× reference, plus a `taker/taker` baseline.
* CFO: `quote_econ`/`evaluate_quote` (round-trip net = spread − 2·maker fee − adverse buffer − hurdle; worst-case binary sizing), learned buffer. CEO: `MM_EXTEND_SHIELD`, `MM_RAISE_ADVERSE_BUFFER`, `MM_DISABLE_VENUE`, `B_RAISE_FLOOR`, `B_DISABLE_VENUE`.
* `sim_lag_world.py` — controlled synthetic world in the live-tape format (regime, repricing lag, **informed-taker delay `D_inf`**, uninformed flow, trade prints). `p6_pool.py`, `p6_stress.py` — pooled replays and the stress matrix.
* Bugs found and fixed while building (each has a test): shadow variants were being switched off / re-tuned by the CEO acting on the *account* (made them an untouched instrument); B's shadow tags moved with the CEO's floor (now a fixed 1.5× reference); a converged-price exit was cancelled again by the shield; PM % stop was sub-tick; a cancel in flight was treated as instantaneous.

## 2. Step 1 — pooled replay (p4, p5 and the new live tape) and synthetic stress

Files: `docs/live_runs/phase6_pooled_3tapes.md` (4,197 s, 142 impulses), `phase6_stepA_pooled.md` (p4+p5), `phase6_stepA_stress.md/.json`. Cluster s.e. by BTC impulse. p4 has no trade prints, so `trades` covers p5+live only.

### 2.1 Architecture A on Polymarket (net after fees, per round trip)

| variant | fill model | round trips | net / trip | hit | net $ |
|---|---|---|---|---|---|
| shield | strict (lower bound) | 521 | −2.97¢ (−647 ± 42 bps) | 25 % | −824.8 |
| no shield | strict | 743 | −3.47¢ (−746 ± 36 bps) | 27 % | −1,350.2 |
| shield | trades (observed prints) | 369 | −2.83¢ (−597 ± 47 bps) | 26 % | −528.8 |
| no shield | trades | 500 | −3.37¢ (−697 ± 41 bps) | 27 % | −845.3 |
| shield | depletion (upper bound) | 2,163 | −0.28¢ (−45 ± 23 bps) | 54 % | −355.4 |
| no shield | depletion | 2,644 | −0.37¢ (+65 ± 116 bps) | 57 % | −409.8 |

Why it loses (live tape, `noshield/trades`): passive exits earn **+0.85 ¢** (72 trips), adverse stops cost **−6.3 ¢** (116) and time stops −2.7 ¢ (53). A 6 : 1 payoff asymmetry needs ≳ 86 % of trips to exit passively; observed 26–57 %. HL: no quote ever posted.

### 2.2 Architecture B (floor 1.5×)

| venue | variant | attempts | filled | net / fill | hit | net $ |
|---|---|---|---|---|---|---|
| HL | all 208 signals (no floor) | 208 | 172 | −6.0 ± 0.3 bps | 0 % | −20.5 |
| HL | **floor passed: 0 of 208** (abstains) | – | – | – | – | 0 |
| HL | taker/taker baseline | 208 | 172 | −8.1 ± 0.2 bps | 0 % | −27.6 |
| PM | all 280 signals (no floor), strict | 280 | 172 | −2.54¢ (−711 ± 91 bps) | 27 % | −600.2 |
| PM | **floor passed** (70 = 25 %), strict | 70 | 36 | **+1.04¢ (+240 ± 175 bps)** | 64 % | +50.3 |
| PM | floor passed, trades | 42 | 22 | +1.73¢ (+493 ± 192 bps) | 77 % | +50.2 |
| PM | floor failed (abstained), strict | 210 | 136 | −3.49¢ (−962 ± 80 bps) | 17 % | −650.6 |
| PM | taker/taker baseline, floor-passed | 70 | 36 | +0.55¢ (+121 ± 186 bps) | 61 % | +28.7 |

The floor separates winners from losers in the right direction, and the maker exit adds ≈ 0.5 ¢ over a taker exit on the passed subset. Floor sweep (post-hoc on the same rows — **not out of sample**, and n shrinks): PM none −2.54¢ → 1× +0.34¢ (n = 53) → 1.5× +1.04¢ → 2× +1.39¢ → 3× +2.76¢ (n = 14). The 1.5× itself was fixed in advance by the brief; the live session (fresh data) gave floor-passed +1.61¢ (n = 12, 75 % hit, ± 382 bps).

### 2.3 Synthetic stress: regime × informed-taker delay (3 seeds × 600 s per cell)

PM-like digitals, shield vs identical policy without it (`trades` model):

| regime | D_inf 0.05 s | 0.15 s | 0.5 s | 1.0 s |
|---|---|---|---|---|
| quiet | −0.42 vs −1.80¢ | −1.41 vs −1.93¢ | −0.42 vs −1.73¢ | −0.61 vs −1.70¢ |
| volatile | −1.40 vs −2.64¢ | −0.72 vs −3.29¢ | −1.25 vs −2.72¢ | −0.82 vs −2.79¢ |

* **A is negative in all 8 cells**, shield or not. The shield is worth +0.5…+2.6 ¢/trip, but *not* monotonically in `D_inf`, and shield trips filled inside the cancel window are few (30 of 419 at 0.05 s, 1 of 497 at 1.0 s). So the benefit is mostly **standing aside after impulses** (fewer exposures: 83 vs 367 trips quiet), not winning the cancel-vs-taker race.
* Cancel-latency sweep on the live-session tape (PM, shield vs none, trades; only the cancel latency changes): 0 ms −3.22 vs −3.83¢; 50 ms −2.62 vs −3.50¢; 150 ms −2.65 vs −3.38¢; 300 ms −2.76 vs −3.41¢. Even an instantaneous cancel leaves A at −3.2 ¢/trip: the lagging venue's quote is adverse because it is *stale in both directions*, not only because the cancel is slow.
* **B**: quiet world — 0 % of 435–474 signals pass the floor in every cell (HL and PM); the no-floor trades lose −1.4…−2.3 ¢ (PM) / −3.6…−4.2 bp (HL). Volatile HL: 98–100 % pass, **+8.5…+10.0 bp/fill, 96–98 % hit** — but `taker/taker` earns **+13.8…+15.3 bp**: when the move is ≫ cost, a fixed maker take-profit caps the overshoot and loses to paying the taker fee. Volatile PM: only 3–5 % pass (the gap *measured at detection* is partial), n = 2–8 per cell — inconclusive.

HL-wide books (4 ticks, D_inf 0.5 s): A at fee 0 is −0.8 bp (quiet) / −1.1 bp (volatile) per trip with the shield (−0.8 / −4.4 without); at fee 1.0 bp it posts nothing.

## 3. Step 2 — fresh live session (1,500 s, `docs/live_runs/phase6_live/`)

BTC vol 0.20–0.41 bps/√s (quiet), 46 impulses, 9 HL perps + 85 PM markets, 9,784 trade prints recorded (`tapes/p6_tape_1.npz`, not committed).

| engine (venue) | trips / fills | net per trade | hit | net $ |
|---|---|---|---|---|
| **A ACCOUNT** (PM, CFO-sized, trades fills) | 16 | −3.13¢ (−848 bps) | 19 % | −25.35 |
| A shield / no-shield (PM, shadow, trades) | 163 / 246 | −2.65¢ / −3.38¢ | 26 % / 24 % | −252.8 / −438.9 |
| A (HL) | 0 (gated out) | – | – | 0 |
| **B ACCOUNT** (PM) | 4 | −0.96¢ | 50 % | −0.64 |
| B floor-passed shadow (PM, trades) | 12 | +1.61¢ (+516 ± 382 bps) | 75 % | +28.95 |
| B no-floor shadow (PM) | 49 | −1.19¢ | 45 % | −82.7 |
| B (HL) | 0 of 81 pass the floor | – | – | 0 |

CEO/CFO: `TIGHTEN_CFO` → `MM_EXTEND_SHIELD` (4/8 trips filled inside a *shield* cancel window) → `DEFENSIVE_MAKER_ONLY` → `MM_DISABLE_VENUE` (A on PM) → `HALT_TRADING` (22:01: expectancy −392 bps over 7 trades) → nine HL perps quarantined on negative markouts. Final equity **$9,974.01 (−0.26 %)**. The CFO's binary worst-case sizing rejected 701 quote decisions as below the minimum size (the clip shrinks with the 50 % gap loss), and 371 were approved.

**Governance finding:** both engines share one CFO book, so A's losses tripped the portfolio expectancy gate and halted B (122 `b_halted` decisions after 22:01) — B's account was starved by A. The side-by-side shadows are unaffected (they ignore CEO actions by construction), but the *account* comparison is confounded; separate risk books per engine are needed for a fair account-level contest.

## 4. Caveats

* Small samples: B's floor-passed PM evidence is 36 / 22 / 12 fills (t ≈ 1.3); the post-hoc floor sweep selects on the data.
* The queue model has no hidden size, no cancellations ahead of us and no other maker's adverse-selection logic; `trades` is a lower bound on fills, `depletion` an upper bound.
* The synthetic world is open-loop, assumes 80 % informed-taker presence and fixed repricing lags (HL 0.8 s, PM 1.5 s). It demonstrates which mechanism dominates, not what real participants do.
* One live session, one quiet regime. No volatile *real* session was observed, so B's best case (large moves) is only tested synthetically.

## 5. Next directions (follow from the data, not from hope)

1. **A as written should be shelved.** Its loss mechanism is quoting a stale price, which no cancel speed fixes. A fair-value-aware variant (post a side only if the oracle-implied fair value sits on the right side of that quote) is the remaining untested idea; it is a different strategy from "quote at the touch".
2. **B is worth more data, not more tuning:** it needs ≳ 150 floor-passed PM fills for the current effect size to reach t > 2 — i.e. several volatile sessions. Until then it is a regime filter with an unproven positive tail. On HL it is correct to leave it off at 4.5 bps taker.
3. In large-move regimes test a **wider / trailing take-profit** (synthetic HL shows taker/taker beating the fixed maker TP by ≈ 5 bp).
4. Give each engine its **own risk book** so one engine's drawdown cannot halt the other.

## 6. Reproduce

```bash
python -m quant_agency.run_live --phase6 --duration 1500 --record tapes/p6.npz
python -m quant_agency.p6_pool tapes/p4_tape_1.npz tapes/p5_tape_1.npz tapes/p6_tape_1.npz --sweeps
python -m quant_agency.p6_stress --seeds 3 --duration 600
python -m quant_agency.sim_lag_world --regime volatile --d-inf 0.5 --out tapes/w_vol.npz
```
