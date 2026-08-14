#!/usr/bin/env bash
# Reproducible local verification for the V11 paper-only research build.
set -euo pipefail
cd "$(dirname "$0")/.."

python3 -m compileall -q research main.py
python3 -m unittest discover -s tests -v

set +e
python3 main.py >/tmp/kalshi_v11_main_stdout.txt 2>/tmp/kalshi_v11_main_stderr.txt
status=$?
set -e
if [[ "$status" -ne 2 ]]; then
  echo "FAIL: legacy main.py was expected to exit with status 2, got $status" >&2
  exit 1
fi
grep -q 'LIVE EXECUTION IS DISABLED' /tmp/kalshi_v11_main_stderr.txt

if git grep -n -I -E 'ghp_[A-Za-z0-9]{20,}|-----BEGIN (RSA |)PRIVATE KEY-----' -- ':!config.example.json'; then
  echo "FAIL: credential-like material was found in tracked files" >&2
  exit 1
fi

echo "V11 validation passed: tests, disabled live entry point, and basic secret scan succeeded."
