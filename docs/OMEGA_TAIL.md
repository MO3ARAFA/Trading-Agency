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
