#!/usr/bin/env bash
# Reproducible local verification for the V11 paper-only research build.
set -euo pipefail
cd "$(dirname "$0")/.."

missing=()
for module in requests cryptography websockets; do
  if ! python3 -c "import ${module}" >/dev/null 2>&1; then
    missing+=("${module}")
  fi
done
if [[ "${#missing[@]}" -gt 0 ]]; then
  echo "FAIL: missing declared dependencies: ${missing[*]}" >&2
  echo "Run: python3 -m pip install -r requirements.txt" >&2
  echo "For an isolated fresh-environment check run: scripts/validate_clean_env.sh" >&2
  exit 2
fi

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
