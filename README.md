# Kalshi Live Trader v10

Automated prediction market trading bot for [Kalshi](https://kalshi.com). Combines latency-based sports sniping, SOTA weather ensemble forecasting, and tennis value strategies.

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
│   └── 209-Member Ensemble (ECMWF+AIFS+GFS+ICON+UKMO)
│
└── Position Manager — Trailing stops, profit targets, time exits
```

## Strategies

### 1. Latency Sniper (MLB, NBA)
Exploits the time gap between ESPN score updates and Kalshi price adjustments. When ESPN reports a score change, the bot calculates new fair value and buys at the stale (old) price before market makers reprice.

- **Baseball Late Lead**: Team up 3+ runs in 6th+ inning → 88-98% win rate
- **Score Change Sniping**: Immediate IOC orders after detected score changes

### 2. Weather Ensemble (209 Members)
Five global weather models combined for temperature forecasting:
- ECMWF IFS (51 members)
- ECMWF AIFS (51 members)
- GFS (31 members)
- ICON (40 members)
- UKMO (36 members)

Quality filters: 25% min edge for range markets, 55% confidence floor, 45c max NO price.

### 3. Tennis Value
- Rankings-based edge when market underprices favorites
- Volatility plays when higher-ranked player loses first set (62-70% comeback rate)

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
- **IOC orders** (Immediate-Or-Cancel) for instant fills on stale prices
- **RSA-PSS signing** for authentication
- Rate-limited to 20 req/sec (well under 30/sec advanced tier limit)

## Risk Management

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
