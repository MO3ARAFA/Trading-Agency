# Phase 1 — Open-source intelligence & reconnaissance

What I searched (GitHub code/repo search + web search, 2026-10-19), what I found, and **exactly where each idea lives in this codebase**.
Star counts are as returned by GitHub at search time. I did not vendor any third-party code; the patterns were re-implemented.

## 1. Methods / papers

| Source | What it gave us | Where it is in the code |
|---|---|---|
| **Hayashi & Yoshida (2005)** cross-covariance for asynchronous ticks; lead-lag estimation by maximising the shifted HY contrast — Hoffmann, Rosenbaum & Yoshida, [arXiv:1303.4871](https://arxiv.org/pdf/1303.4871v1) | Lead-lag estimation on non-synchronous data **without a sampling grid** (no previous-tick interpolation → no Epps bias). Lead/lag = argmax of the shifted HY correlation. | `mathkit.hy_cov`, `hy_leadlag`, `leadlag_summary` (numba, `nogil`, O(n+m) per lag). `LeadLagModel.calibrate_*` |
| Huth & Abergel, [High Frequency Lead/lag Relationships — Empirical facts, arXiv:1111.7103](https://arxiv.org/pdf/1111.7103) | Lead-lag is asymmetric and must be judged by the **peak lag and its magnitude together**, not by contemporaneous correlation. | `leadlag_summary` returns peak lag, peak corr, ρ(0) and a response *decay* span; the hunter uses lag+decay to size each market's opportunity window. |
| [Price Discovery in Cryptocurrency Markets, arXiv:2506.08718](https://arxiv.org/pdf/2506.08718) | HY lead-lag measures + a lead-lag ratio on trade times in crypto. | Motivates the HY lag grid including **negative lags** (market leading BTC) — `lag_grid_s = (-0.5, 3.0, 0.1)`. |
| [A Note on Asynchronous Challenges: Formulaic Bias and Data Loss in the HY Estimator, arXiv:2404.18233](https://arxiv.org/pdf/2404.18233) and the microstructure-noise caveat on HY | HY is biased under noise / tick bounce. | We use HY only to identify the **lag**; β and the gating correlation come from a window-OLS at that lag (HY correlation is not bounded by 1 — we saw 1.12 in testing). |
| CBS thesis *High Frequency Lead-Lag Relationships in the Bitcoin Market* (tick-level, cross-exchange); Tokyo Tech study of BTC→small-cap-altcoin lags | Lead-lag in crypto exists but is liquidity-dependent; small caps lag more. | Universe = top-volume USDT markets + cross-venue BTC/ETH/SOL; per-market lag/β, never a global one. |
| **Stoikov (2018), *The micro-price: a high-frequency estimator of future prices***, Quantitative Finance 18(12) · replication on Binance data: [shaileshkakkar/MicroPriceIndicator](https://github.com/shaileshkakkar/MicroPriceIndicator) (78★) | Imbalance-weighted fair price `P_micro = I·P_ask + (1−I)·P_bid`, `I = Q_bid/(Q_bid+Q_ask)` is a better short-horizon predictor than mid. | `mathkit.micro_price`, `obi`; the BTC oracle's impulse series is the **micro-price** so BTC order-book imbalance enters `Gap` through the reference move. (We implement the first-order weighted micro-price; the full Markov-adjusted `G*` iteration is future work.) |
| Kalman dynamic hedge ratio (pairs-trading literature; examples e.g. [sharathStack/Statistical-Arbitrage-Pairs-Trading-Engine](https://github.com/sharathStack/Statistical-Arbitrage-Pairs-Trading-Engine), small hobby repo — pattern is textbook) | Scalar random-walk state for the regression coefficient. | `mathkit.kalman_beta_step`, `LeadLagModel.update_online` — β is *lag-aligned*: `Δmid_i(t)` vs `ΔBTC(t − ℓ*)`. |
| [OpenMarket (arXiv:2607.26245)](https://arxiv.org/pdf/2607.26245) — ms-level Polymarket–Binance dataset | Large Binance BTC moves precede *other venues'* quote responses by hundreds of ms on the collector clock — i.e. the effect is real but small and latency-sensitive; authors report null/descriptive results, not alpha. | Sets the honest expectation in the report caveats; cross-venue (Gate/Kraken) watchers are included for the same reason. |

## 2. Libraries / architectures

| Repo | Stars | Pattern borrowed |
|---|---|---|
| [nkaz001/hftbacktest](https://github.com/nkaz001/hftbacktest) | 4.9k | **Latency-aware, queue-conservative fill simulation on full tick data.** → `execution_engine.PaperExchange` logic: order-entry latency, fills priced from the **as-of quote at arrival time** (no look-ahead), IOC partial fills capped by displayed size, post-only orders that would cross are rejected, maker fills only when the market trades *through* the resting price. |
| [nautechsystems/nautilus_trader](https://github.com/nautechsystems/nautilus_trader) | 30.3k | **Deterministic, clock-injected, event-driven core**: the same code path runs live and in replay. → `Agency` is synchronous & clock-injected (`on_quote(t,…)`, `scan(t)`, `housekeeping(t)`); asyncio only lives in `feeds.py`. Live tape → `--replay` reproduces runs (tested). |
| [bmoscon/cryptofeed](https://github.com/bmoscon/cryptofeed) | 2.9k | Normalised multi-exchange L1 `Quote` handlers over asyncio websockets with per-feed reconnect. → `feeds.FeedManager`: one reconnecting runner, venue-specific handlers (Binance combined stream, Gate `spot.book_ticker`, Kraken v2 `ticker/bbo`). |
| [KinH8/Hayashi-Yoshida-estimator](https://github.com/KinH8/Hayashi-Yoshida-estimator) (15★), R `yuima::llag`, a Python `lead_lag` module | — | Reference implementations used to sanity-check the HY kernel semantics (we validate against **planted** lag/β in `tests/test_mathkit.py`). |

## 3. High-speed Python stack (what's actually installed and used)

`asyncio` + **`uvloop`** (event loop), **`orjson`** (≈1 µs parse), **`websockets` 17** (`compression=None`), **`numba`** (all hot kernels, `cache=True`; calibration kernels are `nogil` and run in a worker thread so HY recalibration never stalls the event loop), **`numpy`** struct-of-arrays books and logical-index ring buffers (`mathkit.ring_asof` = binary search on a wrapped ring).

Measured here (cloud container, via egress proxy): per-quote book update ≈ 0.8 µs, oracle update ≈ 1.1 µs, a full hunter scan over 66 markets p50 ≈ tens of µs / p99 ≈ 0.4 ms. See the live report for the run's own latency table.

## 4. Cloud-connectivity bypass (probed, not assumed)

| Endpoint | Result from this container |
|---|---|
| `wss://data-stream.binance.vision/stream?streams=…` (port 443) | ✅ ~1,000 msgs/s for 62 books + aggTrade on **one** connection |
| `https://data-api.binance.vision` | ✅ (24h tickers, exchangeInfo for tick/step/min-notional) |
| `api.binance.com` | ❌ HTTP 451 (geo-block) · `data-stream.binance.vision:9443` ❌ reset |
| Gate `spot.book_ticker`, Kraken v2 `ticker (event_trigger=bbo)` | ✅ BBO-level updates |
| Coinbase `ticker` | ✅ but trade-triggered (not BBO) → not used |
| Bybit, OKX WS | ❌ 403 / reset |

**Design consequence:** BTC and every alt share *one* Binance connection, so their relative arrival order equals the venue's publication order (no inter-connection jitter polluting the lead-lag estimate).


## 5. Phase 4 reconnaissance (probed 2026-10-19, from this container)

| Endpoint | Result |
|---|---|
| Binance Vision `bookTicker`/`exchangeInfo` | ✅ only ~7 markets had spread < 0.5 bps (BTCUSDC, ETHUSDC, BTCFDUSD, ETHFDUSD, BNBUSDC, BNBUSDT, ETHUSDT); ETHBTC 3.4 bps; `FDUSDUSDT` did not quote |
| Coinbase Exchange WS | ✅ `ticker` (trade-triggered) and `level2_batch` (full book → true BBO, used); Advanced Trade `level2` snapshot exceeds 4 MB frames |
| Hyperliquid | ✅ WS `bbo` per coin; `/info` is POST-only (GET → 405) |
| Deribit | ✅ WS `quote.<instrument>` (perp BBO) |
| Polymarket Gamma + CLOB WS | ✅ reachable. BTC families: daily `above`, daily brackets, hourly Up/Down (**resolves on Binance BTC/USDT 1H candle**), 5m/15m/4h Up/Down (Chainlink BTC/USD 60 s TWAP). Taker fee schedule `0.07·p·(1−p)`, makers free; tick 0.001 (thresholds) / 0.01 (Up/Down) |
| OKX WS, Bybit | ❌ (reset / 403) · Bitget, KuCoin, MEXC REST ✅ (unused) |

Design notes: Polymarket fair values are driftless-lognormal digitals/TWAPs under the oracle's realised vol; signals use the *change* in fair value vs the *change* in CLOB mid over the BTC-impulse horizon so a persistent implied-vol mismatch cannot look like a gap; a momentum control separates lag-closure from continued BTC drift.
