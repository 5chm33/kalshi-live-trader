# Kalshi Trader: Read-Only Validation Build

This repository is a **research prototype, not a proven profitable trading bot**. The previous live entry point had order-direction, reconciliation, stale-price, strategy-calibration, and position-exit defects. `python3 main.py` now runs a **bounded, public-data, read-only observer**. All authenticated writes in `core/kalshi_client.py` are blocked. `--live` exits with an error. No API credentials or backtest server are needed for observation.

## Run the observer

```bash
python3 -m pip install -r requirements.txt
python3 -m unittest discover -s tests -v
python3 main.py --cycles 6 --interval 10 --output logs/shadow_observations.jsonl
```

Output is append-only JSON Lines (ignored by Git). It records current ESPN MLB games, strict same-time Kalshi market matches, actual executable orderbook quotes and available depth, detected score changes, and **uncalibrated hypothetical** MLB heuristic candidates. When no live game has a matching market, it records a public quote from an unrelated market to verify both market discovery and book connectivity, but does not treat it as a trade. A `cycle_error` aborts on feed or market-data failure. Use `--cycles 1` for a one-shot check; allowed range is 1–180 scans and minimum interval is 10 seconds.

For a **30-minute wall-clock observation** that records source failures rather than stopping on the first outage, run `python3 observe_30m.py --duration-seconds 1800 --interval-seconds 10 --output logs/monitor_30m.jsonl`. It writes a private JSONL journal with `monitor_start`, per-cycle health/source errors, and `monitor_end`. If either feed fails, the resulting win rate is **undefined**; the watcher does not fake quotes, disable TLS verification, or submit an order. The normal observer and account client now use Kalshi's current documented `external-api.kalshi.com` host. A TLS hostname/expiry error at that host is an environmental connectivity failure to fix, not permission to use `verify=False`.

## Optional private account diagnostics (GET-only)

If you own a Kalshi key, store its key ID and PEM in a local **untracked** `config.json` with mode `0600`; never put credentials in a GitHub PR, issue, chat message, CI secret on a public fork, or read-only observation log. The following commands authenticate only to read balance, **primary-subaccount open positions**, resting orders, and recent fills; the performance check reads live and historical market positions. Do not infer other subaccounts are flat from this report:

```bash
chmod 600 config.json
python3 account_preflight.py --config config.json --output logs/account_preflight.json
python3 account_performance.py --config config.json --output logs/account_performance.json
python3 account_limits.py --config config.json --output logs/account_limits.json
```

Both reports are local private files under the Git-ignored `logs/` directory. `balance_dollars` is available **cash**; the API's `portfolio_value` is separately reported as `position_mark_dollars` (not treated as total cash plus positions). Historical per-market realized P&L can include **unrelated manual trades** and is not an attribution to this bot or proof of future profitability. Account read errors abort, rather than implying zero positions or a zero balance. Uploaded older bundles may contain plaintext credentials; never extract or commit their `config.json` into this repository.

For a read-only mark on an **already held** position, run `python3 position_watch.py --config config.json --output logs/position_watch.json`. It joins cursor-complete recent and archived fills, verifies their net quantity against the current signed position, and only displays an estimated liquidation P&L if a freshly queried two-sided book has enough bid depth. Complex prior round trips, missing archived fill directions, partial-contract fee ambiguity, and one-sided books yield `status: unavailable` rather than a fabricated value. The report is private, one-shot, and never submits an exit; generic future fees and top-of-book depth are *estimates*, not a sale guarantee.
The watcher explicitly scopes the venue position and live fill GETs to **primary subaccount 0** and checks every archived fill's subaccount number before using its cost basis. Missing or other-subaccount fills cannot silently value a primary holding.

For the **unfilled observer**, `python3 shadow_performance.py logs/shadow_observations.jsonl --output logs/shadow_performance.json` estimates hypothetical 1-contract net P&L only when a later quote within 60–300 seconds provides enough exit depth. Missing exits remain unresolved; a successful hypothetical is **not** a trade, a realized win, or proof of achievable fills. A scan with no candidates produces an undefined rate, not 0% or 100%.
It accepts YES-only records, requires one contract of entry depth, and refuses to double-count overlapping candidates for the same ticker. It cannot establish a profitable edge in an empty journal.

The GET-only recovery worker `python3 reconcile_journal.py --config config.json --ledger logs/order_ledger.sqlite --output logs/ledger_reconciliation.json` compares **bot-owned journal IDs only** to authenticated order statuses, live+archived fills, and venue positions. A missing order or read failure cannot clear uncertainty; partially filled positions remain open, and an existing unrelated position is never silently adopted. The SQLite journal and reports are private local files. The current build does not create any live order intents or send POST/DELETE; a journal with no bot orders correctly reports zero *bot* intents even when the exchange account has a separate pre-existing holding.

