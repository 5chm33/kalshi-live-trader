# Kalshi V11 Paper-Only Research System

This repository is a **reproducible, paper-only prediction-market research project**. It does not claim profitability, and it does not permit live exchange execution. The prior V10 prototype is retired because it had material execution, accounting, and data-contract defects.

> **Status: research only.** The system uses authenticated `GET` requests to capture Kalshi data, but its code path contains no order creation, amendment, cancellation, or exit capability. Nothing in this repository should be used as a basis for committing real money.

## What V11 Actually Does

| Component | Current behavior | Status |
|---|---|---|
| Kalshi account data | Read-only balance, positions, fills, resting-order, market, and order-book snapshots | Implemented |
| Market data | Fixed-point binary order-book normalization with executable-side depth | Implemented |
| Paper ledger | SQLite observations, signals, paper orders, paper fills, marks, and settlements | Implemented |
| MLB hypothesis | Records exact late-lead game states and matching Kalshi quotes | Implemented; no probability model or paper fills until calibrated |
| Weather research | Parses the actual returned Open-Meteo ensemble members and records dynamic counts | Implemented; no market/settlement mapping or signal path |
| Tennis research | Enforces a complete set-level score contract before a comeback rule can be studied | Disabled pending a verified score source |
| Live trading | Production-order path | **Hard disabled** |

## Why the Old Claims Were Retired

The original prototype presented unsupported claims around “HFT,” a 209-member weather ensemble, strategy coverage, and profitability. The verified V11 weather diagnostic returned **191** usable values for the five-model request: ECMWF IFS 51, ECMWF AIFS 51, ICON 40, GEFS 31, and UKMO 18. It also confirmed that the old system was polling rather than operating a live market-data HFT stack. See [AUDIT_STATUS.md](AUDIT_STATUS.md) and [RESEARCH_API_2026.md](RESEARCH_API_2026.md).

## Safety Properties

The system’s guardrails are intentional architectural restrictions, not settings that can be toggled in a configuration file.

| Safeguard | Behavior |
|---|---|
| Paper-only hard lock | Any mode other than `paper` is rejected. |
| Political-market block | Markets with conservative political/election keywords are rejected. |
| Read-only API client | V11 exposes signed `GET` only. It has no HTTP mutation method. |
| Depth-aware paper fills | The paper broker consumes only displayed opposing-book depth and can partially fill or reject a candidate. |
| Fee accounting | Paper fills include a documented taker-fee estimate and rounding reserve. |
| Durable state | SQLite records raw observations, signals, fills, and recorded settlement outcomes. |
| Calibration gate | The MLB detector cannot emit a signal until a separately fitted, versioned probability model is supplied. |

## Commands

Create a local `config.json` (never commit it):

```json
{
  "api_key": "your-kalshi-api-key",
  "private_key_string": "YOUR_RSA_PRIVATE_KEY_PEM",
  "research": {
    "mode": "paper",
    "environment": "production",
    "database_path": "data/research_v11.sqlite3"
  }
}
```

Install dependencies:

```bash
python3 -m pip install -r requirements.txt
```

Run one read-only MLB collection cycle:

```bash
python3 research/run_mlb_paper.py --config config.json
```

Run the persistent paper collector:

```bash
python3 research/daemon.py --config config.json --interval-seconds 60
```

Inspect the local evidence ledger:

```bash
python3 research/run_evaluation.py --database data/research_v11.sqlite3
```

Inspect actual weather member counts without emitting a signal:

```bash
python3 research/diagnose_weather.py --city dallas --kind high
```

Capture sequence-checked, read-only order-book snapshots and deltas for currently live matched MLB contracts:

```bash
python3 research/capture_mlb_ws.py --config config.json --max-seconds 60
```

`python3 main.py` intentionally exits with a live-execution-disabled message.

For an independent local check of the unit suite, lockout behavior, and basic credential scan:

```bash
scripts/validate_v11.sh
```

## Evidence Standard Before Any Future Live-Readiness Review

A future live-readiness review would require, at minimum, a full documented settlement-source map, fee- and depth-aware paper data, durable reconciliation after restarts, a pre-registered calibration method, adequate out-of-sample sample size, and positive net results after costs. The current system does **not** meet that bar.

## References

[1] [Kalshi API Documentation](https://docs.kalshi.com/)

[2] [Kalshi Fee Schedule](https://kalshi.com/docs/kalshi-fee-schedule.pdf)

[3] [Open-Meteo Ensemble API](https://open-meteo.com/en/docs/ensemble-api)

[4] [MLB Stats API](https://statsapi.mlb.com/)
