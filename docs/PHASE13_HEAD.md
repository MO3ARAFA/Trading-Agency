*Paper only. No order was sent, no credential exists in this repository. Why Phases 1–12 never made money, and the plan:
`docs/AUDIT_AND_PLAN.md`.*

## 1. Verdict

**Not yet shown to be profitable.**
- The evidence supports a small, forecast-free edge, and the tests below found nothing that contradicts it.
- In one hour the engine scanned 7,546 live Polymarket NegRisk events every 24 s. It bought 5 complete sets on paper, filling the
  100 USD account.
- Those sets lock **+1.385 USD** at resolution: 1.39 % of the capital, capital-weighted ≈ **17 % a year**. Every fill was still
  fillable 3 s later.
- That is locked, not realised. Nothing has settled; the first event resolves in about 9 days and the last in about 48.

Three tests stand behind it:

| question | test | result |
|---|---|---|
| Does a complete set pay what it should? | 48,443 closed NegRisk events, paid at the venue's resolved prices (§2) | plain events: **0 losses in 39,390** once two tie-prone families are excluded (12 losses in 47,180 before); augmented events fail 5 %, so they are never used |
| Are the fees what the schedule says? | fill events decoded from Polygon receipts of public trades (§1b) | all **27 legs of the 5 filled events** were charged 0 on-chain, as their `zero_fees` schedule says (one 0.00005 USD rounding); 59 of 61 markets overall matched |
| Can it be executed? | 0.5 s re-read before filling, 3 s re-read after, own takes subtracted from later books (§3) | **5 of 5** fills could still be bought at the same size and profit 3 s later; 2 of 7 opportunity events vanished within 0.5 s |

What this is in money:
- 100 USD earns about 1.4 USD per 10–50-day cycle. If the yield holds that is roughly **15–20 USD a year**, and only if the account is
  re-deployed as soon as each event resolves.
- **Capital is the bottleneck, not opportunities.** 57 opportunities were refused only because their event (25 USD) or the account
  (100 USD) was full.
- The "first dollar" is already locked on paper. It is paid on resolution, provided §4 settles with no shortfall.

What it is not:
- It is not proof. That needs settled positions, sessions on more days, and a real executor. The release gate is §6, and none of it is
  met yet.
- **No real money should be used until then**, and never without the owner's explicit approval.
- Under the stressed fee (0.05 on every fee-enabled leg) the same fills lose money (§3). The edge exists only because these markets
  charge no taker fee, which the chain confirms today. If Polymarket switches these markets to category fees, the strategy stops
  working. The engine's `--fee-stress` reading shows that at once.
