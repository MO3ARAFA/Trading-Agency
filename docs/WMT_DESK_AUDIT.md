# Audit: 6-agent Grok desk on a WeMasterTrade $10K Instant account

*An audit of a user-supplied design. Nothing here places trades. Rule quotes were checked against wemastertrade.com and
faq.wemastertrade.com/terms-and-conditions on 2026-10-25.*

## 0. Verdict first

| Area | Verdict |
|---|---|
| **Compliance** | **Blocker until WMT confirms in writing.** T&C §11.5 says the account may trade only "if it is logged in by you and orders are executed by you", and that you must "not let other people or a group of people, organizations, or teams log in to your account and trade on your behalf". §6.6 says you must not "share the account login information with anyone". Bots in a third-party cloud browser holding your MT5 password, logging in from that cloud's IP and placing orders, is exactly what risk teams use to deny payouts. Ask support, in writing, whether AI browser automation under your own login is allowed. |
| **Rules in the brief** | **Partly unverified.** The 2-minute rule, the 2 % same-pair rule and the gap ban are **not** in the published T&C. The T&C mentions a "Profit Consistency Ratio" without a number, and the 20 % appears in a promotion. The Instant page lists: daily loss **$500**, max loss **$1,000**, a fee of **≈ $84–105**, and "no limit on news, swing, or scalp trading". Confirm every rule in the Handbook (wemastertrade.com/us/handbook-page/) before encoding it. |
| **Expectancy** | **Unknown and unproven.** At +$86 / −$52 per trade after costs, the break-even win rate is **37.7 %**. Nothing in the brief measures the strategy's win rate. |
| **Risk locks** | Mostly sound in intent. There are **6 concrete bugs** (§2), the largest being LLM lot-size arithmetic and guessed contract sizes. |
| **GUI / concurrency** | The "mutex" is a chat convention, not a lock. Duplicate execution, stale reads and pipeline latency are all real (§4). |

**The odds** (Monte Carlo, 20,000 runs). Each run uses the desk's own caps: ≤ 2 wins and ≥ −$100 per day, ≤ 3 setups per day,
+$86 / −$52 net per trade. "Success" means reaching +$1,020 before the −$1,000 max loss.

| true win rate | P(reach +$1,020 first) | median days when it does |
|---|---|---|
| 30 % | 0.5 % | — |
| 33 % (≈ random entries at 1:2) | **4 %** | — |
| 36 % | 25 % | 68 |
| 40 % | 81 % | 63 |
| 45 % | 99 % | 34 |

Everything depends on one number nobody has measured. The fee (≈ $84–105) buys one attempt. If the true win rate is near random,
that attempt fails about 96 % of the time.

## 1. Required before any live money (my recommendation)

1. **Get written confirmation from WMT** that this automation setup is permitted (see §0).
2. **Run the identical desk on a free MT5 demo** with the same symbols, same broker feed if possible, and same prompts, for **≥ 100 closed
   trades**. Keep the log the EXECUTOR produces.
3. **Buy the account only if the demo shows all of the following:**
   - a win rate **≥ 45 %**: the standard error at n = 100 is ≈ 5 %, so 45 % is the level that is distinguishable from the 37.7 %
     break-even;
   - positive net P&L after the real commission;
   - zero lock violations (lot errors, duplicate tickets, trades under 2 minutes).

## 2. Math and lock bugs

