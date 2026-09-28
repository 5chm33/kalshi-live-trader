"""Calibration scorecard format tests with synthetic rows, never trade evidence."""
import unittest
from weather_calibration_report import render


class ReportTests(unittest.TestCase):
    def fixture(self):
        return {'generated_at_utc':'2026-09-26T23:00:00Z','orders':0,'fills':0,
            'live_strategy_authorized':False,'train_start':'2026-06-01','train_end':'2026-08-31',
            'holdout_end':'2026-09-25','target':'2026-09-27',
            'archived_observations':[{'date':'2026-06-01'}], 'missing_or_untrusted_dates':[]}

    def test_missing_history_does_not_become_success(self):
        payload=self.fixture();payload['missing_or_untrusted_dates']=[{'date':'2026-08-01'}]
        text=render(payload)
        self.assertIn('No validated model output',text)
        self.assertIn('No exchange orders',text)

    def test_provisional_model_cannot_be_called_live_trade(self):
        payload=self.fixture()
        payload['target_forecast_grid_max_f']=65.2;payload['target_model_run_utc']='2026-09-26T12:00Z'
        payload['evaluation']={'training_days':92,'holdout_days':25,
            'training_mean_error_f':-.5,'holdout_mae_f':2.8,
            'within_5f_train_days':22,'within_5f_holdout_days':13,'supported_forecast_regime':True,
            'predictions':[{'ticker':'KXHIGHNY-26SEP27-B65','model_probability':.78,
              'wilson_lower_95':.61,'holdout_brier_model':.18,'holdout_brier_naive':.27,
              'holdout_true_count':12,'similar_holdout_true_count':6,
              'yes_ask_dollars':'0.50','one_contract_fee_estimate_dollars':'0.02',
              'fee_inclusive_hurdle':'0.52','provisional_hypothesis_only':True}]}
        text=render(payload)
        self.assertIn('research hypothesis only',text)
        self.assertIn('Execution remains disabled',text)
        self.assertIn('not a strategy backtest',text)
        payload['orders']=1
        with self.assertRaises(ValueError):render(payload)

    def test_incomplete_archive_forces_exploratory_label(self):
        payload=self.fixture()
        payload['missing_or_untrusted_dates']=[{'date':'2026-06-11','reason':'ValueError'}]
        payload['target_forecast_grid_max_f']=65.2
        payload['target_model_run_utc']='2026-09-26T12:00Z'
        payload['evaluation']={'training_days':91,'holdout_days':25,
            'training_mean_error_f':-.5,'holdout_mae_f':2.8,
            'within_5f_train_days':1,'within_5f_holdout_days':4,'supported_forecast_regime':False,
            'predictions':[{'ticker':'KXHIGHNY-X','model_probability':None,
              'wilson_lower_95':None,'holdout_brier_model':None,'holdout_brier_naive':None,
              'holdout_scored_days':0,
              'holdout_true_count':0,'similar_holdout_true_count':0,
              'yes_ask_dollars':'0.50','one_contract_fee_estimate_dollars':'0.02',
              'fee_inclusive_hurdle':'0.52','provisional_hypothesis_only':False}]}
        text=render(payload)
        self.assertIn('Incomplete archive: incomplete-source research only',text)
        self.assertIn('NO — extrapolation',text)
        self.assertIn('unsupported | unsupported',text)
        self.assertNotIn('0.780',text)
        payload['evaluation']['predictions'][0]['provisional_hypothesis_only']=True
        with self.assertRaisesRegex(ValueError,'cannot generate'):
            render(payload)

    def test_unsupported_row_cannot_be_positive_even_with_complete_archive(self):
        payload=self.fixture()
        payload['target_forecast_grid_max_f']=64.9
        payload['target_model_run_utc']='2026-09-26T12:00Z'
        payload['evaluation']={'training_days':91,'holdout_days':24,
            'training_mean_error_f':-4.611,'holdout_mae_f':4.021,
            'within_5f_train_days':1,'within_5f_holdout_days':4,'supported_forecast_regime':False,
            'predictions':[{'ticker':'KXHIGHNY-X','model_probability':None,'wilson_lower_95':None,
                'holdout_brier_model':None,'holdout_brier_naive':None,'holdout_scored_days':16,
                'holdout_true_count':0,'similar_holdout_true_count':0,
                'yes_ask_dollars':'0.50','one_contract_fee_estimate_dollars':'0.02',
                'fee_inclusive_hurdle':'0.52','provisional_hypothesis_only':True}]}
        with self.assertRaisesRegex(ValueError,'Unsupported probability'):
            render(payload)


if __name__=='__main__':unittest.main()
