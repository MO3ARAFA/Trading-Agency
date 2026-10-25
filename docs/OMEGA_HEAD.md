# Omega — 24/7 meme & micro-cap paper engine (100 USD account)

*Paper only. Nothing in this repository signs or sends an order or holds a key. Exploratory: the strategy parameters were fixed before
any live data was seen. Nothing was tuned on the sessions below, and nothing here was pre-registered as a confirmatory test.*

## 1. Verdict

**The engine works. The strategies lose money on real data.**

Engineering, verified:
- Real-time trade prints from every pump.fun bonding curve, decoded from the public Solana RPC (≈ 30 per second), plus 23 Gate meme
  pairs.
- A safety gate, three isolated sleeves and breakers. **The hourly-drawdown quarantine fired live**: `meme_momentum` lost 5.05 USD
  within the hour, was flattened and kept flat for 30 min, then resumed on probation at half size. The other sleeves were not
  touched.
- Throughput of ≈ 5,800 events/s. A 15-minute real-time smoke test ran at **548 fills/hour**, and its recorded tape replays to the
  identical result.
- Resident memory is **flat at 383 MB from minute 60 to minute 135** of a high-density soak (~630 fills/hour).
- 47 new tests; 347 in total, all passing.

Markets, measured. The full tables are in §2.

| evidence | result |
|---|---|
| live paper session, 60 min, 100 USD | equity **93.83 USD** (−6.17): `meme_momentum` 13 round trips at −8.4 % each, `breakout_scalp` 24 at −0.8 % each; `social_sentiment` idle (no X token) |
| every momentum signal on 1.75 h of recorded live pump.fun tape (192 signals, 135 tokens), entered at the curve price 0.8 s later | **gross** return −3.1 % at 10 s, −5.3 % at 30 s, −7.7 % at 60 s, −8.3 % at 120 s, *before* the 2.9 % round-trip cost; net t = −5.3 / −4.0 / −4.9 / −3.5 |

**Why it loses.**
- A visible buying burst on a pump.fun curve is, on average, the top. By the time a burst is observable and an order lands, the
  early buyers are selling into it.
- The gross move after the signal is negative, so no fee level or sizing rule can rescue this signal.
- Stop-losses do not cap the loss. One 5 USD position lost 74 % in 26 seconds when the curve gapped down between two prints.
- On top of that, every pump.fun round trip costs ≈ 2.9 % on 5 USD: 1.25 % fee each way plus network fees.
- Running anywhere near 1,000 fills an hour would multiply those costs. It would not create an edge.

**What this means for the 100 USD.**
- Do not trade this with real money. The evidence says the system as specified loses.
- The engine is still useful as a measurement instrument. It records, replays and scores any new idea against real meme-market data
  in minutes. That is how the next idea should be tested before it is believed.
- The forward-tested, forecast-free alternative in this repository remains Phase 13 (`docs/PHASE13_COMPLETE_SET_ARB.md`).

## 2. Sessions