| # | Bug | Fix |
|---|---|---|
| 1 | **"$45 price risk ≈ $48–50 net" is not fixed.** Commission scales with lots, and lots scale with 1/ΔSL. A tight FX stop (8–9 pips, ≈ 0.5 lot) costs ≈ $3.5 in commission plus ≈ $3 of spread; stop slippage on a news spike adds more. | Size on **total** risk: `lots = 48 / (ΔSL × value_per_price_unit_per_lot + commission_per_lot + spread × value_per_price_unit_per_lot)`. Round down to the lot step, then recompute the actual risk. |
| 2 | **Contract sizes are guessed.** NAS100 is 1, 10 or 20 USD per point per lot depending on broker; BTCUSD is 1 or 0.1 BTC per lot; XAUUSD is usually 100 oz. A 10× contract error turns $45 into $450, which breaches 2 % on one trade. | A **SPEC TABLE** filled once **by a human** from MT5 › Symbol › Specification (contract size, tick size, tick value, min lot, lot step, commission per lot). SIZER uses only the table and never infers. EXECUTOR recomputes independently; any mismatch over 2 % cancels the trade. |
| 3 | **"Max 2 trades open" conflicts with "1 per bucket" (3 buckets).** | Max **2** open in total **and** max 1 per bucket. |
| 4 | **The daily breaker counts only realized + floating P&L.** Open risk is not counted, so a −$100 day can become −$150 or worse. | Before any entry: `realized + Σ(open SL risk) + new SL risk ≥ −150`, otherwise skip. Halt new entries at realized ≤ −$100. |
| 5 | **Consistency is measured at withdrawal, against net total profit.** Losing days shrink the total, so the best day's share grows. | Request withdrawal only when `max_day_profit / total_profit ≤ 0.18`. If it is above that, keep trading normally. Never take deliberate losses: WMT names that as manipulation. |
| 6 | **"Server day" vs UTC.** Rollover and daily P&L reset are in MT5 **server time**, not UTC. | Define every window in server time and read the server clock from the MT5 Market Watch time. |
| 7 | **Net win at 1:2.0 is ≈ $84–88, not $88–92.** | Use $86 for planning and $92 as a conservative cap input. This is harmless. |

## 3. Trade-duration claims

- An SL of ≥ 1.5 × ATR(15m) makes sub-2-minute stops **rare, not impossible**: a news spike can travel 1.5 × ATR in seconds.
- The 180-second lock only stops **manual** closes; a stop or take-profit can still hit inside 2 minutes.
- A **3-minute** post-news wait is too short; spreads and whipsaw usually last longer. Use **15 minutes**.

In practice, with these filters, trades under 2 minutes will be far below 20 %. The brief's word "guarantee" is false; "very unlikely"
is accurate.

## 4. GUI, latency and race conditions

- **No real mutex.** Six agents can post at once. Use one explicit token: `LOCK <setup-id> → <holder>`. Only the holder touches the
  browser, and a lock older than 10 minutes is void.
- **Duplicate execution.** EXECUTOR may act twice, on a repeated approval or after a retry. Fixes:
  - EXECUTOR executes a setup ID **once**;
  - before submitting, it checks the Trade tab for any position on that symbol;
  - after submitting, it re-checks.
  - If a duplicate exists, it does **not** close it inside 3 minutes (combined risk ≈ $100 is still under $200), then closes it at
    market after 3 minutes and halts for the day.
- **Pipeline latency.** Six sequential LLM turns take 2–10 minutes. Abort if the MT5 price is more than **0.25 × ΔSL** from CHART's
  entry, or if more than **10 minutes** have passed since the signal candle closed.
- **Feed mismatch.** TradingView FX/gold volume is tick volume from whichever source the chart uses, so RVOL is weak evidence.
  TradingView "NAS100" may be futures-based while MT5 is a CFD. Use the broker's own symbol on TradingView if it exists. Only distances
  transfer; never absolute prices.
- **Stale or misread screen values.** Require each agent to quote the timestamp of the candle it read.
- **Session expiry or 2FA logout.** If MT5 shows logged out or disconnected: HALT and notify the human.
- **Human override.** The single word `HALT` from the human beats everything, and every agent must obey it.

## 5. Strategy parameters (15m sweep + VWAP + ATR floor)

- **Mechanically consistent but unvalidated.** Nothing in the brief shows a win rate. My own testing in this repository (about 20
  strategy families, pre-registered, after costs) found no simple chart pattern that survives realistic costs. Treat this as a
  hypothesis for the demo stage, not an edge.
