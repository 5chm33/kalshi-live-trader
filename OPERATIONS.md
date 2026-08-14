# V11 Operations and Safety Runbook

## Operating Mode

V11 is a **paper-only research collector**. Its service may authenticate to Kalshi for signed `GET` requests, but the V11 client does not implement a request method for creating, canceling, or modifying orders. The legacy live entry point (`main.py`) exits immediately with status code `2`.

| Component | Location | Purpose |
|---|---|---|
| Cloud collector | `~/kalshi_research_v11/` | Persistent paper-only collection environment |
| Service | `kalshi-research-v11.service` | Starts at boot, collects every 60 seconds |
| Logs | `~/kalshi_research_v11/logs/collector.log` | Cycle summaries and exceptions |
| Ledger | `~/kalshi_research_v11/data/research_v11.sqlite3` | Local immutable observations, candidate states, and settlements |
| Legacy prototype | `~/kalshi_bot_v10/` | Retired; must not be used for execution |

## Operator Commands

```bash
# Current collector status
sudo systemctl status kalshi-research-v11.service

# Stop the collector; it never sends an exchange order while stopping
sudo systemctl stop kalshi-research-v11.service

# Start the collector
sudo systemctl start kalshi-research-v11.service

# Follow paper-only logs
journalctl -u kalshi-research-v11.service -f

# Print the research evidence report
cd ~/kalshi_research_v11
python3 research/run_evaluation.py --database data/research_v11.sqlite3
```

## Credentials and Data

`config.json` contains API credentials and is excluded by `.gitignore`. It must have owner-only permissions (`chmod 600 config.json`) and must never be uploaded, attached to an issue, committed, or copied into the public repository. Runtime ledger databases and logs are also ignored.

If a private key, API key, or GitHub token is shared in chat, logs, or any untrusted location, revoke or rotate it immediately. Credentials grant access independently of this source code’s paper-only safeguards.

## Backups

The ledger is the source of truth for research results. Back up the SQLite file atomically while the service is stopped, or use SQLite’s backup command. Example:

```bash
sudo systemctl stop kalshi-research-v11.service
cp ~/kalshi_research_v11/data/research_v11.sqlite3 ~/research_v11_$(date -u +%F).sqlite3
sudo systemctl start kalshi-research-v11.service
```

## Incident Response

A log exception or unavailable source is a data-quality event, not an invitation to guess, substitute a missing probability, or relax a filter. Preserve the raw data already collected, inspect the service log, and rerun the deterministic tests before changing the collector.

## Live-Readiness Boundary

No amount of uptime substitutes for evidence. Do not create a live-order implementation unless a separate review finds all pre-registered requirements satisfied: settlement-source mapping, calibrated probabilities, fill/fee/slippage measurement, durable reconciliation, out-of-sample validation, and written user authorization. V11 presently does not meet those conditions.
