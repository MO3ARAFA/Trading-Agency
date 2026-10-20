# Phase 12 — analysis plan (written before the hourly premium test is run)

*Everything in Phase 12 is exploratory except the single test frozen below. The plan is committed and pushed before that test is evaluated; `docs/PHASE12_PLAN.json` holds the SHA-256 of the code and of the cached data it will run on.*

## Context and what was already looked at (so nothing is hidden)
* **Funding (90 days, 51 liquid coins, 110 160 coin-hours):** extremes are essentially absent (≥ 3 bps/h positive: 0.02 % of coin-hours; ≥ 5 bps/h: never). Looked at in full; no test claimed.
* **Basis reversion at 5 / 15 / 30 min (3.4 days of 1-minute bars, train/test split, 9 threshold × horizon cells):** the *hedged* spread (short the rich leg / long the cheap one) earns ≈ 0 (−5.0 to +2.0 bps against ≈ 18 bps of cost); the unhedged perp leg is dominated by direction. The cell chosen on the train split tests at +11.7 ± 18.0 bps (t = 0.65). Looked at in full.
* **Post hoc, in the same 3.4-day window (12 more cells, horizons 1–4 h):** after removing the equal-weight market move, the *unhedged perp leg* of "short the rich perp / long the cheap perp" earns +41 ± 21 bps at 4 h (≥ 15 bps) and +160 ± 48 bps at 4 h (≥ 30 bps, 46 events). The hedged spread does not (+3.7 to +6.1 bps). This is a cross-sectional directional effect ("a rich perp underperforms the market over the next hours"), **found by searching**, so it is a hypothesis and not a result.

## The one pre-declared test (H1) — out of sample, 25× more data
* **Data:** hourly bars (Hyperliquid candles + Binance Vision klines), 62 matched pairs as of today's universe (BTC, ETH excluded), 2 400 bars (≈ 100 days). **The last 84 bars (3.5 days, the discovery window) are never used.** Survivorship: the universe is today's top mid-caps by Hyperliquid volume.
* **Signal:** hourly basis `ln(HL close / Binance close)` (bars with < 2 trades on either venue are dropped), deviation from the trailing 24-bar median (excluding the latest bar), trigger `|dev| ≥ 30 bps`, one event per coin per 4 bars.
* **Position:** short the perp if it is rich (dev > 0), long if cheap; enter at the close of the trigger bar, exit 4 bars later.
* **Outcome:** the perp leg's return minus `side × equal-weight spot return` of the 60 coins over the same interval (market-neutral), **minus 6 bps** (3 bps maker round trip on the perp + 3 bps for a market hedge).
* **Test:** one-sided cluster-robust t (clusters = 4-hour blocks), Student-t with clusters − 1 df, α = 0.05; **≥ 30 clusters** required, otherwise "underpowered, no decision". H0: mean net ≤ 0.
* **Secondary (descriptive, no claims):** threshold 15 bps; horizons 1 / 2 / 24 h; raw (unadjusted) perp; the hedged spread; share of events that are rich-perp.
* **If H1 is rejected** the next step is a *forward* paper capture with the same rule, not trading; with a real 100 USD account the expected dollar amounts are small (see below) and per-trade noise is large.

## Real-money constraints used in every simulation (100 USD account)
Notional 20 USD per position (Hyperliquid minimum order ≈ 10 USD), ≤ 4 concurrent positions, ≤ 2× leverage, stop at −10 % (`Bankroll`). Fees are public base-tier assumptions: Hyperliquid maker 1.5 bps / taker 4.5 bps, Binance spot 7.5 bps. This repository contains no code that sends orders and reads no credentials; every number here is a measurement or a paper simulation.

## Track 1 (Polymarket) — plan written before the 60-minute capture (all descriptive; no confirmatory claim)
* **Universe:** Gamma `/events` (≈ 2 100 events, ≈ 41 000 markets). *Slow* = > 24 h to expiry, 24 h volume ≥ 500 USD, cached spread 3–8 ¢, mid 5–95 ¢; the 80 most active (≤ 3 per event). *Control* = the BTC up/down markets of the Phase 5–6 population (8). *Groups* = 40 NegRisk events (3–20 live legs): those whose cached sums are closest to a locked margin, then the busiest.
* **Structural scan (live CLOB books, net of the taker fee schedule, ≥ 5 shares on the thinnest leg):** exclusive sell-set (buy NO on every leg: Σ best bid YES > 1), exhaustive buy-set (Σ best ask YES < 1, only if Σ mids is within 0.05 of 1 and every outcome is live), binary YES/NO mirror check. Reported: counts, margin per set in USD and as a return on capital, duration, depth, **days until the capital is released**, annualised return.
* **Maker evaluation:** virtual post-only bids and asks of the minimum size (5 shares), policies *join* and *penny*, fill models *strict* (lower bound) / *trades* (primary) / *depletion* (upper bound, shown only as a bound), TTL 300 s, markouts at +60 s / +300 s against later quotes, in dollars at 5 shares. Slow universe vs control, same session. Trade-print burstiness (Fano factor of per-minute counts).
* **Set-maker:** join-bids on every leg of small exhaustive groups; completion rate, locked margin when complete, mark-to-mid result of partial sets (legging risk).
* **Fills are simulated, not observed.** The strict / trades / depletion spread is the honest uncertainty; a real queue position and cancellations are not visible in public data.
