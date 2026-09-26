# Implementation Audit — 2026-09-25

**Status: read-only research build. Live order submission is disabled; no profitability or win rate has been established.**

The former `main.py` placed orders directly from uncalibrated heuristics. Its existing August audit correctly identified several blockers; this update records what was verified and changed. The original source remains in Git history. The original read-only build had no credentials; a subsequent private diagnostic inspected account state via GET only. Account-specific numbers are not included in this public audit.

## Critical findings

| Severity | Finding | Status |
| --- | --- | --- |
| Critical | V2 `ask` is **sell YES at a YES price**; code treated it as buy NO at a NO price. The old NO exit had the same price-unit error. | **Blocked**, not trusted or reused. V2 source remains for inspection, but all POST/DELETE requests now raise before network access. |
| Critical | Exit logic removed a local position even if IOC filled zero, partially filled, failed, or the fallback merely placed a resting order; restarts lost state. | **Unresolved**; old position manager not invoked by `main.py`. No live trading until exchange-state reconciliation and exits are rebuilt/tested. |
| Critical | `get_positions()` returned `[]` on API error, confusing unknown holdings with flat exposure. | **Improved**: read failure raises; paginated results are collected. A later private authenticated GET checked balance, positions, orders, and recent fills; continuous trade-time reconciliation remains unimplemented. |
| High | Old win rate counted a winning partial exit as a full trade, divided by all entered trades including open ones, ignored fees, and printed cash change as P&L. | **Unresolved in legacy module; not computed** by read-only observer. |
| High | The old matcher could select a same-team market on a different day, because it ignored ESPN/Kalshi scheduled event times. | **Improved**: exact MLB suffix + both teams under one event + <=4h scheduled-time difference; missing date refuses match. |
| High | The market-list quote is not necessarily executable or recent; no depth/slippage check or fee-adjusted expected return. | **Improved for observation**: fetch a fresh book, derive ask from opposing best bid, validate liquidity, and log bid/ask and estimated fees. No claim of achievable fills. |
| High | Weather scan used incompatible keyword arguments; invalid target date substituted tomorrow, UKMO was omitted from probabilities, and NWS comparison ignored target date. | **Isolated**: weather not traded; date substitution removed, UKMO included, NWS date checked, Gaussian fallback removed. Weather strategy and settlement semantics still unvalidated. |
| High | ESPN score polling every 10 seconds cannot establish an information-latency advantage; model fair values for MLB/tennis/weather have no calibrated out-of-sample evidence. | **Unresolved**; observer logs heuristic candidates only. No live or paper win rate inferred. |

## Reproduction

```bash
python3 -m unittest discover -s tests -v
python3 audit_integration.py
python3 main.py --cycles 6 --interval 10 --output logs/shadow_observations.jsonl
python3 main.py --live  # must fail before order submission
```

No Kalshi backtest server is required. Tests mock all requests. The observation command contacts only public ESPN and Kalshi GET endpoints and exits after a bounded number of cycles. JSONL logs under `logs/` are ignored by Git. Kalshi authenticated writes are blocked independently of the command-line flag.

**Observed on 2026-09-25, 21:11–21:12 UTC:** six consecutive 10-second scans saw one MLB game in progress per scan, zero score changes, zero strictly matching same-time Kalshi markets, zero heuristic candidates, zero quote errors, and zero orders. Six two-sided orderbook probes for an **unmatched** future market succeeded; one sample showed YES bid `$0.45`, YES ask `$0.48`, and depth `284.73` at the ask. This proves public quote connectivity, **not** strategy effectiveness or a hypothetical fill. The prior one-cycle smoke check produced the seventh `cycle` journal row. Win rate is **undefined (0 resolved trades)**, not 0% or 100%.

**Read-only weather check on 2026-09-25:** 191 returned members for NYC 2026-09-26 (ECMWF + AIFS 102, GFS 31, ICON 40, UKMO 18). The advertised fixed count 209 was not observed; neither the empirical ratio nor the code's confidence score is a calibrated settlement probability.

