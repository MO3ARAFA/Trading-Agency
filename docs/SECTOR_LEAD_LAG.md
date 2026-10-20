# Sector lead-lag: do altcoin ecosystems lag their own leaders by more than they lag BTC?

*Measurement window:* 20.0 min after a 3-min warm-up (calibration window), markouts assume **150 ms** order latency and a **1000 USD** clip for the slippage term. Paper only; every signal is *observed and marked out*, none is traded. Nothing here was pre-registered: all comparisons are exploratory.

## Summary (read this first)

**One 23-minute live paper capture (3-min warm-up + 20-min window), 111 markets on Binance Vision / Gate / Kraken / Hyperliquid, six oracles: BTC (baseline), SOL, PEPE, RENDER, plus DOGE and TAO as alternative leaders for the meme and AI ecosystems. Exploratory; nothing was pre-registered; nothing was traded.**

1. **The gaps are not 10–20 bps.** Median |gap| is 2.0–3.9 bps for every oracle (BTC baseline on this same universe: 2.7 bps, not the "1–2 bps" of the earlier BTC-only universe, because this universe is made of wider, noisier alts). The 90th percentile is 3.5–7.8 bps. Gaps ≥ 10 bps are at most 0.2 % of signals for BTC, SOL, RENDER and DOGE (1 signal each, none for SOL), 7 % for PEPE (41 signals) and TAO, and only TAO ever reached 20 bps (2 %). The gap does not scale with the leader: the median leader move at the signal was 1.8 (BTC), 2.3 (SOL), 2.5 (DOGE), 4.6 (TAO), 5.0 (RENDER) and 11.9 (PEPE) bps, yet the median gap is 2–4 bps in all cases. That is what the detection rule produces: a gap must exceed 1.5× the follower's own residual noise, so the gap size mostly reflects follower noise, not the leader's move (see "gap ÷ leader σ" in §2).
2. **Costs beat the gaps everywhere except, at best, break-even on Hyperliquid.** The median spread is as large as the median gap (spread ÷ gap 1.0–1.8; the gap exceeds the spread in only 27–48 % of signals). The net gap `|gap| − (spread + 2×fee + slippage)` is positive for **0 %** of signals for BTC, SOL, PEPE, RENDER and DOGE, and for 9 of 589 TAO signals (1.5 %, all from one event: two impulses 5 s apart, see 5). Even with **zero fees**, crossing the spread loses 2.6–7.9 bps at 5 s (§1, `net0`), so the break-even fee per side is negative for every oracle (§9). Hyperliquid is the only venue where `net0` is about zero (+0.14 to +0.28 bps for BTC, SOL, TAO; −0.3 for DOGE, RENDER) thanks to 1.5–2.4 bps spreads, and its assumed 4.5 bps taker fee (9 bps round trip) turns that into about −9 bps.
3. **Hit rate and gross edge: ordinary, and not better than BTC.** Gross markout at 5 s is +1.0 to +1.8 bps with hit rates of 49–62 % (PEPE 37 %, n = 41). On the same instruments, no sector oracle is significantly better than the BTC oracle (Δ gross: SOL +0.46 ± 0.48, DOGE +0.19 ± 0.48, PEPE +0.36 ± 1.07, RENDER −0.80 ± 0.71, TAO −0.80 ± 0.65 bps, §4). The **time-shift control (§12) says most of this gross edge is not lead-lag**: the BTC oracle fed with *unrelated* data still shows +1.22 ± 0.27 bps (n = 628) against +1.51 ± 0.41 real (difference +0.29 ± 0.49), because selecting on `fair − actual` selects mid-price noise that mean-reverts. Only SOL stands clearly above its placebo (+1.73 ± 0.70 bps, placebo n = 27); DOGE is suggestive (+0.97 ± 0.77), RENDER, TAO and PEPE are indistinguishable from it. This inflates gross, never net, so it cannot rescue the conclusion in 2.
4. **Reaction speed: mixed, and sector-dependent. The answer to "are altcoin ecosystems slower to react to their leaders than to BTC?" is "only the AI pair, and with weaker coupling".** Calibrated lags: RENDER's ecosystem trails RENDER by a median +0.60 s (80 % of members ≥ 0.1 s) versus −0.15 s against BTC (paired Δ +0.75 s, 95 % CI [0.45, 0.90], n = 40); TAO's by +0.20 s (Δ +0.25 s [0.10, 0.60]). But the correlation with those leaders is lower than with BTC (ρ 0.21 and 0.23 vs 0.37), and the markouts show the gap closing *less*, not more (capture of the gap at 5 s: RENDER 31 %, TAO 25 %; RENDER's mean gross is −1.4 bps at 30 s). SOL's and DOGE's ecosystems are indistinguishable from BTC in calibrated lag (Δ +0.05 s, p = 0.49; Δ 0.00 s, p = 0.26) while their gaps close *faster* in the markouts (half of the mean gap by ≈ 1.6 s and ≈ 1.4 s, vs ≈ 4.1 s for BTC). Signals whose calibrated lag is ≥ 0.1 s are consistently better than the rest (gross +2.2 vs +1.1 bps for BTC, +2.3 vs +1.4 for SOL, §5) but still lose to the spread (`net0` −1.2 / −0.8 bps).
5. **Large dislocations exist, are rare, and still do not pay.** 46 signals from 7 impulses reached |gap| ≥ 10 bps (§8). The best one: a −27.9 bps TAO move at t ≈ 631 s flagged 35 markets with a mean gap of 17.7 bps; five seconds later the followers had recovered only +3.4 bps on average (≈ 19 % of the gap), mean spread 5.7 bps, `net0` −2.6 bps. The one clear exception was the **same asset on another venue**: Hyperliquid TAO moved +17.8 bps (spread 0.8 bps, ≈ +6.9 bps after the assumed HL fees). A +32.4 bps PEPE move shows the same pattern (hyperliquid:kPEPE +19.2 bps, the others far less). That is the classic cross-venue lag of the leader's own asset, already the subject of Phases 4–10, not an ecosystem effect, and it is two events.

**Verdict.** In this sample the altcoin-ecosystem lead-lag hypothesis (10–20 bps gaps that outrun costs) is **not supported**: gaps are 2–4 bps, spread alone consumes them, and fees are not the binding constraint. The only structure with a visible tail is the leader's own asset on a cheaper, slower venue after a large move; it is rare (two events in 20 minutes) and is a statement about those two events, not a rate.

## How much weight this can bear

* **One quiet 20-minute window.** BTC volatility was 0.21–0.42 bps/√s throughout, and the median leader move at a signal was only 2–5 bps, PEPE aside (z ≥ 3 against a quiet baseline). A 10–20 bps gap needs a 30–50 bps sector move, which happened twice. A volatile regime could look different; this report cannot say.
* **Clusters, not signals, are the sample size.** 15–50 leader impulses with signals per oracle (PEPE 15, BTC 26, SOL 43, TAO 48, DOGE 49, RENDER 50). All ± are cluster-robust over impulses; the Δ columns treat the BTC and sector clusters as independent, which they are not exactly (overlapping in time), so read them as indicative. The lag sign tests treat the members of one leader as independent, which they are not (several venues of the same asset).
* **PEPE is a poor oracle in this run.** Its book was exactly one tick wide, 24.0 bps, for the whole run (9 k quotes in 23 min; kept because the brief asks for PEPE), so its micro-price barely moves between ticks; only 41 signals / 15 impulses came out of it, its members' median β is 0.14 and ρ 0.10. Treat the PEPE rows as uninformative and use DOGE for memecoins; TAO is a useful check on RENDER, whose book is thin (3.6 k quotes in 23 min against 38 k for SOL, 49 k for DOGE, 15 k for TAO).
* **Calibration is weakly identified in a quiet market.** The BTC hunter's median calibrated lag over all 110 markets is −0.20 s (ρ 0.35); a negative or zero lag means a member moves with, or before, its supposed leader. The lag grid is 0.1 s and starts at −0.5 s.
* **Fees are assumptions.** Lowest-tier public retail taker fees (Binance 7.5 bps with BNB, Gate 20, Kraken 40, Hyperliquid 4.5). VIP or maker-rebate tiers change `net`, not `net0`, and `net0` is already negative nearly everywhere. Slippage uses the CFO cost model at a 1 000 USD clip.
* **Selection effect.** See §12: the gross markout is partly mean reversion of quote noise. It is an upper bound on lead-lag edge.
* **The Phase-4 cross-venue arbitrage module also ran (paper) in the same process**; it is unrelated to these tables and was not analysed here.

## Reproduce

```bash
# live capture (3 min warm-up + 20 min), then the report
python -m quant_agency.sector_report --capture --duration 1200 --notes docs/SECTOR_NOTES.md
# the committed capture, regenerated from the archived rows (incl. the 12 time-shifted control replays)
python -m quant_agency.sector_report --run docs/live_runs/sector20 --placebo docs/live_runs/sector20/placebo/shift* \
       --notes docs/SECTOR_NOTES.md --out docs/SECTOR_LEAD_LAG.md
# a tape replay, and a control replay with the leaders shifted by 300 s
python -m quant_agency.run_live --replay runs/tapes/sector20.npz --out runs --tag sector_replay
python -m quant_agency.run_live --replay runs/tapes/sector20.npz --placebo-shift 300 --out runs --tag placebo300
```

The live tape (12.7 MB) is not committed (`tapes/` is git-ignored); the archived markout rows, signals, calibration tables and universe are in `docs/live_runs/sector20/`. A replay of the tape reproduced the live run's impulse counts exactly and its signal counts within a few signals (calibration runs on worker threads live and synchronously in replay): BTC 1 276 live / 1 273 replay, SOL 747 / 764, PEPE 41 / 41, RENDER 450 / 450, DOGE 509 / 510, TAO 624 / 623.

## 0. What was watched

111 markets: 33 binance, 20 gate, 30 kraken, 28 hyperliquid. Admission: Binance 24 h volume ≥ $250k and spread ≤ 40 bps (leaders always admitted); Gate 24 h volume ≥ $100k; Kraken `X/USD` pairs that are online; Hyperliquid perps (`k`-prefixed for the 1000× contracts). Quote-validation gate on every hunter: spread ≤ 40 bps, fast EW spread ≤ 3× slow EW spread, quote age ≤ 30 s, tick rate ≥ 0.05/s.

| sector oracle | leader | ecosystem members (all venues) |
|---|---|---|
| sol | SOL | 38 markets over 11 assets: BONK, JTO, JUP, ORCA, PENGU, PYTH, RAY, SOL, TRUMP, W, WIF |
| pepe | PEPE | 29 markets over 10 assets: BOME, DOGE, DOGS, FLOKI, MEME, NEIRO, PEPE, PNUT, SHIB, TURBO |
| render | RENDER | 40 markets over 12 assets: AIXBT, AR, ARKM, FET, GRT, ICP, IO, NEAR, RENDER, TAO, VIRTUAL, WLD |
| doge (variant) | DOGE | 29 markets over 10 assets: BOME, DOGE, DOGS, FLOKI, MEME, NEIRO, PEPE, PNUT, SHIB, TURBO |
| tao (variant) | TAO | 40 markets over 12 assets: AIXBT, AR, ARKM, FET, GRT, ICP, IO, NEAR, RENDER, TAO, VIRTUAL, WLD |

Left out (asset: venue → reason): **AIXBT** binance → 24h volume $0.17M < $0.25M, gate → 24h volume $2k < $100k; **AGIX** binance → not listed / not trading, gate → not listed / not tradable, kraken → not listed / offline, hyperliquid → no perp; **DOGE** kraken → not listed / offline; **JUP** gate → 24h volume $79k < $100k; **RAY** hyperliquid → no perp; **BONK** gate → 24h volume $42k < $100k; **ORCA** gate → 24h volume $70k < $100k, hyperliquid → no perp; **FLOKI** gate → 24h volume $59k < $100k; **BOME** gate → 24h volume $72k < $100k, kraken → not listed / offline; **NEIRO** gate → 24h volume $16k < $100k; **TURBO** gate → 24h volume $37k < $100k; **PNUT** gate → 24h volume $28k < $100k; **MEME** gate → 24h volume $20k < $100k; **DOGS** gate → 24h volume $3k < $100k, hyperliquid → no perp; **GRT** gate → 24h volume $34k < $100k, hyperliquid → no perp; **ARKM** hyperliquid → no perp; **IO** gate → 24h volume $59k < $100k, kraken → not listed / offline

## 1. Headline table (all venues pooled, markout horizon 5 s)

| oracle → members | impulses | signals | median \|gap\| bps | median spread bps | spread÷gap | gap > spread | net gap > 0 | gross 5 s (bps) | hit | net0 5 s | net 5 s | capture 5 s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| BTC → all sector alts | 26 | 1091 | 2.74 | 3.40 | 1.27 | 42% | 0% | +1.51 ± 0.41 | 57% | -3.54 ± 0.44 | -35.70 ± 1.62 | 52% |
| SOL → L1 / Solana ecosystem | 43 | 685 | 2.23 | 3.41 | 1.55 | 36% | 0% | +1.75 ± 0.29 | 62% | -2.97 ± 0.39 | -38.39 ± 1.86 | 72% |
| PEPE → memecoins | 15 | 41 | 3.91 | 8.49 | 1.82 | 27% | 0% | +1.70 ± 0.99 | 37% | -7.86 ± 1.11 | -45.30 ± 7.47 | 37% |
| RENDER → AI / compute | 50 | 450 | 3.04 | 3.53 | 1.19 | 43% | 0% | +1.02 ± 0.47 | 49% | -3.51 ± 0.50 | -41.72 ± 2.34 | 31% |
| DOGE → memecoins (alt leader) (variant) | 49 | 441 | 2.03 | 2.64 | 1.29 | 35% | 0% | +1.55 ± 0.26 | 58% | -2.62 ± 0.40 | -27.19 ± 1.37 | 67% |
| TAO → AI / compute (alt leader) (variant) | 48 | 589 | 2.98 | 3.47 | 1.03 | 48% | 2% | +1.04 ± 0.40 | 54% | -3.67 ± 0.47 | -37.21 ± 2.17 | 25% |

`gap` = |β·Δleader(h) − Δmid(h)| at the signal; `spread` = full quoted spread; `net gap` = |gap| − (spread + 2·fee + slippage) (CFO cost model, fee tiers in §9); `gross` = side × mid-to-mid move from t+latency to t+latency+h; `net0` = crossing the spread both ways, zero fees; `net` = net0 − venue taker fees both sides; `capture` = mean gross ÷ mean gap. ± is a cluster-robust s.e. (clusters = leader impulses).

## 2. Gap magnitude: is it 10–20 bps instead of 1–2 bps?

| oracle | median \|gap\| | mean | p90 | ≥5 bps | ≥10 bps | ≥20 bps | median leader move \|Δ\| (bps) | median fair move β·Δ | median hurdle | median gap ÷ leader σ(h) | median lag (s) | share with lag ≥ 0.1 s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| BTC → all sector alts | 2.74 | 2.91 | 4.27 | 5% | 0% | 0% | 1.79 | 2.93 | 1.00 | 7.94 | 0.00 | 36% |
| SOL → L1 / Solana ecosystem | 2.23 | 2.44 | 3.65 | 3% | 0% | 0% | 2.26 | 2.35 | 1.00 | 3.24 | 0.00 | 42% |
| PEPE → memecoins | 3.91 | 4.63 | 7.76 | 29% | 7% | 0% | 11.92 | 3.76 | 1.00 | 1.94 | -0.10 | 41% |
| RENDER → AI / compute | 3.04 | 3.29 | 4.81 | 8% | 0% | 0% | 4.98 | 2.66 | 1.00 | 2.20 | 0.40 | 73% |
| DOGE → memecoins (alt leader) (variant) | 2.03 | 2.31 | 3.47 | 3% | 0% | 0% | 2.53 | 2.23 | 1.00 | 2.74 | 0.00 | 47% |
| TAO → AI / compute (alt leader) (variant) | 2.98 | 4.17 | 6.48 | 15% | 7% | 2% | 4.62 | 2.89 | 1.00 | 2.11 | 0.00 | 42% |

`gap ÷ leader σ(h)` is the gap in units of the leader's own typical move over the impulse horizon: it separates *"the leader simply moves more in bps"* from *"the followers are further behind"*.

## 3. Markout curves (mean ± cluster s.e., bps; hit = gross > 0)

**BTC → all sector alts** — 1091 signals / 26 impulses

| h (s) | n | gross | hit | flat (=0) | gross t | net0 | net | net > 0 | capture of gap | break-even fee/side |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 1091 | +1.03 ± 0.20 | 49% | 46% | 5.3 | -4.10 ± 0.36 | -36.26 ± 1.69 | 0% | 35% | -2.05 |
| 3 | 1091 | +1.39 ± 0.33 | 53% | 34% | 4.2 | -3.65 ± 0.41 | -35.81 ± 1.63 | 0% | 48% | -1.83 |
| 5 | 1091 | +1.51 ± 0.41 | 57% | 26% | 3.7 | -3.54 ± 0.44 | -35.70 ± 1.62 | 0% | 52% | -1.77 |
| 10 | 1091 | +1.82 ± 0.48 | 58% | 21% | 3.8 | -3.26 ± 0.61 | -35.43 ± 1.60 | 1% | 63% | -1.63 |
| 30 | 1091 | +1.80 ± 0.98 | 53% | 12% | 1.8 | -3.25 ± 1.07 | -35.41 ± 1.63 | 4% | 62% | -1.63 |

Half of the mean gap is captured by ≈ 4.1 s.

**SOL → L1 / Solana ecosystem** — 685 signals / 43 impulses

| h (s) | n | gross | hit | flat (=0) | gross t | net0 | net | net > 0 | capture of gap | break-even fee/side |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 685 | +1.02 ± 0.19 | 49% | 42% | 5.5 | -3.81 ± 0.40 | -39.22 ± 1.92 | 0% | 42% | -1.90 |
| 3 | 685 | +1.63 ± 0.20 | 61% | 28% | 8.2 | -3.14 ± 0.51 | -38.56 ± 2.00 | 0% | 67% | -1.57 |
| 5 | 685 | +1.75 ± 0.29 | 62% | 24% | 6.0 | -2.97 ± 0.39 | -38.39 ± 1.86 | 0% | 72% | -1.49 |
| 10 | 685 | +1.75 ± 0.38 | 63% | 17% | 4.6 | -2.93 ± 0.47 | -38.35 ± 1.91 | 1% | 72% | -1.47 |
| 30 | 685 | +1.52 ± 0.74 | 56% | 11% | 2.1 | -3.19 ± 0.82 | -38.61 ± 1.97 | 2% | 62% | -1.59 |

Half of the mean gap is captured by ≈ 1.6 s.

**PEPE → memecoins** — 41 signals / 15 impulses

| h (s) | n | gross | hit | flat (=0) | gross t | net0 | net | net > 0 | capture of gap | break-even fee/side |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 41 | +1.79 ± 0.57 | 32% | 61% | 3.1 | -7.80 ± 1.06 | -45.24 ± 7.55 | 2% | 39% | -3.90 |
| 3 | 41 | +2.09 ± 0.84 | 37% | 49% | 2.5 | -8.07 ± 1.15 | -45.51 ± 7.36 | 2% | 45% | -4.03 |
| 5 | 41 | +1.70 ± 0.99 | 37% | 46% | 1.7 | -7.86 ± 1.11 | -45.30 ± 7.47 | 2% | 37% | -3.93 |
| 10 | 41 | +1.32 ± 1.16 | 39% | 34% | 1.1 | -8.95 ± 1.12 | -46.39 ± 7.34 | 2% | 29% | -4.48 |
| 30 | 41 | -0.69 ± 2.04 | 32% | 24% | -0.3 | -10.90 ± 1.58 | -48.34 ± 7.98 | 0% | -15% | -5.45 |

The mean gross markout never reaches half of the mean gap within 30 s.

**RENDER → AI / compute** — 450 signals / 50 impulses

| h (s) | n | gross | hit | flat (=0) | gross t | net0 | net | net > 0 | capture of gap | break-even fee/side |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 450 | +0.61 ± 0.20 | 41% | 38% | 3.1 | -3.89 ± 0.32 | -42.10 ± 2.33 | 0% | 19% | -1.95 |
| 3 | 450 | +0.72 ± 0.34 | 45% | 23% | 2.1 | -3.78 ± 0.41 | -41.99 ± 2.32 | 1% | 22% | -1.89 |
| 5 | 450 | +1.02 ± 0.47 | 49% | 19% | 2.2 | -3.51 ± 0.50 | -41.72 ± 2.34 | 1% | 31% | -1.76 |
| 10 | 450 | +0.88 ± 0.57 | 50% | 13% | 1.5 | -3.60 ± 0.61 | -41.81 ± 2.41 | 1% | 27% | -1.80 |
| 30 | 450 | -1.40 ± 1.01 | 35% | 7% | -1.4 | -5.85 ± 1.03 | -44.05 ± 2.40 | 3% | -43% | -2.92 |

The mean gross markout never reaches half of the mean gap within 30 s.

**DOGE → memecoins (alt leader) (variant)** — 441 signals / 49 impulses

| h (s) | n | gross | hit | flat (=0) | gross t | net0 | net | net > 0 | capture of gap | break-even fee/side |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 441 | +1.12 ± 0.10 | 51% | 45% | 11.8 | -3.18 ± 0.33 | -27.76 ± 1.37 | 0% | 48% | -1.59 |
| 3 | 441 | +1.31 ± 0.18 | 54% | 37% | 7.2 | -2.85 ± 0.35 | -27.42 ± 1.36 | 0% | 57% | -1.42 |
| 5 | 441 | +1.55 ± 0.26 | 58% | 28% | 5.9 | -2.62 ± 0.40 | -27.19 ± 1.37 | 0% | 67% | -1.31 |
| 10 | 441 | +1.70 ± 0.36 | 59% | 24% | 4.8 | -2.50 ± 0.50 | -27.07 ± 1.42 | 0% | 74% | -1.25 |
| 30 | 441 | +0.99 ± 0.73 | 51% | 13% | 1.4 | -3.26 ± 0.80 | -27.83 ± 1.50 | 2% | 43% | -1.63 |

Half of the mean gap is captured by ≈ 1.4 s.

**TAO → AI / compute (alt leader) (variant)** — 589 signals / 48 impulses

| h (s) | n | gross | hit | flat (=0) | gross t | net0 | net | net > 0 | capture of gap | break-even fee/side |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 589 | +1.22 ± 0.17 | 54% | 36% | 7.3 | -3.55 ± 0.35 | -37.09 ± 2.17 | 0% | 29% | -1.77 |
| 3 | 589 | +1.41 ± 0.36 | 57% | 26% | 3.9 | -3.29 ± 0.47 | -36.83 ± 2.22 | 1% | 34% | -1.65 |
| 5 | 589 | +1.04 ± 0.40 | 54% | 19% | 2.6 | -3.67 ± 0.47 | -37.21 ± 2.17 | 1% | 25% | -1.84 |
| 10 | 589 | +0.98 ± 0.49 | 48% | 15% | 2.0 | -3.77 ± 0.58 | -37.31 ± 2.23 | 2% | 24% | -1.88 |
| 30 | 589 | +0.60 ± 0.99 | 50% | 8% | 0.6 | -4.11 ± 1.01 | -37.65 ± 2.13 | 4% | 14% | -2.05 |

The mean gross markout never reaches half of the mean gap within 30 s.

## 4. Same assets, two oracles: BTC baseline vs the sector leader (h = 5 s)

BTC-hunter rows restricted to the sector's own assets (leader's Binance market excluded, as in the sector hunter), so both rows trade the same instruments.

