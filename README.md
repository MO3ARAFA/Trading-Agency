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
  agency.py             wiring (sync, clock-injected)        feeds.py   asyncio/uvloop/orjson websockets
  telemetry.py          markdown report                      sim.py     synthetic lead-lag market
  run_live.py           CLI: live | --sim | --replay tape    sweep.py   replay one tape under many fee tiers
tests/                  113 tests (math, oracle, hunter, CFO, execution, CEO state machine, end-to-end)
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
