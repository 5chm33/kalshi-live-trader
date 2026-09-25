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
