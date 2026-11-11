import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import analyze_gemini_matched_completion_v1 as m


class HistoricalIntersectionTests(unittest.TestCase):
    def rows(self):
        return [{'benchmark': 'bc', 'method': method, 'question_hash': 'q',
                 'repeat': rep, 'clean_completed': True, 'prediction_status': 'completed',
                 'score': 0 if method == 'visual' else 1}
                for method in m.METHODS for rep in (1, 2, 3)]

    def test_wrong_answers_retained_in_balanced_intersection(self):
        v = m.summarize(self.rows(), 'bc', {'q'}, [1, 2, 3])
        self.assertEqual(v['slots'], 3)
        self.assertEqual(v['methods']['visual']['accuracy'], 0)
        self.assertEqual(v['methods']['visual']['balanced_avg3']['questions'], 1)

    def test_missing_method_is_unknown_not_failed(self):
        v = m.summarize(self.rows()[:-1], 'bc', {'q'}, [1, 2, 3])
        self.assertEqual(v['slots'], 2)
        self.assertEqual(v['methods']['visual']['statuses']['missing_archive_record'], 1)
        self.assertIsNone(v['methods']['visual']['balanced_avg3']['mean'])

    def test_failure_and_missing_grade_remove_paired_slot_for_every_method(self):
        rows = self.rows()
        rows[0].update(clean_completed=False, prediction_status='timeout')
        rows[1]['score'] = None
        v = m.summarize(rows, 'bc', {'q'}, [1, 2, 3])
        self.assertEqual(v['completed_slots'], 2)
        self.assertEqual(v['completed_missing_any_grade'], 1)
        self.assertTrue(all(x['denominator'] == 1 for x in v['methods'].values()))

    def test_duplicate_rejected(self):
        rows = self.rows()
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            m.summarize(rows + [rows[0]], 'bc', {'q'}, [1, 2, 3])


if __name__ == '__main__':
    unittest.main()
