"""Offline cross-generation recovery with real unchanged V8 validators."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import controlled_runtime_recovery_v9 as recovery
import run_inline_recovery_trial_v9 as trial
from inline_route_contract_v2 import ROUTES


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    return path


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.temp = Path(temporary.name)
        self.oldbase = self.temp / 'v8'; self.newbase = self.temp / 'v9'
        self.old = self.oldbase / 'cells/shared_baselines'; self.root = self.newbase / 'cells/shared_baselines'
        self.targetroot = self.oldbase / 'cells/controlled_mmbc'
        self.target = recovery.base.target_path(self.targetroot, 'prefix')
        self.target_value = {'passed': True, 'method': 'visual', 'native_identity_verified': True,
            'final_wire_native_identity_preserved': True, 'final_wire_observed': True,
            'bounded_native_protocol': recovery.base.bounded.PROTOCOL,
            'first_actual_prompt_tokens': 1000, 'native_hashes': ['pixels'], 'prefix_sha256': 'prefix'}
        write(self.target, self.target_value)
        cfg = {'model': ROUTES[0], 'approved_model_routes': ROUTES, 'model_route_policy': 'four-route-rotation-v1',
            'image_transport': 'inline-recent-ten-chunked-v1', 'transport_delivery_version': 'inline-direct-v1',
            'transport_runtime_version': 'visual-transport-runtime-v4', 'gateway_proxy': 'http://10.120.0.246:7890'}
        oldcfg = write(self.old/'configs/q.json', cfg); newcfg = write(self.root/'configs/q.json', cfg)
        prefix = write(self.temp/'prefix.json', {'messages': []})
        scientific = {'method': 'summary', 'question': 'Q', 'question_id': 'q', 'repeat': 1,
            'model': ROUTES[0], 'dataset': 'mmbc', 'image': ['original'], 'threshold': 16384,
            'max_rounds': 60, 'prefix_path': str(prefix)}
        parentplan = write(self.temp/'parent-plan.json', {'jobs': [{'job_id': 'original/summary', 'method': 'summary', 'prefix_key': 'prefix'}],
            'prefixes': [{'key': 'prefix', 'spec': scientific}]})
        spec = {**scientific, 'config_path': str(oldcfg), 'timeout_seconds': 3600,
            'bounded_native_protocol': recovery.base.bounded.PROTOCOL, 'source_parent_plan_path': str(parentplan),
            'source_parent_plan_sha256': recovery.base.sha(parentplan), 'source_parent_job_id': 'original/summary',
            'target_reference_path': str(self.target)}
        oldspec = write(self.old/'controlled-specs/q.json', spec)
        newspec = write(self.root/'controlled-specs/q.json', {**spec, 'config_path': str(newcfg)})
        prior = {**cfg, 'job_id': 'q/summary', 'question': 'Q', 'question_id': 'q', 'repeat': 1,
            'controlled_retry_version': recovery.base.VERSION, 'controlled_method': 'summary',
            'controlled_spec_path': str(oldspec), 'controlled_spec_sha256': recovery.base.sha(oldspec),
            'controlled_target_root': str(self.targetroot), 'controlled_prefix_key': 'prefix',
            'control_target_path': str(self.target), 'config_path': str(oldcfg)}
        oldplan = write(self.old/'plan.json', {'jobs': [prior]})
        self.frozen = {**prior, 'config_path': str(newcfg), 'controlled_spec_path': str(newspec),
            'controlled_spec_sha256': recovery.base.sha(newspec), 'operational_recovery_version': recovery.VERSION,
            'previous_v8_attempt': str(self.old/'jobs/q/summary/attempts/attempt_001')}
        experiment = write(self.root/'experiment.json', cfg); cohort = write(self.root/'cohort.jsonl', {})
        self.plan = {'jobs': [self.frozen], 'definition': {'execution_version': 'visual-hosted-failure-retry-v1',
            'per_cell_concurrency_cap': 16, 'config_sha256': recovery.base.sha(experiment),
            'cohort_sha256': recovery.base.sha(cohort), 'implementation_sha256': {},
            'source_results_sha256': {str(oldplan): recovery.base.sha(oldplan)}}}
        self.freeze()
        self.job = {**self.frozen, 'campaign_root': str(self.root)}
        self.out = self.root/'jobs/q/summary/attempts/attempt_001/runs/attempt_001/native'
        for name, value in [('SOURCE', self.oldbase), ('DEST', self.newbase)]:
            p = patch.object(recovery, name, value); p.start(); self.addCleanup(p.stop)

    def freeze(self):
        path = write(self.root/'plan.json', self.plan)
        write(self.root/'campaign-manifest.json', {'plan_sha256': recovery.base.sha(path)})

    def test_exact_target_copy_passes_both_real_v8_validators_and_is_idempotent(self):
        original = self.target.read_bytes(); source_spec = Path(self.job['controlled_spec_path']).read_bytes()
        with self.assertRaisesRegex(ValueError, 'same campaign cell family'):
            recovery.ORIGINAL_VALIDATE(self.job, self.out)
        spec, cfg = recovery.validate(self.job, self.out)
        copied = recovery.base.target_path(self.root, 'prefix')
        self.assertEqual(copied.read_bytes(), original)
        self.assertEqual(self.target.read_bytes(), original)
        self.assertEqual(Path(self.job['controlled_spec_path']).read_bytes(), source_spec)
        self.assertEqual(spec['target_reference_path'], str(copied))
        self.assertEqual(recovery.validate(self.job, self.out), (spec, cfg))
        proof = json.loads((self.out/'predecessor-target-recovery.json').read_text())
        self.assertEqual(proof['source_target_sha256'], proof['copied_target_sha256'])
        self.assertTrue(proof['all_v8_validation_retained'])

    def test_missing_or_invalid_target_remains_blocked_before_any_copy(self):
        for changed in ({**self.target_value, 'first_actual_prompt_tokens': 17000},
                        {**self.target_value, 'final_wire_observed': False},
                        {**self.target_value, 'bounded_transport_encoding': 'different'}):
            write(self.target, changed)
            with self.assertRaises(ValueError): recovery.validate(self.job, self.out)
            self.assertFalse(recovery.base.target_path(self.root, 'prefix').exists())
        self.target.unlink()
        with self.assertRaises(FileNotFoundError): recovery.validate(self.job, self.out)

    def test_frozen_predecessor_and_original_scientific_input_guards_remain(self):
        for key, value in [('question', 'changed'), ('previous_v8_attempt', '/unrelated/attempt'),
                           ('operational_recovery_version', 'unknown')]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                recovery.validate({**self.job, key: value}, self.out)
        prefix = self.temp/'prefix.json'; prefix.write_text('changed')
        # The original cohort holds this exact prefix path, as in V8. The bound
        # parent plan remains protected against changed question/budget fields.
        parentplan = self.temp/'parent-plan.json'; parentplan.write_text('{}')
        with self.assertRaisesRegex(ValueError, 'Parent plan SHA'):
            recovery.validate(self.job, self.out)

    def test_parallel_byte_publication_never_exposes_partial_target(self):
        path = self.root / 'parallel-target.json'
        raw = b'large exact target bytes' * 10000
        with ThreadPoolExecutor(max_workers=16) as executor:
            list(executor.map(lambda _: recovery.immutable_bytes(path, raw), range(32)))
        self.assertEqual(path.read_bytes(), raw)
        self.assertEqual(list(path.parent.glob(path.name + '.*.tmp')), [])
        with self.assertRaises(ValueError): recovery.immutable_bytes(path, b'changed')
        self.assertEqual(path.read_bytes(), raw)

    def test_trial_routes_controlled_worker_to_new_wrapper_only(self):
        spec = {'operational_recovery_version': recovery.VERSION, 'controlled_retry_version': recovery.base.VERSION,
                'harness': 'hermes'}
        cmd = ['python', '/frozen/controlled_inline_retry_v8.py', '--live']
        with patch.object(trial, 'original', return_value=(cmd, Path('result'), 3600)):
            actual, result, timeout = trial.native_command(spec, Path('out'))
        self.assertEqual(Path(actual[1]).name, 'controlled_runtime_recovery_v9.py')
        self.assertEqual((result, timeout), (Path('result'), 3600))
