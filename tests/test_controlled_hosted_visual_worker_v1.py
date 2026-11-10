import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from controlled_hosted_visual_worker_v1 import annotate


class ControlledHostedTests(unittest.TestCase):
    def test_native_retention_loss_invalidates_old_control_gate(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); p = root / 'metrics/hosted-images-wire-v3.jsonl'
            p.parent.mkdir(); p.write_text(json.dumps({'decision': 'allow', 'selection': {
                'removed': [{'origin': 'native'}, {'origin': 'canvas'}]}}) + '\n')
            original = {'passed': True, 'native_hashes': ['old']}
            got = annotate(original, root)
            self.assertFalse(got['passed'])
            self.assertTrue(got['pre_retention_control_passed'])
            self.assertFalse(got['old_matched_three_arm_comparison_valid'])
            self.assertEqual(got['final_wire_native_removals'], 1)
            self.assertTrue(original['passed'])

    def test_no_wire_is_unknown_not_pass_and_preserved_native_is_explicit(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.assertFalse(annotate({'passed': True}, root)['passed'])
            p = root / 'metrics/hosted-images-wire-v3.jsonl'; p.parent.mkdir()
            p.write_text(json.dumps({'decision': 'allow', 'selection': {'removed': []}}) + '\n')
            got = annotate({'passed': True}, root)
            self.assertTrue(got['passed'])
            self.assertTrue(got['final_wire_native_identity_preserved'])
            self.assertFalse(got['old_matched_three_arm_comparison_valid'])


if __name__ == '__main__':
    unittest.main()
