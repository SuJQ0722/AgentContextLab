import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import prepare_seven_turns500_v12 as prep


class Turns500PreparationTests(unittest.TestCase):
    def test_updates_actual_native_read_sections_without_mutating_history(self):
        old = {'one_hour_retry_version': 'v10', 'runtime_recovery_version': 'v11',
               'bc100': {'max_rounds': 60}, 'pilot': {'compression_trigger_tokens': 32768},
               'mmbc100_campaign': {'max_rounds': 60}, 'visual_page_window': {'max_pages': 7}}
        saved = copy.deepcopy(old); cfg = prep.configure(old)
        self.assertEqual(old, saved)
        for key in ('pilot', 'bc100', 'bc100_campaign', 'mmbc100_campaign'):
            self.assertEqual(cfg[key]['max_rounds'], 500); self.assertEqual(cfg[key]['timeout_seconds'], 3600)
        self.assertEqual(cfg['visual_page_window'], old['visual_page_window'])
        self.assertEqual(cfg['one_hour_retry_version'], 'v10'); self.assertEqual(cfg['runtime_recovery_version'], 'v11')
        self.assertEqual((cfg['max_attempts'], cfg['max_timeout_retries']), (3, 2))

    def test_completed_retained_even_wrong_without_recount(self):
        reason, _ = prep.selection({}, {'status': 'completed', 'score': 0}, '/unused')
        self.assertEqual(reason, 'retain_completed')

    def test_failed_and_blocked_not_retried(self):
        for status in ('failed', 'blocked'):
            self.assertEqual(prep.selection({}, {'status': status}, '/unused')[0], 'exclude_final_non_timeout_failure')

    def test_pending_zero_attempts_can_continue(self):
        with tempfile.TemporaryDirectory() as temp:
            reason, budget = prep.selection({}, None, temp)
            self.assertEqual(reason, 'continue_timeout_or_unfinished'); self.assertEqual(budget['prior_attempts_consumed'], 0)

    def test_previous_zero_model_records_separate_and_three_model_attempts_exhausted(self):
        with tempfile.TemporaryDirectory() as temp:
            a = {'result_path': temp + '/old-model/result.json'}
            b = {'result_path': temp + '/old-reject/result.json', 'classification': 'verified_pre_model_contract_rejection'}
            job = {'prior_attempts_consumed': 1, 'prior_attempt_costs': [a, b], 'prior_operational_attempts': [b]}
            result = {'status': 'timeout', 'prior_attempts_consumed': 1, 'attempt_count': 2,
                      'attempts': [{'result_path': temp + '/new1/result.json'}, {'result_path': temp + '/new2/result.json'}]}
            with patch.object(prep.previous, 'attempt_has_model_or_unknown', return_value=(True, 'conservative_unknown_acceptance')):
                reason, budget = prep.selection(job, result, temp)
            self.assertEqual(reason, 'retain_attempt_budget_exhausted')
            self.assertEqual(budget['prior_attempts_consumed'], 3)
            self.assertEqual(len(budget['prior_attempt_costs']), 3)
            self.assertEqual(len(budget['prior_operational_attempts']), 1)

    def test_stop_interruption_counts_unrecorded_launched_attempt(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); folder = root / 'runs/attempt_001';folder.mkdir(parents=True)
            (folder / 'worker-started.json').write_text('{}')
            old = [{'result_path': temp + '/prior1/result.json'}, {'result_path': temp + '/prior2/result.json'}]
            job = {'prior_attempts_consumed': 2, 'prior_attempt_costs': old}
            with patch.object(prep.previous, 'attempt_has_model_or_unknown', return_value=(True, 'conservative_unknown_acceptance')):
                reason, budget = prep.selection(job, {'status': 'interrupted', 'attempt_count': 0}, root)
            self.assertEqual(reason, 'retain_attempt_budget_exhausted'); self.assertEqual(budget['prior_attempts_consumed'], 3)

    def test_missing_prior_cost_path_cannot_reset_budget(self):
        with self.assertRaises(ValueError): prep.attempt_budget({'prior_attempts_consumed': 2, 'prior_attempt_costs': []}, None, '/unused')

    def test_declared_current_attempts_need_distinct_paths(self):
        with self.assertRaises(ValueError): prep.attempt_budget({}, {'attempt_count': 2, 'attempts': []}, '/unused')
        a = {'result_path': '/unused/result.json'}
        with self.assertRaises(ValueError): prep.attempt_budget({}, {'attempt_count': 2, 'attempts': [a, a]}, '/unused')

    def test_completed_native_survives_interrupted_parent(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / 'runs/attempt_001/result.json';p.parent.mkdir(parents=True);p.write_text(json.dumps({'status': 'completed', 'score': 0}))
            reason, metadata = prep.selection({}, {'status': 'interrupted'}, temp)
            self.assertEqual(reason, 'retain_completed_native');self.assertEqual(metadata['retained_result_path'], str(p))

    def test_known_pre_network_rejection_does_not_consume_model_budget(self):
        with tempfile.TemporaryDirectory() as temp:
            result = {'status': 'interrupted', 'attempts': [{'result_path': temp + '/zero/result.json'}], 'attempt_count': 1}
            with patch.object(prep.previous, 'attempt_has_model_or_unknown', return_value=(False, 'verified_pre_network_image_guard_rejection')):
                reason, budget = prep.selection({}, result, temp)
            self.assertEqual(reason, 'continue_timeout_or_unfinished');self.assertEqual(budget['prior_attempts_consumed'], 0)
            self.assertEqual(len(budget['prior_operational_attempts']), 1)


if __name__ == '__main__': unittest.main()
