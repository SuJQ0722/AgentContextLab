import contextvars
import json
import tempfile
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import controlled_hosted_visual_worker_v2 as worker
import isolated_verified_image_host_v1 as hosting
import run_visual_hosted_retry_trial_v2 as trial
import run_visual_hosted_retry_v2 as controller


class ControlledUploadContextTests(unittest.TestCase):
    def test_retired_host_and_worker_cannot_execute_upload(self):
        from compression_inline_only import CompressionHostingRemoved
        with self.assertRaises(CompressionHostingRemoved):
            hosting.IsolatedVerifiedImageHost('unused', {})(b'canvas')
        with self.assertRaises(CompressionHostingRemoved):
            worker.main()

    def test_trial_replaces_controlled_entry_only_and_keeps_output_timeout(self):
        spec = {'controlled_spec_path': 'frozen.json', 'hosted_runtime_version': 'verified-hosted-images-v4', 'image_transport': 'verified-imgbb-url-v2'}
        with patch.object(trial, 'OriginalNative', return_value=(['python', str(ROOT / 'scripts/controlled_hosted_visual_worker_v1.py'), '--live'], Path('result'), 3600)):
            cmd, result, timeout = trial.native_command(spec, Path('out'))
        self.assertEqual(cmd[1], str(ROOT / 'scripts/controlled_hosted_visual_worker_v2.py'))
        self.assertEqual((result, timeout), (Path('result'), 3600))
        with self.assertRaises(ValueError):
            trial.native_command({}, Path('out'))

    def test_controller_launch_replaces_trial_only(self):
        command = ['python', str(ROOT / 'scripts/run_visual_hosted_retry_trial_v1.py'), '--live']
        with patch.object(controller.subprocess, 'Popen', return_value='child') as popen:
            self.assertEqual(controller.launch(command, cwd=ROOT), 'child')
            self.assertEqual(popen.call_args.args[0][1], str(ROOT / 'scripts/run_visual_hosted_retry_trial_v2.py'))
        self.assertEqual(command[1], str(ROOT / 'scripts/run_visual_hosted_retry_trial_v1.py'))

    def test_control_gate_uses_actual_v4_ledger_and_rejects_native_removals(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            metrics = out / 'metrics'
            metrics.mkdir()
            path = metrics / 'hosted-images-wire-v4.jsonl'
            path.write_text(json.dumps({'decision': 'allow', 'selection': {'removed': []}}) + '\n')
            value = worker.annotate({'passed': True}, out)
            self.assertTrue(value['passed'])
            self.assertTrue(value['final_wire_observed'])
            self.assertFalse(value['old_matched_three_arm_comparison_valid'])
            path.write_text(json.dumps({'decision': 'allow', 'selection': {'removed': [{'origin': 'native'}]}}) + '\n')
            value = worker.annotate({'passed': True}, out)
            self.assertFalse(value['passed'])
            self.assertEqual(value['final_wire_native_removals'], 1)


if __name__ == '__main__':
    unittest.main()
