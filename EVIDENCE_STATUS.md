# V11 Evidence Status

**Status date:** 2026-08-14 UTC  
**Mode:** Research and paper data collection only. Live order submission remains hard-disabled.

> **Conclusion:** There is currently **no validated profitable strategy** in this repository. The generic MLB late-lead hypothesis failed its first fee-adjusted, archived-quote screen and is retired as a broad entry rule.

## First Empirical MLB Result

The initial historical study joined completed MLB late-lead states to the first archived Kalshi minute candle available within a two-minute window. It retained only the first state per game-contract for the outcome report and modeled one YES contract purchased at the archived YES ask. The calculation used the documented taker-fee formula and a conservative one-cent order-rounding reserve.[1]

| Metric | Observed value | Interpretation |
|---|---:|---|
| Aligned quote rows | 501 | Sufficient to reject the broad rule, not sufficient to prove narrow buckets. |
| Leader win rate | 92.02% | High probability alone is not evidence of a profitable entry. |
| Mean quote delay | 30.37 seconds | Timestamp alignment is only minute-candle resolution. |
| Mean fee-adjusted quote-only P&L proxy | **−$0.0472 per contract** | The observed ask already reflected the obvious game-state advantage. |
| Total proxy P&L | **−$23.6245** | A descriptive counterfactual, not executable P&L. |
| Calibrated OOS candidates | 0 | The pre-registered model gate correctly withheld entries. |

The quote-only calculation has intentionally **not** been represented as a backtest or a fill simulation. Historical candles do not contain displayed depth, queue position, partial-fill behavior, acknowledgement latency, adverse selection, or the account’s actual fill-fee record. The result is nevertheless adequate to eliminate the broad “3+ runs in the 6th+” rule as a credible source of edge at the observed asks.

## Current Research Assets

| Component | State | What it can establish |
|---|---|---|
| Official completed MLB feeds | Collecting 2025–2026 states | Calibrated win probabilities for fixed state buckets. |
| Archived Kalshi MLB markets/candles | Extended GET-only collection running | Quote availability and observed post-state asks, not executable depth. |
| Authenticated Kalshi WebSocket collector | Paper-only service | Forward-looking, sequenced executable-book observations. |
| Fee/depth paper broker | Unit-tested | Conservative simulated fill rules when actual depth is captured. |
| Tennis | Blocked | No verified set-level score data contract; no signal permitted. |
| Weather | Data-quality only | Contract-to-station settlement mapping and calibration remain incomplete. |

## Evidence Gate Before Any New Strategy Becomes a Paper Candidate

A future candidate must satisfy all of the following conditions. Passing them does **not** authorize live trading.

1. The model specification, state definition, timing rule, and minimum net edge are committed before evaluation.
2. The model is calibrated on earlier independent games and tested on a later chronological holdout.
3. The evaluation includes the observed ask, documented fee formula, depth and partial-fill assumptions, and a conservative latency allowance.
4. The same rule is then observed prospectively through the live WebSocket paper ledger.
5. No political market is eligible and no code path may place a live order.

## References

[1] [Kalshi Fee Schedule](https://kalshi.com/fee-schedule)

