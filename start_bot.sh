#!/usr/bin/env bash
# V11 paper-only research launcher. It never sends a Kalshi order.
set -euo pipefail
cd "$(dirname "$0")"

echo "============================================"
echo "  KALSHI V11 PAPER-ONLY RESEARCH COLLECTOR"
echo "============================================"
echo "This process uses authenticated GET requests only."

if [[ ! -f config.json ]]; then
  echo "ERROR: config.json is required for authenticated read-only market data." >&2
  exit 1
fi

python3 -m pip install -r requirements.txt
exec python3 research/daemon.py --config config.json --interval-seconds 60
