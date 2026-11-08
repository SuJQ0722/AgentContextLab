import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import dsh_image_preservation as old
import dsh_image_preservation_capacity1 as new
import run_bc_trial_v3 as frozen
import run_bc_trial_v3_capacity1 as trial
import run_bc_campaign_v3_capacity1 as controller
import run_bc_campaign_v3 as original_controller


class CapacityTests(unittest.TestCase):
    def test_only_capacity_and_actual_offload_id_change(self):
        env = {'TOKENHUB_BASE_URL': 'http://127.0.0.1/v1', 'ACL_MODEL': 'fixture',
               'ACL_INPUT_MODALITIES': '["text","image"]', 'ACL_CONTEXT_WINDOW': '131072', 'ACL_MAX_OUTPUT_TOKENS': '8192'}
        before, after = old.preservation_patches(env), new.preservation_patches(env)
        self.assertEqual(after.pop(), {'id': 'image-offload', 'disabled': True})
        provider = after[1]['config']['providers']['tokenhub']
        self.assertEqual(provider['maxRequestImageBytes'], 64 * 1024 * 1024)
        provider['maxRequestImageBytes'] = 20 * 1024 * 1024
        self.assertEqual(after, before)
        bundle = (ROOT/'deepseekHarness/packages/bundle/base/cordis.patch.yml').read_text()
        self.assertIn("id: image-offload\n      name: '@deepseek-ai/dsh-compaction-image-offload'", bundle)

    def test_route_changes_only_dsh_script(self):
        for harness in ['hermes', 'dsh']:
            spec = {'harness': harness, '_spec_path': '/fixture/spec.json', 'strategy': 'visual',
                    'question_id': 'q_001', 'repeat': 1, 'timeout_seconds': 600,
                    'config_path': '/fixture/config.json', 'campaign_root': '/fixture', 'cohort_sha256': 'a'*64}
            before = frozen.native_command(spec, Path('/fixture/out'))
            after = trial.routed_native_command(frozen.native_command)(spec, Path('/fixture/out'))
            if harness == 'hermes': self.assertEqual(before, after)
            else:
                self.assertEqual(after[0][1], str(ROOT/'scripts/run_dsh_eval_v3_capacity1.py'))
                self.assertEqual(after[0][2:], before[0][2:]); self.assertEqual(after[1:], before[1:])

    def test_single_validation_then_lineage_then_launch(self):
        with tempfile.TemporaryDirectory() as td:
            out=Path(td); calls=[]
            spec={'plan_sha256':'a'*64,'harness':'dsh','job_id':'dsh/visual/q_001_r01'}
            validate=Mock(side_effect=lambda *unused:calls.append('validate'))
            def atomic(path, value): calls.append(path.name);path.write_text(json.dumps(value))
            def main():
                frozen.validate_spec(spec,out)
                record=json.loads((out/'runtime-lineage.json').read_text())
                self.assertEqual(record['parent_plan_sha256'],'a'*64)
                self.assertTrue(record['native_transport_changed'])
                calls.append('launch')
            original_command=frozen.native_command
            with patch.object(frozen,'validate_spec',validate),patch.object(frozen,'atomic',atomic),patch.object(frozen,'main',main):
                trial.main()
                self.assertIs(frozen.validate_spec,validate)
                self.assertIs(frozen.native_command,original_command)
            validate.assert_called_once()
            self.assertEqual(calls,['validate','runtime-lineage.json','maintenance.json','launch'])

    def test_failed_validation_and_existing_attempt_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            out=Path(td); atomic=Mock()
            failing=Mock(side_effect=ValueError('bad frozen plan'))
            with self.assertRaises(ValueError): trial.validated_lineage(failing,atomic)({},out)
            atomic.assert_not_called()
            (out/'worker-started.json').write_text('{}')
            trial.validated_lineage(lambda *a:None,atomic)({},out)
            atomic.assert_not_called()

    def test_controller_claims_validation_and_loop_unchanged(self):
        self.assertIs(controller.validate_sources,original_controller.validate_sources)
        self.assertIs(controller.acquire_claim,original_controller.acquire_claim)
        before=(ROOT/'scripts/run_bc_campaign_v3_io2.py').read_text().split('def main():',1)[1]
        after=(ROOT/'scripts/run_bc_campaign_v3_capacity1.py').read_text().split('def main():',1)[1]
        self.assertEqual(after.replace('run_bc_trial_v3_capacity1.py','run_bc_trial_v3_io2.py'),before)

    def test_guard_conditions_unchanged_only_earlier_inspection(self):
        before=(ROOT/'scripts/dsh_wire_image_guard.mjs').read_text().split('\n',1)[1]
        after=(ROOT/'scripts/dsh_wire_image_guard_capacity1.mjs').read_text().split('\n',1)[1]
        self.assertEqual(after.replace('    images=inspect(body); // Preserve actual retained images if subsequent validation rejects.\n',''),before)


if __name__=='__main__': unittest.main()
