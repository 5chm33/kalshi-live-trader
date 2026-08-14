#!/usr/bin/env bash
# One-time, paper-research-only 2026 completed MLB history backfill.
set -euo pipefail
cd "$(dirname "$0")/.."

exec python3 research/backfill_mlb_history.py \
  --database data/research_v11.sqlite3 \
  --start 2026-03-26 \
  --end 2026-08-13 \
  --max-games-per-day 20 \
  --sleep-seconds 0.10
