import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('mm_intersection', Path(__file__).resolve().parents[1] / 'scripts/analyze_mmbc_completed_intersection_v2.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class IntersectionTests(unittest.TestCase):
    def test_completed_wrong_and_ungraded_never_replaced(self):
        for score in (0, None):
            old = {'prediction_status': 'completed', 'score': score}
            self.assertIs(module.retain(old, {'prediction_status': 'completed', 'score': 1}), old)

    def test_failed_can_be_replaced_by_wrong_completed(self):
        new = {'prediction_status': 'completed', 'score': 0}
        self.assertIs(module.retain({'prediction_status': 'timeout'}, new), new)

    def test_pair_intersection_and_balanced_subset(self):
        rows = [{'method': m, 'question_id': q, 'question_sha256': q, 'repeat': rep,
                 'prediction_status': 'completed', 'score': int(rep != 2)}
                for m in module.METHODS for q in ('a', 'b') for rep in (1, 2, 3)]
        rows[-1]['score'] = None
        value = module.summarize(rows)
        self.assertEqual(value['slots'], 5)
        self.assertEqual(value['strict_three_repeat_questions'], ['a'])
        self.assertAlmostEqual(value['methods']['visual']['strict_three_repeat']['avg3'], 2/3)
        self.assertEqual(value['completed_missing_any_grade'], 1)
