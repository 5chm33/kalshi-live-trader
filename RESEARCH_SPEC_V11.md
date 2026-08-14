# V11 Research Specification: Evidence Before Execution

**Purpose:** Replace the current live-order prototype with a durable, read-only data collector and paper-trading system. The system will not place, cancel, amend, or exit any production orders. Live execution remains unavailable by design.

## Non-Negotiable Rules

| Rule | Requirement |
|---|---|
| Default mode | `PAPER` only. Any production order client must require a separate, local, non-versioned explicit activation flag and user confirmation. |
| Political markets | Hard-blocked by category, series allowlist, title keywords, and ticker keywords. |
| Source evidence | Every signal records raw-source timestamp, local receipt timestamp, source ID, market snapshot, and payload hash. |
| Market price | Use executable order-book price and available depth—not a displayed last price or midpoint. |
| Fees | Apply Kalshi’s July 7, 2026 taker formula: `ceil_to_0.0001(M × 0.07 × C × P × (1-P))`; apply maker multiplier only when confirmed by the series fee schedule. |
| Fill model | Paper entry fills only if opposite-side displayed depth supports the proposed size at or better than the computed executable price. Otherwise: partial fill or no fill. |
| P&L | Track gross P&L, entry/exit fees, assumed slippage, net P&L, mark-to-executable-bid, and settlement P&L separately. |
| State | SQLite transaction log is the source of truth. In-memory state is only a cache and is rebuilt from the database on restart. |
| Reconciliation | All production-account reads are GET-only. Reconcile balances, fills, open positions, and resting orders by cursor and timestamp. |
| Promotion gate | No strategy can move from paper to a production-ready review until it satisfies the validation criteria below. |

## Strategy Status

| Strategy | Current status | V11 treatment | Promotion requirement |
|---|---|---|---|
| MLB late lead | Candidate hypothesis only | Enable in paper mode with explicit, versioned assumptions | ≥200 paper opportunities across ≥30 calendar days; positive net out-of-sample expectancy after fees/slippage; maximum drawdown and confidence intervals reported |
| Post-score price response | Candidate measurement study | Log game-source change receipt vs. market-price response, without assuming a lag exists | Demonstrate source-to-market response distribution and profitable fillable net edge after an intentional latency buffer |
| Weather temperature | Data-quality study | Capture forecasts, model member counts, market terms, and final settlement; no paper entry until settlement mapping is verified | ≥100 settled, correctly mapped markets with calibration/Brier-score analysis and positive fee-adjusted paper expectancy |
| Tennis comeback | Disabled | Do not create signals until a source provides trustworthy point/set/game state, surface, event identity, and match format | Same as above plus pre-registered first-set-loss condition and identity-match audit |
| Cross-market / market making | Deferred | Research only after an order-book normalizer, queue model, and fill model exist | Separate design review; no claiming arbitrage from implied prices alone |

## MLB Candidate Specification

The candidate is intentionally a **measurement rule**, not a claim of predictive edge.

```text
Eligibility:
  - MLB regular-season game identified in both MLB feed and Kalshi event mapping.
  - Game status is live; linescore supplies inning and team runs.
  - Leader has a run lead ≥ 3.
  - Inning is ≥ 6; extra innings are recorded separately.
  - Matched Kalshi contract is active, allowed, and has a valid two-sided book.
  - Paper order size is no more than visible depth at executable price.

Candidate valuation:
  - Store only a pre-registered baseline win probability table.
  - Apply a sensitivity range rather than treating one heuristic probability as truth.
  - Trade candidate only if lower-bound probability minus all-in executable cost exceeds configured edge threshold.

Data recorded:
  - Game state, source timestamp, local receipt time, Kalshi snapshot time.
  - Best YES/NO bid, implied asks, depth, contract tick size/price range.
  - Fair-value model version and every input.
  - Paper order and estimated entry fee.
  - Subsequent marks, exit signals, and settled outcome.
```

## Paper Execution Model

### Canonical Binary Book

Let `Y_bid` be the highest YES bid and `N_bid` the highest NO bid. Then:

```text
YES ask = 1 - N_bid
NO ask  = 1 - Y_bid
```

A paper long YES uses the YES ask and the volume from the opposite NO-bid level(s). A paper long NO uses the NO ask and the volume from the opposite YES-bid level(s). The engine walks levels to calculate a volume-weighted execution price. A signal is rejected when the spread, required depth, or uncertainty makes the net edge non-positive.

### Fees

For a taker fill at price `P`, count `C`, and multiplier `M`:

```text
fee = ceil_to_0.0001(M × 0.07 × C × P × (1 - P))
```

The estimator will use the documented series multiplier where available. When unavailable, it will record `fee_model_status=unknown` and reject the candidate instead of assuming zero fees. The ledger separately records Kalshi’s possible balance-rounding effect as an execution uncertainty until an actual fill demonstrates the applicable precision treatment.

## Validation Metrics

Every strategy report must calculate these statistics by strategy version, market series, and entry-condition bucket:

| Metric | Definition |
|---|---|
| Fillable candidates | Signals that passed market-status, spread, depth, and fee checks |
| Paper fill rate | Filled contracts divided by proposed contracts under documented book model |
| Gross expectancy | Mean gross settlement/exit P&L per filled contract |
| Net expectancy | Gross P&L less estimated fees and slippage per filled contract |
| Brier score | Mean squared error of stated probability versus settled binary outcome |
| Calibration | Predicted-probability bins compared with observed win rates |
| Maximum drawdown | Largest peak-to-trough paper equity decline |
| Concentration | Share of P&L from top 1, 5, and 10 events |
| Latency profile | Source-event receipt to Kalshi price-change distributions |
| Sensitivity | Net P&L under more pessimistic fees, fills, and latency assumptions |

## Success Criteria

A strategy is **research-supported** only when it has a preregistered rule, clean identity mappings, no look-ahead leakage, and positive *out-of-sample* net expectancy under conservative fill/fee assumptions. A strategy is **not** production-approved merely because it produces a high historical win rate or a small sample of profits.

## References

[1] https://docs.kalshi.com/getting_started/order_direction
[2] https://docs.kalshi.com/api-reference/orders/create-order-v2
[3] https://docs.kalshi.com/getting_started/orderbook_responses
[4] https://kalshi.com/docs/kalshi-fee-schedule.pdf
[5] https://docs.kalshi.com/getting_started/fee_rounding
[6] https://docs.kalshi.com/getting_started/historical_data