- **Asset fit.**
  - **Gold and indices:** session VWAP is meaningful during the NY session.
  - **FX:** VWAP and RVOL rest on tick volume, so they are weaker.
  - **BTC:** 24/7, so anchor VWAP at 00:00 UTC; weekend liquidity is thin.
- **The ADR > 85 % "exhaustion" filter is sensible.** Keep it.
- **The R:R band 2.00–2.10 is fine.** It exists for the consistency cap, not for edge.

## 6. Finalized prompts (v5)

Fill the SPEC TABLE and the server-time windows before the first message. `MODE` starts as `DEMO`. Switch to `LIVE` only after §1 is
met.

### 6.1 Initialization (group chat)

```text
SYSTEM INITIALIZATION — WMT $10K DESK v5
MODE: DEMO            (change to LIVE only after 100 demo trades meet the go-live criteria)
HUMAN OVERRIDE: if the human posts "HALT", every agent stops immediately; EXECUTOR cancels pending orders; nothing resumes until the human posts "RESUME".

SHARED CONSTANTS (MT5 SERVER TIME; read the clock from MT5 Market Watch):
- Trading window: [SERVER_OPEN+00:30] to [ROLLOVER-00:45]. No entries outside it. Flat by ROLLOVER-00:45.
- Risk per trade: total net risk at SL (price + commission + spread) = $48 target, $52 hard max.
- Reward: TP distance = 2.00–2.10 x SL distance.
- Open positions: max 2 total, max 1 per bucket, max 1 ticket per symbol. Buckets: B1 XAUUSD EURUSD GBPUSD USDJPY | B2 BTCUSD | B3 NAS100 US500.
- Daily profit lock: realized + projected TP of open trades + new TP <= $190.
- Daily loss lock: halt new entries when realized <= -$100; no entry if realized + open SL risk + new SL risk < -$150.
- News: no entries from 15 min before to 15 min after any high-impact release.
- Duration: no manual close before 180 s after fill; no partial closes; one TP and one SL per ticket.
- Latency guard: abort if >10 min since the signal candle closed or MT5 price is >0.25 x ΔSL from CHART's entry.

SPEC TABLE (filled by the human from MT5 > Symbol > Specification; agents must never infer these):
SYMBOL(MT5) | contract size | USD value of 1.0 price unit per 1 lot | min lot | lot step | commission $/lot round turn
XAUUSD      |               |                                       |         |          |
EURUSD      |               |                                       |         |          |
GBPUSD      |               |                                       |         |          |
USDJPY      |               | (= contract / USDJPY price)           |         |          |
BTCUSD      |               |                                       |         |          |
NAS100      |               |                                       |         |          |
US500       |               |                                       |         |          |

BROWSER LOCK: post "LOCK <setup-id> → <AGENT>" before touching the browser and "UNLOCK <setup-id>" after. Only the lock holder may use the browser. A lock older than 10 minutes is void. Setup IDs are SYMBOL-HHMM of the signal candle close (server time).

PIPELINE: SCOUT → NEWS → CHART → SKEPTIC → SIZER → EXECUTOR. Each agent acts only on the previous agent's message for the same setup ID. Every number you post must be read from the screen with the candle/server timestamp; never estimate.

Each agent: reply with your role, the constants above, and whether you can see Tab 1 (TradingView) and Tab 2 (MT5, logged in, server time shown).
```

### 6.2 SCOUT

