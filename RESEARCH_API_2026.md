# Kalshi API and Data Contract Notes — 2026-08-14

This document records implementation constraints verified against Kalshi’s official documentation before the research-system rebuild. It is not a trading recommendation.

## Confirmed Exchange Contracts

| Topic | Verified contract | Engineering consequence |
|---|---|---|
| Order side | V2 `book_side=bid` is long YES; `book_side=ask` is long NO. V2 quotes both directions on the YES-leg price scale. | The code must not reuse legacy buy/sell/no-price abstractions internally. Every signal must specify `outcome_side`, `book_side`, executable YES-leg price, and intended exposure. |
| Order outcome | A V2 response includes immediate `fill_count`, `remaining_count`, `average_fill_price`, and `average_fee_paid`. | Do not treat accepted orders as fills. Persist the response, then reconcile with fills and positions. |
| IOC | IOC cancels unfilled quantity after matching. | A paper engine must model partial or zero fills from available order-book depth, not assume full execution. |
| Order book | REST order books expose YES and NO bids; implied YES ask is `1 - best NO bid`. | Build a canonical book normalizer from raw fixed-point strings and use it for cost/slippage estimation. |
| WebSocket | Kalshi supports authenticated `ticker`, `trade`, `orderbook_delta`, `fill`, and `market_positions` streams. New clients should explicitly request `use_yes_price=true` for unified price-scale deltas. | Use WebSockets for market data; REST provides snapshots/recovery and account reconciliation. A ten-second polling loop is not latency infrastructure. |
| Fees | Fills report `fee_cost`; balance rounding can create additional rounding fee/rebate behavior. | Record actual post-fill fees in live/demo mode. In paper mode, estimate a conservative fee and label it as an estimate. |
| Rate limits | Advanced tier has independent read and write token budgets of 300 tokens/sec. Endpoint costs determine sustained request count. | Throttle by measured endpoint cost and use event-driven subscriptions; do not flood REST. |
| Historical data | Kalshi offers live and historical fills, positions, markets, trades, and candlesticks separated by a published cutoff. | Reconcile account history using both surfaces and make ingestion cursor-based/idempotent. |
| Demo | Kalshi provides a separate demo environment with mock funds and distinct credentials. | Test transport, order semantics, reconciliation, and failure handling in demo. Do not infer a market edge from demo fills. |

## Data Source Decisions

The baseball paper-trading feed will favor MLB’s public schedule/live-feed surface for game identifiers, status, team names, scores, innings, and linescore data. The current schedule endpoint verified on 2026-08-14 exposes game ID, status, teams, and linescore fields. The implementation must capture received timestamps and source payload hashes, because polling latency is part of the research question.

Tennis will remain disabled until a source provides reliable match-level score detail sufficient for the exact hypothesis being tested: sets, games, match format, player identity, tournament/surface, and current state. Rankings alone do not validate a live comeback strategy.

Weather will be rebuilt around real model-response member counts and settlement-source alignment. The prior code’s five-model/209-member marketing claim is not a valid input to a probability model until each requested model is returned, parsed, weighted, and empirically calibrated.

## Research Gate

A strategy is not eligible for any live-order module until its paper-trading log includes source timestamp, market snapshot, executable depth, estimated and actual fee model, fill assumption, exit rule, settlement/outcome, and net P&L. A strategy must also demonstrate positive results out-of-sample after fees and conservative fill assumptions.

## References

[1] https://docs.kalshi.com/getting_started/order_direction
[2] https://docs.kalshi.com/api-reference/orders/create-order-v2
[3] https://docs.kalshi.com/getting_started/orderbook_responses
[4] https://docs.kalshi.com/getting_started/quick_start_websockets
[5] https://docs.kalshi.com/getting_started/fee_rounding
[6] https://docs.kalshi.com/getting_started/rate_limits
[7] https://docs.kalshi.com/getting_started/historical_data
[8] https://docs.kalshi.com/getting_started/demo_env
[9] https://statsapi.mlb.com/api/v1/schedule/games/?sportId=1&date=2026-08-14&hydrate=linescore,liveData

