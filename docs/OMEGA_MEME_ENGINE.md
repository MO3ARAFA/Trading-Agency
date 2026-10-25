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

### Live: pump.fun (Solana RPC) + 23 Gate meme pairs, 60 min, 100 USD

`live_20261024_231441` · 60 min of market time · 177,577 trade prints · 396,906 quotes · 1,722 launches · 0 tweets

**74 fills (74 per hour)**, 37 round trips, 0 failed transactions, account equity **93.83 USD** (from 100.00). Resident memory 115 → 322 MB (first / largest status sample).

| sleeve | round trips | win rate | mean net / trade (USD) | ± s.e. | mean net / trade (% of cost) | fees paid (USD) | gross before fees (USD) | net (USD) | hold (median s) |
|---|---|---|---|---|---|---|---|---|---|
| breakout_scalp | 24 | 21% | -0.0387 | 0.0063 | -0.78 % | 0.475 | -0.453 | -0.929 | 4 |
| meme_momentum | 13 | 15% | -0.4032 | 0.2865 | -8.35 % | 1.337 | -3.905 | -5.242 | 27 |

Exit reasons: stop 20, sell_pressure 6, take_profit 5, trail 3, time_stop 2, governance_flatten 1

| sleeve × fill model | n | net (USD) | mean (USD) |
|---|---|---|---|
| breakout_scalp × depletion | 16 | -0.7454 | -0.0466 |
| breakout_scalp × primary | 24 | -0.9287 | -0.0387 |
| breakout_scalp × strict | 6 | -0.1773 | -0.0295 |
| meme_momentum × adverse | 13 | -5.2420 | -0.4032 |
| meme_momentum × adverse_exit | 5 | -4.1476 | -0.8295 |
| meme_momentum × primary | 13 | -5.2420 | -0.4032 |

Governance: meme_momentum QUARANTINE (hourly drawdown 5.05 USD >= 5.00; flat until +1800s); meme_momentum PROBATION (cool-down over: resume at 0.5x size)

pump.fun entries: mean entry cost 1.58 % of notional (curve fee + network), mean latency 1.06 s, mean slippage vs decision price +0.41 %.

### Smoke test: synthetic market in real time, density 4, 15 min (mechanics only; the P&L is a property of the generator)

`synth_20261024_231833` · 15 min of market time · 515,111 trade prints · 57,455 quotes · 2,208 launches · 197,845 tweets

**137 fills (548 per hour)**, 68 round trips, 0 failed transactions, account equity **123.30 USD** (from 100.00). Resident memory 95 → 296 MB (first / largest status sample).

Processed 772,621 events in 900 s of wall time (858 events/s).

| sleeve | round trips | win rate | mean net / trade (USD) | ± s.e. | mean net / trade (% of cost) | fees paid (USD) | gross before fees (USD) | net (USD) | hold (median s) |
|---|---|---|---|---|---|---|---|---|---|
| breakout_scalp | 6 | 17% | -0.0274 | 0.0161 | -0.55 % | 0.120 | -0.045 | -0.164 | 107 |
| meme_momentum | 62 | 76% | +0.3789 | 0.0537 | +7.58 % | 10.393 | +33.882 | +23.490 | 22 |

Exit reasons: take_profit 39, trail 19, stop 8, time_stop 1, sell_pressure 1

| sleeve × fill model | n | net (USD) | mean (USD) |
|---|---|---|---|
| breakout_scalp × depletion | 5 | -0.1616 | -0.0323 |
| breakout_scalp × primary | 6 | -0.1644 | -0.0274 |
| breakout_scalp × strict | 3 | -0.1453 | -0.0484 |
| meme_momentum × adverse | 62 | +22.4892 | +0.3627 |
| meme_momentum × adverse_exit | 50 | +17.9860 | +0.3597 |
| meme_momentum × primary | 62 | +23.4897 | +0.3789 |

Governance: no breaker fired.

pump.fun entries: mean entry cost 1.61 % of notional (curve fee + network), mean latency 0.97 s, mean slippage vs decision price +0.55 %.

### Every momentum signal on the recorded live tapes

`omega_signal_study.py` on 4 recorded live tapes (1.75 h; the first three are the sessions restarted after the bug fixes noted in §5, the fourth is the 60-min session above): **192 signals on 135 tokens**, at most one per token per 60 s, same conditions as the engine. Entry at the curve price as of +0.8 s, exit as of +h; round-trip cost of a 5 USD trade = 2.93 % (SOL 101.98 USD). Standard errors clustered by token.

