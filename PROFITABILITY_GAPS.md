# Profitability Gaps and Research Priorities

## Current Finding

The project has **no measured basis to claim profitability**. The live paper ledger began with zero candidates because no MLB games were active during the overnight start window. The earlier prototype’s losses are therefore not evidence that a new MLB hypothesis fails, but neither are they evidence that it works.

> A trading signal is not an edge until its forecast is calibrated and its expected value remains positive after the executable spread, fees, depth, delay, and any exit cost.

## Blocking Gaps

| Gap | Current state | Required evidence | Priority |
|---|---|---|---|
| Fair-value model | The MLB rule identifies a game state only; it emits no probability | A pre-registered model trained on historical game states and evaluated out of sample | P0 |
| Time alignment | REST snapshots are not timestamped against score publication latency | Store source receive time, score update time when available, Kalshi book sequence/time, and every candidate’s executable quote | P0 |
| Executable book state | WebSocket connector exists but does not maintain full snapshot/delta books | Sequenced in-memory book with gap detection, resync, and durable top-of-book/depth observations | P0 |
| Settlement data | Reconciler is implemented but has no observed candidates yet | Actual Kalshi result recorded for each candidate and each paper fill | P0 |
| Cost model | Taker fee is modeled; maker/exit/latency effects are not | Per-fill fee/multiplier validation and paper exit assumptions that consume real depth | P1 |
| Market mapping | MLB mapping is strict but only covers game-winner suffixes | Mapping coverage and mismatch-rate report from real game days | P1 |
| Weather | Actual ensemble-member parser works; contract/settlement-source mapping is absent | Contract-specific official observation source, strike-unit rule, and historical forecast calibration | P1 |
| Tennis | No verified live set-level score source | Proven score contract plus calibration by surface, set state, and rank/strength features | P2 |

## Near-Term Research Sequence

The first strategy study is deliberately narrow: **MLB game-winner contracts in late-lead states**. It will collect the official MLB game state, matched Kalshi market, full executable book state, and final contract result. The model will remain disabled until the dataset can support an out-of-sample probability estimate.

The study must report, for every bucket, the candidate count, realized contract win rate, Wilson interval, market-implied probability at the executable ask, estimated all-in cost, and net paper result. Buckets with sparse samples are descriptive only and must not be promoted to a trading model.

## Explicit Non-Solutions

More market categories, faster blind polling, larger position sizes, static stop-loss percentages, and an uncalibrated Kelly formula do not solve the missing-edge problem. They only scale activity before the system knows whether it has a positive expected value.

## References

[1] [Kalshi Historical Data](https://docs.kalshi.com/getting_started/historical_data)

[2] [Kalshi WebSockets](https://docs.kalshi.com/getting_started/quick_start_websockets)

[3] [Kalshi Order Book Responses](https://docs.kalshi.com/getting_started/orderbook_responses)
