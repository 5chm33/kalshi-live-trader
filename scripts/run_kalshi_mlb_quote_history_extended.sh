#!/usr/bin/env bash
# Extended, GET-only archived Kalshi MLB quote collection for research coverage.
# The collector is bounded to 1,000 team-market contracts and records only
# archival metadata/candles; it cannot submit an order.
set -euo pipefail
cd "$(dirname "$0")/.."

exec python3 research/backfill_kalshi_mlb_history.py \
  --config config.json \
  --database data/research_v11.sqlite3 \
  --max-pages 1 \
  --max-markets 1000
