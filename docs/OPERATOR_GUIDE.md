# Operator guide — Trading-Agency (paper mode only)

Scope: how to run, record, replay and inspect **Pure Architecture B** (high-conviction magnitude-gated taker sniper) on Polymarket + Hyperliquid using the Binance BTC oracle, and what must be true before anyone connects a wallet. **Nothing in this repository can place an order**: there are no credentials, no signing code and no code path that transmits one. `OrderPayload.exchange_params()` only shows what *would* be sent.

Status of the evidence (read this first): B has a positive point estimate on floor-passed Polymarket entries but has **not** passed a significance bar on fresh data (see docs/PHASE7.md, docs/PHASE8.md). Hyperliquid never clears B's floor. Every recorded session was in a quiet BTC regime (0.20–0.25 bps/√s). Treat everything below as an engineering and research harness.

## 1. Setup

```bash
cd Trading-Agency
pip install -r requirements.txt          # numpy, numba, aiohttp, uvloop, orjson, websockets, pytest
python -m pytest tests -q                # 190+ tests, ~20 s; run before every session
```
Outbound access needed (no keys): `data-stream.binance.vision:443` (oracle), `data-api.binance.vision` (REST), Hyperliquid and Polymarket public websockets, `gamma-api.polymarket.com` (market discovery). If a corporate/cloud proxy blocks them the run prints the failing feed in the status line (`polymarket:DOWN/…`).

## 2. Launch a live **paper** session (Pure B, isolated sleeves)

```bash
python -m quant_agency.run_live --phase7 --b-exit trail --duration 2700 --record tapes/mysession.npz --tag mysession --out runs
```

| flag | meaning |
|---|---|
| `--phase7` | Pure Architecture B on isolated per-venue risk sleeves; Architecture A is never constructed. (`--phase6` still exists for reproducing the A-vs-B comparison; do not use it for new work.) |
| `--b-exit` | exit policy of the **account** sleeve: `fixed0.7` `fixed1.0` `wide1.5` `wide2.0` `adaptive` `trail`. All six always run as shadows regardless. |
| `--b-floor 1.5` | absolute floor multiple: fire only if predicted move ≥ mult × (spread + taker-in fee + maker-out fee). Default 1.5. Changing it changes the hypothesis. |
| `--sleeve-capital 10000` | paper bankroll of *each* sleeve. |
| `--duration` | seconds of live capture. |
| `--record path.npz` | save the full event tape (quotes, trade prints, Polymarket specs) for deterministic replay. Saved only when the run ends normally. |
| `--stop-fills N --prior-fills K` | count-only stopping rule: stop once K + live floor-passed Polymarket `trail` fills ≥ N (used by the Phase 8 collector). |
| `--hl-maker-bps / --hl-taker-bps` | Hyperliquid fee assumptions (default 1.5 / 4.5 bps — assumptions, not measurements). |
| `--status-every 120` | status-line period (s). |

The status line shows BTC micro-price, the fast Z-scores and **`vol=… bps/√s`** (the regime number), signal counts, feed health (`up/DOWN/messages`) and, in Phase 7+, the running count of floor-passed Polymarket fills.

## 3. Record and replay

```bash
# deterministic replay of a tape through the full agency (A not built), writes a report like a live run
python -m quant_agency.run_live --replay tapes/p7_tape_1.npz --phase7 --tag replay --out runs
# all six exits on every tape, pooled, with cluster-robust t-statistics
python -m quant_agency.p7_pool tapes/p4_tape_1.npz tapes/p5_tape_1.npz tapes/p6_tape_1.npz tapes/p7_tape_1.npz --out docs/live_runs/pooled.md
# synthetic lag worlds (mechanism checks only; quiet / volatile regimes, informed-taker delay sweep)
python -m quant_agency.sim_lag_world --regime volatile --d-inf 0.5 --out tapes/w_vol.npz
python -m quant_agency.p7_pool --synthetic --seeds 3 --duration 600
# the single pre-registered Phase 8 comparison (refuses to claim a pass if frozen files changed)
python -m quant_agency.p8_eval --check-frozen
python -m quant_agency.p8_eval --prior tapes/p4_tape_1.npz … --fresh tapes/p8_tape_1.npz --out docs/live_runs/phase8_eval.md
```
`tapes/` and `runs/` are git-ignored (large). Replay is deterministic given a tape, but live counters can differ from the replay of the same tape by a few fills (live uses wall-clock scheduling); analyses are always done on replays.

