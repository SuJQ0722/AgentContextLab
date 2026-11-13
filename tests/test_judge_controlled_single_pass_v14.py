import sys
import json
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from judge_controlled_single_pass_v14 import valid_control, matched_group, measured_costs


class ControlledGradeTests(unittest.TestCase):
    def test_route_usage_deduplicated_and_missing_cache_not_zero(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); metrics = root / 'metrics'; metrics.mkdir()
            known = {'prompt_tokens': 100, 'completion_tokens': 10, 'total_tokens': 110, 'prompt_tokens_details': {'cached_tokens': 0}}
            partial = {'prompt_tokens': 50, 'completion_tokens': 2, 'total_tokens': 52}
            records = [{'event': 'request_started', 'request_id': key} for key in ['a', 'b']]
            records += [{'event': 'route_failed', 'request_id': 'a', 'raw_provider_usage': partial},
                        {'event': 'stream_complete', 'request_id': 'b', 'raw_provider_usage': known},
                        {'event': 'route_returned', 'request_id': 'b', 'raw_provider_usage': known}]
            (metrics / 'transport-phases-v3.jsonl').write_text('\n'.join(json.dumps(r) for r in records))
            cost = measured_costs(root)['physical_wire_all_purposes']
            self.assertEqual(cost['calls_started'], 2)
            self.assertEqual(cost['total_tokens_reported_known'], 162)
            self.assertEqual(cost['cached_unknown'], 1)
            self.assertIsNone(cost['full_cached_input_tokens'])
    def test_exact_target_identity_and_real_usage_required(self):
        target = {'first_actual_prompt_tokens': 10000, 'prefix_sha256': 'same', 'native_hashes': ['a'], 'actual_route': 'same'}
        control = {**target, 'passed': True, 'final_wire_native_identity_preserved': True}
        self.assertTrue(valid_control(control, target))
        self.assertFalse(valid_control({**control, 'first_actual_prompt_tokens': None}, target))
        self.assertFalse(valid_control({**control, 'native_hashes': ['different']}, target))
        self.assertFalse(valid_control({**control, 'first_actual_prompt_tokens': 10300}, target))
    def test_partial_group_and_missing_grade_not_accuracy(self):
        rows = [{'method': m, 'control_valid': True, 'score': 1, 'prefix_sha256': 'same', 'native_hashes': ['a'], 'actual_prompt_tokens': 10000}
                for m in ['visual', 'summary', 'window']]
        self.assertTrue(matched_group(rows))
        self.assertFalse(matched_group(rows[:2]))
        rows[0]['score'] = None
        self.assertFalse(matched_group(rows))


if __name__ == '__main__': unittest.main()
