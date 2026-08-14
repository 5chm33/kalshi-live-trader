#!/usr/bin/env bash
# Fresh-virtualenv validation. Requires network access only to install declared deps.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${V11_CLEAN_VENV:-$(mktemp -d)}"
CLEANUP=0
if [[ -z "${V11_CLEAN_VENV:-}" ]]; then
  CLEANUP=1
fi
cleanup() {
  if [[ "$CLEANUP" -eq 1 ]]; then rm -rf "$VENV_DIR"; fi
}
trap cleanup EXIT

if ! "$PYTHON_BIN" -m venv "$VENV_DIR" 2>/dev/null; then
  echo "FAIL: Python venv support is required (install python3-venv, then retry)." >&2
  exit 2
fi
"$VENV_DIR/bin/python" -m pip install --disable-pip-version-check --quiet --upgrade pip
"$VENV_DIR/bin/python" -m pip install --disable-pip-version-check --quiet -r "$ROOT/requirements.txt"
cd "$ROOT"
"$VENV_DIR/bin/python" -m compileall -q research main.py
"$VENV_DIR/bin/python" -m unittest discover -s tests -v
"$VENV_DIR/bin/python" main.py >/tmp/kalshi_v11_clean_main_stdout.txt 2>/tmp/kalshi_v11_clean_main_stderr.txt || status=$?
if [[ "${status:-0}" -ne 2 ]]; then
  echo "FAIL: legacy main.py must exit status 2 in clean environment." >&2
  exit 1
fi
grep -q 'LIVE EXECUTION IS DISABLED' /tmp/kalshi_v11_clean_main_stderr.txt
echo "V11 clean-environment validation passed."
