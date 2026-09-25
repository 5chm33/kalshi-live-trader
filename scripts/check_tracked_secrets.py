"""Fail CI if tracked files contain likely credentials or private key material."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

FORBIDDEN_FILENAMES = {"config.json", ".env", ".env.local"}
FORBIDDEN_SUFFIXES = {".pem", ".key", ".p12", ".pfx"}
SIGNATURES = (
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(rb"gh[pousr]_[A-Za-z0-9]{30,}"),
)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    names = subprocess.check_output(["git", "ls-files", "-z"], cwd=root).split(b"\x00")
    bad = []
    for raw in names:
        if not raw:
            continue
        rel = raw.decode("utf-8", "replace")
        path = root / rel
        if path.name.lower() in FORBIDDEN_FILENAMES or path.suffix.lower() in FORBIDDEN_SUFFIXES:
            bad.append(f"forbidden tracked credential filename: {rel}")
            continue
        if not path.is_file() or path.stat().st_size > 3_000_000:
            continue
        contents = path.read_bytes()
        if any(pattern.search(contents) for pattern in SIGNATURES):
            bad.append(f"private key/token literal in tracked file: {rel}")
    if bad:
        print("\n".join(bad), file=sys.stderr)
        return 1
    print(f"No tracked credential files or private-key literals in {len(names)-1} tracked files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
