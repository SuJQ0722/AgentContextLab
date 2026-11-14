import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import recovery_once_contract_v18 as contract
import run_recovery_once_trial_v18 as trial


class MMBCSecondRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.spec = {'job_id': 'hermes/visual/q001_r01', 'model': 'deepseek-v4.1-flash-1017',
                     'benchmark': 'mmbc100', 'harness': 'hermes', 'strategy': 'visual', 'question_id': 'q001', 'repeat': 1,
                     'config_sha256': 'cfg', 'campaign_root': str(self.root), 'slot_id': 'bc/hermes/visual/q001/1',
                     'prior_attempts_consumed': 7,
                     'prior_attempt_costs': [{'result_path': f'/history/{n}/result.json'} for n in range(7)],
                     'new_authorized_ordinal': 8}
        rec = {k: self.spec[k] for k in contract.IDENTITY}
        rec.update(destination_root=str(self.root), prior_attempts_consumed=7,
                   prior_cost_ledger_sha256=contract.digest(self.spec['prior_attempt_costs']),
                   active_at_cutoff=False, completed_retained=False, cleanup_confirmed=True, dispatch_allowed=True)
        auth = {'version': contract.VERSION, 'user_authorized': True, 'additional_attempts_per_slot': 1,
                'cutoff_utc': contract.CUTOFF, 'deadline_utc': contract.DEADLINE, 'jobs': {self.spec['slot_id']: rec}}
        source = self.root / 'old-timeout.json'
        source.write_text(json.dumps({'status': 'timeout', 'native_cleanup_confirmed': True,
                                      'unconfirmed_child_termination': []}))
        source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
        rec.update(latest_result_path=str(source), latest_result_sha256=source_sha)
        observations = [{'slot_id': self.spec['slot_id'] if i == 0 else f'mmbc-slot-{i}',
                         'benchmark': 'mmbc100', 'harness': 'hermes', 'method': 'visual',
                         'status': 'timeout_unresolved', 'question_id': 'q001', 'repeat': 1,
                         'latest_terminal_result_path': str(source),
                         'latest_terminal_result_sha256': source_sha} for i in range(118)]
        report = self.root / 'report.json'; report.write_text(json.dumps({'observations': observations}))
        auth.update(selection_report_path=str(report),
                    selection_report_sha256=hashlib.sha256(report.read_bytes()).hexdigest())
        self.auth = auth
        p = self.root / 'authorization.json'; raw = json.dumps(auth).encode(); p.write_bytes(raw)
        self.spec.update(one_pass_authorization_path=str(p), one_pass_authorization_sha256=hashlib.sha256(raw).hexdigest())
        self.now = contract.datetime.fromisoformat(contract.CUTOFF.replace('Z', '+00:00')).timestamp() + 1

    def invoke(self, runner, **kw):
        return trial.execute(self.root / 'spec.json', self.spec, self.root / 'out',
                             runner=runner, should_stop=lambda _: False, now=lambda: self.now, **kw)

    def test_timeout_is_exactly_one_and_historical_seven_are_preserved(self):
        calls = []
        def run(path, spec, out, ordinal, parent):
            calls.append(ordinal)
            (out / 'result.json').write_text(json.dumps({'job_id': spec['job_id'], 'status': 'timeout',
                'attempt_number': ordinal, 'native_cleanup_confirmed': True, 'unconfirmed_child_termination': []}))
        result = self.invoke(run)
        self.assertEqual(calls, [8]); self.assertEqual(result['total_attempts_including_prior'], 8)
        self.assertEqual(result['prior_attempt_costs'], self.spec['prior_attempt_costs'])
        self.assertEqual(result['max_timeout_retries'], 0)
        self.invoke(run); self.assertEqual(calls, [8])

    def test_unknown_start_is_never_replayed(self):
        (self.root / 'out/runs/attempt_008').mkdir(parents=True)
        with self.assertRaisesRegex(RuntimeError, 'Unknown prior start'):
            self.invoke(lambda *a: self.fail('must not launch'))

    def test_stop_or_round_deadline_never_calls_native(self):
        result = trial.execute(self.root / 'spec.json', self.spec, self.root / 'out',
            runner=lambda *a: self.fail('must not launch'), should_stop=lambda _: True, now=lambda: self.now)
        self.assertEqual(result['attempt_count'], 0)
        self.now = 9999999999.0
        self.assertEqual(self.invoke(lambda *a: self.fail('must not launch'))['status'], 'not_started')

    def test_changed_history_and_active_slot_are_rejected(self):
        self.spec['prior_attempt_costs'][0]['result_path'] = '/different/result.json'
        with self.assertRaisesRegex(ValueError, 'ledger'):
            contract.validate_authorization(self.spec)

    def test_latest_contract_accepts_real_prior_greater_than_three(self):
        cfg = {'one_pass_version': contract.VERSION, 'timeout_seconds': 3600, 'max_attempts': 1,
               'max_timeout_retries': 0, 'max_output_tokens': 8192, 'max_rounds': 500,
               'turn_limit_version': 'seven-page-turns500-v12',
               'runtime_recovery_version': 'seven-page-canvas-budget-recovery-v11'}
        for name in ('pilot', 'bc100', 'bc100_campaign'):
            cfg[name] = {'max_rounds': 500, 'timeout_seconds': 3600}
        spec = {**cfg, **self.spec}
        contract.validate_turns(spec, cfg)
        bad = copy.deepcopy(cfg); bad['max_timeout_retries'] = 1
        with self.assertRaises(ValueError): contract.validate_turns(spec, bad)

    def test_changed_latest_timeout_is_rejected(self):
        (self.root / 'old-timeout.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'Latest timeout result changed'):
            contract.validate_authorization(self.spec)

    def test_other_benchmark_or_method_cannot_use_grant(self):
        for field, value in [('benchmark', 'bc100'), ('strategy', 'none'), ('harness', 'dsh')]:
            bad = {**self.spec, field: value}
            with self.assertRaisesRegex(ValueError, 'only covers'):
                contract.validate_authorization(bad)

    def test_non_timeout_or_unclean_source_is_rejected_even_if_signed(self):
        for state in [{'status': 'completed', 'native_cleanup_confirmed': True, 'unconfirmed_child_termination': []},
                      {'status': 'timeout', 'native_cleanup_confirmed': False, 'unconfirmed_child_termination': [123]}]:
            source = self.root / 'old-timeout.json'; source.write_text(json.dumps(state))
            source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
            auth = copy.deepcopy(self.auth)
            auth['jobs'][self.spec['slot_id']]['latest_result_sha256'] = source_sha
            report_path = self.root / 'report.json'; report = json.loads(report_path.read_text())
            for row in report['observations']: row['latest_terminal_result_sha256'] = source_sha
            report_path.write_text(json.dumps(report))
            auth['selection_report_sha256'] = hashlib.sha256(report_path.read_bytes()).hexdigest()
            path = self.root / 'authorization.json'; path.write_text(json.dumps(auth))
            spec = {**self.spec, 'one_pass_authorization_sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
            with self.assertRaises(ValueError): contract.validate_authorization(spec)

    def test_dsh_visual_uses_handle_repair(self):
        with patch.object(trial, 'native_v12', return_value=(['python', '/scripts/dsh_turns500_worker_v12.py'], '/result', 3600)):
            command, _, _ = trial.native_command({'harness': 'dsh', 'strategy': 'visual'}, self.root)
        self.assertEqual(Path(command[1]).name, 'dsh_canvas_worker_v13.py')


if __name__ == '__main__': unittest.main()
