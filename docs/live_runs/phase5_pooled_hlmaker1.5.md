pooled over 2 sessions; signals: {'hyperliquid': 127, 'polymarket': 197}; HL maker fee 1.5 bps

### hyperliquid — fill model `strict`

| variant | attempts | filled | fill rate | net bps / fill ±s.e. | net bps / attempt ±s.e. | 5s markout after fill (bps) |
|---|---|---|---|---|---|---|
| taker/taker | 127 | 104 | 82% | -8.2±0.3 | -6.74±0.50 | +1.5 |
| taker/passive | 127 | 104 | 82% | -6.5±0.4 | -5.34±0.48 | +1.6 |
| join/taker-exit+shield | 127 | 7 | 6% | -5.9±0.6 | -0.33±0.22 | -0.6 |
| join/passive noshield | 127 | 9 | 7% | -6.8±0.5 | -0.48±0.24 | -0.7 |
| join/passive+shield | 127 | 7 | 6% | -6.6±0.7 | -0.36±0.24 | -0.6 |
| penny/passive+shield | 127 | 8 | 6% | -6.7±0.7 | -0.42±0.28 | -0.7 |

### hyperliquid — fill model `depletion`

| variant | attempts | filled | fill rate | net bps / fill ±s.e. | net bps / attempt ±s.e. | 5s markout after fill (bps) |
|---|---|---|---|---|---|---|
| taker/taker | 127 | 104 | 82% | -8.2±0.3 | -6.74±0.50 | +1.5 |
| taker/passive | 127 | 104 | 82% | -6.4±0.4 | -5.22±0.48 | +1.6 |
| join/taker-exit+shield | 127 | 12 | 9% | -5.7±0.7 | -0.53±0.28 | -0.0 |
| join/passive noshield | 127 | 15 | 12% | -5.6±1.1 | -0.66±0.31 | -0.2 |
| join/passive+shield | 127 | 12 | 9% | -5.3±1.2 | -0.50±0.30 | -0.0 |
| penny/passive+shield | 127 | 19 | 15% | -4.3±0.8 | -0.64±0.30 | +1.2 |

### polymarket — fill model `strict`

| variant | attempts | filled | fill rate | net bps / fill ±s.e. | net ¢/share / fill | net bps / attempt ±s.e. | 5s markout after fill (bps) |
|---|---|---|---|---|---|---|---|
| taker/taker | 197 | 123 | 62% | -933.6±145.9 | -3.22 | -582.88±84.10 | +36.2 |
| taker/passive | 197 | 123 | 62% | -864.8±125.7 | -3.10 | -539.97±78.32 | +36.8 |
| join/taker-exit+shield | 197 | 21 | 11% | -1558.7±924.6 | -4.63 | -166.16±81.36 | -571.7 |
| join/passive noshield | 197 | 27 | 14% | -973.0±643.6 | -3.36 | -133.36±40.96 | -399.2 |
| join/passive+shield | 197 | 21 | 11% | -1216.2±759.9 | -4.02 | -129.65±40.82 | -550.1 |
| penny/passive+shield | 197 | 20 | 10% | -1229.0±759.3 | -3.81 | -124.77±40.66 | -547.2 |

### polymarket — fill model `depletion`

| variant | attempts | filled | fill rate | net bps / fill ±s.e. | net ¢/share / fill | net bps / attempt ±s.e. | 5s markout after fill (bps) |
|---|---|---|---|---|---|---|---|
| taker/taker | 197 | 123 | 62% | -933.6±145.9 | -3.22 | -582.88±84.10 | +36.2 |
| taker/passive | 197 | 123 | 62% | -703.0±122.1 | -2.44 | -438.95±72.87 | +15.9 |
| join/taker-exit+shield | 197 | 43 | 22% | -535.5±259.9 | -2.00 | -116.88±51.46 | +113.1 |
| join/passive noshield | 197 | 55 | 28% | -289.8±196.3 | -1.06 | -80.91±48.12 | +90.4 |
| join/passive+shield | 197 | 43 | 22% | -412.3±230.2 | -1.43 | -90.00±46.06 | +69.2 |
| penny/passive+shield | 197 | 77 | 39% | -176.2±153.1 | -0.66 | -68.87±57.14 | +247.9 |

