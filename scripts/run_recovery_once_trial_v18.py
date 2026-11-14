"""One physical attempt for one audited missing slot; no timeout retry."""
import argparse
import json
import time
from pathlib import Path
from unittest.mock import patch
import run_seven_retry3_trial_v10 as base
from run_turns500_trial_v12 import native_command as native_v12
from recovery_once_contract_v18 import VERSION, IDENTITY, validate_authorization, validate_turns, dispatch_allowed


def native_command(spec, out):
    command, result, timeout = native_v12(spec, out)
    if spec['harness'] == 'dsh' and spec['strategy'] == 'visual':
        if Path(command[1]).name != 'dsh_turns500_worker_v12.py':
            raise ValueError('Unexpected DSH scientific worker')
        command[1] = str(Path(command[1]).with_name('dsh_canvas_worker_v13.py'))
    return command, result, timeout


def run_attempt(spec_path, spec, attempt, ordinal, out):
    original = base.trial.atomic
    def record(path, value):
        if Path(path).name == 'result.json':
            value = {**value, 'one_pass_version': VERSION, 'max_new_attempts': 1,
                     'max_timeout_retries': 0, 'timeout_retries_used': 0,
                     'retry_policy': 'One new authorized attempt; no retry after timeout or failure'}
        return original(path, value)
    with patch.object(base.trial, 'atomic', record):
        base.run_attempt(spec_path, spec, attempt, ordinal, out)


def execute(spec_path, spec, out, *, should_stop, runner=None, now=time.time):
    validate_authorization(spec)
    ordinal = spec['new_authorized_ordinal']
    result_path = out / 'runs' / f'attempt_{ordinal:03d}' / 'result.json'
    if result_path.exists():
        value = json.loads(result_path.read_text())
        if value.get('job_id') != spec['job_id'] or value.get('attempt_number') != ordinal:
            raise ValueError('Existing attempt identity differs')
    elif should_stop(spec) or not dispatch_allowed(now()):
        return {**{k: spec[k] for k in IDENTITY if k in spec}, 'status': 'not_started',
                'failure_category': 'dispatch_stopped_or_round_deadline', 'api_calls': 0,
                'native_cleanup_confirmed': True, 'unconfirmed_child_termination': [],
                'attempt_count': 0, 'attempts': [], 'score': None, 'one_pass_version': VERSION,
                'prior_attempts_consumed': spec['prior_attempts_consumed'],
                'prior_attempt_costs': spec['prior_attempt_costs'], 'max_timeout_retries': 0}
    else:
        if result_path.parent.exists():
            raise RuntimeError('Unknown prior start in this round: never replay')
        result_path.parent.mkdir(parents=True)
        base.immutable_json(result_path.parent / 'one-pass-authorization.json', {
            'version': VERSION, 'slot_id': spec['slot_id'], 'ordinal': ordinal,
            'authorization_sha256': spec['one_pass_authorization_sha256'], 'max_new_attempts': 1})
        (runner or run_attempt)(spec_path, spec, result_path.parent, ordinal, out)
        if not result_path.exists():
            raise RuntimeError('Attempt terminal proof missing; no second attempt permitted')
        value = json.loads(result_path.read_text())
    record = {'attempt_number': ordinal, 'result_path': str(result_path),
              'result_sha256': base.trial.digest(result_path.read_bytes()), 'status': value['status'],
              'native_artifact_root': value.get('native_artifact_root'), 'native_result_path': value.get('native_result_path'),
              'end_to_end_seconds': value.get('end_to_end_seconds')}
    return {**value, 'one_pass_version': VERSION, 'max_new_attempts': 1, 'max_timeout_retries': 0,
            'attempt_count': 1, 'attempts': [record], 'timeout_retries_used': 0,
            'prior_attempts_consumed': spec['prior_attempts_consumed'],
            'prior_attempt_costs': spec['prior_attempt_costs'],
            'prior_operational_attempts': spec.get('prior_operational_attempts', []),
            'total_attempts_including_prior': ordinal, 'max_total_model_attempts': ordinal,
            'current_generation_attempt_limit': 1, 'retry_stop_reason': 'new_round_single_attempt_no_retry',
            'retry_policy': 'One new authorized attempt; no retry after timeout or failure',
            'usage_attempt_paths': [value.get('native_artifact_root')],
            'statistical_unit': 'existing question-repeat; recovery is not a new seed'}


def main():
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument('--spec', type=Path, required=True)
    a, _ = p.parse_known_args()
    spec = json.loads(a.spec.read_text())
    validate_turns(spec, json.loads(Path(spec['config_path']).read_text()))
    validate_authorization(spec)
    with patch.object(base, 'native_command', native_command), patch.object(base, 'execute', execute):
        base.main()


if __name__ == '__main__':
    main()
