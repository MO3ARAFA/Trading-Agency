# Phase 10 — final packaging: the continuous collector and the pre-impulse regime gate

## TL;DR
* **Built:** `regime_daemon --continuous` (one supervised `run_live` process, tape rotation every 30 min, shadow rows logged live, process cycled every 1.5 h, crash-restart with back-off) and an optional `--max-sigma60` gate inside Architecture B. 217 tests pass. Everything is paper-only.
* **Two corrections to the brief, both from the data:**
  1. **The "+248 bps quiet-breakout" number does not describe the specification you asked for.** Phase 9 labelled entries with σ60 *at the signal time*, a window that contains the triggering impulse. Re-labelled with the baseline *before* the impulse — which is what "breaks out from a non-chaotic baseline" means — the same 71 entries give **+128 ± 161 bps (N = 62, t = 0.80) below 0.50 and +347 ± 327 bps (N = 9) at or above it**. 8 of the 16 entries Phase 9 called "active" had a quiet baseline: the label was reacting to the impulse, not to prior turbulence. The gate removes 13 % of entries and the gated mean is not distinguishable from zero (nor from the ungated +156). The honest in-sample figure for *Pure B + `fixed0.7` + σ_pre < 0.50* is **+128 bps, t = 0.80, post hoc** — a planning input, not a result.
  2. **A 24/7 *warm* process is not possible with the current architecture.** Polymarket markets are discovered once per process and the `MarketBook` is fixed-size, so the 5-minute/15-minute markets a process started with expire and are not replaced. The daemon therefore keeps one process warm for 1.5 h at a time (tape rotation never touches the engines) and restarts it immediately; the cost is ≈ 1–2 min per session (20 s oracle warm-up, discovery, and the 75 s of BTC history the gate needs) ≈ 2 %. My earlier "5–10 %" applied to 10-minute segments.
* The microstructure story (calm book gets sniped, providers pull quotes in turbulence) is a hypothesis. The only supporting observation: turbulent-baseline signals had wider Polymarket spreads (median 526 vs 282 bps) and a lower floor pass rate (19 % vs 26 %); their `fixed0.7` outcomes were *not* worse (9 entries).
* **Pre-registered test for your multi-hour run:** `docs/PREREG_PHASE10.md` (24 code files SHA-256-pinned). H1: gated, floor-passed Polymarket `fixed0.7` net expectancy > 0, fresh data only, **N\* = 608** entries (power 0.80 for the in-sample +128 bps; 0.34 if the truth is half), count-only stop or 72 capture-hours. At the in-sample supply (≈ 24 gated fills per hour) that is **≈ 26 hours** of capture.

## The journey (Phases 1–10)
| Phase | What | Result |
|---|---|---|
| 1–3 | Research, oracle/hunter/CFO/CEO agency, first live run on 60 Binance alts | Lead-lag gaps exist but are ≲ 1 bp gross vs ~2 bp spread and 15 bp fees: detected, refused, governed |
| 4 | Zero-fee pairs, cross-venue, triangles; Hyperliquid + Polymarket watchers | Tight-spread edge only at 0 ms latency; Hyperliquid lags (+2.5 bps gross, unprofitable at 4.5 bps taker); Polymarket converges but loses −2.4¢/share as a taker |
| 5 | Queue-aware passive maker sniper + cancel shield | Not supported: makers don't fill (HL) or fill adversely (PM); found and fixed a binary-contract sizing flaw (−$396 → −$18) |
| 6 | A: pre-positioned quote maker with oracle cancel-shield; B: magnitude-floor taker + maker exit | A loses on PM in every non-optimistic fill model (shield cuts the loss, never flips it) and is gated out on HL. B abstains on HL (0 signals pass) and is positive-but-insignificant on PM |
| 7 | Isolated risk sleeves; six B exits | Uncapping looked better in-sample (trail t = 2.2) but not after a six-way correction |
| 8 | Single pre-registered test, `trail` vs `fixed0.7` | **Not supported** (fresh paired difference −175 bps, t = −0.63) |
| 9 | Power calculation, regime breakdown, regime-triggered daemon | N\* = 386 for the pooled population; regime split suggested "active is worse" |
| 10 | Pre-impulse gate, continuous collector, new pre-registration | The Phase 9 split was largely an impulse-size artefact (+128, not +248); N\* = 608; collection not yet run |

