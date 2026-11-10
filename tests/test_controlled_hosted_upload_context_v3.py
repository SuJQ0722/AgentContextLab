import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import controlled_hosted_visual_worker_v3 as worker
import run_visual_hosted_retry_trial_v3 as trial
import run_visual_hosted_retry_v3 as controller
from inline_route_contract_v1 import ROUTES, validate_routes


def config():
    return dict(model=ROUTES[0], model_route_policy='four-route-rotation-v1', approved_model_routes=ROUTES,
                image_transport='inline-recent-ten-chunked-v1', transport_delivery_version='inline-direct-v1',
                transport_runtime_version='visual-transport-runtime-v3')


class ControlledInlineV3Tests(unittest.TestCase):
    def test_control_gate_reads_inline_native_retention(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory);(out / 'metrics').mkdir()
            path = out / 'metrics/inline-images-wire-v1.jsonl'
            path.write_text(json.dumps({'decision': 'allow', 'selection': {'removed': []}}) + '\n')
            value = worker.annotate({'passed': True}, out)
            self.assertTrue(value['passed']);self.assertTrue(value['final_wire_observed'])
            self.assertFalse(value['old_matched_three_arm_comparison_valid'])
            path.write_text(json.dumps({'decision': 'allow', 'selection': {'removed': [{'origin': 'native'}]}}) + '\n')
            self.assertFalse(worker.annotate({'passed': True}, out)['passed'])

    def test_strict_route_contract_and_trial_preserve_output(self):
        cfg = config();validate_routes(cfg, cfg)
        with self.assertRaises(ValueError):
            validate_routes(dict(cfg, approved_model_routes=ROUTES + ['other']), cfg)
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / 'cfg.json';p.write_text(json.dumps(cfg))
            spec = dict(cfg, config_path=str(p))
            for old, new in trial.WORKERS.items():
                with patch.object(trial, 'OriginalNative', return_value=(['python', str(ROOT / 'scripts' / old)], Path('native-result'), 1800)):
                    cmd, result, timeout = trial.native_command(spec, Path(directory))
                    self.assertEqual(cmd[1], str(ROOT / 'scripts' / new))
                    self.assertEqual((result, timeout), (Path('native-result'), 1800))

    def test_default_dry_run_never_installs_transport_or_host(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory);spec = root / 'spec.json';spec.write_text('{}')
            with patch.object(worker, 'validate', return_value=({}, config())), \
                 patch.object(worker, 'inline_install', side_effect=AssertionError('No live transport allowed')), \
                 patch.object(worker, 'runtime_install', side_effect=AssertionError('No model transport allowed')), \
                 patch.object(sys, 'argv', ['worker', '--spec', str(spec), '--out', str(root / 'out')]), redirect_stdout(io.StringIO()) as stdout:
                worker.main()
            self.assertEqual(json.loads(stdout.getvalue())['model_calls'], 0)
        self.assertFalse(hasattr(worker, 'VerifiedImageHost'))
        self.assertNotIn('verified_hosted_images', Path(worker.__file__).read_text())

    def test_controller_substitutes_only_trial_entry(self):
        command = ['python', str(ROOT / 'scripts/run_visual_hosted_retry_trial_v1.py'), '--live']
        with patch.object(controller.subprocess, 'Popen', return_value='child') as popen:
            self.assertEqual(controller.launch(command, cwd=ROOT), 'child')
            self.assertEqual(popen.call_args.args[0][1], str(ROOT / 'scripts/run_visual_hosted_retry_trial_v3.py'))
        self.assertEqual(command[1], str(ROOT / 'scripts/run_visual_hosted_retry_trial_v1.py'))


if __name__ == '__main__':
    unittest.main()
