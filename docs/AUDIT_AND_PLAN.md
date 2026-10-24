# Audit of Phases 1–12 and the Phase 13 plan

*Paper-only project. No file in this repository holds a credential or sends an order. Nothing below says the system is profitable with
real money. It says what was measured, what failed, and what the next test is.*

## 1. What was built

| layer | modules | state |
|---|---|---|
| Feeds | `feeds.py` (Binance, Hyperliquid, Polymarket CLOB websockets, Gate, Kraken), tape recording and replay | works; one session reconnected 4 times in an hour without data loss |
| Signal | `btc_oracle.py`, `inefficiency_hunter.py` (Hayashi-Yoshida lead-lag, Kalman β), `sector_oracles.py`, `midcap_crossvenue.py`, `poly_structural.py`, `hl_funding_basis.py` | works; every signal family was measured live |
| Decision | `cfo_agent.py` (net edge after spread, fees, slippage, hurdle; fractional Kelly; breakers), `ceo_agent.py` (state machine NORMAL → HALTED) | works; it refused almost every signal, which was the right call |
| Execution | `execution_engine.py`, `queue_model.py` (queue-aware maker fills: strict / trades / depletion) | paper only, by design |
| Evaluation | pre-registration with SHA-256 freezes (Phases 8–12), cluster-robust t-tests, train/test splits, placebo replays | works; it stopped every false positive before it reached money |

The engineering is not what kept the project from making money. Each strategy was built correctly, measured honestly and refused by its
own cost model. The cause was the choice of edge.

## 2. Why Phases 1–12 never made a dollar

| phase | edge tried | measured | why it loses |
|---|---|---|---|
| 1–3 | BTC leads 60 Binance alts by seconds | gaps ≲ 1 bp gross | ≈ 2 bp spread + 15 bp retail taker fees: 17× the edge |
| 4–6 | BTC leads Hyperliquid / Polymarket crypto markets | HL +2.5 bps gross vs 4.5 bps taker; PM maker fills adversely selected, taker −2.4 ¢/share | the lag is real, but faster firms take it before a retail-latency order arrives; passive quotes fill only when they are wrong |
| 7–10 | Architecture B (taker in, maker out) with exit and regime variants | in-sample +128 bps, t = 0.80; never significant; pre-registered N\* = 608 not reached | search over many exits on one small sample; the effect does not survive more data |
| 11 | sector oracles; same-asset Binance → Hyperliquid tail lag | pre-registered: **−8.46 ± 1.63 bps** (t = −5.2) | the lag is +3.9 bps and sub-second; costs are about 3× that |
| 12 | Hyperliquid funding carry, basis reversion, premium drift; Polymarket passive quoting | funding extremes ≥ 3 bps/h are 0.02 % of hours; hedged basis ≈ 0 after costs; the pre-declared premium test: t = 0.87, H0 not rejected; slow-market maker markouts −1 ¢/share | no persistent premium; makers are still picked off |

**Diagnosis in one line.** Phases 1–12 all raced faster, better-capitalised firms for predictive or latency edges. Retail fees and
latency are larger than every such edge we measured. More tuning would not have fixed that: tuning on these samples is how the in-sample
+128 bps of Phase 7 appeared.

**Weaknesses found in the process (fixed):**
- Gamma `/markets` and `/events` stop at offset 2100. The Phase 12 universe, and the first Phase 13 scan, therefore saw only the most
  active ~1,200 NegRisk events. Splitting by end date now finds **7,521**.
- The Phase 12 run A slow-market filter admitted in-play tennis matches. It is fixed, and run A is labelled contaminated.
- Per-fill standard errors overstated significance. They are now market-level (cluster) statistics.
- Paper fills never removed liquidity. A paper strategy could "buy" the same displayed shares on every sweep. Phase 13 now subtracts
  everything it has taken from later books (`deplete`).
- A killed session left no summary and a truncated tape. Summaries are now written every sweep and on SIGTERM, and replay skips a
  truncated last line.

## 3. The one edge that does not depend on a forecast

Phase 12's structural scan found exhaustive Polymarket NegRisk events whose YES asks summed to less than 1 after fees. The best were net
1–2 % per set, lasting up to 30 minutes, with up to ≈ 13 USD of depth. Published research reports the same mechanism at scale: about
40 M USD of realised arbitrage on Polymarket from April 2024 to April 2025, 29 M USD of it NegRisk rebalancing (Saguillo et al.,
"Unravelling the Probabilistic Forest", arXiv 2508.03474).

A complete set does not depend on any forecast. If the listed outcomes are exhaustive and exactly one resolves YES, one YES share of each
pays exactly 1 USDC. The risks are not price direction. They are:

1. **Resolution risk.** Are the outcomes really exhaustive?
2. **Fees.** Do they eat the margin?
3. **Legging.** Can every leg be bought before the asks move?
4. **Lock-up.** The capital is idle until resolution.
5. **Venue risk.** Disputes (UMA), smart-contract and platform risk.

## 4. The Phase 13 plan, and status

| # | step | how it is tested | status |
|---|---|---|---|
| 1 | Backtest the payoff assumption on closed NegRisk events, plain vs augmented | realised payout of one YES set and one NO set at the venue's resolution prices | **done**: 48,443 events, see `PHASE13_COMPLETE_SET_ARB.md` §2 |
| 2 | Engine `complete_set_arb.py`: whole-universe scan via the CLOB batch `/books`, exact depth walk, per-market fee schedule, YES-sets (exhaustive only) and NO-sets | 15 unit tests | done |
| 3 | Risk manager: ≤ 25 USD per event, ≤ 100 USD deployed, ≤ 8 events, ≤ 60 days of lock-up, minimum annualised return, kill file, halt after repeated data errors | unit tests | done |
| 4 | Paper executor: wait 0.5 s, re-read every leg, fill only what is still profitable at fresh prices, subtract its own takes, re-read 3 s later as a legging proxy | live paper session, 100 USD | done (1 h): 5 fills, 100 USD deployed, +1.385 USD locked, 5 of 5 still fillable 3 s later |
| 5 | Fee uncertainty: some fee-enabled markets carry `feeType: zero_fees` (rate 0) although the docs list category rates of 0.04–0.07 | every fill is also priced at a 0.05 stressed rate; `--fee-stress` trades under it | done |
| 6 | Settlement: mark every paper position to the actual resolution | `--settle docs/live_runs/phase13/session1`, re-run after the events resolve (≈ 2 Nov – 11 Dec 2026) | **open**: 0 of 5 settled |
| 7 | Live trading | requires the owner's explicit approval, a dedicated wallet, and steps 6 and 8 passing | **not started, not authorised** |
| 8 | Before any real order: a measured round trip with ≥ 5 shares on one cheap leg, to confirm the fee charged and the fill latency | manual, with approval | not started |

The release gate for real money is in `PHASE13_COMPLETE_SET_ARB.md` §6.