## The specification (what the code does, in order)
1. **Signal.** Binance BTC impulse (Polymarket scan: |Z| ≥ 2 on the 1/3/5/10 s horizons and ≥ 1 bp) → for each Polymarket contract, gap = (change in model fair probability from the BTC move over the horizon) − (change in the CLOB mid), in bps of the mid.
2. **Absolute floor (B).** Predicted move |Δ̂| = edge_credit·|gap| must be ≥ **1.5 × (spread + taker entry fee + maker exit fee)**, all in bps of the entry price; Polymarket taker fee per share = 0.07·p·(1−p), maker fee 0. Otherwise abstain.
3. **Regime gate (optional, `--max-sigma60 0.5`).** σ_pre = √(mean of the squares of 1-s Binance mid log-returns in bps over the 60 s ending **15 s before** the signal) < 0.50 bps/√s; unknown = no fire.
4. **Entry.** IOC taker at the touch after 150 ms order latency, filled against the as-of quote at arrival; rejected on price move or < 50 % liquidity.
5. **Exit `fixed0.7`.** Post-only maker take-profit at the converged touch of 0.7 × |gap| (8–10 s window), scratch if the impulse stalls, taker stop only on a genuine reversal / CFO stop, taker fallback at the work deadline (all with 150 ms cancel latency charged).
6. **Sizing/risk.** Per-venue sleeve with its own CFO book and governor; size by worst-case binary loss per share (long p, short 1−p, 50 % gap), 60 s expiry guard, fractional Kelly and caps.
7. **Evaluation unit.** One floor-passed, IOC-filled entry; net bps of notional after fees; cluster-robust t (clusters = BTC impulse); fill model `strict` (lower bound; `trades` and `depletion` reported).
**Historical, in-sample, post hoc:** all 71 floor-passed entries +156 ± 145 bps (t = 1.07); gated (σ_pre < 0.50) +128 ± 161 (N = 62, t = 0.80). Neither is a validated edge. Phases 6–8 never produced a significant result for any B exit.

## The three commands (your machine, persistent host: laptop left on, VPS, tmux/systemd)
```bash
git clone -b claude/kind-cori-5ei4hp https://github.com/MO3ARAFA/Trading-Agency.git && cd Trading-Agency
python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt     # tested: Python 3.13; pins in requirements-tested.txt
python -m quant_agency.regime_daemon --continuous                                    # Ctrl-C = graceful stop; add nohup/tmux to leave it running
```
Then, any time (the collection can be inspected while it runs):
```bash
python -m quant_agency.p10_eval --runs 'runs/p10r*' --out docs/live_runs/phase10_eval.md     # the one pre-registered test (frozen-code check included)
python -m quant_agency.p10_eval --check-frozen
python -m quant_agency.inspect_run runs/p10r1_<timestamp>                                    # sleeve states, last fills
```
Outputs: `runs/p10r<k>_<timestamp>/` (report, `b_shadow.jsonl` = the data, `signals.jsonl`, sleeve events), `tapes/p10r<k>_partNNNN.npz` (≈ 16 MB/h, concatenate with `python -m quant_agency.tape_tools concat …`), `runs/p9_daemon/daemon_log.jsonl`. Do not pass any threshold override (`--max-sigma60`, `--n-star`) in the confirmatory run: overrides mark it *validation* (`p10v*`) and `p10_eval` refuses it.

## What to expect, and what not to conclude
* ≈ 26 h to N\* at in-sample supply; the cap is 72 h. Expect each session to open with 1–2 quiet minutes. A feed outage appears as `DOWN` in the status log; a crash restarts cold after a back-off (logged as `child_crash`).
* Your machine must be able to reach `data-stream.binance.vision`, Hyperliquid and Polymarket public websockets; the agency only *reads* public data. Check the venue terms and your jurisdiction before running anything that touches them.
* The more probable outcome on the evidence so far is a null (gated in-sample t = 0.80). A rejection of H1 would still not be a trading recommendation: OPERATOR_GUIDE §6 (independent replication, a genuinely volatile-regime session analysed on its own, measured latency/fees, shadow-live reconciliation, legal and key-safety work) applies unchanged. There is no code in this repository that can place an order.

## Files added/changed in Phase 10
`high_conviction_sniper.py` (σ_now/σ_pre tags on every shadow row, account gate, shadow-row log, gated fill counter), `cfo_agent.py` (`regime_gate` reason), `agency.py` (BTC mid → sniper), `run_live.py` (`--max-sigma60 --rotate-min --shadow-log`), `tape_tools.py`, `regime_daemon.py` (`--continuous`, session cycling), `p10_gate.py` (definition check + power), `p10_eval.py` (the confirmatory test), `tests/test_phase10.py`; evidence in `docs/live_runs/phase10_gate.md/.json`.
