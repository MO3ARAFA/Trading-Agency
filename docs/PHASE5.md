# Phase 5 — queue-aware passive maker sniper on Hyperliquid + Polymarket (2026-10-19)

**Bottom line: the thesis is not supported.** Resting post-only orders at the touch (or one tick inside) does not convert the Binance→venue lag into profit on
either battleground. Orders either don't fill (Hyperliquid: 3–15 %) or fill disproportionately when the impulse fails (Polymarket, `strict`/`trades` models: conditional 5 s markout
−400…−1,600 bps against an unconditional +36…+250 bps; under the optimistic `depletion` bound it is +69…+248 bps, which is why that bound is only an upper limit). The oracle cancel shield showed no measurable benefit. Everything below is measured; nothing is tuned to the data.

## 0. Audit of the premises
| Premise | Finding |
|---|---|
| "Statistically proven" Hyperliquid lead and Polymarket convergence | They were *leads* from one 20-minute session (HL: 39 signals/≈20 impulses). Pooling two independent sessions now gives **127 HL and 197 Polymarket signals**; the unconditional lead is still there (HL gross ≈ +1.5…2.3 bps at t+5s) but it is a *directional taker* gross before costs, and a quiet-regime one (BTC vol 0.20–0.25 bps/√s). |
| "Maker fee 0 on Polymarket, ~1 bp on Hyperliquid" | Polymarket: yes (taker-only schedule). Hyperliquid: public base tier is 1.5 bps maker / 4.5 taker; tested **1.5, 1.0 and 0.0** bps maker — conclusions do not change (§3). Exits that fall back to taker still pay 4.5 bps. |
| "Penny-jump when spread ≥ 2¢" | Implemented (Polymarket only; Hyperliquid is 1 tick wide). It is the *least bad* variant, not a positive one. |
| "Count fills only from trades through our price" | Implemented, with three models. **The Phase 4 tape has no trade prints**, so Step A can only *bound* fills (strict ≤ truth ≤ depletion). Trade prints were recorded live for Step B (8,356 prints) so the `trades` model is observed there. |

## 1. What was built (`maker_sniper.py`, CFO/CEO changes; 140 tests)
* **Queue-aware order state machine** per signal × variant: in-flight → arrival judged on the **as-of quote at arrival** (post-only that would cross is rejected; join queues behind the visible size; penny starts at the front) → resting → cancel (effective only after the 150 ms cancel latency; fills inside that window are real and flagged) → passive exit worked for `T_work`, taker fallback, adverse stop, time stop.
* **Fill models:** `strict` (opposite touch must cross — certain, lower bound), `depletion` (displayed-size depletion counts as trades — optimistic upper bound), `trades` (real prints consume the queue, sweep through beyond our price).
* **Oracle cancel shield** on every BTC tick: cancel if < 40 % of the impulse is intact, on a 0.3 bps reversal, or when the venue already did 80 % of the gap.
* **6 variants on identical signals:** `taker/taker` (Phase 4 baseline), `taker/passive`, `join/taker-exit+shield`, `join/passive` with and without shield, `penny/passive+shield` — plus one CFO-sized, CFO-accounted attempt.
* **CFO** (`evaluate_snipe`): maker/taker fee schedules, expected exit mix, **adverse-selection buffer = max(learned shortfall, 0.75 × half-spread)** (a prior I added when a test showed the model otherwise happily "earned" a 5¢ spread), learned P(fill)/P(passive exit). **CEO**: fill rate, cancel-latency fills, net maker markout → shield tighten/relax, buffer raise, venue disable.
* Trade-print feeds (Hyperliquid `trades`, Polymarket `last_trade_price`) recorded on the tape; deterministic replay decodes them.

## 2. Step A — deterministic replay of the Phase 4 tape (no prints ⇒ bounds) and Step B — fresh 25-minute live session (with prints)
Pooled over both sessions, shadow variants on **identical signals**, `net` after fees, unfilled attempts count as 0, cluster-robust s.e. over BTC impulses
(`docs/live_runs/phase5_pooled_hlmaker1.5.md`):

**Hyperliquid (127 signals, $200 paper size, maker 1.5 / taker 4.5 bps)**

| variant | fill model | fill rate | net bps / fill | net bps / attempt | 5s markout after fill |
|---|---|---|---|---|---|
| taker/taker (Phase 4 baseline) | – | 82 % | −8.2 ± 0.3 | −6.74 ± 0.50 | +1.5 |
| join/passive+shield | strict (lower bound) | 6 % | −6.6 ± 0.7 | −0.36 ± 0.24 | −0.6 |
| join/passive+shield | depletion (upper bound) | 9 % | −5.3 ± 1.2 | −0.50 ± 0.30 | −0.0 |
| penny/passive+shield | depletion | 15 % | −4.3 ± 0.8 | −0.64 ± 0.30 | +1.2 |

**Polymarket (197 signals, $50 paper size, maker 0 / taker `0.07·p·(1−p)`)**

| variant | fill model | fill rate | net ¢/share / fill | net bps / attempt | 5s markout after fill |
|---|---|---|---|---|---|
| taker/taker | – | 62 % | −3.22 | −583 ± 84 | +36 |
| join/passive+shield | strict | 11 % | −4.02 | −130 ± 41 | −550 |
| join/passive+shield | depletion | 22 % | −1.43 | −90 ± 46 | +69 |
| **penny/passive+shield** | depletion (optimistic) | 39 % | **−0.66** (−176 ± 153 bps/fill) | −69 ± 57 | +248 |
| penny/passive+shield | strict | 10 % | −3.81 | −125 ± 41 | −547 |