## 4. Inspecting the sleeves (CFO/CEO states)

Each venue has an **independent** sleeve (`hyperliquid_b`, `polymarket_b`): its own CFO book (equity, exposure, breakers, blacklist, config copy) and its own governor `NORMAL → TIGHTENED → DEFENSIVE → HALTED` (then timed probation). A loss or halt in one sleeve cannot change the other's state. The global CEO does **not** govern B in Phase 7+.

```bash
python -m quant_agency.inspect_run runs/mysession_<timestamp>            # sleeves, governor events, last fills, global CEO audit
python -m quant_agency.inspect_run runs/mysession_<timestamp> --follow   # refresh every 30 s while the run writes
```
Files in a run directory: `report.md` (full report), `summary.json` (`"sleeves": [...]` final states), `sleeve_events.jsonl` (every governor action with evidence), `trades.jsonl` (account fills, tagged with their `sleeve`), `b_account.jsonl` (every account attempt incl. non-fills), `signals.jsonl` (every signal with the CFO decision and its reason, e.g. `below_absolute_floor`, `halted`, `size_below_min`), `ceo_audit.jsonl` (global CEO, mostly irrelevant to B).

What the governor does (per sleeve, every 30 s, ≥ 6 fresh round trips, cluster-robust by BTC impulse): net + s.e. below −tolerance → TIGHTEN (floor +0.5, size ×0.5) → DEFENSIVE (floor ≥ 3×, ×0.25) → HALT (10 min) → resume on probation at ×0.25 from the current equity. A CFO drawdown/daily-loss breaker inside the sleeve halts only that sleeve. To see why signals were refused: `jq -r '.decision.reason' runs/<dir>/signals.jsonl | sort | uniq -c | sort -rn`.

## 5. Volatility-regime awareness (the collector's biggest blind spot)

B is built for large, continuing BTC impulses; every recorded session was quiet. A quiet-regime result cannot confirm or refute B's design case, and Hyperliquid only clears the floor if moves are ≫ 10 bps. To collect the missing regime:

0a. **Phase 10 (current): continuous collector.** `python -m quant_agency.regime_daemon --continuous` — one supervised warm process (feeds, hunter and oracle stay warm; tape parts every 30 min; shadow rows logged live to `runs/p10r*/b_shadow.jsonl`; process cycled every 1.5 h because Polymarket markets are discovered once per process), pre-impulse σ60 < 0.50 gate in Architecture B, count-based stop at N* = 608 or 72 capture-hours. Evaluate with `python -m quant_agency.p10_eval --runs 'runs/p10r*'`. See docs/PHASE10_FINAL.md and docs/PREREG_PHASE10.md. Everything below in this item describes the superseded Phase 9 triggered mode.
0. **One command (Phase 9, superseded): let the regime daemon decide.** It sits in cheap standby (one Binance websocket, ≈ 1 % CPU, ≈ 43 MB) and launches/stops recorded Pure-B sessions (`--b-exit fixed0.7`, sleeves active, A never built) by pre-registered rules:
   ```bash
   python -m quant_agency.regime_daemon --dry-run      # watch the σ60 trace and the decisions it WOULD take; launches nothing
   python -m quant_agency.regime_daemon                 # confirmatory mode: N* and the 24 h cap come from docs/PREREG_PHASE9.json
   python -m quant_agency.p9_eval --check-frozen        # was anything changed since the pre-registration?
   python -m quant_agency.p9_eval --tapes tapes/p9_seg*.npz --out docs/live_runs/phase9_eval.md
   ```
   Triggers (σ60 = RMS of the last 60 one-second Binance mid returns, bps/√s; `quant_agency/regime.py`): start in London 07:00–10:00 UTC or US 13:30–16:30 UTC (Mon–Fri), or when σ60 ≥ 0.45 for 30 s; stop only outside windows after σ60 < 0.35 for 300 s and ≥ 600 s of session. Segments are ≤ 2,700 s and saved as `tapes/p9_seg<k>.npz`; the log is `runs/p9_daemon/daemon_log.jsonl` (60 s σ60 trace, every start/stop with its reason, fills per segment). Stop the daemon with Ctrl-C/SIGTERM: it asks the running segment to finish gracefully (tape saved) first. Any threshold override (`--start-thr`, `--extra-window`, …) marks the run as *validation* (prefix `p9v_seg`, separate log) and `p9_eval` refuses those tapes. Keep it on a persistent host — the tapes are the data. A graceful segment end finalises open positions as a taker exit at the last quote; that is by design and part of the analysed sample.
   Caveat from the data we have: `fixed0.7` was *worse* in the active regime (−161 ± 271 bps, N = 16) than in quiet (+248 ± 166, N = 55). The daemon is a collector, not a signal that active windows pay.
