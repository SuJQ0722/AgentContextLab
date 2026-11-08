import copy
import json
from pathlib import Path
import signal
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import replace_bc_v3_reader as ops


class ReaderReplacementTests(unittest.TestCase):
    def test_only_concurrency_changes(self):
        old = json.loads(ops.OLD_CONFIG.read_text()); new = json.loads(ops.NEW_CONFIG.read_text())
        ops.validate_configs(old, new)
        wrong = dict(new); wrong['fetch_timeout'] += 1
        with self.assertRaises(ValueError): ops.validate_configs(old, wrong)
        self.assertEqual({k for k in old if old[k] != new[k]}, {'max_concurrent_requests'})

    def test_script_and_old_config_exact_match(self):
        row = {'_argv': ['/opt/python', str(ops.SERVICE), '--config', str(ops.OLD_CONFIG)], '_cwd': str(ROOT)}
        self.assertTrue(ops.is_reader(row))
        row['_argv'][-1] = str(ops.NEW_CONFIG)
        self.assertFalse(ops.is_reader(row))
        row['_argv'] = ['/opt/python', '-c', 'print("local_reader_text_service.py")', '--config', str(ops.OLD_CONFIG)]
        self.assertFalse(ops.is_reader(row))

    def test_only_owned_extraction_children_allowed(self):
        parent = {'pid': 20, 'ppid': 1, 'pgrp': 20, 'executable': '/opt/python', '_argv': ['python']}
        child = {'pid': 21, 'ppid': 20, 'pgrp': 20, 'executable': '/opt/python', '_argv': ['python', '-c', 'from multiprocessing.spawn import spawn_main']}
        unrelated = {'pid': 55, 'ppid': 1, 'pgrp': 55, 'executable': '/opt/python', '_argv': ['python', 'hermes_bc_worker_v3.py']}
        self.assertEqual([r['pid'] for r in ops.owned_targets(parent, [parent, child, unrelated])], [20, 21])
        bad = copy.deepcopy(child); bad['_argv'] = ['python', 'run_bc_trial_v3.py']
        with self.assertRaises(ValueError): ops.owned_targets(parent, [bad])
        bad = dict(child, pgrp=99)
        with self.assertRaises(ValueError): ops.owned_targets(parent, [bad])

    def test_pid_reuse_or_changed_boot_never_signalled(self):
        old = {'pid': 20, 'start_identity': '100'}
        with patch.object(ops, 'boot', return_value='boot1'), patch.object(ops, 'proc', return_value={'state': 'S', 'start_identity': '200'}), patch.object(ops.os, 'kill') as kill:
            ops.signal_identity(old, signal.SIGTERM, 'boot1'); kill.assert_not_called()
            with self.assertRaises(RuntimeError): ops.signal_identity(old, signal.SIGTERM, 'boot2')
            kill.assert_not_called()

    def test_root_network_allowlist_never_copies_credentials(self):
        dotenv = {'http_proxy': 'http://user:password@10.120.0.246:7890',
                  'https_proxy': 'http://10.120.0.246:7890', 'no_proxy': 'localhost,127.0.0.1',
                  'TOKENHUB_API_KEY': 'model-secret', 'SCO_ACCESS_KEY_SECRET': 'cloud-secret',
                  'AWS_SECRET_ACCESS_KEY': 'aws-secret', 'UNRELATED': 'not-network'}
        original = b'PATH=/opt/bin\0HOME=/root\0SCO_ACCESS_KEY_SECRET=old-cloud-secret\0'
        with patch.object(ops, 'read_env', return_value=dotenv), patch.object(Path, 'read_bytes', return_value=original):
            env = ops.clean_reader_env(20)
        self.assertEqual(env['PATH'], '/opt/bin')
        self.assertEqual(env['http_proxy'], dotenv['http_proxy'])
        self.assertEqual(env['no_proxy'], dotenv['no_proxy'])
        self.assertFalse(any(k in env for k in ('TOKENHUB_API_KEY', 'SCO_ACCESS_KEY_SECRET', 'AWS_SECRET_ACCESS_KEY', 'UNRELATED')))
        summary = ops.proxy_summary(env)
        self.assertEqual(summary['http_proxy']['hostname'], '10.120.0.246')
        self.assertEqual(summary['http_proxy']['port'], 7890)
        self.assertTrue(summary['http_proxy']['credentials_present'])
        serialized = json.dumps(summary)
        self.assertNotIn('password', serialized)
        self.assertNotIn('cloud-secret', serialized)

    def test_affected_trials_uses_local_pids_not_campaign_glob(self):
        import os
        import socket
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); records = []
            for i, script in enumerate(['run_bc_trial_v3.py', 'run_bc_trial_v3_io.py', 'run_bc_trial_v3_io2.py']):
                out = root / f'jobs/hermes/visual/q_{i}/attempts/attempt_001'; out.mkdir(parents=True)
                record = {'pid': i + 100, 'state': 'S', 'start_identity': str(i), '_cwd': str(ROOT),
                          '_argv': ['python', str(ROOT / 'scripts' / script), '--out', str(out), '--spec', str(out.parents[1] / 'spec.json')]}
                records.append(record)
                (out / 'running.json').write_text(json.dumps({'pid': record['pid'], 'start_identity': record['start_identity'],
                    'hostname': socket.gethostname(), 'boot_id': 'boot1', 'pid_namespace': os.readlink('/proc/self/ns/pid'),
                    'job_id': f'hermes/visual/q_{i}'}))
            unknown = []
            with patch.object(ops, 'boot', return_value='boot1'), patch.object(ops, 'alive', return_value=True), \
                 patch.object(Path, 'glob', side_effect=AssertionError('shared tree scan forbidden')), \
                 patch.object(Path, 'rglob', side_effect=AssertionError('shared tree scan forbidden')):
                rows = ops.affected_trials(root, 'boot1', records, unknown)
            self.assertEqual(len(rows), 3); self.assertEqual(unknown, [])

    def test_missing_or_mismatched_attempt_is_partial_unknown(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); out = root / 'jobs/dsh/none/q_001/attempts/attempt_001'; out.mkdir(parents=True)
            record = {'pid': 20, 'state': 'S', 'start_identity': '100', '_cwd': str(ROOT),
                      '_argv': ['python', str(ROOT / 'scripts/run_bc_trial_v3_io2.py'), '--out', str(out), '--spec', str(out.parents[1] / 'spec.json')]}
            with patch.object(ops, 'boot', return_value='boot1'):
                unknown = []; rows = ops.affected_trials(root, 'boot1', [record], unknown)
                self.assertEqual(rows, []); self.assertEqual(unknown[0]['reason'], 'missing_or_invalid_local_attempt_metadata')
                (out / 'running.json').write_text(json.dumps({'pid': 20, 'start_identity': 'old-identity'}))
                unknown = []; rows = ops.affected_trials(root, 'boot1', [record], unknown)
                self.assertEqual(rows, []); self.assertEqual(unknown[0]['reason'], 'attempt_identity_mismatch')

    def test_changed_boot_inventory_refuses(self):
        with patch.object(ops, 'boot', return_value='other'):
            with self.assertRaises(RuntimeError): ops.affected_trials(Path('/fixture'), 'expected', [], [])


if __name__ == '__main__': unittest.main()
