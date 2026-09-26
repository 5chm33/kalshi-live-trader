# One-contract real-money execution pilot (experimental)

**Completed result (2026-09-26 21:20 UTC):** One real one-contract IOC entry and one reduce-only IOC exit filled. Signed venue orders, actual fees, and a flat numbered account verified **−$0.0276 realized net** and **$1.9724 final isolated cash**. Both pilot services are stopped; the lifetime one-entry journal forbids a second entry. This experiment did **not** establish a profitable strategy. Do not fund or start another live pilot without a new, expressly bounded decision; continue the independent public-data studies instead.

**Scope approved by the user on 2026-09-26:** At most **$2 of existing Kalshi cash** can be moved to a new numbered subaccount, and at most **one** real YES entry (one whole contract, price no higher than $0.50, estimated entry fee reserved up to $0.04) can be attempted. This is an execution-quality test with a real chance of loss, **not a profitable strategy**. The primary bot (`main.py`) and two already-running research collectors remain read-only. Their old zero-win record is not changed by this experiment.

Kalshi's [exchange-sharding guide](https://docs.kalshi.com/getting_started/exchange_sharding) says baseball markets reside on **shard 3** and collateral must be on that shard. A signed GET confirmed the existing cash is on shard 0. The one-time funding command moves exactly $2 from the primary account on shard 0 to primary shard 3 (the [intra-account API](https://docs.kalshi.com/api-reference/portfolio/intra-account-transfer) specifies **20,000 centicents**), creates a new numbered subaccount on shard 3, and transfers exactly **200 cents** from primary shard 3 into it. Each exchange write has a durable owner-only stage marker; if an acknowledgement or GET is ambiguous, funding halts without retry. The numbered account is [API-only](https://docs.kalshi.com/getting_started/subaccounts); a full-account API key still technically has broader rights, but the pilot gateway itself refuses the primary account and all other shards. Do not add funds to this subaccount during the experiment.

The pilot chooses a future, nonprovisional, active MLB winner market whose contract rules give an original scheduled start 15 minutes to six hours away. It requires an authenticated account preflight and real depth-one YES/NO bids, ≥1 contract each, YES ask $0.35–$0.50, displayed spread ≤$0.04, valid market price grid, and current series/event fee override. Immediately before each IOC, it opens a **new authenticated Kalshi WebSocket orderbook subscription**, parses its sequence-numbered venue snapshot, and requires the independently fetched REST best bids and sizes to agree within a short receipt window; mismatches halt. Kalshi's snapshot has no venue timestamp, so this is a strong short-lived cross-check **not a guarantee of a future fill**. It submits exactly one `immediate_or_cancel` YES bid on [V2](https://docs.kalshi.com/api-reference/orders/create-order-v2) at the observed YES ask. It does **not** claim the contract has positive expected value. One unsuccessful IOC still uses up the one-entry pilot. A filled contract is not flat or profitable merely because the server acknowledged the order.

The ledger is bound to the numbered subaccount and persists `prepared -> submitting -> reconcile` **before** the single POST; no write is retried on timeout. Only a uniquely identified venue order (including the historical tier after archival), actual unique recent/archived fills, and a matching signed venue position may be reconciled. If a one-contract entry only fills 0.01–0.99, the exact owned fraction is eligible for a correspondingly sized **reduce-only** YES ask. After ≥1 minute, an exit is attempted only if the current best bid exceeds verified per-contract cost plus a conservative exit-fee estimate and $0.01. After ten minutes, a reduction can cross the current best bid even at a loss (the entire $2 deposit is the outside loss bound). Up to three terminal, fill-reconciled reduce-only exit attempts are allowed; each subsequent attempt uses only the verified residual fraction. If the book is one-sided, closed, or the exchange GETs disagree, no invented fill or zero value is recorded; inventory may remain until venue settlement. An unexpectedly resting IOC is canceled only after its order ID, client ID, shard, and subaccount are GET-verified. Keep the trade report private until venue settlement or confirmed flat position.

On the connected computer only, after reviewing/tests and finding the exchange connection healthy:

```bash
cd /home/ubuntu/kalshi-live-trader
.venv/bin/python audit_integration.py
.venv/bin/python fund_pilot.py --execute \
  --config /home/ubuntu/.config/kalshi/config.json \
  --journal logs/pilot_funding.json
# Use the new numbered subaccount printed by the funding command, never 0.
.venv/bin/python pilot_live.py --execute \
  --config /home/ubuntu/.config/kalshi/config.json \
  --subaccount NUMBER \
  --ledger logs/pilot_orders.sqlite \
  --deadline-utc YYYY-MM-DDTHH:MM:SSZ
```

Only the operator performing the authorized pilot should start it. If a deployment service is installed, inspect `systemctl show kalshi-pilot-live --property=ActiveState,Result,ExecMainStatus` and `journalctl -u kalshi-pilot-live`; `sudo systemctl stop kalshi-pilot-live` stops *new automated actions*, not an already-open venue position. Always reconcile order, fills, balance, and holdings by signed GET after a stop. Do not re-run `fund_pilot.py` on an ambiguous funding stage, and do not delete or swap the ledger to evade its one-entry limit.

**No auto-activation of the historical strategies:** This pilot does not assert positive expected value, frequent trading, or an eventual 100% win rate. Report realized P&L only after confirmed exits or a venue-recorded settlement, including the actual Kalshi fees. A live bid mark is an estimate, never realized profit.