| sector | oracle | signals | median \|gap\| | median spread | gross 5 s | hit | net0 5 s | net 5 s | lag med (s) | Δ gross vs BTC (±, approx.) |
|---|---|---|---|---|---|---|---|---|---|---|
| sol | BTC | 406 | 2.60 | 3.40 | +1.29 ± 0.39 | 54% | -3.26 ± 0.48 | -37.03 ± 2.15 | 0.00 |  |
| sol | SOL | 685 | 2.23 | 3.41 | +1.75 ± 0.29 | 62% | -2.97 ± 0.39 | -38.39 ± 1.86 | 0.00 | +0.46 ± 0.48 |
| pepe | BTC | 248 | 2.37 | 2.86 | +1.35 ± 0.41 | 54% | -4.58 ± 0.85 | -30.88 ± 3.30 | -0.10 |  |
| pepe | PEPE | 41 | 3.91 | 8.49 | +1.70 ± 0.99 | 37% | -7.86 ± 1.11 | -45.30 ± 7.47 | -0.10 | +0.36 ± 1.07 |
| render | BTC | 412 | 3.03 | 3.54 | +1.82 ± 0.53 | 63% | -3.21 ± 0.55 | -38.35 ± 2.91 | 0.00 |  |
| render | RENDER | 450 | 3.04 | 3.53 | +1.02 ± 0.47 | 49% | -3.51 ± 0.50 | -41.72 ± 2.34 | 0.40 | -0.80 ± 0.71 |
| doge | BTC | 240 | 2.45 | 2.86 | +1.36 ± 0.41 | 52% | -4.91 ± 0.85 | -31.59 ± 3.31 | -0.10 |  |
| doge | DOGE | 441 | 2.03 | 2.64 | +1.55 ± 0.26 | 58% | -2.62 ± 0.40 | -27.19 ± 1.37 | 0.00 | +0.19 ± 0.48 |
| tao | BTC | 413 | 3.04 | 3.54 | +1.84 ± 0.52 | 63% | -3.23 ± 0.53 | -38.32 ± 2.81 | 0.00 |  |
| tao | TAO | 589 | 2.98 | 3.47 | +1.04 ± 0.40 | 54% | -3.67 ± 0.47 | -37.21 ± 2.17 | 0.00 | -0.80 ± 0.65 |

