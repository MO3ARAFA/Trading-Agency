# Pre-registration — same-asset cross-venue tail lag (Binance Vision spot → Hyperliquid perp), mid-caps

*Written and frozen before any confirmatory data exists. The files listed in `PREREG_MIDCAP_XV.json` are hashed; `python -m quant_agency.midcap_eval --check-frozen` refuses to produce a verdict if any of them changed.*

## Why this test exists, and what it is not
The 20-minute sector capture (`docs/SECTOR_LEAD_LAG.md`) found that ecosystem followers do not close their gap to a sector leader fast enough to beat costs, and contained **one** event in which the leader's *own* asset on Hyperliquid
(TAO, −27.9 bps on Binance) repriced by +17.8 bps gross / ≈ +6.9 bps net of assumed fees. That is an observation selected after the fact (n = 1, one regime), **not** evidence. It is excluded from this test: only data from
`xvr*` run directories collected after this file was committed count. The premise that BTC/ETH are arbitraged to within ~2.4 bps on Hyperliquid is *not* assumed; BTC and ETH run through the identical scanner as a baseline and are
reported, not trusted.

## Design (what is measured)
* **Pairs.** Every Binance Vision USDT spot market that also has an active Hyperliquid perp, minus BTC/ETH, gold and stable tokens, minus coins whose Binance book is quantised (1 tick > 10 bps) or wider than 15 bps, minus coins below
  $1M (Binance) or $0.5M (Hyperliquid) of 24 h volume; the **50 with the highest Hyperliquid 24 h volume** are the mid-cap set. BTC and ETH are added as the baseline pairs.
* **Oracle.** Coin *i* on Binance is the only oracle for coin *i* on Hyperliquid. No β, no calibration: `gap = [ln B(t) − ln B(t−h)] − [ln H(t) − ln H(t−h)]`, h ∈ {1 s, 3 s}, evaluated on every Binance tick of the coin
  (basis-neutral by construction).
* **Signal.** `|ΔB| ≥ 4 bps`, `sign(gap) = sign(ΔB)`, `|gap| ≥ 4 bps` (shadow floor; cooldown 3 s per pair). Tiers are cut afterwards: ≥ 8, ≥ 10, ≥ 15 bps and **full cost cleared**:
  `|gap| ≥ HL spread + 2 × 4.5 bps + 0.5 × spread × min(1 000 USD / touch size in USD, 4)`.
* **Trade model.** Taker on the perp at the touch (ask for an up-move, bid for a down-move) `latency` after the Binance tick, taker exit at the touch `h` later. Latencies 0 / 150 / 500 / 1 000 ms, horizons 1 / 3 / 5 / 10 / 30 s.
  Fee tiers are applied afterwards to the spread-crossing result: taker/taker 9 bps, taker-in/maker-out 6 bps, maker/maker 3 bps (the two maker tiers assume no fill risk and are optimistic; they are descriptive only).
* **Clusters.** 10-second time blocks (a market-wide move hits many coins at once); one block id is shared by every coin in it.

## Primary hypothesis (the only confirmatory claim)
**H1.** Among mid-cap signals that clear the **full cost hurdle** and whose entry-side touch is worth **≥ 1 000 USD**, the mean **net** result — taker in and out, crossing the perp spread both ways, 4.5 bps per side — at **h = 5 s** with **150 ms**
entry latency is **> 0**.

* Test: one-sided cluster-robust t (clusters = 10-s blocks per run), Student-t reference with clusters − 1 df, α = 0.05 (same machinery as Phases 8–10: `p9_eval.primary_test`).
* A decision needs **≥ 15 clusters** in the primary subset; with fewer the outcome is reported as *"underpowered — no decision"* (estimate and bootstrap CI shown, no claim either way).
* Primary specification is fixed: no other latency, horizon, tier, fee tier, size filter or asset subset can be promoted to a primary after seeing data.

## Stopping rule (count-only; never looks at an outcome)
Collect in **60-minute stages** (`xvr_s1`, `xvr_s2`, …). After each stage run `python -m quant_agency.midcap_eval --count --runs 'runs/xvr_*'`, which prints only the number of primary-subset signals and clusters.
Stop when the primary subset has **≥ 20 clusters** or after **4 stages (4 hours)**, whichever comes first. The test is evaluated **once**, after stopping. Stages are pooled; run directories are the only unit of pooling.

## Secondary, descriptive (no claims, no multiplicity adjustment)
Occurrence rates of ≥ 8 / 10 / 15 bps and full-cost dislocations per hour and per coin-hour; gross and net markouts by tier × latency × horizon × fee tier; the BTC/ETH baseline at equal gap tiers; the time-shifted placebo
(Binance legs circularly shifted against the perps, ≥ 12 shifts); sensitivity to the touch-size filter (0 / 250 / 500 / 1 000 / 5 000 USD); direction split; per-coin table; leave-one-cluster-out and leave-top-asset-out of the primary estimate.

## What a result would and would not mean
A rejection means: *under the stated fills (taker at the touch, 150 ms, 1 000 USD at the touch, 4.5 bps/side) the measured mean net is positive in this sample.* It would not establish a tradable strategy. Known limits, fixed here so they cannot be
argued away later:
* timestamps are local **receive** times on two websocket feeds; a venue-dependent feed delay shows up as "lag" and cannot be separated from true repricing lag with this data;
* Hyperliquid publishes the book per block, so quotes are discrete in time; a quote seen at the touch may be gone when an order arrives (no queue or adverse-selection model for taker orders beyond the latency);
* touch sizes of mid-cap perps are small (a 20 000-USD order would not fit at the touch; sizes ≥ 1 000 USD are required here, nothing larger is tested);
* perps pay funding and carry a basis to spot (ignored over seconds); fee tiers are public base-tier assumptions;
* one or a few regimes: BTC volatility is recorded per run and reported.

A non-rejection or an underpowered outcome is reported as such. If H1 is rejected, the next step is a *new* pre-registered out-of-sample capture, not trading.