1. **Check the regime before launching (manual alternative)** (indicative Parkinson estimate in the oracle's own unit):
   ```bash
   python -m quant_agency.regime_check          # e.g. "last 15 min 0.19 bps/√s (quiet)"
   ```
   Heuristic bands: quiet < 0.30, elevated 0.30–0.60, volatile ≥ 0.60 bps/√s. They are anchored to the only regime we have recorded (0.20–0.25), **not calibrated** — confirm against the live `vol=` field after the first minute.
2. **Candidate windows** (UTC; check the calendar, DST shifts them): the US cash open 13:30–14:30 (14:30–15:30 outside US DST), scheduled US macro prints (CPI, NFP, FOMC statement ≈ 18:00/19:00 UTC on decision days), and the first hour after the Asian/European opens. Start the collector ~10 minutes *before* the window so the oracle warm-up (20 s) and the Polymarket discovery are done. Use `--duration 6000` for a 13:30–16:00 window; keep `--record` on.
3. **Do not condition on outcome.** Pick the window from the calendar/regime check, not from whether the last session made money. Record the regime of every session (the `vol=` trace and `regime_check` output) next to its result, and report quiet and volatile sessions **separately**.
4. **Risk during macro prints:** Polymarket books can gap several cents between quotes; the CFO sizes by the worst-case binary loss (long `p`, short `1−p`, 50 % gap) and refuses entries inside 60 s of expiry — leave those guards on.
5. Reproducibility: never edit strategy files between sessions you intend to pool. Pre-register any new confirmatory test the way docs/PREREG_PHASE8.md does (hypothesis, metric, N, stopping rule, hash of the code).

## 6. Connecting an execution wallet — what must be true first, and what not to do

**There is no execution code here, and writing it is the smallest part of the job.** Do not connect a wallet, create API keys, or paste a private key into this repository, a config file, a shell history or a chat until *all* of the following are true:

1. **Statistical bar cleared on data not used to choose the strategy.** At minimum: the pre-registered test (`p8_eval`) passes on fresh data with N ≥ 70 floor-passed fills (raw t > 2.0 and the multiplicity-adjusted t > 2.63), **and** the effect is observed again in an independent later batch, **and** at least one genuinely volatile BTC session has been recorded and analysed separately. Today none of these holds.
2. **Measured, not assumed, microstructure.** The simulator assumes 150 ms order and cancel latency, an as-of-arrival fill, a queue model with no hidden size, and a Polymarket taker fee of `0.07·p·(1−p)` per share. Before real money: measure real order round-trip latency from your actual host, confirm the live fee schedule and tick/minimum-size rules for the specific markets, and verify settlement/resolution mechanics of the contract types you trade. Re-run the replay with the measured numbers; the edge must survive them.
3. **Shadow-live reconciliation at a trivial size.** Before scaling anything, route a handful of tiny real orders and compare each against what the paper engine predicted for the same signal (fill/no-fill, price, fee, latency). Large, systematic differences mean the paper results are not transferable.
4. **Legal / compliance / venue terms.** Verify that you are permitted to trade the venue from your jurisdiction and entity, the venue's terms on automated trading, tax treatment, and any KYC. This is your responsibility; the repository does not address it.
5. **Operational safety, designed before the first order:** a dedicated wallet holding only the capped risk capital (never a main wallet); keys in a secrets manager/hardware signer, never in the repo or environment dumps; an independent kill switch that cancels open orders and stops the process without relying on the agency's own CEO/CFO; hard position, daily-loss and per-market caps enforced *outside* the strategy process; alerting on feed loss, stale quotes and balance changes; a runbook for a stuck position near expiry.
6. **Stage it:** paper → micro-size real (a few dollars per trade) → a multiple of that only after the reconciliation in step 3 is clean over many fills. Treat the first real fills as an experiment on the simulator, not as production.

**Things you should NOT do:** switch Hyperliquid on (B abstains there at 4.5 bps taker; 0 of 317 signals pass); re-enable Architecture A (shelved: it loses on Polymarket in every non-optimistic fill model); change the floor, the exit, or the sleeves' tolerances after seeing results and then pool the data as if nothing changed; pick the best of the six exits after the fact and report its t-statistic without the multiplicity adjustment; lift the governor's HALT by hand to "get a trade"; size by notional on binary contracts (the CFO's worst-case sizing exists because a short at 0.33 can lose 2× its notional); read a paper P&L as a forecast of live P&L.

## 6b. Sector lead-lag capture (measurement only)

```bash
# 3 min warm-up + 20 min window, records the tape, writes docs/SECTOR_LEAD_LAG.md
python -m quant_agency.sector_report --capture --duration 1200 --notes docs/SECTOR_NOTES.md
# or by hand
python -m quant_agency.run_live --sectors --duration 1380 --record runs/tapes/sector.npz --out runs --tag sector
python -m quant_agency.run_live --replay runs/tapes/sector.npz --placebo-shift 300 --out runs --tag placebo300   # control: leaders time-shifted
python -m quant_agency.sector_report --run runs/sector_<stamp> --placebo runs/placebo*_<stamp>
```
`--sector-list sol,pepe,render,doge,tao` chooses the oracles, `--sector-mult` the leader-volatility factor of the gap hurdle (`0` = flat 1 bp). Nothing in this mode places or prepares orders, the CEO is not run, and
the CFO book is untouched; every signal (BTC baseline included) becomes a markout row tagged with the oracle that produced it. Run directory artefacts: `sector_markouts.jsonl`, `sector_signals.jsonl`,
`sector_map.json`, `sector_models.json`, `sector_universe.json`. A sector tape replays deterministically (the sector map is stored in the tape).

## 6c. Same-asset cross-venue capture (Binance spot -> Hyperliquid perp; measurement only)

```bash
python -m quant_agency.midcap_eval --check-frozen                                   # pre-registered files intact?
python -m quant_agency.run_live --midcap-xv --duration 3660 --out runs --tag xvr_s1 --record runs/tapes/xvr_s1.npz   # one 60-minute stage
python -m quant_agency.midcap_eval --count --runs 'runs/xvr_s*_2026*'               # count-only stopping statistic (stop at >= 20 clusters or 4 stages)
python -m quant_agency.midcap_eval --runs 'runs/xvr_s*_2026*'                       # the single pre-registered test (refuses non-xvr* directories and changed frozen files)
python -m quant_agency.run_live --replay runs/tapes/xvr_s1.npz --placebo-shift 600 --out runs --tag xvp_s1_600   # control: Binance legs shifted against the perps
python -m quant_agency.midcap_report --runs 'runs/xvr_s*_2026*' --placebo 'runs/xvp_s*_2026*' --notes docs/MIDCAP_NOTES.md
```
Naming matters: confirmatory stages are `xvr*`, validation/smoke runs `xvv*`, controls `xvp*`. Nothing in this mode prepares an order; the arb module and the CEO are idle.

## 7. Troubleshooting

| symptom | likely cause / action |
|---|---|
| `polymarket:DOWN` or no PM signals | feed or discovery failure (network/proxy); restart. The run records nothing useful without PM. |
| `size_below_min` dominates `signals.jsonl` | the sleeve is TIGHTENED/DEFENSIVE (size ×0.5/×0.25) or equity is small relative to the worst-case binary sizing — expected behaviour, not a bug. |
| `halted` decisions | the sleeve's governor or a CFO breaker halted that sleeve; see `sleeve_events.jsonl`. The other sleeve is unaffected by design. |
| replay count differs from live counter by a few | live scheduling jitter; use the replay for analysis. |
| `p8_eval` says frozen-code check FAIL | a strategy/analysis file changed after pre-registration; the result is exploratory, not confirmatory — say so, or revert. |