**Private legacy upload checked separately:** configuration files were excluded from the public repository, review bundles, tests, and PR. Read-only diagnostics (`account_preflight.py` and `account_performance.py`) are available, but account-specific results remain local under Git-ignored `logs/`. Historical account-wide P&L is **not** attributable to this bot; a single synthetic `TEST-TICKER` with no outcome in the older local trade-history file is not evidence of profitability.

**Legacy code comparison (static only):** the older execution loop could treat a canceled/unknown order as released exposure, drop a partially filled position, omit a NO-side exit, and bypass stated exposure caps. Its capital ledger and stop-loss paths were not actually wired into a single authoritative gateway. The older arbitrage/scalping strategies used incompatible price/quantity interfaces and did not establish executable, fee-adjusted returns. The desktop “Kelly” widget was a **manual percentage-of-account display**, with no probability, price, payoff, fee, or edge inputs; it incorrectly sized against cash plus position mark and submitted no trades. The safe elements to retain are explicit read-only account checks, strict quote validation, separate decision/risk/execution layers, and manual intervention as a boundary—not the old order implementations or profitability language.

**Additional safety implementation, 2026-09-25 21:36–21:50 UTC:** pure V2 arithmetic now tests all four YES/NO buy/sell directions, pilot sizing never forces a minimum trade without a positive calibrated net edge, and an exclusive SQLite journal persists prepared/submitting/uncertain/partial-fill/partial-exit states across restarts. It blocks a timeout retry, duplicate ID conflict, unknown order, unreconciled venue position, and unowned exit. These components are **not connected to a live POST**; write blocking remains at the client boundary. A separate one-shot account viewer now combines live and archived fills, cross-checks an open holding against venue quantity, and uses a fresh two-sided orderbook to show a private estimated liquidation value (or `unavailable`); no existing position was sold or adopted by the bot. Shadow performance only values hypothetical short-horizon exits that were actually observed and deep enough; it does not call them fills or wins.

**Fresh public scan:** two MLB games in progress, zero strict same-time matched markets, zero candidates, zero orders. Continuing to poll this universe does not by itself create a calibrated signal. A model-verified eligible market, real fee schedule, authenticated live order-status/fill synchronization, durable operation, and supervised kill switch are still required before an actual trading pilot.

**Follow-up read-only scan:** six additional cycles each saw two live MLB games, no strict matched market, no candidate, and no real order. The short-horizon shadow evaluator returned an undefined positive rate because there were **zero candidates and zero observed hypothetical exits**. An authenticated GET-only journal worker successfully checked a new, private empty bot journal: **zero bot-originated intents**, independently of any user-owned exchange positions. This verifies the reconciliation interface on an empty journal, **not** a real-order lifecycle on Kalshi.

**Independent adversarial review and remediation:** the position viewer originally mixed primary positions with fills from all subaccounts; reads are now scoped to primary `subaccount=0` where supported, and every historical fill is validated/filtered by `subaccount_number`. The actual archived fill and order responses used in the private read-only check carried the needed scope/identity fields; a future response lacking them fails closed. Shadow scoring now rejects non-YES records, requires displayed entry depth, and does not reuse the same short-horizon book for overlapping candidates. **Still P1-blocked:** net account position equality does not prove bot ownership when manual trades can interleave in the same subaccount, and sequential REST reads are not an atomic portfolio snapshot. No live execution path will be attached without an exclusive bot inventory boundary and independently verified lifecycle. Archived order recovery is fail-closed if required historical fields are absent.