## Additional Verified Fee and Change Notes

Kalshi’s public fee-schedule PDF, effective July 7, 2026, specifies the standard taker fee as `ceil_to_0.0001(M × 0.07 × C × P × (1-P))` and the maker fee as `ceil_to_0.0001(M × 0.0175 × C × P × (1-P))`, where `M` is the applicable series multiplier, `C` is contracts, and `P` is dollar price. The V11 paper ledger implements the taker formula only when the multiplier is known; it rejects unknown-fee candidates rather than silently treating them as zero-fee.

The official changelog on August 13, 2026 added price-level structures with sub-cent ticks and advised clients to snap orders to the `step` in a market response’s `price_ranges` array. It also changed `GET /portfolio/balance` portfolio-value scoping by exchange index. V11 therefore uses fixed-point decimals rather than cents/floats and will treat `price_ranges` parsing as a required contract before any later demo-order capability is considered.

Additional references:

[10] https://kalshi.com/docs/kalshi-fee-schedule.pdf
[11] https://docs.kalshi.com/changelog

## Verified Weather Data Notes

Open-Meteo’s Ensemble API documents individual member forecasts, including 51-member ECMWF IFS, 51-member AIFS, 31-member GFS, and 40-member ICON global ensembles. The number of returned members is model- and request-dependent; V11 must count the actual parsed values in every payload rather than advertise a fixed combined total. Open-Meteo also documents an Historical Forecast API (coverage approximately 2021/2022 onward) and a Previous Runs / Single Runs distinction suitable for fixed-lead forecast evaluation.

For U.S. weather settlement validation, the NWS API documents forecast, alert, and observation access at `api.weather.gov`. It requires an identifying User-Agent and notes that observations may be delayed by up to 20 minutes after upstream QC. Consequently, NWS observation data cannot be used as an unqualified low-latency settlement proxy; each Kalshi weather series must be explicitly mapped to its published settlement source.

Additional references:

[12] https://open-meteo.com/en/docs/ensemble-api
[13] https://open-meteo.com/en/docs/historical-forecast-api
[14] https://www.weather.gov/documentation/services-web-api

### Live Diagnostic Result — 2026-08-14

A read-only live request for Dallas daily maximum temperature (target 2026-08-15) using the legacy five-model request returned **191 actual values**, not 209: ECMWF IFS 51, ECMWF AIFS 51, ICON 40, GEFS 31, and UKMO global 18. The V11 parser reports these dynamic counts directly and the former 209-member claim is retired.

## Historical Data and WebSocket Validation

Kalshi’s official Historical Data documentation states that live and historical market/trade data are partitioned by a moving cutoff (target live window: approximately three months); an empirical study must route older markets/trades through `GET /historical/...` endpoints after checking `GET /historical/cutoff`. This is required for any retrospective strategy data collection.

The official WebSocket documentation requires an authenticated handshake and specifies that `orderbook_delta` delivers an initial `orderbook_snapshot` followed by sequenced deltas. The synchronizer must treat a sequence gap as a required resnapshot, not continue with a stale book. The official orderbook description confirms fixed-point ascending YES and NO bid arrays, with asks implied by the reciprocal opposite-side best bid.

A live, read-only V11 diagnostic on 2026-08-14 successfully connected to the official production WebSocket endpoint and reconstructed an initial snapshot for `KXMLBGAME-26AUG161920SEAHOU-SEA`: 21 YES levels, 15 NO levels, best YES bid $0.4200 and implied best YES ask $0.4900. No order or write request was sent.

Additional references:

[15] https://docs.kalshi.com/getting_started/historical_data
[16] https://docs.kalshi.com/getting_started/quick_start_websockets
[17] https://docs.kalshi.com/websockets/orderbook-updates
[18] https://docs.kalshi.com/getting_started/orderbook_responses
