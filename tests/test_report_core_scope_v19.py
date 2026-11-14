import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import report_core_scope_v19 as module


class ScopeTests(unittest.TestCase):
    def test_controlled_metadata_excluded_even_without_path_marker(self):
        self.assertFalse(module.core_job({'experiment_kind': 'controlled'}))
        self.assertFalse(module.core_job({'experiment_kind': 'mmbc', 'calibration_not_scored': True}))
        self.assertTrue(module.core_job({'experiment_kind': 'mmbc', 'calibration_not_scored': False}))

    def test_replacement_keeps_history_and_removes_wrong_success(self):
        slot = {'slot_id': 'x', 'selected_completed': {'result_sha256': 'wrong'},
                'known_score': 1, 'cost_records': [{'path': 'preserve'}]}
        correction = {'slot_id': 'x', 'before': {'selected_result_sha256': 'wrong'},
                      'after': {'selected_result_path': None, 'latest_terminal_status': 'timeout',
                                'latest_terminal_result_path': 'core', 'latest_terminal_result_sha256': 'right'}}
        result = module.replace_baseline(slot, correction)
        self.assertIsNone(result['selected_completed'])
        self.assertIsNone(result['known_score'])
        self.assertEqual(result['cost_records'], slot['cost_records'])
        self.assertEqual(slot['known_score'], 1)
        self.assertEqual(result['latest_known_result']['path'], 'core')
        correction['before']['selected_result_sha256'] = 'changed'
        with self.assertRaises(ValueError): module.replace_baseline(slot, correction)

    def test_question_identity_alone_cannot_accept_controlled_completion(self):
        observer = module.ScopeReporter.__new__(module.ScopeReporter)
        observer.expected_job = lambda _: {'experiment_kind': 'controlled'}
        with patch.object(module.base.Reporter, 'result', return_value={'status': 'completed', 'identity_valid': True}):
            record = observer.result('arbitrary-name/result.json', {})
        self.assertFalse(record['identity_valid'])
        self.assertIsNone(module.base.choose_completed([record]))


if __name__ == '__main__':
    unittest.main()