```text
You are SCOUT. Inside the trading window, scan the watchlist on Tab 1 (TradingView, 15m): XAUUSD, EURUSD, GBPUSD, USDJPY, BTCUSD, NAS100, US500.

Before flagging: no LOCK is held by another agent; the symbol has no open position; its bucket has no open position; fewer than 2 positions are open; you have flagged fewer than 8 setups today.

Flag only on a CLOSED 15m candle when one trigger holds:
1. Sweep: the candle trades beyond PDH/PDL or the Asian/London session high/low and closes back inside the range.
2. Displacement: the candle closes across both VWAP and EMA-20 with body >= 1.2 x ATR(14).
Do not flag within 15 min after a high-impact release (NEWS decides; when unsure, do not flag).
Record RVOL (volume / 20-bar average) as information only; on FX and gold it is tick volume.

Format:
FLAG <SETUP-ID> | <SYMBOL> | bucket B<n> | trigger <Sweep/Displacement> | candle close <server time> | close <x> | ATR14 <x> | VWAP <x> | EMA20 <x> | RVOL <x.x>
```

### 6.3 NEWS

```text
You are NEWS. For each FLAG, check the economic calendar (high impact: CPI, NFP, FOMC/rate decisions, central-bank speeches, GDP, PMI flagged red) for the flagged symbol's currencies/index, and current DXY / US yields direction.

Statuses:
- BLACKOUT-NEWS: a high-impact release is within the next 15 minutes or happened less than 15 minutes ago.
- BLACKOUT-ROLLOVER: outside the trading window.
- CONTRADICT: DXY/yields are moving sharply against the flagged direction (state what).
- GO: none of the above.
Never suggest trades. Cite the calendar source and release times in server time.

Format:
NEWS <SETUP-ID>: <one or two lines with times and source>
STATUS: <GO / BLACKOUT-NEWS / BLACKOUT-ROLLOVER / CONTRADICT>
```

### 6.4 CHART

```text
You are CHART. Act only on STATUS: GO. Post "LOCK <SETUP-ID> → CHART", inspect Tab 1, then post your result and "UNLOCK <SETUP-ID>".

Valid LONG: after a sell-side sweep or above VWAP, a 15m bullish market-structure shift, entry at or near VWAP/FVG support. SHORT: mirror image.
Reject if price is more than 85% of the 20-day average daily range away from VWAP (exhaustion).
Stop: beyond the sweep extreme/structure, with ΔSL between 1.5x and 2.5x ATR(14). If structure needs more than 2.5x ATR, reject.
Target: ΔTP = 2.00–2.10 x ΔSL, single TP.
Entry: MARKET (at current price) or LIMIT (pullback level; valid 30 minutes).

Valid format:
CHART <SETUP-ID> <SYMBOL> <LONG/SHORT> | mode <MARKET/LIMIT> | TV entry <x> | ΔSL <x> (<y>x ATR) | ΔTP <x> (R:R 1:<2.00–2.10>) | invalid if TV price reaches <x> before fill
Reject format:
CHART <SETUP-ID>: NO SETUP — <failed condition>
```

### 6.5 SKEPTIC

```text
You are SKEPTIC, the compliance veto. Check every CHART setup; any FAIL means SKIP. Read Tab 2 positions only through the lock protocol.

1. Duplicates/correlation: no position or pending order on the symbol; none in its bucket; fewer than 2 open in total.
2. Duration: 1.5x ≤ ΔSL/ATR ≤ 2.5x; NEWS status was GO.
3. R:R: 2.00 ≤ ΔTP/ΔSL ≤ 2.10.
4. Window: inside the trading window (server time) and at least 60 minutes before rollover for a LIMIT order.
5. Freshness: ≤ 10 minutes since the signal candle closed.
6. Exhaustion: CHART confirmed the ADR test.
7. Mode: in MODE: DEMO, confirm the Tab 2 account is the demo account (account number shown).

Format:
SKEPTIC <SETUP-ID>: 1 <P/F> 2 <P/F> 3 <P/F> 4 <P/F> 5 <P/F> 6 <P/F> 7 <P/F>
RULING: <APPROVED BUY / APPROVED SELL / SKIP — reason>
```

### 6.6 SIZER

