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
                  'forecast':{'uncalibrated_grid_max_f':70,'forecast_generated_age_seconds':60,
                              'forecast_update_age_seconds':120},
                  'books':[{'before_utc':'2026-09-26T22:00:00Z','after_utc':'2026-09-26T22:00:01Z','quote':{'yes_ask_size_fp':'2'}},
                           {'before_utc':'2026-09-26T22:00:02Z','after_utc':'2026-09-26T22:00:03Z','quote':None}],
                  'book_skew_seconds':3.0,'max_book_skew_seconds':5.0,
                  'paper_orders':0,'real_orders':0,'real_fills':0}
        return start,decision

    def test_capture_not_called_profit_or_fill(self):
        with tempfile.TemporaryDirectory() as d:
            text=render(self.journal(d,list(self.sample())))
        self.assertIn('valid pre-event observations: 1',text)
        self.assertIn('one-contract YES asks displayed; not fills',text)
        self.assertIn('Fee-adjusted returns and win percentage: **undefined**',text)
        self.assertNotIn('100%',text)

    def test_fee_hurdle_never_claimed_as_forecast_or_fill(self):
        with tempfile.TemporaryDirectory() as d:
            start,decision=self.sample()
            decision['markets']=[{'ticker':'KXHIGHNY-26SEP27-T65'},
                                 {'ticker':'KXHIGHNY-26SEP27-T72'}]
            decision['books']=[{'ticker':'KXHIGHNY-26SEP27-T65','before_utc':'2026-09-26T22:00:00Z','after_utc':'2026-09-26T22:00:01Z','quote':{
                'yes_ask_size_fp':'105.04','yes_ask':'0.6200',
                'no_ask_size_fp':'198.00','no_ask':'0.3900',
                'indicative_yes_taker_fee_ceiling':'0.0200',
                'indicative_no_taker_fee_ceiling':'0.0200'}},
                               {'ticker':'KXHIGHNY-26SEP27-T72','before_utc':'2026-09-26T22:00:02Z','after_utc':'2026-09-26T22:00:03Z','quote':None}]
            text=render(self.journal(d,[start,decision]))
        self.assertIn('0.6400 (105.04 shown)',text)
        self.assertIn('0.4100 (198.00 shown)',text)
        self.assertIn('one-sided/empty; ineligible',text)
        self.assertIn('Not a forecast probability or trade signal',text)
        self.assertIn('Fee-adjusted returns and win percentage: **undefined**',text)

    def test_legacy_or_skewed_timing_is_visible_but_excluded_from_hurdles(self):
        with tempfile.TemporaryDirectory() as d:
            start,decision=self.sample()
            decision.pop('book_skew_seconds')
            text=render(self.journal(d,[start,decision]))
        self.assertIn('freshness/skew proof unavailable',text)
        self.assertIn('No full market/book rows yet',text)

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