Δ gross = sector-oracle gross − BTC-oracle gross on the same instruments; the s.e. combines the two cluster s.e.s as if independent, which they are not exactly (impulses of different leaders overlap in time), so read it as indicative.

## 5. Reaction speed: calibrated lead-lag per oracle (Hayashi–Yoshida peak lag, 180 s windows)

| oracle | markets | median lag (s) | share lag ≥ 0.1 s | median ρ (3 s OLS) | median decay (s) | median β | same markets vs BTC: lag / ρ / decay | paired Δlag (sector−BTC), 95 % CI, sign test (members of one leader are not independent) | paired Δρ |
|---|---|---|---|---|---|---|---|---|---|
| SOL → L1 / Solana ecosystem | 38 | -0.10 | 37% | 0.38 | 0.20 | 0.84 | -0.10 / 0.35 / 0.15 | +0.05 [-0.10, 0.20], p=0.487 (n=38) | +0.02 [-0.02, 0.08] |
| PEPE → memecoins | 29 | -0.50 | 34% | 0.10 | 0.00 | 0.14 | -0.30 / 0.34 / 0.10 | +0.00 [-0.10, 0.00], p=0.815 (n=29) | -0.16 [-0.26, 0.00] |
| RENDER → AI / compute | 40 | 0.60 | 80% | 0.21 | 0.30 | 0.31 | -0.15 / 0.37 / 0.20 | +0.75 [0.45, 0.90], p<0.001 (n=40) | -0.12 [-0.20, -0.09] |
| DOGE → memecoins (alt leader) (variant) | 29 | -0.20 | 28% | 0.33 | 0.10 | 0.58 | -0.30 / 0.31 / 0.10 | +0.00 [0.00, 0.30], p=0.263 (n=29) | +0.02 [-0.00, 0.07] |
| TAO → AI / compute (alt leader) (variant) | 40 | 0.20 | 57% | 0.23 | 0.30 | 0.39 | -0.20 / 0.37 / 0.20 | +0.25 [0.10, 0.60], p=0.004 (n=40) | -0.08 [-0.19, -0.03] |

