# Trading-Agency — autonomous multi-agent quant agency (BTC lead-lag / micro-mispricing)

One mission: **use live BTCUSDT as the master oracle, watch 50+ markets in real time, and trigger (paper) trades the instant a lead-lag
dislocation clears strict statistical and cost thresholds — under an autonomous CEO↔CFO governance loop.**

```
                    wss://data-stream.binance.vision  (1 combined conn: BTC book+aggTrade + 60 alts)   Gate BBO · Kraken BBO
                                         │ perf_counter timestamp at socket exit
                                         ▼
 TIER 1  ┌──────────────┐   ┌─────────────────────┐   ┌──────────────────────────────────────────────┐
 sensory │ btc_oracle   │   │ market_watchers     │   │ inefficiency_hunter                          │
 & hunter│ micro-price  │──▶│ SoA book: bid/ask/  │──▶│ HY lead-lag lag l*, Kalman β, ρ, residual σ  │
         │ OBI, Δ1/3/5/ │   │ qty, tick time,     │   │ Gap = β·Δ(BTC micro, h) − Δ(mid_i, h)        │
         │ 10s, Z, flow │   │ staleness, spread   │   │ stale/lagging-quote detection (lag window)   │
         └──────────────┘   │ regime, as-of ring  │   └───────────────┬──────────────────────────────┘
                            └─────────────────────┘                   │ Signal
 TIER 2                                                               ▼
 CFO       cfo_agent: NetEdge = credit·|Gap| − (Spread + Fees + Slippage + Hurdle) · fractional-Kelly ∧ risk ∧ liquidity ∧
           exposure caps · per-market & portfolio breakers · markout curves t+1/3/5/10/30s for EVERY signal (shadow cohort too)
                                                                      │ approved Decision
 TIER 3                                                               ▼
 execution execution_engine: full payload (IOC taker sniper | post-only maker, tick-rounded limit, liquidity-capped qty,
           convergence TP, hard time-stop, adverse stop) → latency-aware PAPER exchange (as-of quotes, no look-ahead)
                                                                      │ trades, markouts, KPIs
 TIER 4                                                               ▼
 CEO       ceo_agent: audits win-rate / expectancy (bps, R) / markout decay / spread+slippage drag / per-market P&L and the
           CFO's *predicted vs realised* edge ──▶ quarantine markets · retune CFO hurdle/size/credit/slippage · taker→maker-only ·
           retune Hunter Z & lag window to the vol regime · NORMAL→TIGHTENED→DEFENSIVE→HALTED→probation · JSONL audit trail
```

**Paper only.** There are no exchange credentials anywhere and no code path that transmits an order; `OrderPayload.exchange_params()`
shows what *would* be sent.

## Layout
```
quant_agency/
  mathkit.py            numba kernels: micro-price, OBI, ring as-of search, Hayashi-Yoshida, Kalman β
  btc_oracle.py         Tier 1  master BTC feed state (tick / 100 ms / 1 s rings, Z-scores, vol regime, trade flow)
  market_watchers.py    Tier 1  MarketBook (struct-of-arrays) + Binance universe discovery + cross-venue metas
  inefficiency_hunter.py Tier 1 LeadLagModel (HY + OLS + Kalman) and the gap scanner
  cfo_agent.py          Tier 2  gating, sizing, breakers, MarkoutTracker
  execution_engine.py   Tier 3  payloads + paper exchange
  ceo_agent.py          Tier 4  supervisor + state machine + audit
  sector_oracles.py     secondary oracles (SOL / PEPE / RENDER / DOGE / TAO): universe discovery, per-leader hunters, observe-only sink
  sector_report.py      sector lead-lag report generator (+ live capture driver, time-shift control)
  agency.py             wiring (sync, clock-injected)        feeds.py   asyncio/uvloop/orjson websockets
  telemetry.py          markdown report                      sim.py     synthetic lead-lag market
  run_live.py           CLI: live | --sim | --replay tape    sweep.py   replay one tape under many fee tiers
tests/                  239 tests (math, oracle, hunter, CFO, execution, CEO state machine, end-to-end)
docs/RESEARCH.md        Phase 1 reconnaissance → code map
```

## Run
```bash
pip install numpy numba uvloop orjson websockets aiohttp pytest scipy
python -m pytest tests -q

# live: 60 Binance alts + BTC oracle + 6 cross-venue markets, 15 min, record the tape
python -m quant_agency.run_live --markets 60 --duration 900 --record tapes/t.npz
# replay the same tape under other cost assumptions (deterministic)
python -m quant_agency.sweep tapes/t.npz --fees 7.5 4.5 1 0
# offline dry-run on the synthetic market
python -m quant_agency.run_live --sim --duration 300 --fee-bps 0
```
Each run writes `runs/<tag>_<ts>/` with `report.md`, `summary.json`, `signals.jsonl`, `payloads.jsonl`, `trades.jsonl`, `ceo_audit.jsonl`, `config.json`.

