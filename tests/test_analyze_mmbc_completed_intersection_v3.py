import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('mm_intersection_v3', Path(__file__).resolve().parents[1] / 'scripts/analyze_mmbc_completed_intersection_v3.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class IntersectionV3Tests(unittest.TestCase):
    def test_completed_wrong_or_ungraded_retained(self):
        for score in (0, None):
            old = {'prediction_status': 'completed', 'score': score}
            self.assertIs(module.retain(old, {'prediction_status': 'completed', 'score': 1}), old)

    def test_recovery_state_replaces_old_failure_without_double_count(self):
        rows = [{'method': method, 'prediction_status': 'timeout'} for method in module.METHODS for _ in range(300)]
        rows[-1] = {'method': 'vanilla_visual', 'prediction_status': 'running', 'historical_prediction_status': 'timeout'}
        counts = module.slot_state_counts(rows)
        self.assertEqual(counts['vanilla_visual'], {'timeout': 299, 'running': 1})
        with self.assertRaises(ValueError): module.slot_state_counts(rows + [rows[-1]])

    def test_missing_score_excludes_entire_pair_and_unbalanced_question(self):
        rows = [{'method': m, 'question_id': q, 'question_sha256': q, 'repeat': rep,
                 'prediction_status': 'completed', 'score': int(rep != 2)}
                for m in module.METHODS for q in ('a', 'b') for rep in (1, 2, 3)]
        rows[-1]['score'] = None
        result = module.summarize(rows)
        self.assertEqual(result['slots'], 5)
        self.assertEqual(result['strict_three_repeat_questions'], ['a'])
        self.assertEqual(result['completed_missing_any_grade'], 1)

    def test_question_identity_mismatch_rejected(self):
        rows = [{'method': m, 'question_id': 'a', 'question_sha256': m, 'repeat': 1,
                 'prediction_status': 'completed', 'score': 1} for m in module.METHODS]
        with self.assertRaises(ValueError): module.summarize(rows)
