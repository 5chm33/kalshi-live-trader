#!/usr/bin/env bash
# One-time, paper-research-only completed MLB history backfill.
set -euo pipefail
cd "$(dirname "$0")/.."

exec python3 research/backfill_mlb_history.py \
  --database data/research_v11.sqlite3 \
  --start 2025-03-27 \
  --end 2025-09-28 \
  --max-games-per-day 20 \
  --sleep-seconds 0.10