| horizon | n | tokens | gross mean | ± s.e. | median | p10 / p90 | net mean | t (net) | share beating the cost |
|---|---|---|---|---|---|---|---|---|---|
| 10 s | 191 | 135 | -3.14 % | 1.14 % | +0.00 % | -21.1 % / +8.7 % | -6.07 % | -5.32 | 24 % |
| 30 s | 187 | 131 | -5.30 % | 2.05 % | -1.55 % | -35.5 % / +15.5 % | -8.23 % | -4.01 | 28 % |
| 60 s | 184 | 129 | -7.72 % | 2.18 % | -4.81 % | -39.0 % / +15.6 % | -10.65 % | -4.89 | 24 % |
| 120 s | 176 | 121 | -8.34 % | 3.23 % | -10.99 % | -42.5 % / +19.8 % | -11.27 % | -3.49 | 23 % |
| 300 s | 149 | 97 | -1.68 % | 6.34 % | -13.10 % | -44.6 % / +26.8 % | -4.61 % | -0.73 | 28 % |

The gross move is negative at every horizon up to 2 minutes. About a quarter of the signals beat the cost, which is what lets a few trades look good, but the typical signal loses. At 300 s the mean recovers because of a few very large winners (p90 +27 %); the median is −13 %. That is the lottery-ticket shape of meme tokens, not an edge a 2-5 USD account can harvest reliably.
### Memory soak (synthetic, density 4, as fast as possible)

Resident memory of the whole process (engine + synthetic generator) every 15 minutes of market time, 151 minutes, 1583 fills (629 per hour):

| market minute | 0 | 15 | 30 | 45 | 60 | 75 | 90 | 105 | 120 | 135 | 150 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| RSS (MB) | 95 | 301 | 366 | 373 | 383 | 383 | 383 | 383 | 383 | 383 | 385 |

It rises while the time windows fill: the 1-hour social windows, the 30-minute token TTL and the rolling-hour equity history. Then it is flat. The bounded-footprint test (`test_engine_state_is_bounded_over_synthetic_hours`) checks the same thing container by container.
## 3. Architecture

```
 public Solana RPC (logsSubscribe, pump program) ──► TradeEvent / CreateEvent decoder ──┐   meme_discovery.py
 Gate spot.book_ticker + spot.trades (meme pairs) ──────────────────────────────────────┤   (invoke-stack attribution,
 DexScreener profiles / boosts (X handles) ─────────────────────────────────────────────┤    plausibility, LRU universe,
 Solana RPC getAccountInfo + RugCheck /report ──► SafetyChecker ──► SafetyGate ─────────┤    numba ring windows)
 X API v2 recent search (only with X_BEARER_TOKEN) ──► SocialBook ──► Social Alpha Score ┤   x_sentiment_crawler.py
                                                                                        ▼
                    HFPaperEngine (sync, clock-injected)  hf_paper_engine.py
                    strategies: meme_momentum · social_sentiment · breakout_scalp
                    sizing (2–5 USD, 1.5 % risk, exchange minimums) → pending order (latency)
                    → fill model (curve as-of landing + adverse; Gate taker; queue strict/trades/depletion)
                    → position → exits (stop / take-profit / trail / time / creator dump / sell pressure)
                                                                                        ▼
                    OmegaCEO + SleeveBook ×3  omega_governance.py
                    rolling-hour drawdown ≥ 5 USD → QUARANTINE + flatten → PROBATION (½ size) → NORMAL
                    account −20 USD or KILL file → HALT; ≤ 1,000 fills / rolling hour
                                                                                        ▼
                    omega_daemon.py: live / synthetic / replay, tape (gzip, rotated), audit JSONL (5 min),
                    warm state (60 s, --resume), status + RSS (30 s), summary at exit
```

All the components are new. They follow the design of the earlier phases: the isolated sleeves of `sleeves.py` and the queue models of
`queue_model.py`, reused unchanged. Existing modules and their tests are untouched.

## 4. Costs: what a trade has to beat

