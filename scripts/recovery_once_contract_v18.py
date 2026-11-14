"""User-authorized second recovery of only frozen MMBC VERA timeout slots.

This is a distinct single-attempt grant, not a reset of V15 or a retry loop.
"""
import hashlib
import json
from datetime import datetime
from functools import lru_cache
from pathlib import Path

VERSION = 'mmbc-timeout-once-v18'
CUTOFF = '2026-11-14T03:25:12Z'
DEADLINE = '2026-11-14T19:20:06Z'
IDENTITY = ('job_id', 'model', 'harness', 'strategy', 'question_id', 'repeat', 'config_sha256')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def validate_retry(spec, config):
    for row in (spec, config):
        if row.get('one_pass_version') != VERSION:
            raise ValueError('Explicit one-pass contract required')
        for name, expected in (('timeout_seconds', 3600), ('max_attempts', 1), ('max_timeout_retries', 0)):
            if type(row.get(name)) is not int or row[name] != expected:
                raise ValueError('Invalid one-pass field: ' + name)
    if config.get('max_output_tokens') != 8192:
        raise ValueError('Preserve 8192 output budget')


def validate_turns(spec, config):
    validate_retry(spec, config)
    for row in (spec, config):
        if row.get('turn_limit_version') != 'seven-page-turns500-v12' or row.get('runtime_recovery_version') != 'seven-page-canvas-budget-recovery-v11':
            raise ValueError('Preserve verified turn and image runtime')
        if type(row.get('max_rounds')) is not int or row['max_rounds'] != 500:
            raise ValueError('Preserve 500 native turns')
    for section in ('pilot', 'bc100', 'bc100_campaign', 'mmbc100_campaign', 'mmbc_vanilla_campaign'):
        if section not in config:
            if section in ('pilot', 'bc100', 'bc100_campaign'):
                raise ValueError('Missing native turn section')
            continue
        if config[section].get('max_rounds') != 500 or config[section].get('timeout_seconds') != 3600:
            raise ValueError('Native budget differs')
    if 'job_id' in spec:
        consumed = spec.get('prior_attempts_consumed')
        costs = spec.get('prior_attempt_costs')
        if type(consumed) is not int or consumed < 0 or not isinstance(costs, list) or len(costs) != consumed:
            raise ValueError('Actual historical attempt count and ledger required')
        keys = [r.get('result_path') or r.get('attempt_path') or r.get('native_artifact_root') for r in costs]
        if any(not isinstance(k, str) or not k for k in keys) or len(set(keys)) != len(keys):
            raise ValueError('Historical physical attempts must be unique and traceable')
        if spec.get('new_authorized_ordinal') != consumed + 1:
            raise ValueError('New ordinal must follow actual historical attempts')
    return {'hermes_max_iterations': 500, 'dsh_bc100_maxSteps': 500, 'new_attempts': 1}


@lru_cache(maxsize=128)
def authorization(path, expected_sha):
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha:
        raise ValueError('One-pass authorization changed')
    value = json.loads(raw)
    if value.get('version') != VERSION or value.get('user_authorized') is not True or value.get('additional_attempts_per_slot') != 1:
        raise ValueError('A single new attempt must be explicitly granted')
    if value.get('cutoff_utc') != CUTOFF or value.get('deadline_utc') != DEADLINE:
        raise ValueError('Recovery cutoff/deadline changed')
    report_raw = Path(value['selection_report_path']).read_bytes()
    if hashlib.sha256(report_raw).hexdigest() != value['selection_report_sha256']:
        raise ValueError('Frozen selection report changed')
    report = json.loads(report_raw)
    eligible = {r['slot_id']: r for r in report['observations']
                if (r['benchmark'], r['harness'], r['method'], r['status']) ==
                ('mmbc100', 'hermes', 'visual', 'timeout_unresolved')}
    if len(eligible) != 118 or not value['jobs'] or not set(value['jobs']) <= set(eligible):
        raise ValueError('Grant must be a nonempty subset of the frozen 118 timeouts')
    for slot, row in value['jobs'].items():
        reference = eligible[slot]
        if row.get('question_id') != reference['question_id'] or row.get('repeat') != reference['repeat']:
            raise ValueError('Question or repeat differs from selected timeout slot')
        if (row.get('latest_result_path') != reference['latest_terminal_result_path'] or
                row.get('latest_result_sha256') != reference['latest_terminal_result_sha256']):
            raise ValueError('Latest timeout source differs from frozen selection')
    return value


def validate_authorization(spec):
    if (spec.get('benchmark'), spec.get('harness'), spec.get('strategy')) != ('mmbc100', 'hermes', 'visual'):
        raise ValueError('This grant only covers MMBC Hermes VERA')
    value = authorization(spec['one_pass_authorization_path'], spec['one_pass_authorization_sha256'])
    row = value['jobs'][spec['slot_id']]
    for key in IDENTITY:
        if row.get(key) != spec.get(key):
            raise ValueError('Authorized identity differs: ' + key)
    if Path(row['destination_root']).resolve() != Path(spec['campaign_root']).resolve():
        raise ValueError('Authorization belongs to another prediction root')
    if row.get('dispatch_allowed') is not True or row.get('active_at_cutoff') is not False or row.get('completed_retained') is not False:
        raise ValueError('Completed or already running slots cannot receive another attempt')
    if row.get('prior_attempts_consumed') != spec['prior_attempts_consumed'] or row.get('prior_cost_ledger_sha256') != digest(spec['prior_attempt_costs']):
        raise ValueError('Historical attempt ledger differs from audited grant')
    if row.get('cleanup_confirmed') is not True:
        raise ValueError('Historical native cleanup must be confirmed')
    raw = Path(row['latest_result_path']).read_bytes()
    if hashlib.sha256(raw).hexdigest() != row['latest_result_sha256']:
        raise ValueError('Latest timeout result changed after authorization')
    result = json.loads(raw)
    if result.get('status') != 'timeout':
        raise ValueError('Only timed-out source attempts may run in this round')
    if not (result.get('native_cleanup_confirmed') is True or result.get('slot_released') is True) or result.get('unconfirmed_child_termination') != []:
        raise ValueError('Timeout source lacks confirmed native cleanup')
    return value


def dispatch_allowed(now):
    # Leave a full one-hour attempt and ten minutes for cleanup before final cutoff.
    cutoff = datetime.fromisoformat(CUTOFF.replace('Z', '+00:00')).timestamp()
    deadline = datetime.fromisoformat(DEADLINE.replace('Z', '+00:00')).timestamp()
    return cutoff <= now and now + 4200 <= deadline
