import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import prepare_visual_inline_two_hour_v7 as preparation
import run_visual_inline_two_hour_trial_v7 as trial


class TwoHourTests(unittest.TestCase):
    def test_any_completed_is_retained_even_followed_by_failure(self):
        for score in (0, 1, None):
            self.assertFalse(preparation.choose([{'status': 'completed', 'score': score}, {'status': 'timeout'}])[0])

    def test_only_latest_execution_failure_selected(self):
        self.assertTrue(preparation.choose([{'status': 'timeout'}, {'status': 'failed'}])[0])
        self.assertFalse(preparation.choose([{'status': 'failed'}, {'status': 'not_started'}])[0])
        self.assertFalse(preparation.choose([])[0])

    def test_fixed_scope_has_seven_scales_and_no_new_benchmark(self):
        self.assertEqual(len(preparation.CELLS), 13)
        self.assertEqual(sum(c.startswith('rq3_') for c in preparation.CELLS), 7)
        self.assertFalse(any('agentic' in c for c in preparation.CELLS))

    def test_deadline_disagreement_is_rejected(self):
        spec = {'two_hour_recovery_version': preparation.PROTOCOL, 'timeout_seconds': 7200}
        cfg = {'timeout_seconds': 7200, 'max_output_tokens': 8192}
        trial.validate_deadline(spec, cfg)
        with self.assertRaises(ValueError):
            trial.validate_deadline(spec, {**cfg, 'timeout_seconds': 1800})
        with self.assertRaises(ValueError):
            trial.validate_deadline(spec, {**cfg, 'max_output_tokens': 4096})

    def test_controlled_source_requires_copied_deadline(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / 'controlled.json'
            p.write_text(json.dumps({'timeout_seconds': 3600, 'config_path': 'cfg'}))
            spec = {'two_hour_recovery_version': preparation.PROTOCOL, 'timeout_seconds': 7200,
                    'config_path': 'cfg', 'controlled_spec_path': str(p),
                    'controlled_input_reuse_version': 'controlled-frozen-input-reuse-v1'}
            cfg = {'timeout_seconds': 7200, 'max_output_tokens': 8192}
            with self.assertRaises(ValueError): trial.validate_deadline(spec, cfg)
            p.write_text(json.dumps({'timeout_seconds': 7200, 'config_path': 'cfg'}))
            trial.validate_deadline(spec, cfg)

    def test_dsh_outer_deadline_does_not_add_240_seconds(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / 'config.json'
            config.write_text(json.dumps({'timeout_seconds': 7200, 'max_output_tokens': 8192}))
            spec = {'two_hour_recovery_version': preparation.PROTOCOL, 'timeout_seconds': 7200,
                    'config_path': str(config)}
            command = ['python', str(trial.ROOT / 'scripts/dsh_hosted_bc_worker_v1.py'), '--timeout', '7200']
            with patch.object(trial, 'validate_routes'), patch.object(trial, 'OriginalNative', return_value=(command, Path('result'), 7440)):
                actual, _, timeout = trial.native_command(spec, Path(directory))
            self.assertEqual(timeout, 7200)
            self.assertEqual(Path(actual[1]).name, 'dsh_inline_bc_worker_v6.py')
            self.assertEqual(actual[actual.index('--timeout') + 1], '7200')
