### Memory soak (synthetic, density 4, as fast as possible)

Resident memory of the whole process (engine + synthetic generator) every 15 minutes of market time, 151 minutes, 1583 fills (629 per hour):

| market minute | 0 | 15 | 30 | 45 | 60 | 75 | 90 | 105 | 120 | 135 | 150 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| RSS (MB) | 95 | 301 | 366 | 373 | 383 | 383 | 383 | 383 | 383 | 383 | 385 |

It rises while the time windows fill: the 1-hour social windows, the 30-minute token TTL and the rolling-hour equity history. Then it is flat. The bounded-footprint test (`test_engine_state_is_bounded_over_synthetic_hours`) checks the same thing container by container.
