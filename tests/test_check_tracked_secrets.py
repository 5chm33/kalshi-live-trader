"""Synthetic Git fixtures for the tracked-secret scanner; no real credentials."""
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.check_tracked_secrets import scan


class SecretScanTests(unittest.TestCase):
    def repository(self, root: Path, files: dict[str, bytes]) -> None:
        subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
        for name, content in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        subprocess.run(['git', 'add', '.'], cwd=root, check=True)

    def test_large_tracked_private_key_literal_is_not_skipped(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            synthetic_signature = b'-----BEGIN ' + b'RSA PRIVATE KEY-----'
            self.repository(root, {'blob.bin': b'x' * 3_100_000 + synthetic_signature})
            findings = scan(root)
        self.assertEqual(findings, ['private key/token literal in tracked file: blob.bin'])

    def test_environment_and_credentials_filenames_are_rejected_without_printing_contents(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.repository(root, {'.env.production': b'PLACEHOLDER=value\n',
                                   'credentials.json': b'{}\n'})
            findings = scan(root)
        self.assertEqual(sorted(findings), sorted([
            'forbidden tracked credential filename: .env.production',
            'forbidden tracked credential filename: credentials.json',
        ]))


if __name__ == '__main__':
    unittest.main()
