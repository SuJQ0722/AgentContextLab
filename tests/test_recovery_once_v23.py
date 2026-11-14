import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import test_recovery_once_v18 as old_tests
import recovery_once_contract_v23 as contract
import run_recovery_once_trial_v23 as trial


class PendingTransferTests(unittest.TestCase):
    def write(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def setUp(self):
        self.old = old_tests.MMBCSecondRecoveryTests()
        self.old.setUp()
        self.addCleanup(self.old.doCleanups)
        self.root = self.old.root
        self.spec = copy.deepcopy(self.old.spec)
        self.spec.update(campaign_root=str(self.root / 'new'), config_sha256='new-cfg')
        plan = self.root / 'plan.json'
        plan_sha = self.write(plan, {'jobs': [self.old.spec]})
        stop = self.root / 'STOP'
        stop.write_text('stop-new-dispatch-only')
        status = self.root / 'controllers/hermes/c/status.json'
        self.write(status, {'controller_id': 'c', 'stop_dispatch': True, 'reserved_not_started': None})
        row = {'source_plan_path': str(plan), 'source_plan_sha256': plan_sha,
               'source_campaign_root': str(self.root), 'destination_root': self.spec['campaign_root'],
               'stop_path': str(stop), 'stop_sha256': hashlib.sha256(stop.read_bytes()).hexdigest(),
               'source_controller_status_path': str(status), 'source_controller_id': 'c'}
        manifest = {'version': contract.VERSION, 'transferred_existing_grant': True,
                    'jobs': {self.spec['slot_id']: row}}
        path = self.root / 'migration.json'
        self.spec.update(migration_manifest_path=str(path), migration_manifest_sha256=self.write(path, manifest))
        auth = copy.deepcopy(self.old.auth)
        auth.update(version=contract.VERSION, additional_attempts_per_slot=0, transferred_existing_grant=True)
        auth['jobs'][self.spec['slot_id']].update(config_sha256='new-cfg', destination_root=self.spec['campaign_root'])
        path = self.root / 'new-authorization.json'
        self.spec.update(one_pass_authorization_path=str(path), one_pass_authorization_sha256=self.write(path, auth))
        self.now = self.old.now

    def invoke(self, runner):
        return trial.execute(self.root / 'spec.json', self.spec, self.root / 'new/out',
                             should_stop=lambda _: False, runner=runner, now=lambda: self.now)

    def test_transfer_retains_same_ordinal_and_executes_once(self):
        calls = []
        def run(path, spec, out, ordinal, parent):
            calls.append(ordinal)
            self.write(out / 'result.json', {'job_id': spec['job_id'], 'status': 'timeout',
                       'attempt_number': ordinal, 'native_cleanup_confirmed': True, 'unconfirmed_child_termination': []})
        result = self.invoke(run)
        self.invoke(run)
        self.assertEqual(calls, [8])
        self.assertEqual(result['total_attempts_including_prior'], 8)
        self.assertEqual(result['prior_attempt_costs'], self.old.spec['prior_attempt_costs'])

    def test_claimed_old_job_cannot_be_transferred(self):
        (self.root / 'jobs' / self.spec['job_id'] / 'claim').mkdir(parents=True)
        with self.assertRaisesRegex(ValueError, 'claimed'):
            self.invoke(lambda *args: self.fail('must not run'))

    def test_old_attempt_artifact_blocks_migration(self):
        (self.root / 'jobs' / self.spec['job_id'] / 'attempts/attempt_001').mkdir(parents=True)
        with self.assertRaisesRegex(ValueError, 'attempt artifacts'):
            contract.validate_authorization(self.spec)

    def test_old_controller_must_remain_stopped(self):
        self.write(self.root / 'controllers/hermes/c/status.json', {'controller_id': 'c', 'stop_dispatch': False})
        with self.assertRaisesRegex(ValueError, 'acknowledged'):
            contract.validate_authorization(self.spec)

    def test_reserved_old_job_cannot_migrate(self):
        self.write(self.root / 'controllers/hermes/c/status.json',
                   {'controller_id': 'c', 'stop_dispatch': True, 'reserved_not_started': self.spec['job_id']})
        with self.assertRaisesRegex(ValueError, 'reserved'):
            contract.validate_authorization(self.spec)

    def test_changed_ordinal_cannot_add_attempt(self):
        self.spec['new_authorized_ordinal'] += 1
        with self.assertRaisesRegex(ValueError, 'ordinal'):
            contract.validate_authorization(self.spec)

    def test_changed_migration_manifest_is_rejected(self):
        Path(self.spec['migration_manifest_path']).write_text('{}')
        with self.assertRaisesRegex(ValueError, 'evidence changed'):
            contract.validate_authorization(self.spec)

    def test_native_entry_uses_explicit_core_worker(self):
        with patch.object(trial, 'native_v12', return_value=(['python', '/scripts/hermes_turns500_worker_v12.py'], '/result', 3600)):
            command, _, _ = trial.native_command(self.spec, self.root)
        self.assertEqual(Path(command[1]).name, 'hermes_core_recent_ten_worker_v23.py')

    def test_policy_and_budgets_are_explicit(self):
        cfg = {'one_pass_version': contract.VERSION, 'native_image_policy': 'core_recent10',
               'core_transport_version': contract.TRANSPORT, 'timeout_seconds': 3600, 'max_attempts': 1,
               'max_timeout_retries': 0, 'max_output_tokens': 8192, 'max_rounds': 500,
               'turn_limit_version': 'seven-page-turns500-v12', 'runtime_recovery_version': 'seven-page-canvas-budget-recovery-v11'}
        cfg.update({key: {'max_rounds': 500, 'timeout_seconds': 3600} for key in ('pilot', 'bc100', 'bc100_campaign')})
        contract.validate_turns({**cfg, **self.spec}, cfg)
        with self.assertRaisesRegex(ValueError, 'recent-ten'):
            contract.validate_turns({**cfg, **self.spec}, {**cfg, 'native_image_policy': 'strict_native'})


if __name__ == '__main__':
    unittest.main()
