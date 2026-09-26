"""Synthetic formatting fixtures; none is a forecast or a real trade."""
import json
import tempfile
import unittest
from pathlib import Path

import weather_forward as study
from weather_forward_report import render


class WeatherReportTests(unittest.TestCase):
    def journal(self, base, rows):
        p=Path(base)/'weather.jsonl'
        p.write_text(''.join(json.dumps(x)+'\n' for x in rows));p.chmod(0o600)
        return p

    def sample(self):
        start={'type':'study_start','observed_at_utc':'2026-09-26T21:00:00Z',
               'series':study.SERIES,'first_target':study.FIRST_TARGET.isoformat(),
               'last_target':study.LAST_TARGET.isoformat(),'until_utc':study.stamp(study.DEADLINE),
               'cutoff_local':'18:00 America/New_York','paper_orders':0,'real_orders':0,'real_fills':0}
        decision={'type':'decision_observation','target_date':'2026-09-27',
                  'forecast':{'uncalibrated_grid_max_f':70},
                  'books':[{'quote':{'yes_ask_size_fp':'2'}},{'quote':None}],
                  'paper_orders':0,'real_orders':0,'real_fills':0}
        return start,decision

    def test_capture_not_called_profit_or_fill(self):
        with tempfile.TemporaryDirectory() as d:
            text=render(self.journal(d,list(self.sample())))
        self.assertIn('valid pre-event observations: 1',text)
        self.assertIn('one-contract YES asks displayed; not fills',text)
        self.assertIn('Fee-adjusted returns and win percentage: **undefined**',text)
        self.assertNotIn('100%',text)

    def test_verified_source_and_venue_counted_once(self):
        with tempfile.TemporaryDirectory() as d:
            start,decision=self.sample()
            label={'type':'source_and_venue_label','target_date':'2026-09-27',
                   'twc_station_row':{'data':{'maxTemp':69}},
                   'paper_orders':0,'real_orders':0,'real_fills':0}
            text=render(self.journal(d,[start,decision,label]))
        self.assertIn('double-confirmed final labels: 1',text)
        self.assertIn('| 2026-09-27 | captured | 70 | 69 | Yes |',text)

    def test_public_only_rejects_order_claim(self):
        with tempfile.TemporaryDirectory() as d:
            start,decision=self.sample()
            decision['real_orders']=1
            with self.assertRaises(ValueError):
                render(self.journal(d,[start,decision]))

    def test_later_source_revision_invalidates_prior_confirmation(self):
        with tempfile.TemporaryDirectory() as d:
            start,decision=self.sample()
            label={'type':'source_and_venue_label','target_date':'2026-09-27',
                   'twc_station_row':{'data':{'maxTemp':69},'status':'official'},
                   'venue_settlements':[{'ticker':'one','result':'yes'}],
                   'paper_orders':0,'real_orders':0,'real_fills':0}
            revision={'type':'source_revision_or_disagreement','target_date':'2026-09-27',
                      'previous_label':label,
                      'current_source_snapshot':{'row':{'data':{'maxTemp':70},'status':'revised'}},
                      'paper_orders':0,'real_orders':0,'real_fills':0}
            text=render(self.journal(d,[start,decision,label,revision]))
        self.assertIn('double-confirmed final labels: 0',text)
        self.assertIn('source revision or disagreement UNRESOLVED',text)
        self.assertIn('| 2026-09-27 | captured | 70 | — | No |',text)

if __name__=='__main__':
    unittest.main()