| venue | per side | round trip on a 5 USD trade | on a 2 USD trade |
|---|---|---|---|
| pump.fun bonding curve | 1.25 % curve fee (95 bps protocol + 30 bps creator, read from the venue's own trade events) + 0.000105 SOL network fee (base + priority; ≈ 0.011 USD at the session's 102 USD/SOL) | **≈ 2.9 %** + slippage | ≈ 3.6 % |
| Gate spot | 0.20 % (pair fee) + half the spread | ≈ 0.4–0.6 % | same; minimum order 3 USD |

At 1,000 fills an hour (500 round trips) of 5 USD on pump.fun, costs alone are ≈ **73 USD an hour**. Trading that often only works if each
trade beats ≈ 2.9 % on average, after the latency between seeing a burst and landing on the curve. The trade count is a capacity limit
enforced by the CEO, not a target. The engine trades only when a signal fires.

## 5. What is and is not proven

**Proven by tests and runs:**
- Decoding of real pump.fun trade events.
- Fill and fee arithmetic, the three queue models, the breakers, and sleeve isolation.
- Kill file, rate cap, bounded state, identical replay of a recorded tape, warm-state resume.
- Throughput far above the live event rate.

**Not proven:**
- Any edge. The synthetic market's P&L is a property of a generator I wrote: its "organic" pumps trend by construction.
- The live session is the only market evidence, and it is short.
- The social sleeve has not run on real X data: no API token is configured. Its bot filter is verified only on synthetic tweets.

**Known simplifications:**
- Exits on the curve always fill: no slippage limit on sells. That is optimistic only when a seller would otherwise wait.
- Sizes beyond the displayed Gate top-of-book pay a flat 10 bps.
- MEV / sandwich risk on Solana is not modelled.
- Latency is a fixed 0.8 s plus the time to the next print.
- PumpSwap / Raydium pools of migrated tokens are not decoded yet.

**Bugs the live runs caught, all fixed before the 60-minute session** (the first three tapes come from these restarted sessions; their
market data is valid, their paper P&L is not used):
- A governance event's `kind` field collided with the audit logger's argument, so the first breaker event would have crashed the poll
  loop. Worse, in an async daemon a crashed task dies silently. Callbacks are now guarded, a dead task stops the run visibly, and 20
  repeated errors halt the account.
- Tape rotation asked a text-mode gzip handle for its file position and failed after 20,000 events. It now uses the raw compressed
  file.
- A passive fill was booked one market event late.
- The public Solana RPC answers `getTokenLargestAccounts` with HTTP 429 from shared IPs. Every safety check failed, so the gate
  correctly refused every momentum trade. Holder data now comes from RugCheck, and authorities still come from the mint account on
  chain.
- An early estimate of the memory footprint grew without bound: a per-symbol de-duplication set held up to 20,000 IDs, and idle social
  trackers lived a full hour. Both are bounded now (see the soak table).
- There was no evidence in the repository of the "1.5 MB/min leak" the brief mentions. The bound is now tested either way.

## 6. Operating it

```bash
pip install -r requirements.txt && python -m pytest tests -q
python -m quant_agency.omega_daemon --continuous --out runs/omega                    # 24/7, live feeds, paper only
python -m quant_agency.omega_daemon --continuous --duration 3600 --record            # one recorded hour
python -m quant_agency.omega_daemon --continuous --resume runs/omega/<run>/omega_state.json
python -m quant_agency.omega_daemon --synthetic --duration 900 --speed 1 --density 4 --record   # 15-min smoke, ~550 fills/h
python -m quant_agency.omega_daemon --replay runs/omega/<run>/tape.jsonl.gz --speed 0
touch runs/omega/KILL                                                                # halt every sleeve
python -m quant_agency.omega_report --runs runs/omega/<run> --out report.md
export X_BEARER_TOKEN=...                                                            # optional: enables the social sleeve (official API)
```

For a real 24/7 deployment, run it under a supervisor that restarts it with `--resume` (systemd `Restart=always`, or `while true;
do ...; done`). The daemon exits on its own when a feed task dies, so the supervisor sees the failure instead of a silent hang.

**Real money:** there is no order-signing code, and none should be added before all of the following hold, with the owner's explicit
approval:
1. A positive, statistically significant net result on live paper data the parameters were not tuned on (a pre-registered test, as
   in Phases 8–11).
2. Settlement of the cost model against a handful of real minimum-size trades.
3. An external kill switch and a dedicated wallet holding only the risk capital.
