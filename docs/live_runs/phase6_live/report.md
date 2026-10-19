# Quant Agency — Phase 6 report: Architecture A (pre-positioned quote maker) vs Architecture B (high-conviction taker sniper)

* mode **live**, duration **1500s**; Binance BTC oracle, **9 Hyperliquid perps**, **85 Polymarket markets**; trade prints: **9784** (`trades` fill model is observed).
* latencies: order **150 ms**, cancel **150 ms** (fills inside the window are real and counted). A: quote only while every fast-horizon (0.25/1/3 s) |BTC Z| < **1.0**, cancel the vulnerable side at Z ≥ **2.0**, stay off it {'hyperliquid': 3.0, 'polymarket': 7.5} s; no quotes inside 180 s of expiry, flat by 90 s (CFO entry guard 60 s). B: floor **1.5x (spread + taker-in + maker-out fee)**.
* **fees (assumptions):** Hyperliquid maker 1.5 bps / taker 4.5 bps per side; Polymarket maker 0, taker `0.07·p·(1−p)`/share. A's HL economics are linear in the maker fee (round trip = 2 x fee vs the spread).
* oracle regime: **46 BTC impulses** (Z ≥ 2.0 on a fast horizon, ≥ 0.3 bps), calm 89% of the time (the window in which A is allowed to quote).

## Architecture A — pre-positioned quote maker with oracle cancel-shield

One clip per market, both sides at the touch while calm; a round trip = maker entry fill + exit (passive at the touch, else taker stop / time stop / shield-flatten). Net includes both legs' fees and the taker exit when it happens. `noshield` runs the identical quote policy but never cancels on an impulse.

### hyperliquid

**No quote was ever posted** (42874 gating decisions): the CFO's round-trip economics (spread − 2 x maker fee − adverse buffer − hurdle) were never positive. This is the result, not a bug: with maker fee 1.5 bps the two legs cost more than the whole spread.

### polymarket

| variant | round trips | net / trip | cluster s.e. | hit | net $ | passive exit | trips filled in shield-cancel window / any cancel window | quotes posted | shield cancels | shield flattens | post-only rejects |
|---|---|---|---|---|---|---|---|---|---|---|---|
| shield/strict | 154 | -2.88¢ (-689 bps) | ±74 | 22% | -259.88 | 23% | 10 / 86 | 1712 | 827 | 39 | 33 |
| noshield/strict | 237 | -3.59¢ (-780 bps) | ±61 | 22% | -456.37 | 25% | 0 / 93 | 1250 | 0 | 0 | 35 |
| shield/depletion | 669 | -0.49¢ (-115 bps) | ±31 | 52% | -227.80 | 51% | 25 / 228 | 1962 | 912 | 121 | 95 |
| noshield/depletion | 829 | -0.80¢ (-170 bps) | ±28 | 52% | -350.56 | 52% | 0 / 237 | 1640 | 0 | 0 | 35 |
| shield/trades | 163 | -2.65¢ (-639 bps) | ±72 | 26% | -252.75 | 28% | 11 / 86 | 1711 | 827 | 40 | 34 |
| noshield/trades | 246 | -3.38¢ (-740 bps) | ±60 | 24% | -438.89 | 29% | 0 / 91 | 1252 | 0 | 0 | 36 |

**ACCOUNT quoter (CFO-sized, `trades` fills):** 16, -3.13¢ (-848 bps), ±211, 19%, -25.35; exit reasons {'passive_fill': 5, 'shield_flatten': 3, 'adverse_stop': 6, 'time_stop': 2}.

### Does the shield earn its keep? (same quote policy, same ticks)

| venue | fill model | round trips (shield vs none) | net / trip | net $ total | trips filled in a shield-cancel window |
|---|---|---|---|---|---|
| polymarket | strict | 154 vs 237 | -2.88¢ vs -3.59¢ | -259.88 vs -456.37 | 10 vs 0 |
| polymarket | depletion | 669 vs 829 | -0.49¢ vs -0.80¢ | -227.80 vs -350.56 | 25 vs 0 |
| polymarket | trades | 163 vs 246 | -2.65¢ vs -3.38¢ | -252.75 vs -438.89 | 11 vs 0 |

### Adverse selection: when do the entry fills happen?

A fill within 10 s after a BTC impulse is, by construction, the quote that was on the wrong side of it.