BTC hunter over all 110 calibrated markets: median lag -0.20 s, median ρ 0.35.

A *positive* lag means the member moves after the oracle; a lag of 0 (or the −0.5 s grid edge) means the member is contemporaneous with – or leads – the supposed leader, in which case a 'gap' is a transient divergence rather than a lead-lag opportunity. Rows split by that condition:

| oracle | lag ≥ 0.1 s: signals | gross 5 s | net0 5 s | lag < 0.1 s: signals | gross 5 s | net0 5 s |
|---|---|---|---|---|---|---|
| BTC → all sector alts | 396 | +2.20 ± 0.47 | -1.23 ± 0.53 | 695 | +1.12 ± 0.45 | -4.85 ± 0.56 |
| SOL → L1 / Solana ecosystem | 289 | +2.29 ± 0.32 | -0.84 ± 0.46 | 396 | +1.36 ± 0.30 | -4.53 ± 0.40 |
| PEPE → memecoins | 17 | +3.42 ± 1.96 | -7.25 ± 2.31 | 24 | +0.49 ± 0.68 | -8.30 ± 1.24 |
| RENDER → AI / compute | 329 | +1.14 ± 0.49 | -2.74 ± 0.51 | 121 | +0.70 ± 0.49 | -5.60 ± 0.58 |
| DOGE → memecoins (alt leader) (variant) | 207 | +2.28 ± 0.27 | -0.49 ± 0.30 | 234 | +0.90 ± 0.35 | -4.49 ± 0.51 |
| TAO → AI / compute (alt leader) (variant) | 245 | +1.87 ± 0.44 | -0.77 ± 0.58 | 344 | +0.45 ± 0.41 | -5.74 ± 0.44 |

