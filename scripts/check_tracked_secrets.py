"""Fail CI if tracked files contain likely credentials or private key material."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

FORBIDDEN_FILENAMES = {"config.json", "credentials.json", "secrets.json", ".env", ".env.local"}
FORBIDDEN_SUFFIXES = {".pem", ".key", ".p8", ".der", ".p12", ".pfx"}
SIGNATURES = (
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(rb"gh[pousr]_[A-Za-z0-9]{30,}"),
)
CHUNK_SIZE = 64 * 1024
OVERLAP = 256


def forbidden_filename(path: Path) -> bool:
    name = path.name.lower()
    return name in FORBIDDEN_FILENAMES or name.startswith('.env.') or path.suffix.lower() in FORBIDDEN_SUFFIXES


def has_signature(path: Path) -> bool:
    """Bounded-memory scan that cannot silently skip a large tracked blob."""
    tail = b''
    with path.open('rb') as source:
        while chunk := source.read(CHUNK_SIZE):
            data = tail + chunk
            if any(pattern.search(data) for pattern in SIGNATURES):
                return True
            tail = data[-OVERLAP:]
    return False


def scan(root: Path) -> list[str]:
    names = subprocess.check_output(["git", "ls-files", "-z"], cwd=root).split(b"\x00")
    bad = []
    for raw in names:
        if not raw:
            continue
        rel = raw.decode("utf-8", "replace")
        path = root / rel
        if forbidden_filename(path):
            bad.append(f"forbidden tracked credential filename: {rel}")
            continue
        if path.is_file() and has_signature(path):
            bad.append(f"private key/token literal in tracked file: {rel}")
    return bad


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    names = subprocess.check_output(["git", "ls-files", "-z"], cwd=root).split(b"\x00")
    bad = scan(root)
    if bad:
        print("\n".join(bad), file=sys.stderr)
        return 1
    print(f"No tracked credential files or private-key literals in {len(names)-1} tracked files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
