"""Deployment-manifest checks for credentialless public-only collectors."""
from __future__ import annotations

import unittest
from pathlib import Path


class DeploymentManifestTests(unittest.TestCase):
    def test_public_collectors_are_bounded_hardened_and_writer_free(self):
        root = Path(__file__).resolve().parents[1]
        units = {
            'kalshi-weather-forward.service': 'weather_forward.py',
            'kalshi-mlb-book-study.service': 'collect_mlb_microstructure.py',
        }
        for filename, program in units.items():
            with self.subTest(unit=filename):
                text = (root / 'deploy' / 'systemd' / filename).read_text()
                self.assertIn(f'ExecStart=', text)
                self.assertIn(program, text)
                self.assertIn('NoNewPrivileges=yes', text)
                self.assertIn('ProtectSystem=strict', text)
                self.assertIn('PrivateTmp=yes', text)
                self.assertIn('UMask=0077', text)
                self.assertIn('InaccessiblePaths=/home/ubuntu/.config/kalshi', text)
                self.assertIn('ReadWritePaths=/home/ubuntu/kalshi-live-trader/logs/research', text)
                self.assertIn('RuntimeMaxSec=', text)
                self.assertNotIn('pilot_live.py', text)
                self.assertNotIn('fund_pilot.py', text)
                self.assertNotIn('--execute', text)


if __name__ == '__main__':
    unittest.main()