## 6. By venue (h = 5 s)

| oracle | venue | signals | median gap | median spread | gross | hit | net0 | net (venue fees) | fee/side assumed |
|---|---|---|---|---|---|---|---|---|---|
| BTC | binance | 267 | 2.75 | 3.77 | +0.97 ± 0.49 | 40% | -4.26 ± 0.55 | -19.26 ± 0.55 | 7.5 |
| BTC | gate | 223 | 2.84 | 5.02 | +0.74 ± 0.40 | 50% | -4.68 ± 0.49 | -44.68 ± 0.49 | 20.0 |
| BTC | hyperliquid | 365 | 2.61 | 1.78 | +2.62 ± 0.41 | 79% | +0.14 ± 0.54 | -8.86 ± 0.54 | 4.5 |
| BTC | kraken | 236 | 2.90 | 5.79 | +1.13 ± 0.57 | 49% | -7.33 ± 0.89 | -87.33 ± 0.89 | 40.0 |
| sol | binance | 114 | 2.54 | 3.40 | +1.15 ± 0.40 | 45% | -3.31 ± 0.55 | -18.31 ± 0.55 | 7.5 |
| sol | gate | 138 | 2.13 | 6.54 | +1.36 ± 0.32 | 59% | -4.87 ± 0.39 | -44.87 ± 0.39 | 20.0 |
| sol | hyperliquid | 248 | 1.98 | 1.51 | +2.58 ± 0.32 | 78% | +0.28 ± 0.38 | -8.72 ± 0.38 | 4.5 |
| sol | kraken | 185 | 2.52 | 5.68 | +1.31 ± 0.34 | 55% | -5.71 ± 0.47 | -85.71 ± 0.47 | 40.0 |
| pepe | binance | 8 | 5.58 | 11.98 | -0.31 ± 0.21 | 0% | -11.49 ± 2.14 | -26.49 ± 2.14 | 7.5 |
| pepe | gate | 4 | 3.65 | 3.20 | -3.20 ± 2.28 | 25% | -6.69 ± 2.15 | -46.69 ± 2.15 | 20.0 |
| pepe | hyperliquid | 15 | 4.32 | 11.98 | +4.90 ± 1.89 | 53% | -5.24 ± 2.61 | -14.24 ± 2.61 | 4.5 |
| pepe | kraken | 14 | 2.80 | 8.49 | +0.83 ± 0.97 | 43% | -8.94 ± 1.38 | -88.94 ± 1.38 | 40.0 |
| render | binance | 69 | 3.03 | 3.54 | +1.15 ± 0.69 | 41% | -2.92 ± 0.80 | -17.92 ± 0.80 | 7.5 |
| render | gate | 90 | 3.11 | 6.08 | +0.36 ± 0.52 | 50% | -6.06 ± 0.58 | -46.06 ± 0.58 | 20.0 |
| render | hyperliquid | 151 | 2.93 | 1.59 | +1.39 ± 0.60 | 60% | -0.30 ± 0.62 | -9.30 ± 0.62 | 4.5 |
| render | kraken | 140 | 3.04 | 5.57 | +0.98 ± 0.55 | 41% | -5.62 ± 0.55 | -85.62 ± 0.55 | 40.0 |
| doge | binance | 100 | 2.01 | 3.36 | +0.84 ± 0.31 | 38% | -4.34 ± 0.78 | -19.34 ± 0.78 | 7.5 |
| doge | gate | 51 | 1.82 | 2.39 | +0.39 ± 0.31 | 41% | -2.15 ± 0.34 | -42.15 ± 0.34 | 20.0 |
| doge | hyperliquid | 224 | 2.15 | 2.35 | +2.32 ± 0.28 | 75% | -0.32 ± 0.29 | -9.32 ± 0.29 | 4.5 |
| doge | kraken | 66 | 2.13 | 5.42 | +0.89 ± 0.43 | 41% | -8.15 ± 0.90 | -88.15 ± 0.90 | 40.0 |
| tao | binance | 103 | 2.92 | 4.22 | +0.54 ± 0.51 | 37% | -3.82 ± 0.51 | -18.82 ± 0.51 | 7.5 |
| tao | gate | 128 | 2.70 | 5.58 | +0.15 ± 0.43 | 42% | -6.08 ± 0.52 | -46.08 ± 0.52 | 20.0 |
| tao | hyperliquid | 219 | 3.05 | 1.51 | +2.03 ± 0.44 | 74% | +0.14 ± 0.49 | -8.86 ± 0.49 | 4.5 |
| tao | kraken | 139 | 3.32 | 5.61 | +0.68 ± 0.55 | 46% | -7.35 ± 0.67 | -87.35 ± 0.67 | 40.0 |