| venue | variant | round trips | entered ≤10 s after an impulse | net bps (those) | net bps (calm fills) | mean 5s markout after fill (bps) |
|---|---|---|---|---|---|---|
| polymarket | noshield/strict | 237 | 54% | -708.6 | -864.7 | -352.3 |
| polymarket | shield/strict | 154 | 29% | -606.3 | -723.9 | -324.1 |

## Architecture B — high-conviction taker sniper + passive maker exit

Fire only if the CFO-credited predicted move |Δ̂| = edge_credit·|gap| ≥ **1.5x (spread + taker entry fee + maker exit fee)**. Shadow rows are spawned for *every* signal and tagged `floor_ok`, so the floor's effect is read off the same ticks. Exit: maker take-profit at the converged touch → scratch (passive at the touch) if the impulse stalls → taker only on a genuine reversal / time stop.

### hyperliquid

81 signals; **0 (0%) pass the floor** (81 abstained); median predicted-move/floor ratio 0.22; median |Δ̂| 2.3 bps vs median floor 10.2 bps.

| fill model | variant | attempts | filled | net / fill | cluster s.e. | hit | net $ | passive exit | scratched | exit reasons |
|---|---|---|---|---|---|---|---|---|---|---|
| strict | B (all signals, no floor) | 81 | 68 | -5.30 bps | ±0.7 | 0% | -7.19 | 82% | 1 | reversal_stop=1, work_expired=11, passive_fill=56 |
| strict | B (floor failed) ← abstained | 81 | 68 | -5.30 bps | ±0.7 | 0% | -7.19 | 82% | 1 | reversal_stop=1, work_expired=11, passive_fill=56 |
| depletion | B (all signals, no floor) | 81 | 68 | -5.30 bps | ±0.7 | 0% | -7.19 | 82% | 1 | reversal_stop=1, work_expired=11, passive_fill=56 |
| depletion | B (floor failed) ← abstained | 81 | 68 | -5.30 bps | ±0.7 | 0% | -7.19 | 82% | 1 | reversal_stop=1, work_expired=11, passive_fill=56 |
| trades | B (all signals, no floor) | 81 | 68 | -5.14 bps | ±0.7 | 0% | -6.98 | 85% | 1 | reversal_stop=1, work_expired=9, passive_fill=58 |
| trades | B (floor failed) ← abstained | 81 | 68 | -5.14 bps | ±0.7 | 0% | -6.98 | 85% | 1 | reversal_stop=1, work_expired=9, passive_fill=58 |
| - | taker/taker baseline (all signals) | 81 | 68 | -7.97 bps | ±0.6 | 0% | -10.81 | 0% | 0 | time_stop=4, take_profit=63, adverse_stop=1 |

### polymarket

83 signals; **23 (28%) pass the floor** (60 abstained); median predicted-move/floor ratio 0.57; median |Δ̂| 330.3 bps vs median floor 672.1 bps.

