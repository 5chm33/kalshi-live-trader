#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p backups exports
python3 research/backup.py --database data/research_v11.sqlite3 --backup-dir backups --retain 14
latest=$(find backups -maxdepth 1 -type f -name 'research_v11_*.sqlite3' -printf '%T@ %p\n' | sort -nr | head -1 | cut -d' ' -f2-)
if [[ -z "${latest}" ]]; then
  echo "No backup produced" >&2
  exit 1
fi
python3 research/verify_restore.py "$latest"
python3 research/export_ledger.py --database data/research_v11.sqlite3 --output-dir exports --retain 30