## 7. The leader's own asset on other venues vs the rest of the ecosystem (h = 5 s)

Same-asset copies (e.g. SOL on Gate / Kraken / Hyperliquid) are the classic cross-venue lag; the other assets are the *ecosystem* lead-lag the brief is about.

| oracle | group | signals | median gap | median spread | gross | hit | net0 | net |
|---|---|---|---|---|---|---|---|---|
| sol | SOL on other venues | 69 | 1.55 | 0.96 | +1.46 ± 0.29 | 68% | +0.40 ± 0.30 | -35.73 ± 3.42 |
| sol | other ecosystem assets | 616 | 2.32 | 3.99 | +1.78 ± 0.30 | 62% | -3.35 ± 0.40 | -38.69 ± 1.89 |
| pepe | PEPE on other venues | 10 | 4.06 | 2.40 | +2.76 ± 2.51 | 50% | -0.72 ± 2.56 | -44.32 ± 14.47 |
| pepe | other ecosystem assets | 31 | 3.87 | 11.98 | +1.37 ± 0.87 | 32% | -10.17 ± 1.07 | -45.62 ± 7.95 |
| render | RENDER on other venues | 81 | 3.33 | 5.56 | +1.59 ± 0.58 | 48% | -3.27 ± 0.70 | -46.38 ± 3.56 |
| render | other ecosystem assets | 369 | 2.91 | 3.53 | +0.90 ± 0.50 | 50% | -3.57 ± 0.53 | -40.70 ± 2.79 |
| doge | DOGE on other venues | 56 | 1.71 | 0.63 | +1.28 ± 0.25 | 70% | +0.53 ± 0.27 | -17.32 ± 1.55 |
| doge | other ecosystem assets | 385 | 2.16 | 2.86 | +1.59 ± 0.27 | 56% | -3.07 ± 0.44 | -28.62 ± 1.56 |
| tao | TAO on other venues | 63 | 2.74 | 1.51 | +1.47 ± 0.56 | 62% | -1.10 ± 0.60 | -38.55 ± 3.70 |
| tao | other ecosystem assets | 526 | 2.99 | 3.70 | +0.99 ± 0.41 | 53% | -3.98 ± 0.48 | -37.05 ± 2.19 |

## 8. Tail events: signals with |gap| ≥ 10 bps

46 signals from 7 leader impulses (of 231 impulses that produced any signal) reached the 10–20 bps range the brief asked about.