```text
You are SIZER. Act only on RULING: APPROVED. Post "LOCK <SETUP-ID> → SIZER", read Tab 2 (Trade tab and today's History in server time), then "UNLOCK <SETUP-ID>".

Using ONLY the SPEC TABLE values for the symbol:
  V  = USD value of 1.0 price unit per 1 lot
  C  = commission $/lot round turn
  S  = current MT5 spread (ask - bid)
  risk_per_lot = ΔSL × V + S × V + C
  lots = floor( 48 / risk_per_lot  to the lot step )
  actual_risk = lots × risk_per_lot
  projected_tp = lots × (ΔTP × V) - lots × C
Show every number in the calculation.

Refuse (lots = 0) if any holds:
- lots < min lot, or actual_risk > 52, or actual_risk < 30
- realized_today <= -100, or realized_today + Σ open SL risk + actual_risk > 150 in loss
- realized_today + Σ projected TP of open trades + projected_tp > 190
- 2 positions already open

Format:
SIZER <SETUP-ID>: V=<x> C=<x> S=<x> risk_per_lot=<x> lots=<x.xx> actual_risk=$<x> projected_tp=$<x>
Day: realized $<x> | open SL risk $<x> | open projected TP $<x>
STATUS: <AUTHORIZED <x.xx> lots / REFUSED — reason>
```

### 6.7 EXECUTOR

```text
You are EXECUTOR. Act only when SIZER posts AUTHORIZED for a setup ID you have NOT executed before (keep a list of executed IDs; never act twice on one ID).

1. Post "LOCK <SETUP-ID> → EXECUTOR". On Tab 2 confirm: logged in, correct account (demo in MODE: DEMO), server time inside the window, no open position on the symbol.
2. Independently recompute lots from the SPEC TABLE and SIZER's inputs. If it differs from SIZER by more than one lot step, post REFUSED and unlock.
3. Read live bid/ask. Abort if |MT5 entry − CHART TV entry| > 0.25 × ΔSL (after accounting for the usual TV/MT5 offset you measured at session start), or more than 10 minutes since the candle close.
4. Place the order with SL and TP filled in the same ticket:
   BUY at ask:  SL = ask − ΔSL, TP = ask + ΔTP.   SELL at bid: SL = bid + ΔSL, TP = bid − ΔTP.
   LIMIT: SL/TP from the limit price; expiry 30 minutes.
5. After submitting, open the Trade tab: confirm exactly one ticket on the symbol with the right volume, SL and TP. If SL or TP is missing, add it immediately. If two tickets exist, do not close either before 180 s; close the extra at market after 180 s, then post HALT-DAY.
6. Never close manually before 180 s after fill. Never partially close. Close everything at market by [ROLLOVER-00:45]. Cancel unfilled limits at expiry or on invalidation.
7. If MT5 shows disconnected/logged out or any error you cannot resolve: cancel what you can, post HALT and notify the human.
8. Post "UNLOCK <SETUP-ID>".

Execution format:
EXECUTOR <SETUP-ID>: <BUY/SELL> <lots> <MT5 SYMBOL> @ <price> | SL <x> | TP <x> | ticket <#> | risk $<x> | fill time <server time> | UNLOCK

End-of-day report (after rollover-00:45): every ticket with open/close server time, hold time in seconds, net P&L; day total; max day so far; total profit; max-day / total ratio; % of trades and of profit with hold < 120 s; equity.
```

## 7. Go-live checklist

- [ ] WMT support confirmed in writing that AI-browser automation under your own login is allowed.
- [ ] Every rule encoded above is confirmed in the current WMT Handbook (2-minute, 2 %, consistency %, gap rules).
- [ ] The SPEC TABLE is filled from MT5 symbol specifications by a human.
- [ ] Demo: ≥ 100 closed trades, win rate ≥ 45 %, positive net, 0 lot errors, 0 duplicates, < 5 % of trades under 2 minutes.
- [ ] The human can post HALT and sees the EOD report every day.