| fill model | variant | attempts | filled | net / fill | cluster s.e. | hit | net $ | passive exit | scratched | exit reasons |
|---|---|---|---|---|---|---|---|---|---|---|
| strict | B (all signals, no floor) | 83 | 49 | -1.19¢ (-328 bps) | ±156.5 | 45% | -82.67 | 53% | 1 | adverse_stop=4, passive_fill=26, work_expired=18, reversal_stop=1 |
| strict | B (floor passed) ← the architecture | 23 | 12 | +1.61¢ (+516 bps) | ±382.3 | 75% | +28.95 | 67% | 0 | passive_fill=8, adverse_stop=2, work_expired=2 |
| strict | B (floor failed) ← abstained | 60 | 37 | -2.09¢ (-602 bps) | ±125.7 | 35% | -111.61 | 49% | 1 | adverse_stop=2, passive_fill=18, work_expired=16, reversal_stop=1 |
| depletion | B (all signals, no floor) | 83 | 49 | -0.75¢ (-253 bps) | ±151.8 | 49% | -64.26 | 63% | 0 | adverse_stop=4, passive_fill=31, work_expired=14 |
| depletion | B (floor passed) ← the architecture | 23 | 12 | +1.73¢ (+529 bps) | ±380.4 | 75% | +29.70 | 75% | 0 | passive_fill=9, adverse_stop=2, work_expired=1 |
| depletion | B (floor failed) ← abstained | 60 | 37 | -1.56¢ (-507 bps) | ±125.5 | 41% | -93.97 | 59% | 0 | adverse_stop=2, passive_fill=22, work_expired=13 |
| trades | B (all signals, no floor) | 83 | 49 | -1.19¢ (-328 bps) | ±156.5 | 45% | -82.67 | 53% | 1 | adverse_stop=4, passive_fill=26, work_expired=18, reversal_stop=1 |
| trades | B (floor passed) ← the architecture | 23 | 12 | +1.61¢ (+516 bps) | ±382.3 | 75% | +28.95 | 67% | 0 | passive_fill=8, adverse_stop=2, work_expired=2 |
| trades | B (floor failed) ← abstained | 60 | 37 | -2.09¢ (-602 bps) | ±125.7 | 35% | -111.61 | 49% | 1 | adverse_stop=2, passive_fill=18, work_expired=16, reversal_stop=1 |
| - | taker/taker baseline (all signals) | 83 | 49 | -2.13¢ (-538 bps) | ±115.3 | 20% | -130.58 | 0% | 0 | adverse_stop=5, take_profit=43, time_stop=1 |
| - | taker/taker baseline (floor passed) | 23 | 12 | -0.23¢ (+77 bps) | ±270.7 | 67% | +4.81 | 0% | 0 | take_profit=9, adverse_stop=3 |

**ACCOUNT (CFO-sized, floor + net-edge + binary risk + expiry guard):** 4 fills, net -0.64 $ (-99.8 bps/fill), hit 50%, exits {'passive_fill': 1, 'adverse_stop': 1, 'work_expired': 2}.

## A vs B side by side (same session, same oracle, same CFO/CEO)

| venue | engine | round trips / fills | per hour | net per trade | hit | net $ |
|---|---|---|---|---|---|---|
| hyperliquid | A ACCOUNT | 0 | - | - | - | - |
| hyperliquid | A shield/strict | 0 | - | - | - | - |
| hyperliquid | B ACCOUNT | 0 | - | - | - | - |
| hyperliquid | B floor-passed/strict | 0 | - | - | - | - |
| polymarket | A ACCOUNT | 16 | 38 | -3.13¢ | 19% | -25.35 |
| polymarket | A shield/strict | 154 | 370 | -2.88¢ | 22% | -259.88 |
| polymarket | B ACCOUNT | 4 | 10 | -0.96¢ | 50% | -0.64 |
| polymarket | B floor-passed/strict | 12 | 29 | +1.61¢ | 75% | +28.95 |

## CFO / CEO governance

* equity $9,974.01 (start $10,000); account round trips: A 16, B 6; CFO state HALTED: ceo_halt; CEO state HALTED.
* CFO gate decisions (A `mm_*`, B `b_*`): {'mm_size_below_min': 701, 'mm_ok': 371, 'b_halted': 122, 'b_below_absolute_floor': 30, 'b_ok': 6, 'b_size_below_min': 4, 'b_net_edge_below_hurdle': 2}
* learned A adverse buffers {'hyperliquid': 0.3, 'polymarket': 400.0}; B floor multiple 1.5; blocked A ('polymarket',) / B (); shield holds {'hyperliquid': 3.0, 'polymarket': 7.5}.

**CEO Phase 6 interventions:**

```
21:49:31 MM_EXTEND_SHIELD           polymarket   4/8 round trips were filled inside a *shield* cancel-latency window (net -290.1bps): staying off the vulnerable side 6→7.5s after an impulse
21:57:31 MM_DISABLE_VENUE           polymarket   quote-maker net -921.1±371.4bps per round trip after 3 corrections; pulling all quotes on this venue
```

All CEO interventions: 17 (final state HALTED).

## Caveats

* Paper only. A real queue also has cancellations ahead of us, hidden size and other makers' adverse-selection logic; prints give a lower-bound `trades` model, `depletion` an upper bound.
* The cancel-vs-informed-taker race is the decisive unknown: A is only protected when (BTC detection + cancel latency) < the delay of the informed flow hitting the stale quote. This report measures the outcome on the data it saw; it cannot measure other participants' latency. The synthetic stress test sweeps that delay explicitly.
* Fee assumptions above are inputs, not measurements. Small samples: read the cluster s.e.