| t (s into window) | oracle | leader move (bps) | signals ≥ thr | mean gap | mean spread | gross 5 s | net0 5 s | best market (gross) | venues |
|---|---|---|---|---|---|---|---|---|---|
| 212 | doge | -3.0 | 1 | 16.7 | 23.7 | +0.00 | -23.70 | kraken:PNUT/USD (-0.0) | kraken |
| 497 | tao | -3.7 | 2 | 18.6 | 14.0 | -4.94 | -15.28 | IOUSDT (+3.2) | binance, hyperliquid |
| 631 | tao | -27.9 | 35 | 17.7 | 5.7 | +3.36 | -2.55 | hyperliquid:TAO (+17.8) | binance, gate, hyperliquid, kraken |
| 636 | tao | -17.3 | 3 | 12.7 | 9.4 | -0.18 | -9.37 | ARKMUSDT (-0.0) | binance, hyperliquid, kraken |
| 934 | render | +19.5 | 1 | 10.9 | 11.1 | -1.86 | -11.14 | kraken:WLD/USD (-1.9) | kraken |
| 942 | pepe | +32.4 | 3 | 11.2 | 8.4 | +5.99 | -2.79 | hyperliquid:kPEPE (+19.2) | binance, gate, hyperliquid |
| 961 | BTC | -4.6 | 1 | 11.7 | 20.4 | -10.20 | -40.90 | MEMEUSDT (-10.2) | binance |

Pooled tail signals: gross 5 s +2.46 ± 2.01, net0 -5.05 ± 5.11, net -41.74 ± 11.69 (clusters = 7; treat as anecdote, not a rate).

| venue (tail signals only) | signals | mean gap | mean spread | gross 5 s | net0 5 s | net 5 s |
|---|---|---|---|---|---|---|
| binance | 12 | 17.14 | 7.02 | +1.21 ± 2.43 | -7.53 ± 7.04 | -22.53 ± 7.04 |
| gate | 9 | 16.62 | 5.30 | +2.78 ± 2.24 | -3.34 ± 0.81 | -43.34 ± 0.81 |
| hyperliquid | 12 | 16.45 | 1.76 | +3.59 ± 6.66 | +0.82 ± 8.49 | -8.18 ± 8.49 |
| kraken | 13 | 16.59 | 8.48 | +2.35 ± 1.06 | -9.35 ± 3.64 | -89.35 ± 3.64 |

## 9. Fees: how much would have to change?

Taker fee per side (public lowest-tier retail schedules; **assumptions**, not verified for any account): Binance 7.5 bps, Gate 20, Kraken 40, Hyperliquid 4.5. Mean net0 (spread-crossing, before fees) at 5 s and the same number after a *uniform* per-side fee:

| oracle | net0 5 s | −2×0 | −2×2 | −2×4.5 | −2×7.5 | break-even fee per side |
|---|---|---|---|---|---|---|
| BTC → all sector alts | -3.54 | -3.54 | -7.54 | -12.54 | -18.54 | -1.77 |
| SOL → L1 / Solana ecosystem | -2.97 | -2.97 | -6.97 | -11.97 | -17.97 | -1.49 |
| PEPE → memecoins | -7.86 | -7.86 | -11.86 | -16.86 | -22.86 | -3.93 |
| RENDER → AI / compute | -3.51 | -3.51 | -7.51 | -12.51 | -18.51 | -1.76 |
| DOGE → memecoins (alt leader) (variant) | -2.62 | -2.62 | -6.62 | -11.62 | -17.62 | -1.31 |
| TAO → AI / compute (alt leader) (variant) | -3.67 | -3.67 | -7.67 | -12.67 | -18.67 | -1.84 |

## 10. Latency sensitivity (mean gross / net0 at h = 5 s)

| oracle | 0.0 s | 0.15 s | 0.5 s |
|---|---|---|---|
| BTC | +2.17 / -2.85 | +1.51 / -3.54 | +0.97 / -4.11 |
| sol | +2.47 / -2.19 | +1.75 / -2.97 | +1.28 / -3.45 |
| pepe | +3.58 / -6.12 | +1.70 / -7.86 | +0.98 / -8.67 |
| render | +1.49 / -3.00 | +1.02 / -3.51 | +0.88 / -3.66 |
| doge | +1.92 / -2.21 | +1.55 / -2.62 | +1.19 / -3.09 |
| tao | +1.48 / -3.16 | +1.04 / -3.67 | +0.48 / -4.23 |

## 11. Where the gaps are (sector oracles, h = 5 s, assets with ≥ 3 signals)

**sol** (SOL oracle)

| asset | signals | mean gap | mean spread | gross | net |
|---|---|---|---|---|---|
| PENGU | 97 | 1.96 | 2.58 | +1.55 | -36.42 |
| JUP | 78 | 1.81 | 4.40 | +1.62 | -34.42 |
| TRUMP | 74 | 2.06 | 3.08 | +1.95 | -29.06 |
| WIF | 72 | 2.33 | 4.57 | +1.99 | -34.59 |
| SOL | 69 | 1.59 | 1.01 | +1.46 | -35.73 |
| PYTH | 61 | 3.18 | 7.92 | +2.15 | -41.89 |
| JTO | 61 | 3.42 | 5.55 | +2.18 | -37.66 |
| RAY | 58 | 2.75 | 6.07 | +1.69 | -53.00 |
| BONK | 42 | 2.10 | 3.90 | +1.79 | -40.01 |
| ORCA | 38 | 3.56 | 8.52 | +1.94 | -54.37 |
| W | 35 | 3.51 | 9.14 | +0.66 | -37.17 |

**pepe** (PEPE oracle)

| asset | signals | mean gap | mean spread | gross | net |
|---|---|---|---|---|---|
| FLOKI | 12 | 3.26 | 7.33 | +1.70 | -57.40 |
| PEPE | 10 | 5.89 | 2.88 | +2.76 | -44.32 |
| BOME | 7 | 4.92 | 17.47 | +3.23 | -22.78 |
| TURBO | 5 | 5.22 | 11.99 | +0.00 | -24.59 |
| DOGS | 3 | 2.88 | 14.08 | +0.44 | -94.08 |

**render** (RENDER oracle)

