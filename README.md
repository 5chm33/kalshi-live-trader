# Kalshi Live Trader v10

Automated prediction-market research prototype for [Kalshi](https://kalshi.com). It combines a polling-based sports signal detector, an experimental weather ensemble, and a tennis value prototype.

> **Important:** This repository is public for independent code review. It is **not validated as profitable**, is **not high-frequency trading**, and contains known blocking integration defects. Read [AUDIT_STATUS.md](AUDIT_STATUS.md) before running it. Do not use it unattended or with money you cannot afford to lose.

The project’s current behavior and limitations are documented in the audit; the architecture below describes intended components, not a guarantee that every component is currently wired into the execution loop.


## Architecture

```
main.py (orchestrator)
├── Fast Loop (10s) — Sports + Tennis
│   ├── ESPN Live Score Feed → Score change detection
│   ├── Market Matcher → Links ESPN games to Kalshi tickers
│   ├── Latency Sniper → Buys stale prices after score changes
│   └── Tennis Value → Rankings-based value + volatility plays
│
├── Slow Loop (180s) — Weather
│   └── Experimental multi-model ensemble (live member count must be verified)
│
└── Position Manager — Trailing stops, profit targets, time exits
```

## Strategies

### 1. Polling-Based Sports Signal Detector (MLB implemented)
Polls ESPN score updates and evaluates a heuristic late-game baseball rule. The checked-in implementation is **MLB-only**, uses a 10-second REST polling loop, and does not implement a live WebSocket subscription or demonstrate exploitable latency after fees and fills.

- **Baseball Late Lead**: A heuristic for teams up 3+ runs in the sixth inning or later; its net profitability has not been validated.
- **Score Change Handling**: IOC orders may be submitted after detected score changes; no latency advantage has been demonstrated.

### 2. Experimental Weather Ensemble (member count must be validated live)
The engine requests five global weather-model families for temperature forecasting:
- ECMWF IFS (51 members)
- ECMWF AIFS (51 members)
- GFS (31 members)
- ICON (40 members)
- UKMO (36 members)

Quality filters: 25% min edge for range markets, 55% confidence floor, 45c max NO price.

### 3. Experimental Tennis Value
- Coarse rankings-based heuristic when the market underprices a favorite
- An intended comeback heuristic; the current score feed does **not** provide the first-set state required to verify the claimed first-set-loss rule

## Setup

1. Clone this repo
2. Create `config.json`:
```json
{
  "api_key": "your-kalshi-api-key",
  "private_key_string": "-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----"
}
```
3. Install dependencies: `pip install -r requirements.txt`
4. Run: `python3 main.py`

## API

Uses Kalshi V2 API with:
- **IOC orders** (Immediate-Or-Cancel) supported by the order client; they do not establish that a stale-price fill is available.
- **RSA-PSS signing** for authentication
- Rate-limited to 20 req/sec (well under 30/sec advanced tier limit)

## Intended Risk Controls (not independently verified)

- Max 8 concurrent positions
- Max 50% of balance at risk
- Max 20% per trade
- Trailing stop: 20% from peak
- Hard stop loss: -35%
- Profit target: auto-sell at 90c
- Time exit: 2 hours max hold for flat positions

## Requirements

- Python 3.10+
- Kalshi Advanced tier API access
- `requests` and `cryptography` packages