## Results
See **[docs/LIVE_RESULTS.md](docs/LIVE_RESULTS.md)** (live telemetry, markout tables, fee×latency sweep, CEO→CFO audit trail) and `docs/live_runs/`.
Short version: lead-lag gaps exist but are ≲1 bp gross vs ~2 bp spread and 15 bp fees — the agency detects them, refuses to trade them, and the CEO governs accordingly.

## Phase 4 — venue & microstructure specialization
`venues.py`, `cross_venue_arb.py`, `polymarket_watcher.py` + new feeds (Coinbase, Hyperliquid, Deribit, Polymarket CLOB). 151 markets / 7 feeds live.
See **[docs/PHASE4.md](docs/PHASE4.md)**: the `<0.5 bps` hypothesis replicates at 0 ms latency but not at 150 ms; Hyperliquid is the only latency-robust lead
(gross +2.5 bps, unprofitable at taker fees); Polymarket's CLOB converges to BTC-implied value but is not tradable as a taker (−2.4 ¢/share net).
```bash
python -m quant_agency.run_live --phase4 --duration 1200 --record tapes/p4.npz
```

## Phase 5 — queue-aware passive maker sniper (Hyperliquid + Polymarket)
`maker_sniper.py`: post-only join / penny-jump entries with a queue model (strict / depletion / real trade prints), cancel latency, oracle cancel shield,
passive exits, six variants scored on identical signals. **Result: not supported** — makers either don't fill (HL 3–15 %) or fill adversely (PM conditional markout
−400…−1,600 bps under the strict/trades fill models; the optimistic depletion bound is the only one that is not negative). See **[docs/PHASE5.md](docs/PHASE5.md)**; also documents a binary-contract risk-sizing flaw found live and fixed.
```bash
python -m quant_agency.run_live --phase5 --duration 1500 --record tapes/p5.npz
python -m quant_agency.p5_pool tapes/p4_tape_1.npz tapes/p5_tape_1.npz
```

## Phase 6 — pre-positioned quote maker (A) vs high-conviction taker sniper (B)
`pre_positioned_mm.py` (two-sided post-only quotes while BTC is calm, oracle cancel-on-impulse, inventory exits at the converged price), `high_conviction_sniper.py`
(hard floor `|Δ̂| ≥ 1.5×(spread + taker-in + maker-out)`, IOC in, maker take-profit, stall-scratch), shared `queue_model.py`, and a controlled `sim_lag_world.py`
(regime × informed-taker delay). **Result: no tradable edge.** A loses on Polymarket in every non-optimistic fill model (the shield cuts the loss but never flips it, even at 0 ms
cancel) and is gated out on Hyperliquid (1.5 bp maker fee > spread); B abstains on HL (0/208 signals pass) and its floor-passed Polymarket subset is positive but not significant
(n = 36, t ≈ 1.3). See **[docs/PHASE6.md](docs/PHASE6.md)** (174 tests).
```bash
python -m quant_agency.run_live --phase6 --duration 1500 --record tapes/p6.npz
python -m quant_agency.p6_pool tapes/p4_tape_1.npz tapes/p5_tape_1.npz tapes/p6_tape_1.npz --sweeps
python -m quant_agency.p6_stress --seeds 3 --duration 600
```

## Phase 7 — Pure Architecture B on isolated risk sleeves
`sleeves.py` (one independent CFO book + governor per venue — a drawdown in `polymarket_b` cannot halt `hyperliquid_b`; Architecture A shelved) and six B exit policies
(`fixed0.7/1.0`, `wide1.5/2.0`, `adaptive`, Binance-guided `trail`) run on identical entries. **Result:** uncapped exits look better in-sample on Polymarket
(48 floor-passed fills: `trail` +680 ± 306 bps, t = 2.2; Phase 6 reference `fixed0.7` t = 1.1) but nothing survives a correction for six exits and the fresh 3,000 s live session
(12 fills) was uninformative; Hyperliquid never clears the floor (0/317). t > 2 on a pre-registered exit was **not** reached. See **[docs/PHASE7.md](docs/PHASE7.md)** (187 tests).
```bash
python -m quant_agency.run_live --phase7 --b-exit wide2.0 --duration 3000 --record tapes/p7.npz
python -m quant_agency.p7_pool tapes/p4_tape_1.npz tapes/p5_tape_1.npz tapes/p6_tape_1.npz tapes/p7_tape_1.npz
```