**Connectivity regression checked 2026-09-25 22:22 UTC:** both supported Kalshi production hosts, including the [recommended dedicated host](https://docs.kalshi.com/getting_started/api_environments), presented an unrelated expired certificate (`internetpositif.id`) to this sandbox. Strict Python requests, cURL, and the browser all rejected it. We neither suppressed certificate verification nor sent authenticated headers into that connection. Kalshi's unauthenticated market API was separately reachable from a stateless web reader, so this establishes a **sandbox-to-Kalshi TLS-path problem**, not a proven Kalshi-wide outage. A later signed GET from the attached computer did securely verify the user's **Advanced** effective tier. [Official rate limits](https://docs.kalshi.com/getting_started/rate_limits) give Advanced **300 read and 300 write tokens per second**, not unlimited orders, and the locally journaled policy separately caps new entry attempts at three per UTC day by default (exits exempt). A timed, GET-only observer logs every source failure instead of fabricating a win rate; see its private journal for final duration and results. API redirects carrying signed headers are now disabled.

**Completed bounded observer, 2026-09-25/26:** 180 scans accumulated 1,800 seconds of **active** runtime but spanned several wall-clock hours because the temporary sandbox paused; the session was not continuous. ESPN succeeded 180/180; Kalshi succeeded 161/180; 19 cycles failed TLS; 235 strict game/market matches produced **one** uncalibrated candidate and **zero** orders. The one real-data candidate had a subsequent depth-qualified quote within its 60–300 second scoring window and no source failure in that window: the estimated, hypothetical 1-contract round-trip net was **−$0.06** after generic fees. This is not a fill, a settled loss, or a valid win-rate estimate; it is evidence **against** forcing a trade from the current heuristic.

**Continuous remote observer, 2026-09-26 02:07:58–02:37:58 UTC:** the user-provided persistent computer completed exactly 30 minutes of wall-clock observation at 10-second intervals. **180/180 ESPN and 180/180 Kalshi cycles succeeded, zero source errors, maximum inter-scan gap 10 seconds.** It recorded 1,125 strict same-game/time matches, **zero** new heuristic candidates, and **zero** real bot orders. The attached computer's signed read-only account check confirmed the effective Advanced API tier and was repeated after the window; trading remained disabled. This clean sample cannot establish a bot win rate, realized P&L, or a positive edge. Private account-specific values remain outside this public audit.

## Operating options

| Approach | Tradeoffs | Cost | Setup Complexity |
| --- | --- | --- | --- |
| Bounded read-only scans in this temporary environment | Immediate evidence and local JSONL; stops after requested cycles, cannot run unattended forever | No exchange orders/fees; no hosting purchase | Low |
| Same observer on your own always-on machine | Durable local logs and control, but the computer must stay powered on; still **no live orders** | No additional hosted-service charge; your electricity/internet | Medium |

An always-on hosted trader is premature while strategy validation and exit reconciliation remain blocked. This temporary sandbox is not durable hosting.

## Independent API references

- [V2 Create Order](https://docs.kalshi.com/api-reference/orders/create-order-v2): `bid` buys YES; `ask` sells YES; the submitted price is the YES price.
- [Orderbook](https://docs.kalshi.com/api-reference/market/get-market-orderbook): YES and NO bids are returned; asks are derived from the opposite bid.
- [Positions](https://docs.kalshi.com/api-reference/portfolio/get-positions), [Fills](https://docs.kalshi.com/api-reference/portfolio/get-fills), and [Orders](https://docs.kalshi.com/api-reference/orders/get-orders) have separate cursors/state.
- [Rate limits](https://docs.kalshi.com/getting_started/rate_limits) use token buckets, not a fixed 20/30 requests-per-second promise.
- [Fee schedule](https://kalshi.com/fee-schedule) has series-specific exemptions/fees; fee estimates are not authoritative actual charge records.
- [WebSocket connection](https://docs.kalshi.com/websockets/websocket-connection) requires signed API key **headers during the handshake**. An earlier assumption that a query-parameter key was necessary was not supported by current docs; no WebSocket subscriber is implemented here.

## Next gate before any `$10` live experiment

1. Keep credentials private and least-privileged; verify current cash, existing positions, orders, and all relevant fills **continuously** against the exchange, including restart and stale-data behavior. One read-only snapshot is insufficient. Never commit keys or paste them in an issue/PR.
2. Build persistent, idempotent order/fill accounting and tested, reliable exits for both sides; enforce an exchange-reconciled **absolute $10 maximum total loss/exposure**, lower per-trade cap, max orders/day, and a kill switch.
3. Establish enough resolved, independently logged **out-of-sample** shadow signals with conservative fill assumptions and series-correct fees; report net return, drawdown, fill rate, sample size, and uncertainty, not just win percentage.
4. Agree on exact eligible series, risk budget, maximum runtime, and execution policy before enabling writes; run a bounded supervised pilot, not an unattended loop in an ephemeral sandbox.
