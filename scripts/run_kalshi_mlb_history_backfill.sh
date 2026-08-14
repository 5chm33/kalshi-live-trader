#!/usr/bin/env bash
# Bounded, GET-only archived Kalshi MLB market/candlestick collection.
set -euo pipefail
cd "$(dirname "$0")/.."

exec python3 research/backfill_kalshi_mlb_history.py \
  --config config.json \
  --database data/research_v11.sqlite3 \
  --max-pages 5 \
  --max-markets 250