* Maker variants look better *per attempt* only because they mostly **don't trade** (a taker loses ≈ 7 bps/attempt on HL and ≈ 580 bps on PM; a maker that rarely fills loses less). That is abstention, not edge: per **fill** every maker variant is negative at both fill bounds, except Polymarket penny at the optimistic bound, which is indistinguishable from zero (−176 ± 153 bps).
* **Step B alone (live, with prints, 35 HL / 81 PM signals):** the `trades` model tracks `strict` (prints at our exact price rarely arrive before the touch crosses): HL **1 fill of 35**; PM **8–10 fills of 81** with conditional 5 s markout **−1,235 bps** vs +253 bps unconditional (adverse-selection gap −1,487 bps).

## 3. Why — measured mechanisms
1. **The lag wave runs away from a resting bid.** HL orders ended `converged` (venue already did ≥ 80 % of the gap) in 74/92 (Step A) and 16/35 (Step B) cases, TTL in most of the rest. When the signal is right, the order doesn't fill; fills come from the cases where price moves back through us.
2. **Adverse selection is huge on Polymarket under the certain-fill models**: conditional markout after a passive fill is −400…−1,600 bps (`strict`, and live `trades`) vs the unconditional +36…+250 bps. Under the optimistic `depletion` bound the conditional markout is *positive* (+69…+248 bps) — that bound credits fills no one can confirm, so the truth lies between; the live `trades` model sits on the adverse side, and the pooled net is negative at both bounds except penny/depletion, which is statistically zero.
3. **Passive exits rarely fill**, so fills pay taker on the way out: HL fees per fill ≈ 5–6 bps (maker 1.5 + taker 4.5) against a gross of −1.7…+0.1 bps. Lowering the maker fee helps only the entry leg: pooled `join/passive+shield` net/fill at maker **1.5 → 1.0 → 0.0 bps: −6.6 → −6.1 → −5.1 (strict), −5.3 → −4.7 → −3.4 (depletion)** — still negative at zero.
4. **The shield did not earn its keep**: fill rate 3 % vs 3 % (HL), 9 % vs 11 % (PM); net per attempt identical within noise; on PM the shielded variant's net per fill is *worse* (it pulls the benign orders, not the toxic ones). Most orders are cancelled by convergence or TTL before the shield matters. Cancel-window fills: **0** under `strict`/`trades`; 23 under `depletion` on PM (a model artifact of its "level vanished ⇒ filled" rule), mean −519 bps.
5. Gap vs price grid: median HL gap 2.2–3.1 bps ≈ 5–9 ticks, PM gap ≈ 1.4–1.6 ticks. (My first guess — "gap < 1 tick" — was wrong and was checked before being written down.)

## 4. The account loss in Step B (and the risk-sizing flaw it exposed)
The CFO-accounted attempts lost **$396.59** in 3 Polymarket trades (−4 % equity), tripping the 2 % portfolio breaker and the CEO halt. One trade **sold** the Up token at 0.33 (981 shares) and the price jumped to 0.69 within 0.4 s: −$367.8. Binary risk was sized by *notional and a bps stop*, but a short at price p can lose (1−p)/share (2× its notional at 0.33) and a resolution can gap through any stop inside one order latency. **Fixed afterwards:** risk is sized on the worst-case loss per share (`p` long, `1−p` short, 50 % gap), plus no entries in the last 60 s before expiry; regression tests added. The same tape through the fixed code loses **−$17.97** on the same trades (`docs/live_runs/phase5_replayB_final/`). Phase 4's Polymarket trades carried the same latent flaw at smaller size.
The CEO/CFO machinery did what it should *after* the fact (breaker → halt → quarantines of the toxic Up/Down windows), but it could not have prevented a mis-sized position — that was a CFO bug.

## 5. Governance in this phase
CEO sniper interventions are implemented and unit-tested (buffer raise → venue disable, shield tighten/relax, evidence-gated). In the live session the account sample was too small for them to fire (3 fills); a bug where a capped buffer produced a no-op "raise" was found while preparing this report and fixed (escalates to disable).

## 6. Limits and what I'd do next
* Quiet regime in both sessions (BTC vol ≈ 0.20–0.25 bps/√s); 127/197 pooled signals from 2 sessions; cluster-robust s.e. shown, power low. Parameters (hold 40 %, TTL 6/12 s, work 8/10 s, latencies 150 ms) were fixed a priori and **not tuned** on the results.
* No real queue: cancellations ahead of us, hidden size and other makers' adverse-selection management are unobservable; the strict/depletion bounds bracket them. Polymarket aggressor side is inferred from price vs mid.
* Shadow variants use a small fixed size and do not move the book.
* Directions that could change the conclusion (none claimed): a *market-making* strategy that quotes both sides and is paid for spread rather than lag; much higher-conviction taker entries only (e.g. impulses ≫ costs); volatile regimes where the lag gap is large vs fees; a gateway close enough to rest and cancel inside the lag wave.

## Reproduce
```bash
python -m quant_agency.run_live --phase5 --duration 1500 --record tapes/p5.npz          # live (oracle + Hyperliquid + Polymarket + trade prints)
python -m quant_agency.run_live --replay tapes/p4_tape_1.npz --phase5                    # Step A (bounded fills)
python -m quant_agency.p5_pool tapes/p4_tape_1.npz tapes/p5_tape_1.npz --hl-maker-bps 1.0  # pooled variants, fee sensitivity
```
