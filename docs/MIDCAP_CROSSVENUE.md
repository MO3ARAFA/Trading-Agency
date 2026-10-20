# Same-asset cross-venue tail lag: Binance Vision spot → Hyperliquid perp (1-to-1, mid-caps)

*Capture:* 2.00 h of measurement after a 60 s warm-up per run, 50 matched mid-cap pairs + 2 baseline pairs (BTC, ETH); runs xvr_s1, xvr_s2. Paper only; every signal is observed and marked out, none is traded. Entry = taker on the perp at the touch `latency` after the Binance tick, exit = taker at the touch.

## Summary (read this first)

**The pre-registered test says no. After 2 hours of live capture across 50 matched mid-cap pairs, signals that clear the full cost hurdle have a mean net of −8.46 ± 1.63 bps (27 signals, 26 clusters, t = −5.17; bootstrap 95 % CI [−11.7, −5.3]): H0 (net ≤ 0) is not rejected, and the estimate is significantly *negative*.** The TAO → Hyperliquid event (+17.8 bps gross, ≈ +6.9 net) that motivated the test was the favourable tail of a distribution whose centre is a loss; it was an observation selected after the fact, and it did not generalise.

1. **Dislocations are not rare in this universe, and they are not the problem.** Same-asset gaps ≥ 10 bps occurred 196 times per hour (3.9 per coin-hour over 50 mid-caps), ≥ 15 bps 71 per hour, and gaps clearing the full cost hurdle 55 per hour (1.1 per coin-hour). BTC and ETH, run through the identical scanner as the baseline, produced 4 signals ≥ 4 bps and **none ≥ 8 bps** in two hours, which is consistent with them being tightly arbitraged, but it is also what a quiet market does to *any* coin (BTC volatility was 0.20–0.36 bps/√s), so this run cannot tell the two explanations apart.
2. **The lag exists, is fast, and is small.** Against the time-shifted control (Binance legs shifted against the perps, 24 replays), gross markouts at ≥ 8 bps are +3.91 ± 0.34 bps real vs −0.04 ± 0.05 placebo (difference +3.95 ± 0.34): unlike the sector run, the control here is clean, so this is a genuine same-asset repricing effect. But it is a sub-second one: gross at ≥ 8 bps is +4.78 (0 ms), +3.91 (150 ms), +1.61 (500 ms) and +0.02 bps (1 000 ms). By one second the perp has done whatever it was going to do.
3. **It closes about a third of the gap, and then stops.** For ≥ 8 bps gaps (mean 12.1 bps) the perp recovers 33 % by 1 s, 30 % by 3 s, 32 % by 5 s, 33 % by 10 s and 36 % by 30 s. A lagging price keeps closing with the horizon; this one does not, so roughly two thirds of the measured "gap" is a *persistent* perp-vs-spot divergence, not a lag. I tested the obvious explanation (the Binance leg's mid jumping on a wide, thin book) and it **does not hold**: closure is 32 % on Binance books ≤ 2 bps wide (n = 96), 26 % on 2–5 bps and 34 % above 5 bps (§7, exploratory). What the persistent part is (perp-specific flow, basis or funding steps, mark/oracle dynamics, thin-book mid noise on the perp leg) was not tested.
4. **Costs finish it.** At 150 ms the full-cost-cleared tier earns +6.76 ± 1.10 gross, +2.99 after crossing the perp spread (`net0`), and −6.01 ± 1.11 after 9 bps of taker fees; at 0 ms −3.67 ± 1.20; at 500 ms −10.78. The only positive cells in the whole latency × tier × fee table are the *maker/maker 3 bps* tier at 0 ms for the full-cost tier (+2.33 ± 1.20), which assumes zero latency **and** resting orders that fill at crossing prices with no fill risk — an internally inconsistent combination, not a result. Taker-in / maker-out (6 bps) is −0.67 ± 1.20 at best (0 ms, full cost; −3.01 at 150 ms), again assuming the maker exit fills.
5. **The big gaps live in books you cannot trade.** For signals ≥ 10 bps the median entry-side touch is **251 USD** (9 % show ≥ 1 000 USD, 3 % ≥ 5 000 USD) and the median perp spread 4.3 bps. ALT alone is 38 % of all ≥ 8 bps signals (median touch 84 USD, perp spread 5.8 bps), then DOT, COMP, ZRO, TIA, CHIP, NIL. Filtering to deeper touches does not rescue it: ≥ 10 bps with ≥ 5 000 USD at the touch is −8.37 ± 2.11 net (n = 13), the primary subset itself (≥ 1 000 USD) is −7.63 ± 1.47 over its post-warm-up signals. Dropping the best cluster leaves −8.30; dropping NEAR (23 % of the subset) leaves −8.27.

**Verdict.** A taker strategy on the Hyperliquid perp after a same-asset Binance move does not pay in this sample: the repricing that exists is sub-second, worth ≈ 4 bps, and a third of the measured gap; costs are 9 bps of fees plus 2–4 bps of spread; and the biggest gaps sit in books worth tens of dollars. I would not spend more capture time on the taker version. If anything is left, it is a *different* hypothesis that would need its own pre-registration: maker-side quoting on the perp after a Binance impulse (adverse selection and fill probability decide it, and this data says nothing about either), or a volatile-regime capture (see below).

## How much weight this can bear

* **A quiet two hours.** BTC volatility 0.20–0.36 bps/√s in both stages, no large market-wide move. The sector run's best event (−27.9 bps TAO) was a single-coin shock; this capture contains 103 ten-second blocks with a full-cost gap but nothing resembling a market-wide cascade. Behaviour in a volatile regime (where the perp may lag more, or books thin out further) is untested.
* **Primary sample size.** 26 clusters is enough for the pre-registered ≥ 15 and the answer is far from the boundary (t = −5.2), but it is 27 signals; the descriptive tiers (470 signals ≥ 10 bps, 315 clusters) are larger and agree in sign and size.
* **Receive-time clocks.** Both legs are timestamped when our process receives them. A venue-dependent feed delay appears as "lag" and cannot be separated from true repricing lag here; the sub-second size of the effect is exactly where this matters. It biases *toward* finding a lag, so it does not rescue the negative result.
* **Perp mechanics ignored:** funding, the spot/perp basis, per-block book publication, and queue/adverse selection for taker orders beyond the stated latency; fee tiers are public base-tier assumptions.
* **Post hoc pieces are labelled.** Only §1 is confirmatory. Tiers, latencies, the Binance-spread stratification and the per-coin table are descriptive.
* **Report/evaluator parity.** §1 is computed on exactly the frozen evaluator's population (no warm-up trim); the descriptive tables trim the first 60 s of each stage (one primary-subset signal falls in it).

## Reproduce

```bash
python -m quant_agency.midcap_eval --check-frozen                       # pre-registered files intact?
python -m quant_agency.midcap_eval --count --runs 'runs/xvr_s*_2026*'   # count-only stopping statistic
python -m quant_agency.run_live --midcap-xv --duration 3660 --out runs --tag xvr_s1 --record runs/tapes/xvr_s1.npz   # one 60-minute stage
python -m quant_agency.run_live --replay runs/tapes/xvr_s1.npz --placebo-shift 600 --out runs --tag xvp_s1_600        # control replay
python -m quant_agency.midcap_eval --runs 'runs/xvr_s*_2026*'           # the single pre-registered test
# the committed capture, regenerated from the archived rows
python -m quant_agency.midcap_report --runs 'docs/live_runs/midcap/xvr_s*' --placebo 'docs/live_runs/midcap/placebo/xvp_*' --notes docs/MIDCAP_NOTES.md
```

Stage 1 (60 min) gave 11 clusters in the primary subset (< 20), so stage 2 ran as pre-registered and reached 26 (≥ 20); the stopping statistic was the cluster count only and no outcome was looked at before the single evaluation. The tapes (about 100 MB each) are not committed; the archived rows (rounded to 4 decimals, so the archive reproduces the evaluator to the third decimal: −8.455 vs −8.455) are in `docs/live_runs/midcap/`.

## 1. Pre-registered primary test (`docs/PREREG_MIDCAP_XV.md`)

H1: mean **net** > 0 for mid-cap signals with |gap| ≥ full cost hurdle and ≥ 1 000 USD at the entry-side touch; taker in / taker out at 4.5 bps per side, crossing the perp spread both ways, 5 s exit, 150 ms entry latency; one-sided α = 0.05, cluster-robust t over 10-second blocks, Student-t with clusters − 1 df, ≥ 15 clusters required.

| signals | clusters | mean net (bps) | s.e. | t | df | t crit | p (1-sided) | bootstrap 95 % CI | mean gross | mean gap | hit (net>0) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 27 | 26 | -8.46 | 1.63 | -5.17 | 25 | 1.71 | 1.000 | [-11.65, -5.30] | +3.76 | 23.5 | 11% |

**Decision: do not reject H0.**

Frozen-file check at report time: intact.

Robustness of the primary estimate: dropping the single best cluster leaves a mean net of -8.30 bps (n = 25); dropping the most frequent asset (NEAR, 23% of the subset) leaves -8.27 bps (n = 20). 

## 2. How often do same-asset dislocations occur?

A signal is a Binance tick on which the coin moved ≥ 4 bps over 1 or 3 s and the perp has not followed by ≥ 4 bps (cooldown 3 s per pair). An *event* is a distinct (coin, 10-second block). Rates are per hour of measurement (2.00 h) and per coin-hour (50 mid-caps, 2 baseline).

| group | gap tier | signals | events | coins | 10-s blocks | events / h | events / coin-h | signals with ≥ 1 000 USD at the touch |
|---|---|---|---|---|---|---|---|---|
| mid-caps | ≥ 4 bps (shadow floor) | 11597 | 9100 | 52 | 718 | 4550.00 | 91.000 | 2435 |
| mid-caps | ≥ 8 bps | 974 | 802 | 38 | 489 | 401.00 | 8.020 | 152 |
| mid-caps | ≥ 10 bps | 470 | 391 | 30 | 315 | 195.50 | 3.910 | 42 |
| mid-caps | ≥ 15 bps | 156 | 142 | 20 | 134 | 71.00 | 1.420 | 20 |
| mid-caps | ≥ full cost (spread + 9 bps fee + slip) | 121 | 111 | 22 | 103 | 55.50 | 1.110 | 26 |
| BTC+ETH baseline | ≥ 4 bps (shadow floor) | 4 | 4 | 2 | 3 | 2.00 | 0.040 | 3 |
| BTC+ETH baseline | ≥ 8 bps | 0 | 0 | 0 | 0 | 0.00 | 0.000 | 0 |
| BTC+ETH baseline | ≥ 10 bps | 0 | 0 | 0 | 0 | 0.00 | 0.000 | 0 |
| BTC+ETH baseline | ≥ 15 bps | 0 | 0 | 0 | 0 | 0.00 | 0.000 | 0 |
| BTC+ETH baseline | ≥ full cost (spread + 9 bps fee + slip) | 0 | 0 | 0 | 0 | 0.00 | 0.000 | 0 |

## 3. Markouts by tier and latency (mid-caps, h = 5 s; mean ± cluster s.e., bps)

`gross` = mid-to-mid; `net0` = crossing the perp spread both ways, no fees; fee tiers are subtracted from `net0` (taker/taker 9 bps; taker-in/maker-out 6; maker/maker 3 — the maker tiers keep the spread-crossing price and assume no fill risk, so they are optimistic). *maker exit at mid* = cross on entry, exit at the mid, 6 bps.

| tier | latency | signals | clusters | gross | hit | net0 | net 9 bps | net 6 | net 3 | maker exit at mid (opt.) |
|---|---|---|---|---|---|---|---|---|---|---|
| ≥ 4 bps (shadow floor) | 0 ms | 11597 | 718 | +4.02 ± 0.07 | 82% | +1.61 ± 0.07 | -7.39 ± 0.07 | -4.39 ± 0.07 | -1.39 ± 0.07 | -3.14 ± 0.07 |
| ≥ 4 bps (shadow floor) | 150 ms | 11597 | 718 | +3.80 ± 0.07 | 81% | +1.33 ± 0.08 | -7.67 ± 0.08 | -4.67 ± 0.08 | -1.67 ± 0.08 | -3.41 ± 0.07 |
| ≥ 4 bps (shadow floor) | 500 ms | 11597 | 718 | +2.40 ± 0.07 | 71% | -0.29 ± 0.08 | -9.29 ± 0.08 | -6.29 ± 0.08 | -3.29 ± 0.08 | -5.03 ± 0.08 |
| ≥ 4 bps (shadow floor) | 1000 ms | 11597 | 718 | +0.61 ± 0.07 | 55% | -2.18 ± 0.07 | -11.18 ± 0.07 | -8.18 ± 0.07 | -5.18 ± 0.07 | -6.94 ± 0.07 |
| ≥ 8 bps | 0 ms | 974 | 489 | +4.78 ± 0.34 | 72% | +0.23 ± 0.35 | -8.77 ± 0.35 | -5.77 ± 0.35 | -2.77 ± 0.35 | -3.41 ± 0.35 |
| ≥ 8 bps | 150 ms | 974 | 489 | +3.91 ± 0.34 | 70% | -0.82 ± 0.36 | -9.82 ± 0.36 | -6.82 ± 0.36 | -3.82 ± 0.36 | -4.44 ± 0.35 |
| ≥ 8 bps | 500 ms | 974 | 489 | +1.61 ± 0.33 | 58% | -3.42 ± 0.36 | -12.42 ± 0.36 | -9.42 ± 0.36 | -6.42 ± 0.36 | -7.16 ± 0.34 |
| ≥ 8 bps | 1000 ms | 974 | 489 | +0.02 ± 0.33 | 49% | -4.79 ± 0.35 | -13.79 ± 0.35 | -10.79 ± 0.35 | -7.79 ± 0.35 | -8.52 ± 0.33 |
| ≥ 10 bps | 0 ms | 470 | 315 | +5.18 ± 0.60 | 69% | -0.21 ± 0.61 | -9.21 ± 0.61 | -6.21 ± 0.61 | -3.21 ± 0.61 | -3.44 ± 0.61 |
| ≥ 10 bps | 150 ms | 470 | 315 | +3.88 ± 0.58 | 66% | -1.77 ± 0.62 | -10.77 ± 0.62 | -7.77 ± 0.62 | -4.77 ± 0.62 | -4.98 ± 0.60 |
| ≥ 10 bps | 500 ms | 470 | 315 | +1.01 ± 0.56 | 52% | -4.98 ± 0.60 | -13.98 ± 0.60 | -10.98 ± 0.60 | -7.98 ± 0.60 | -8.32 ± 0.56 |
| ≥ 10 bps | 1000 ms | 470 | 315 | -0.51 ± 0.52 | 47% | -6.12 ± 0.55 | -15.12 ± 0.55 | -12.12 ± 0.55 | -9.12 ± 0.55 | -9.45 ± 0.52 |
| ≥ 15 bps | 0 ms | 156 | 134 | +8.10 ± 1.17 | 72% | +2.39 ± 1.20 | -6.61 ± 1.20 | -3.61 ± 1.20 | -0.61 ± 1.20 | -0.79 ± 1.18 |
| ≥ 15 bps | 150 ms | 156 | 134 | +5.77 ± 1.12 | 66% | -0.49 ± 1.20 | -9.49 ± 1.20 | -6.49 ± 1.20 | -3.49 ± 1.20 | -3.68 ± 1.17 |
| ≥ 15 bps | 500 ms | 156 | 134 | +2.20 ± 0.97 | 56% | -4.84 ± 1.05 | -13.84 ± 1.05 | -10.84 ± 1.05 | -7.84 ± 1.05 | -7.91 ± 0.99 |
| ≥ 15 bps | 1000 ms | 156 | 134 | +0.08 ± 0.91 | 49% | -5.95 ± 0.96 | -14.95 ± 0.96 | -11.95 ± 0.96 | -8.95 ± 0.96 | -9.16 ± 0.91 |
| ≥ full cost (spread + 9 bps fee + slip) | 0 ms | 121 | 103 | +8.50 ± 1.21 | 74% | +5.33 ± 1.20 | -3.67 ± 1.20 | -0.67 ± 1.20 | +2.33 ± 1.20 | +1.35 ± 1.19 |
| ≥ full cost (spread + 9 bps fee + slip) | 150 ms | 121 | 103 | +6.76 ± 1.10 | 70% | +2.99 ± 1.11 | -6.01 ± 1.11 | -3.01 ± 1.11 | -0.01 ± 1.11 | -1.14 ± 1.11 |
| ≥ full cost (spread + 9 bps fee + slip) | 500 ms | 121 | 103 | +3.40 ± 0.98 | 60% | -1.78 ± 1.06 | -10.78 ± 1.06 | -7.78 ± 1.06 | -4.78 ± 1.06 | -5.76 ± 1.00 |
| ≥ full cost (spread + 9 bps fee + slip) | 1000 ms | 121 | 103 | +1.12 ± 0.87 | 55% | -3.07 ± 0.89 | -12.07 ± 0.89 | -9.07 ± 0.89 | -6.07 ± 0.89 | -7.17 ± 0.86 |

## 4. Markout curves (mid-caps)

**≥ 8 bps, 0 ms**

| h (s) | signals | clusters | gross | hit | net 9 bps |
|---|---|---|---|---|---|
| 1 | 974 | 489 | +4.63 ± 0.19 | 82% | -9.10 ± 0.20 |
| 3 | 974 | 489 | +4.59 ± 0.30 | 76% | -8.83 ± 0.32 |
| 5 | 974 | 489 | +4.78 ± 0.34 | 72% | -8.77 ± 0.35 |
| 10 | 974 | 489 | +4.81 ± 0.44 | 67% | -8.66 ± 0.45 |
| 30 | 974 | 489 | +5.05 ± 0.66 | 62% | -8.35 ± 0.66 |

**≥ 8 bps, 150 ms**

| h (s) | signals | clusters | gross | hit | net 9 bps |
|---|---|---|---|---|---|
| 1 | 974 | 489 | +4.01 ± 0.20 | 78% | -9.79 ± 0.22 |
| 3 | 974 | 489 | +3.67 ± 0.30 | 73% | -9.93 ± 0.32 |
| 5 | 974 | 489 | +3.91 ± 0.34 | 70% | -9.82 ± 0.36 |
| 10 | 974 | 489 | +4.04 ± 0.44 | 66% | -9.58 ± 0.46 |
| 30 | 974 | 489 | +4.33 ± 0.67 | 59% | -9.25 ± 0.68 |

**≥ 10 bps, 0 ms**

| h (s) | signals | clusters | gross | hit | net 9 bps |
|---|---|---|---|---|---|
| 1 | 470 | 315 | +5.45 ± 0.33 | 81% | -9.10 ± 0.36 |
| 3 | 470 | 315 | +5.09 ± 0.53 | 72% | -9.08 ± 0.56 |
| 5 | 470 | 315 | +5.18 ± 0.60 | 69% | -9.21 ± 0.61 |
| 10 | 470 | 315 | +4.96 ± 0.75 | 63% | -9.28 ± 0.77 |
| 30 | 470 | 315 | +4.64 ± 1.03 | 61% | -9.51 ± 1.04 |

**≥ 10 bps, 150 ms**

| h (s) | signals | clusters | gross | hit | net 9 bps |
|---|---|---|---|---|---|
| 1 | 470 | 315 | +4.44 ± 0.35 | 74% | -10.27 ± 0.40 |
| 3 | 470 | 315 | +3.82 ± 0.51 | 69% | -10.63 ± 0.54 |
| 5 | 470 | 315 | +3.88 ± 0.58 | 66% | -10.77 ± 0.62 |
| 10 | 470 | 315 | +3.79 ± 0.73 | 62% | -10.70 ± 0.76 |
| 30 | 470 | 315 | +3.63 ± 1.03 | 58% | -10.78 ± 1.04 |

**≥ full cost (spread + 9 bps fee + slip), 0 ms**

| h (s) | signals | clusters | gross | hit | net 9 bps |
|---|---|---|---|---|---|
| 1 | 121 | 103 | +6.66 ± 0.80 | 77% | -5.79 ± 0.71 |
| 3 | 121 | 103 | +8.59 ± 1.24 | 79% | -3.14 ± 1.19 |
| 5 | 121 | 103 | +8.50 ± 1.21 | 74% | -3.67 ± 1.20 |
| 10 | 121 | 103 | +8.03 ± 1.48 | 71% | -4.09 ± 1.42 |
| 30 | 121 | 103 | +7.34 ± 2.38 | 67% | -4.71 ± 2.33 |

**≥ full cost (spread + 9 bps fee + slip), 150 ms**

| h (s) | signals | clusters | gross | hit | net 9 bps |
|---|---|---|---|---|---|
| 1 | 121 | 103 | +5.12 ± 0.79 | 71% | -7.95 ± 0.86 |
| 3 | 121 | 103 | +6.78 ± 0.96 | 75% | -6.19 ± 0.97 |
| 5 | 121 | 103 | +6.76 ± 1.10 | 70% | -6.01 ± 1.11 |
| 10 | 121 | 103 | +6.12 ± 1.31 | 67% | -6.75 ± 1.28 |
| 30 | 121 | 103 | +5.65 ± 2.23 | 67% | -7.07 ± 2.23 |

## 5. Mid-caps vs the BTC / ETH baseline at equal gap tiers (150 ms, h = 5 s)

| gap tier | group | signals | clusters | mean gap | median perp spread | gross | hit | net0 |
|---|---|---|---|---|---|---|---|---|
| ≥ 4 bps (shadow floor) | mid-caps | 11597 | 718 | 5.6 | 1.78 | +3.80 ± 0.07 | 81% | +1.33 ± 0.08 |
| ≥ 4 bps (shadow floor) | BTC+ETH | 4 | 3 | 4.1 | 0.42 | +4.49 ± 0.17 | 100% | +4.15 ± 0.15 |
| ≥ 8 bps | mid-caps | 974 | 489 | 12.1 | 3.36 | +3.91 ± 0.34 | 70% | -0.82 ± 0.36 |
| ≥ 8 bps | BTC+ETH | 0 | 0 | – | – | – | – | – |

## 6. Control: Binance legs time-shifted against the perps

The same tape(s) were replayed 24 times with every Binance leg circularly shifted by 150, 300, 600, 900, 1200, 1500, 1800, 2100, 2400, 2700, 3000, 3300 s (each on every stage's tape) while the perps kept their clock, so the same-asset relationship is destroyed. Compare with §3 (150 ms, h = 5 s).

| gap tier | real signals | placebo signals per replay | placebo gross | placebo hit | placebo net 9 bps | real gross | real − placebo gross (±, approx.) |
|---|---|---|---|---|---|---|---|
| ≥ 4 bps (shadow floor) | 11597 | 7530.7 | -0.01 ± 0.02 | 44% | -11.27 ± 0.02 | +3.80 ± 0.07 | +3.81 ± 0.07 |
| ≥ 8 bps | 974 | 1214.2 | -0.04 ± 0.05 | 46% | -12.61 ± 0.05 | +3.91 ± 0.34 | +3.95 ± 0.34 |
| ≥ 10 bps | 470 | 667.0 | +0.06 ± 0.07 | 47% | -13.15 ± 0.08 | +3.88 ± 0.58 | +3.82 ± 0.59 |
| ≥ 15 bps | 156 | 264.2 | +0.24 ± 0.14 | 47% | -13.85 ± 0.16 | +5.77 ± 1.12 | +5.53 ± 1.13 |
| ≥ full cost (spread + 9 bps fee + slip) | 121 | 250.5 | +0.09 ± 0.11 | 44% | -11.78 ± 0.11 | +6.76 ± 1.10 | +6.66 ± 1.10 |

## 7. Could it have been traded? (signals ≥ 10 bps, 150 ms, h = 5 s)

* Entry-side touch size: median 251 USD; 9% of signals show ≥ 1 000 USD, 3% ≥ 5 000 USD (the clip assumed for slippage is 1 000 USD).
* Perp spread at the signal: median 4.29 bps; Binance spread: median 9.13 bps.
* Age of the perp quote at the signal: median 0.14 s; 5% older than 1 s (a quote that old is a resting order nobody has repriced – or a dead book).
* Direction: 228 up-moves (gross +3.91 ± 0.88) and 242 down-moves (gross +3.84 ± 0.90); the perp short leg additionally pays/receives funding, ignored here (seconds).

Sensitivity to the touch-size filter (150 ms, h = 5 s; descriptive — the primary test uses ≥ 1 000 USD):

| gap tier | min touch (USD) | signals | clusters | gross | net 9 bps |
|---|---|---|---|---|---|
| ≥ 10 bps | 0 | 470 | 315 | +3.88 ± 0.58 | -10.77 ± 0.62 |
| ≥ 10 bps | 250 | 237 | 196 | +4.06 ± 0.81 | -11.03 ± 0.89 |
| ≥ 10 bps | 500 | 100 | 88 | +2.70 ± 1.22 | -11.88 ± 1.41 |
| ≥ 10 bps | 1,000 | 42 | 41 | +3.20 ± 1.42 | -9.62 ± 1.66 |
| ≥ 10 bps | 5,000 | 13 | 13 | +4.44 ± 1.76 | -8.37 ± 2.11 |
| ≥ full cost (spread + 9 bps fee + slip) | 0 | 121 | 103 | +6.76 ± 1.10 | -6.01 ± 1.11 |
| ≥ full cost (spread + 9 bps fee + slip) | 250 | 70 | 64 | +5.19 ± 1.35 | -7.43 ± 1.38 |
| ≥ full cost (spread + 9 bps fee + slip) | 500 | 44 | 41 | +4.05 ± 1.26 | -8.44 ± 1.51 |
| ≥ full cost (spread + 9 bps fee + slip) | 1,000 | 26 | 25 | +3.98 ± 1.40 | -7.63 ± 1.47 |
| ≥ full cost (spread + 9 bps fee + slip) | 5,000 | 10 | 10 | +2.46 ± 1.92 | -10.00 ± 2.28 |

**Exploratory (post hoc, not pre-registered): is the incomplete gap closure a leader-book-quality artefact?** The Binance leg's mid can jump on a wide, thin book without any price change; if that explained why the perp closes only part of the gap, closure would be much higher on tight Binance books. Gap ≥ 8 bps, h = 5 s, by the Binance spread at the signal:

| latency | Binance spread (bps) | signals | clusters | mean gap | gross | closure (gross ÷ gap) | net 9 bps | median touch (USD) | median perp spread |
|---|---|---|---|---|---|---|---|---|---|
| 0 ms | ≤ 2 | 96 | 85 | 12.0 | +4.48 ± 0.69 | 37% | -6.80 ± 0.73 | 400 | 2.04 |
| 0 ms | 2–5 | 152 | 127 | 11.9 | +3.73 ± 0.48 | 31% | -8.26 ± 0.52 | 262 | 2.30 |
| 0 ms | > 5 | 726 | 424 | 12.1 | +5.04 ± 0.45 | 42% | -9.14 ± 0.46 | 400 | 3.99 |
| 150 ms | ≤ 2 | 96 | 85 | 12.0 | +3.84 ± 0.69 | 32% | -7.42 ± 0.70 | 400 | 2.04 |
| 150 ms | 2–5 | 152 | 127 | 11.9 | +3.13 ± 0.52 | 26% | -8.96 ± 0.59 | 262 | 2.30 |
| 150 ms | > 5 | 726 | 424 | 12.1 | +4.09 ± 0.44 | 34% | -10.32 ± 0.47 | 400 | 3.99 |

Gap closure over the horizon (gap ≥ 8 bps, 150 ms): 1.0 s: 33%, 3.0 s: 30%, 5.0 s: 32%, 10.0 s: 33%, 30.0 s: 36%. A lagging perp would keep closing with the horizon; this one stops.

## 8. By coin (gap ≥ 8 bps, 150 ms, h = 5 s; coins with ≥ 1 signal)

| coin | signals ≥ 8 | signals ≥ 10 | events | mean gap | median perp spread | median touch (USD) | gross | net 9 bps |
|---|---|---|---|---|---|---|---|---|
| ALT | 371 | 238 | 245 | 13.0 | 5.78 | 84 | +4.00 ± 0.79 | -12.18 ± 0.83 |
| DOT | 124 | 7 | 113 | 9.0 | 1.76 | 679 | +2.67 ± 0.24 | -8.74 ± 0.25 |
| COMP | 75 | 43 | 61 | 14.0 | 8.03 | 637 | +4.13 ± 1.55 | -13.15 ± 1.62 |
| ZRO | 55 | 21 | 50 | 12.6 | 2.61 | 171 | +6.46 ± 1.57 | -5.24 ± 1.55 |
| TIA | 43 | 17 | 41 | 12.1 | 1.89 | 375 | +4.55 ± 0.82 | -6.65 ± 0.81 |
| CHIP | 41 | 22 | 39 | 12.8 | 3.21 | 49 | +4.24 ± 1.23 | -8.62 ± 1.37 |
| WLD | 35 | 21 | 32 | 12.0 | 1.84 | 400 | +3.64 ± 1.28 | -7.38 ± 1.28 |
| NIL | 30 | 18 | 29 | 12.8 | 2.36 | 20 | +4.86 ± 1.10 | -7.72 ± 1.00 |
| ENA | 23 | 2 | 23 | 8.9 | 1.61 | 450 | +2.19 ± 0.87 | -8.54 ± 0.90 |
| S | 22 | 14 | 21 | 13.4 | 3.54 | 333 | +2.22 ± 0.86 | -10.66 ± 0.79 |
| JUP | 20 | 12 | 17 | 14.5 | 1.82 | 399 | +3.61 ± 1.46 | -7.83 ± 1.43 |
| ARB | 19 | 4 | 17 | 9.4 | 1.06 | 973 | +1.35 ± 1.04 | -8.94 ± 1.18 |
| PENDLE | 14 | 6 | 14 | 10.2 | 2.40 | 43 | +2.19 ± 1.35 | -9.23 ± 1.35 |
| APT | 12 | 7 | 12 | 10.7 | 2.60 | 436 | +7.32 ± 0.70 | -4.48 ± 0.67 |
| NEAR | 12 | 7 | 12 | 13.5 | 0.21 | 1,541 | +2.69 ± 1.66 | -6.98 ± 1.62 |
| STRK | 11 | 3 | 9 | 9.5 | 1.80 | 534 | +4.72 ± 2.75 | -7.05 ± 2.88 |
| PUMP | 8 | 5 | 8 | 12.4 | 3.40 | 1,577 | +6.65 ± 2.12 | -5.88 ± 2.33 |
| INJ | 7 | 4 | 7 | 11.6 | 1.06 | 400 | +2.28 ± 3.75 | -8.52 ± 4.03 |
| CRV | 6 | 1 | 6 | 10.2 | 2.19 | 392 | +5.32 ± 0.59 | -5.23 ± 0.40 |
| SAND | 5 | 1 | 5 | 9.0 | 1.77 | 186 | +3.39 ± 2.55 | -7.34 ± 2.36 |
| PYTH | 5 | 2 | 5 | 11.4 | 4.53 | 250 | +1.17 ± 0.67 | -12.69 ± 0.97 |
| MORPHO | 4 | 3 | 4 | 13.1 | 1.85 | 132 | +1.60 ± 0.59 | -9.31 ± 0.45 |
| LDO | 3 | 2 | 3 | 9.6 | 1.80 | 34 | +5.61 ± 2.69 | -5.06 ± 2.66 |
| ZEC | 3 | 0 | 3 | 9.1 | 0.88 | 3,114 | +5.13 ± 0.84 | -4.90 ± 0.86 |
| AERO | 3 | 3 | 3 | 11.5 | 1.87 | 18 | +5.87 ± 4.24 | -5.64 ± 3.72 |

## 9. Universe

52 pairs (BTC, ETH baseline + 50 mid-caps ranked by Hyperliquid 24 h volume): ZEC, HYPE, NEAR, SOL, PUMP, WLD, XRP, ENA, ARB, ZRO, SUI, CRV, INJ, STRK, UNI, TAO, AAVE, ONDO, PENGU, DOGE, BNB, XPL, ADA, LINK, DOT, AERO, NIL, TIA, LTC, AVAX, PYTH, PENDLE, JUP, MORPHO, TRUMP, CHIP, ALT, BCH, APT, ETHFI, XLM, ASTER, FIL, ICP, S, TRX, HBAR, LDO, SAND, FET.

Admission: Binance 24 h volume ≥ $1M, Hyperliquid 24 h volume ≥ $0.5M, Binance spread ≤ 15 bps, one Binance tick ≤ 10 bps of price; gold/stable tokens excluded. Left out: **DYDX** Binance 24h volume $0.57M < $1M; **APE** Binance 24h volume $0.87M < $1M; **PEPE** Binance spread 24.0 bps > 15; **CFX** HL 24h volume $0.14M < $0.5M; **GMX** Binance 24h volume $0.21M < $1M; **SNX** Binance 24h volume $0.21M < $1M; **COMP** Binance 24h volume $0.61M < $1M; **YGG** Binance 24h volume $0.16M < $1M; **SHIB** HL 24h volume $0.39M < $0.5M; **RUNE** HL 24h volume $0.31M < $0.5M; **BANANA** Binance 24h volume $0.06M < $1M; **TRB** Binance 24h volume $0.39M < $1M; **BIGTIME** Binance 24h volume $0.06M < $1M; **BLUR** Binance 24h volume $0.75M < $1M; **MINA** HL 24h volume $0.25M < $0.5M; **POLYX** Binance 24h volume $0.11M < $1M; **GAS** Binance 24h volume $0.09M < $1M; **MEME** Binance 24h volume $0.36M < $1M; **ORDI** Binance 24h volume $0.85M < $1M; **NEO** Binance 24h volume $0.24M < $1M; **ZEN** HL 24h volume $0.14M < $0.5M; **SUSHI** Binance 24h volume $0.17M < $1M; **IMX** Binance 24h volume $0.27M < $1M; **BONK** HL 24h volume $0.46M < $0.5M; **GMT** Binance 24h volume $0.23M < $1M; **SUPER** HL 24h volume $0.16M < $0.5M; **LUNC** Binance 24h volume $0.71M < $1M; **RSR** HL 24h volume $0.25M < $0.5M; **GALA** HL 24h volume $0.15M < $0.5M; **ACE** HL 24h volume $0.12M < $0.5M; **WIF** Binance 24h volume $0.99M < $1M; **CAKE** HL 24h volume $0.31M < $0.5M; **PEOPLE** Binance 24h volume $0.20M < $1M; **ENS** Binance 24h volume $0.38M < $1M; **ETC** HL 24h volume $0.27M < $0.5M; **XAI** Binance 24h volume $0.23M < $1M; **MANTA** Binance 24h volume $0.46M < $1M; **UMA** Binance 24h volume $0.08M < $1M; **DYM** Binance 24h volume $0.27M < $1M; **W** Binance spread 15.2 bps > 15; ….
