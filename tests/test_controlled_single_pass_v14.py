import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import controlled_single_pass_v14 as v


class ControlledSinglePassTests(unittest.TestCase):
    def test_target_published_after_bounded_annotation_only(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); cell = root / 'cells/browsecomp_v3'; key = 'browsecomp_v3/q_008_r01'
            target = v.v8.target_path(cell, key)
            job = {'job_id': 'controlled/' + key + '/visual', 'campaign_root': str(cell),
                   'controlled_method': 'visual', 'controlled_prefix_key': key, 'control_target_path': str(target),
                   'single_pass_v14': {'target_mode': 'new_visual_measured'}}
            plan = {'source_sha256': {}, 'jobs': [job]}
            v.save(root / 'plan.json', plan)
            out = cell / 'jobs' / job['job_id'] / 'attempt_001'
            class FakeAdapter:
                def annotate(self, value):
                    return {**value, 'bounded_native_protocol': v.bounded.PROTOCOL}
            value = {'passed': True, 'method': 'visual', 'first_actual_prompt_tokens': 12000,
                'native_hashes': ['native'], 'prefix_sha256': 'prefix', 'native_identity_verified': True,
                'final_wire_native_identity_preserved': True, 'final_wire_observed': True}
            self.assertFalse(v.v8.valid_target(value))
            original_policy = {'write_seconds': 45., 'stream_seconds': 300., 'max_failed_sends': 2}
            installed = Mock(return_value={'uninstall': lambda: None})
            def fake_main():
                annotated = v.bounded.BoundedAdapter().annotate(value)
                self.assertTrue(v.v8.valid_target(annotated))
                v.v8.parent.runtime_install(original_policy, out, route_policy='four-route-rotation-v1')
            with patch.object(v, 'validate_plan'), patch.object(v.bounded, 'BoundedAdapter', FakeAdapter), \
                    patch.object(v.v8, 'main', fake_main), patch.object(v.v8.parent, 'runtime_install', installed), \
                    patch.object(sys, 'argv', []):
                v.worker(root, job, out)
            self.assertEqual(installed.call_args.args[0], {'write_seconds': 300., 'stream_seconds': 630., 'max_failed_sends': 2})
            self.assertEqual(original_policy['write_seconds'], 45.)
            self.assertEqual(installed.call_args.kwargs['route_policy'], 'four-route-rotation-v1')
            self.assertTrue(target.exists())
            self.assertEqual(json.loads(target.read_text())['first_actual_prompt_tokens'], 12000)
            # A later measurement cannot replace this first target.
            self.assertFalse(v.v8.publish_target(job, {**json.loads(target.read_text()), 'first_actual_prompt_tokens': 10000}))
            self.assertEqual(json.loads(target.read_text())['first_actual_prompt_tokens'], 12000)

    def test_explicit_extra_attempt_authorization_required(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            v.save(root / 'plan.json', {'source_sha256': {}, 'jobs': [], 'formal_groups': 0})
            with patch.object(sys, 'argv', ['worker', '--root', str(root), '--live']):
                with self.assertRaisesRegex(ValueError, 'authorization'):
                    v.main()


if __name__ == '__main__': unittest.main()
