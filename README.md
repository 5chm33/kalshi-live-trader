# Kalshi Trader: Read-Only Validation Build

This repository is a **research prototype, not a proven profitable trading bot**. The previous live entry point had order-direction, reconciliation, stale-price, strategy-calibration, and position-exit defects. `python3 main.py` now runs a **bounded, public-data, read-only observer**. All authenticated writes in `core/kalshi_client.py` are blocked. `--live` exits with an error. No API credentials or backtest server are needed for observation.

## Run the observer

```bash
python3 -m pip install -r requirements.txt
python3 -m unittest discover -s tests -v
python3 main.py --cycles 6 --interval 10 --output logs/shadow_observations.jsonl
```

Output is append-only JSON Lines (ignored by Git). It records current ESPN MLB games, strict same-time Kalshi market matches, actual executable orderbook quotes and available depth, detected score changes, and **uncalibrated hypothetical** MLB heuristic candidates. When no live game has a matching market, it records a public quote from an unrelated market to verify both market discovery and book connectivity, but does not treat it as a trade. A `cycle_error` aborts on feed or market-data failure. Use `--cycles 1` for a one-shot check; allowed range is 1–180 scans and minimum interval is 10 seconds.

## Optional private account diagnostics (GET-only)

If you own a Kalshi key, store its key ID and PEM in a local **untracked** `config.json` with mode `0600`; never put credentials in a GitHub PR, issue, chat message, CI secret on a public fork, or read-only observation log. The following commands authenticate only to read balance, all open positions/resting orders, and recent fills; the performance check reads live and historical market positions:

```bash
chmod 600 config.json
python3 account_preflight.py --config config.json --output logs/account_preflight.json
python3 account_performance.py --config config.json --output logs/account_performance.json
```

Both reports are local private files under the Git-ignored `logs/` directory. `balance_dollars` is available **cash**; the API's `portfolio_value` is separately reported as `position_mark_dollars` (not treated as total cash plus positions). Historical per-market realized P&L can include **unrelated manual trades** and is not an attribution to this bot or proof of future profitability. Account read errors abort, rather than implying zero positions or a zero balance. Uploaded older bundles may contain plaintext credentials; never extract or commit their `config.json` into this repository.

**A candidate is not a fill or win.** No P&L or win rate is computed. To measure performance, timestamp every candidate, use orderbook depth and achievable entry/exit prices, include actual fee schedule, reconcile hypothetical fills conservatively, wait for an exit/settlement, and report sample size and out-of-sample uncertainty. A handful of wins or an almost-100% win rate is not evidence of profitability; net return after fees and drawdown matter more.

## Safety improvements in this build

- Correct YES/NO quote math: orderbooks contain YES bids and NO bids; YES ask is `1 - best NO bid`, and NO ask is `1 - best YES bid`. An absent or one-sided book is **not** a zero-priced opportunity.
- Exact MLB team code plus event-time match (within four hours) prevents matching today's game to tomorrow's market with the same teams.
- Every candidate uses a newly fetched executable orderbook, not the 30-second market-discovery snapshot; bid/ask and depth are logged.
- The standard taker-fee formula is used as an **estimate only**, subject to series-specific fees and real fill accounting. Quoted instant-exit P&L includes entry and exit estimated taker fees.
- No substituted weather forecast date, fictitious normal-distribution fallback, or silently omitted UKMO member in the computed ensemble; missing target data means no probability.
- Position GET failures are not treated as an empty portfolio; portfolio positions are paginated. **This does not mean live reconciliation is complete.**
- Authenticated POST/DELETE writes are blocked at the HTTP client boundary. There is no continuous service in this temporary sandbox; an observer only runs for its configured number of scans.

## Still blocked before real-money orders

1. A calibrated, out-of-sample forecast advantage at *achievable* prices, after actual series fees; the MLB probability lookup and tennis rank tables are currently heuristic, not validated.
2. End-to-end order semantics: Kalshi V2 `bid` buys YES at a **YES price**, while `ask` sells YES at a **YES price**. Buying NO economically means selling YES at `1 - NO ask`, not using a NO price as the V2 ask price.
3. Reconciliation of open orders, positions, fills, fees, partial fills, and account equity across restarts; no fallback values when an account endpoint fails.
4. A tested exit path on both sides, with bounded slippage, real orderbook depth, status handling, and a capital cap enforced against the exchange portfolio. IOC orders can fail to fill; stops are *conditional order requests*, not guaranteed limits on loss.
5. Strategy-specific weather market settlement rules (station, time zone, rounding and temperature boundary semantics), model calibration and ensemble dependence. Tennis comeback needs actual set-level state. No live trade should be generated from those modules yet.
6. Credential provisioning through a private, read-only-first integration; never commit private keys. A private authenticated account diagnostic can verify current cash, positions and resting orders, but it does not grant live-trading readiness or demonstrate a strategy edge.

Review [AUDIT_STATUS.md](AUDIT_STATUS.md) for the dated findings and links to Kalshi's current API documentation. The old implementation remains available in repository history for independent review; don't restore it as a live entry point.
