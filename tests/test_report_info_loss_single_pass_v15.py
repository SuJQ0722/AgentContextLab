import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from report_info_loss_single_pass_v15 import matched_facts


class MatchedReportTests(unittest.TestCase):
    def row(self, method, split='holdout', version='fixed-output-span-support-v14'):
        return {'case': 'q', 'method': method, 'split': split, 'judge_version': version,
                'facts': [{'id': 'f1', 'answer': '42'}], 'qa_answers': {'f1': '42'},
                'judgment': {'f1': {'supported': True}}}
    def test_missing_arm_never_creates_complete_curve(self):
        self.assertEqual(matched_facts([self.row('text')], 'qa', ['text', 'canvas']), {})
    def test_development_and_old_judge_do_not_fill_holdout(self):
        rows = [self.row('text'), self.row('canvas', version='legacy')]
        self.assertEqual(matched_facts(rows, 'recall', ['text', 'canvas']), {})
        self.assertEqual(matched_facts([self.row('text', 'dev'), self.row('canvas', 'dev')], 'qa', ['text', 'canvas']), {})
    def test_complete_matched_facts(self):
        self.assertEqual(matched_facts([self.row('text'), self.row('canvas')], 'recall', ['text', 'canvas']), {('q', 'f1'): {'text': 1, 'canvas': 1}})


if __name__ == '__main__': unittest.main()