## Phase 8 — single pre-registered exit validation (`trail` vs `fixed0.7`) and operator guide
Hypothesis, metric, stopping rule and code hashes were committed **before** any new data (`docs/PREREG_PHASE8.md/.json`). **Result: not supported** — fresh-only paired difference −175 bps
(t = −0.63, N = 24); cumulative N = 72, `trail` t = +1.67 (< 2.0, < 2.63). The Phase 7 improvement did not replicate; B with the reference exit remains an unproven lead (+162 ± 144 bps).
See **[docs/PHASE8.md](docs/PHASE8.md)**; **[docs/OPERATOR_GUIDE.md](docs/OPERATOR_GUIDE.md)** covers live paper runs, tape record/replay, sleeve inspection (`inspect_run`),
volatility-window collection (`regime_check`) and the conditions that must hold before any wallet is connected (none do today).
```bash
python -m quant_agency.p8_eval --check-frozen
python -m quant_agency.inspect_run runs/<run_dir>
python -m quant_agency.regime_check
```

## Phase 9 — power-calculated `fixed0.7` protocol and the regime-triggered collector
`regime.py` (σ60 estimator), `regime_daemon.py` (standby supervisor: launches/stops recorded Pure-B sessions on volatility or London/US windows, graceful segments), `p9_regime.py`
(volatility breakdown + power calculation), `p9_eval.py` (the single confirmatory test). **No test result yet — by design:** N\* = **386** floor-passed Polymarket entries (power 0.80 at the observed +156 bps;
0.34 if the truth is half of it), pre-registered with 21 code hashes before any confirmatory data; the existing data lean *against* an active-regime advantage (`fixed0.7` +248 bps quiet vs −161 active, not significant).
See **[docs/PHASE9.md](docs/PHASE9.md)** and **[docs/PREREG_PHASE9.md](docs/PREREG_PHASE9.md)**; usage in **[docs/OPERATOR_GUIDE.md](docs/OPERATOR_GUIDE.md)** §5.
```bash
python -m quant_agency.regime_daemon --dry-run
python -m quant_agency.regime_daemon
```

## Phase 10 — final packaging: continuous collector + pre-impulse regime gate
`python -m quant_agency.regime_daemon --continuous` supervises one warm `run_live --phase7` process (tape rotation, live shadow-row log, 1.5 h process cycling because Polymarket markets are discovered once per process),
with an optional pre-impulse σ60 gate (`--max-sigma60`) in Architecture B. **Correction:** the Phase 9 "+248 bps quiet" bucket was largely an impulse-size artefact — with the baseline measured *before* the
impulse the gated specification is **+128 ± 161 bps (t = 0.80, post hoc)**. Pre-registered test (`docs/PREREG_PHASE10.md`): N\* = 608 gated entries, ≈ 26 h of capture. See **[docs/PHASE10_FINAL.md](docs/PHASE10_FINAL.md)**.
```bash
git clone -b claude/kind-cori-5ei4hp https://github.com/MO3ARAFA/Trading-Agency.git && cd Trading-Agency
python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
python -m quant_agency.regime_daemon --continuous
```

## Sector lead-lag study — altcoin ecosystems vs their own leaders (BTC baseline)
`python -m quant_agency.run_live --sectors --duration 1380 --record runs/tapes/sector20.npz` runs BTC plus sector oracles (SOL, PEPE, RENDER, and DOGE / TAO as alternative leaders) in parallel on one `MarketBook`:
each leader has its own `BtcOracle` and its own `InefficiencyHunter` over its ecosystem's alts on Binance Vision, Gate, Kraken and Hyperliquid (111 markets), with a leader-volatility-scaled gap hurdle,
a quote-validation gate and a CFO-model net gap `|gap| − (spread + 2·fee + slippage)`. Observe-only: no order is ever prepared.
**Result of the first 20-minute capture (exploratory):** median |gap| 2–4 bps (not 10–20), spread ≈ gap, net gap > 0 in 0 % of signals for five of six oracles, no sector oracle better than BTC on the same
instruments, and a time-shifted-leader control shows most of the gross markout is selection, not lead-lag. Rare ≥ 10 bps dislocations (7 impulses) reached only the leader's own asset on Hyperliquid.
See **[docs/SECTOR_LEAD_LAG.md](docs/SECTOR_LEAD_LAG.md)**; regenerate with `python -m quant_agency.sector_report --run docs/live_runs/sector20 --placebo docs/live_runs/sector20/placebo/shift* --notes docs/SECTOR_NOTES.md`.