| asset | signals | mean gap | mean spread | gross | net |
|---|---|---|---|---|---|
| RENDER | 81 | 3.47 | 4.95 | +1.59 | -46.38 |
| VIRTUAL | 69 | 2.40 | 2.70 | +0.71 | -38.03 |
| ICP | 60 | 2.99 | 3.92 | +0.94 | -44.84 |
| AR | 58 | 3.42 | 7.06 | +1.32 | -37.61 |
| TAO | 42 | 2.74 | 2.31 | +0.45 | -35.70 |
| WLD | 37 | 4.46 | 4.66 | +1.47 | -42.00 |
| NEAR | 33 | 3.93 | 1.93 | +1.09 | -34.67 |
| GRT | 27 | 2.87 | 6.74 | +0.63 | -64.60 |
| FET | 22 | 3.68 | 4.45 | +0.58 | -34.77 |
| ARKM | 13 | 4.91 | 12.08 | +1.11 | -55.01 |
| AIXBT | 8 | 2.99 | 2.90 | -0.63 | -12.49 |

**doge** (DOGE oracle)

| asset | signals | mean gap | mean spread | gross | net |
|---|---|---|---|---|---|
| SHIB | 82 | 1.61 | 3.33 | +1.11 | -39.31 |
| FLOKI | 73 | 2.05 | 4.28 | +1.88 | -24.15 |
| NEIRO | 59 | 2.22 | 2.59 | +1.47 | -12.20 |
| PEPE | 59 | 3.06 | 4.15 | +1.85 | -34.10 |
| DOGE | 56 | 1.71 | 0.69 | +1.28 | -17.32 |
| PNUT | 38 | 3.57 | 5.29 | +2.79 | -19.40 |
| DOGS | 30 | 2.31 | 7.14 | +0.97 | -41.02 |
| BOME | 24 | 2.26 | 3.98 | +1.36 | -17.82 |
| TURBO | 18 | 3.44 | 12.70 | +1.00 | -46.36 |

**tao** (TAO oracle)

| asset | signals | mean gap | mean spread | gross | net |
|---|---|---|---|---|---|
| VIRTUAL | 78 | 2.72 | 2.53 | +0.96 | -33.16 |
| FET | 73 | 4.15 | 5.11 | +0.85 | -36.50 |
| AR | 71 | 3.96 | 7.21 | +0.95 | -41.19 |
| TAO | 63 | 3.67 | 2.22 | +1.47 | -38.55 |
| WLD | 62 | 5.57 | 3.15 | +1.64 | -34.68 |
| RENDER | 61 | 3.77 | 4.75 | +0.92 | -35.80 |
| ICP | 59 | 3.77 | 3.81 | +1.05 | -32.60 |
| NEAR | 45 | 5.00 | 1.86 | +0.51 | -32.70 |
| GRT | 30 | 3.89 | 6.21 | +0.78 | -50.98 |
| ARKM | 26 | 6.61 | 12.22 | +0.85 | -57.66 |
| AIXBT | 19 | 4.27 | 7.94 | +2.08 | -26.48 |

## 12. Control: leaders time-shifted against the members

The same tape was replayed 12 times with every leader's quote stream (BTC included) circularly shifted by 100, 1000, 1100, 1200, 200, 300, 400, 500, 600, 700, 800, 900 s while the members kept their clock, so the leader-to-member relationship is destroyed but each stream keeps its own statistics. Whatever signals survive are produced by noise and by whatever calibration the hunters could still find.

| oracle | real signals | placebo signals (mean per replay) | ratio | real gross 5 s | placebo gross 5 s | real − placebo (±, approx.) | real hit | placebo hit | placebo net0 5 s |
|---|---|---|---|---|---|---|---|---|---|
| BTC → all sector alts | 1091 | 52.3 | 0.048 | +1.51 ± 0.41 | +1.22 ± 0.27 (n=628) | +0.29 ± 0.49 | 57% | 45% | -3.48 ± 0.37 |
| SOL → L1 / Solana ecosystem | 685 | 2.2 | 0.003 | +1.75 ± 0.29 | +0.02 ± 0.64 (n=27) | +1.73 ± 0.70 | 62% | 44% | -5.32 ± 1.30 |
| PEPE → memecoins | 41 | 3.7 | 0.089 | +1.70 ± 0.99 | +0.61 ± 0.29 (n=44) | +1.09 ± 1.03 | 37% | 39% | -6.69 ± 1.42 |
| RENDER → AI / compute | 450 | 2.2 | 0.005 | +1.02 ± 0.47 | +1.27 ± 0.63 (n=26) | -0.25 ± 0.78 | 49% | 35% | -3.35 ± 0.52 |
| DOGE → memecoins (alt leader) (variant) | 441 | 2.9 | 0.007 | +1.55 ± 0.26 | +0.57 ± 0.72 (n=35) | +0.97 ± 0.77 | 58% | 17% | -14.47 ± 1.84 |
| TAO → AI / compute (alt leader) (variant) | 589 | 8.9 | 0.015 | +1.04 ± 0.40 | +0.86 ± 0.32 (n=107) | +0.19 ± 0.51 | 54% | 36% | -5.54 ± 0.44 |

A collapse of the signal count says the hunters' signals depend on a real leader→member relationship rather than on generic quote noise. It does **not** prove the surviving gross markout is lead-lag: selecting on `fair − actual` also picks up mid-price noise that mean-reverts, which inflates gross (never net) for every oracle alike.

## 13. Run diagnostics

| hunter | members | calibrated | impulses | scans | signals | gap hurdle rule |
|---|---|---|---|---|---|---|
| BTC | 110 | 110 | 37 | 48810 | 1276 | flat 1 bp |
| sol | 38 | 38 | 49 | 16244 | 747 | max(1 bp, 0.5·β·σ_leader(h)) |
| pepe | 29 | 29 | 55 | 5583 | 41 | max(1 bp, 0.5·β·σ_leader(h)) |
| render | 40 | 40 | 57 | 2043 | 450 | max(1 bp, 0.5·β·σ_leader(h)) |
| doge | 29 | 29 | 60 | 21341 | 509 | max(1 bp, 0.5·β·σ_leader(h)) |
| tao | 40 | 40 | 56 | 9203 | 624 | max(1 bp, 0.5·β·σ_leader(h)) |