**A candidate is not a fill or win.** No P&L or win rate is computed. To measure performance, timestamp every candidate, use orderbook depth and achievable entry/exit prices, include actual fee schedule, reconcile hypothetical fills conservatively, wait for an exit/settlement, and report sample size and out-of-sample uncertainty. A handful of wins or an almost-100% win rate is not evidence of profitability; net return after fees and drawdown matter more.

## Safety improvements in this build

- Correct YES/NO quote math: orderbooks contain YES bids and NO bids; YES ask is `1 - best NO bid`, and NO ask is `1 - best YES bid`. An absent or one-sided book is **not** a zero-priced opportunity.
- Exact MLB team code plus event-time match (within four hours) prevents matching today's game to tomorrow's market with the same teams.
- Every candidate uses a newly fetched executable orderbook, not the 30-second market-discovery snapshot; bid/ask and depth are logged.
- The standard taker-fee formula is used as an **estimate only**, subject to series-specific fees and real fill accounting. Quoted instant-exit P&L includes entry and exit estimated taker fees.
- No substituted weather forecast date, fictitious normal-distribution fallback, or silently omitted UKMO member in the computed ensemble; missing target data means no probability.
- Position GET failures are not treated as an empty portfolio; portfolio positions are paginated. **This does not mean live reconciliation is complete.**
- Authenticated POST/DELETE writes are blocked at the HTTP client boundary. There is no continuous service in this temporary sandbox; an observer only runs for its configured number of scans.
- New, **unconnected** execution primitives (`core/order_math.py`, `core/execution_ledger.py`, `core/position_valuation.py`) cover V2 YES/NO quote conversion, zero-bet-if-no-edge sizing, exclusive crash-persistent order journaling, order-status GET recovery, partial-fill/exit ownership, and actual-fill accounting with a fresh-book exit estimate. These are regression-tested components, **not an activated execution loop**. The existing position is user-owned and must never be silently assigned to bot-owned inventory.
- Local risk limits are separate from API usage tiers: the journal now caps new entry submission attempts at **three per UTC day** by default, while preserving the ability to submit a verified exit. Kalshi's [official rate-limit documentation](https://docs.kalshi.com/getting_started/rate_limits) specifies finite **Advanced** token buckets (300 read and 300 write tokens/second, with endpoint-specific costs), not unlimited trades or a guarantee of profitable fills. The account's effective tier could not be re-queried while the sandbox's Kalshi TLS validation failed.
- Signed GETs now refuse cross-host redirects, which otherwise might forward signed headers. The limits command will report the **effective** tier and token refill only when Kalshi's certificate validates; it never grants permission to bypass the independent three-entry local safety cap.

## Still blocked before real-money orders

1. A calibrated, out-of-sample forecast advantage at *achievable* prices, after actual series fees; the MLB probability lookup and tennis rank tables are currently heuristic, not validated.
2. End-to-end order semantics: Kalshi V2 `bid` buys YES at a **YES price**, while `ask` sells YES at a **YES price**. Buying NO economically means selling YES at `1 - NO ask`, not using a NO price as the V2 ask price.
3. Reconciliation of open orders, positions, fills, fees, partial fills, and account equity across restarts; no fallback values when an account endpoint fails.
4. A tested exit path on both sides, with bounded slippage, real orderbook depth, status handling, and a capital cap enforced against the exchange portfolio. IOC orders can fail to fill; stops are *conditional order requests*, not guaranteed limits on loss.
5. Strategy-specific weather market settlement rules (station, time zone, rounding and temperature boundary semantics), model calibration and ensemble dependence. Tennis comeback needs actual set-level state. No live trade should be generated from those modules yet.
6. Credential provisioning through a private, read-only-first integration; never commit private keys. A private authenticated account diagnostic can verify current cash, positions and resting orders, but it does not grant live-trading readiness or demonstrate a strategy edge.
7. **Exclusive inventory ownership**: this primary subaccount has user-owned activity. A net position of the right size does not prove the bot owns that lot, and REST reads of orders/fills/positions are not atomic with later manual activity. Do not connect a POST or automated reduce-only exit to this ledger on a shared primary subaccount. A dedicated, exclusive bot subaccount (or equally strong isolation) and continuous verification are required before such activation. Historical recovery intentionally remains blocked when archived records lack identity fields; it is not an excuse to retry an uncertain order.

Review [AUDIT_STATUS.md](AUDIT_STATUS.md) for the dated findings and links to Kalshi's current API documentation. The old implementation remains available in repository history for independent review; don't restore it as a live entry point.
