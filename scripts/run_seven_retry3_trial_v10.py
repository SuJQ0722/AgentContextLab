"""One leased question, immutable attempts, retries only for confirmed timeouts."""
import argparse
import fcntl
import json
from pathlib import Path
import signal
import sys
import time
from unittest.mock import patch

import run_bc_trial_v3 as trial
import run_visual_hosted_retry_trial_v1 as native
from run_bc_trial_v3_io import HeartbeatAtomic
from lab import ROOT, python_for
from one_hour_timeout_retry_v10 import VERSION, TIMEOUT_SECONDS, MAX_ATTEMPTS, validate, retry_decision
from inline_route_contract_v2 import validate_routes
from prepare_visual_hosted_retry_v1 import validate_sources
from bc_route_runtime_v1 import immutable_json

BASELINE_NATIVE_COMMAND = trial.native_command

WORKERS = {'controlled_hosted_visual_worker_v1.py': 'controlled_visual_inline_worker_v5.py',
           'hermes_visual_hosted_retry_worker_v1.py': 'hermes_visual_inline_retry_worker_v4.py',
           'dsh_hosted_bc_worker_v1.py': 'dsh_retry3_worker_v10.py'}


def validate_spec(spec, out):
    root=Path(spec['campaign_root']);plan_path=root/'plan.json'
    if trial.digest(plan_path.read_bytes())!=spec['plan_sha256']:raise ValueError('Plan changed')
    plan=json.loads(plan_path.read_text());validate_sources(plan,root)
    expected=next((j for j in plan['jobs'] if j['job_id']==spec['job_id']),None)
    if expected is None or any(spec.get(k)!=v for k,v in expected.items()):raise ValueError('Frozen job changed')
    if spec.get('cohort_sha256')!=plan['definition']['cohort_sha256']:raise ValueError('Cohort changed')
    if out.resolve()!=(root/'jobs'/spec['job_id']/'attempts/attempt_001').resolve():raise ValueError('Output outside job')
    config=Path(spec['config_path'])
    if not config.resolve().is_relative_to(root.resolve()) or trial.digest(config.read_bytes())!=spec['config_sha256']:
        raise ValueError('Per-job frozen config changed')
    for path in (root/'jobs'/spec['job_id']/'claim/owner.json',Path(spec['slot_path'])/'owner.json'):
        owner=json.loads(path.read_text())
        if owner['controller_id']!=spec['controller_id'] or owner['job_id']!=spec['job_id']:raise ValueError('Claim/slot owner differs')
    claim=json.loads((root/'jobs'/spec['job_id']/'claim/owner.json').read_text())
    if claim['slot']!=spec['slot_path']:raise ValueError('Claim slot differs')
    return root


def native_command(spec, out):
    if spec.get('controlled_spec_path') or spec.get('controlled_retry_version'):
        raise ValueError('Controlled experiments are outside seven-page retry3 scope')
    config = json.loads(Path(spec['config_path']).read_text())
    validate(spec, config); validate_routes(spec, config)
    if spec.get('controlled_spec_path'):
        controlled = json.loads(Path(spec['controlled_spec_path']).read_text())
        if controlled['timeout_seconds'] != TIMEOUT_SECONDS or controlled['config_path'] != spec['config_path']:
            raise ValueError('Controlled spec must use the same one-hour config')
        if spec.get('controlled_input_reuse_version') != 'controlled-frozen-input-reuse-v1':
            raise ValueError('Controlled input bytes must remain frozen')
    if spec.get('controlled_retry_version')=='controlled-inline-matched-retry-v8':
        return [python_for(ROOT),str(ROOT/'scripts/controlled_inline_retry_v8.py'),'--spec',spec['_spec_path'],'--out',str(out/'native'),'--live'],out/'native/native-result.json',TIMEOUT_SECONDS
    if spec.get('strategy') != 'visual':
        command, result, _ = BASELINE_NATIVE_COMMAND(spec, out)
        if spec['harness'] == 'hermes':
            command[1] = str(ROOT / 'scripts/hermes_baseline_inline_worker_v8.py')
        else:
            command[1] = str(ROOT / 'scripts/dsh_baseline_inline_worker_v8.py')
            command[command.index('--cohort-file')+1] = spec['native_cohort_path']
            command[command.index('--cohort-sha256')+1] = spec['native_cohort_sha256']
        return command, result, TIMEOUT_SECONDS
    command, result, _ = native.native_command(spec, out)
    old = Path(command[1])
    if old.parent != ROOT / 'scripts' or old.name not in WORKERS:
        raise ValueError('Unexpected native worker')
    command[1] = str(ROOT / 'scripts' / WORKERS[old.name])
    return command, result, TIMEOUT_SECONDS


def stopped(spec):
    root = Path(spec['campaign_root'])
    return any(p.exists() for p in (root / 'STOP', root / 'stops' / spec['harness'], ROOT / 'outputs/PAUSED_BY_USER.json'))


def deadline_evidence(out):
    """Only a route/worker deadline proves timeout, not an arbitrary SDK error."""
    for name in ('inline-images-wire-dsh-v1.jsonl', 'transport-phases-v3.jsonl'):
        for path in (out / 'native').rglob(name):
            with path.open() as stream:
                for line in stream:
                    try: row = json.loads(line)
                    except ValueError: continue
                    if row.get('event') in ('trial_transport_deadline', 'route_deadline_exhausted'):
                        return {'path': str(path), 'event': row['event'], 'at_unix': row.get('at_unix'),
                                'reason': row.get('reason'), 'source': 'explicit worker route deadline event'}
    return None


def run_attempt(spec_path, spec, out, number, parent_out):
    original_validate, original_atomic = validate_spec, HeartbeatAtomic(trial.atomic)
    def check(value, actual_out):
        if actual_out.resolve() != out.resolve():
            raise ValueError('Attempt output changed')
        return original_validate(value, parent_out)
    def record(path, value):
        value = dict(value)
        if Path(path) == out / 'result.json':
            evidence = deadline_evidence(out) if value.get('status') == 'failed' else None
            if evidence:
                value.update(status='timeout', failure_category='attempt_transport_deadline', timeout_evidence=evidence)
            value.update(native_cleanup_confirmed=value.get('slot_released') is True and value.get('unconfirmed_child_termination') == [],
                         slot_released=False, slot_held_for_question_retries=True,
                         attempt_number=number, one_hour_retry_version=VERSION,
                         retry_policy='Only confirmed timeouts; at most two additional attempts')
        original_atomic(path, value)
        if Path(path) == out / 'heartbeat.json':
            original_atomic(parent_out / 'heartbeat.json', {**value, 'attempt_number': number, 'question_retry_manager': True})
    handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}
    try:
        with patch.object(trial, 'validate_sources', validate_sources), \
             patch.object(trial, 'validate_spec', check), \
             patch.object(trial, 'native_command', native_command), \
             patch.object(trial, 'atomic', record), \
             patch.object(trial, 'release_slot', lambda slot: None), \
             patch.object(sys, 'argv', ['trial', '--spec', str(spec_path), '--out', str(out), '--live']):
            trial.main()
    finally:
        for sig, handler in handlers.items():
            signal.signal(sig, handler)


def execute(spec_path, spec, out, *, runner=run_attempt, should_stop=stopped):
    """Exclusive caller owns the outer slot until every child has terminated."""
    records = []; started = time.monotonic(); reason = None
    for number in range(1, MAX_ATTEMPTS + 1):
        attempt = out / 'runs' / f'attempt_{number:03d}'
        result_path = attempt / 'result.json'
        if result_path.exists():
            result = json.loads(result_path.read_text())
            if result.get('attempt_number') != number or result.get('job_id') != spec['job_id'] or result.get('one_hour_retry_version') != VERSION:
                raise ValueError('Existing attempt has another identity')
        else:
            if should_stop(spec):
                reason = 'dispatch_stopped'; break
            if attempt.exists():
                raise RuntimeError('Existing incomplete attempt: preserve unknown work; do not replay')
            attempt.mkdir(parents=True)
            runner(spec_path, spec, attempt, number, out)
            if not result_path.exists():
                raise RuntimeError('Native attempt has no terminal proof; retry prohibited')
            result = json.loads(result_path.read_text())
        records.append({'attempt_number': number, 'result_path': str(result_path), 'result_sha256': trial.digest(result_path.read_bytes()),
                        'status': result['status'], 'end_to_end_seconds': result.get('end_to_end_seconds'),
                        'native_artifact_root': result.get('native_artifact_root'),
                        'native_result_path': result.get('native_result_path')})
        again, reason = retry_decision(result, number, should_stop(spec))
        if not again:
            break
    if not records:
        return {'job_id': spec['job_id'], 'status': 'not_started', 'failure_category': reason,
                'native_cleanup_confirmed': True, 'unconfirmed_child_termination': [], 'attempts': [],
                'api_calls': 0, 'score': None, 'end_to_end_seconds': 0}
    last = json.loads(Path(records[-1]['result_path']).read_text())
    durations = [r['end_to_end_seconds'] for r in records]
    return {**last, 'attempts': records, 'attempt_count': len(records), 'timeout_retries_used': len(records)-1,
            'max_timeout_retries': MAX_ATTEMPTS-1, 'attempt_timeout_seconds': TIMEOUT_SECONDS,
            'retry_stop_reason': reason, 'one_hour_retry_version': VERSION,
            'end_to_end_seconds': sum(durations) if all(isinstance(x, (int, float)) for x in durations) else None,
            'retry_manager_current_invocation_seconds': time.monotonic()-started,
            'usage_attempt_paths': [r['native_artifact_root'] for r in records],
            'attempt_end_to_end_seconds_sum': sum(durations) if all(isinstance(x, (int, float)) for x in durations) else None,
            'usage_accounting': 'Aggregate raw usage from ALL attempt paths; unknown usage remains unknown; local image cache is not provider cached-input usage',
            'statistical_unit': 'one question-repeat; retries are not additional seeds',
            'score': None, 'evaluation_status': 'not_judged'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spec', type=Path, required=True); parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--live', action='store_true'); args = parser.parse_args()
    spec = json.loads(args.spec.read_text()); spec['_spec_path'] = str(args.spec.resolve()); out = args.out.resolve()
    config = json.loads(Path(spec['config_path']).read_text()); validate(spec, config); validate_routes(spec, config)
    if not args.live:
        print(json.dumps({'live': False, 'model_calls': 0, 'timeout_seconds': TIMEOUT_SECONDS, 'max_timeout_retries': MAX_ATTEMPTS-1, 'max_attempts': MAX_ATTEMPTS})); return
    validate_spec(spec, out)
    out.mkdir(parents=True, exist_ok=True)
    with (out / 'retry-manager.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if (out / 'result.json').exists():
            return
        if not (out / 'worker-started.json').exists():
            immutable_json(out / 'worker-started.json', {**trial.identity(), 'started_at': trial.now(), 'version': VERSION})
        stop_requested = False
        def stop(*unused):
            nonlocal stop_requested
            stop_requested = True
        for sig in (signal.SIGTERM, signal.SIGINT):signal.signal(sig, stop)
        result = execute(args.spec.resolve(), spec, out, should_stop=lambda value: stop_requested or stopped(value))
        clean = result.get('native_cleanup_confirmed') is True and result.get('unconfirmed_child_termination') == []
        result.update(slot_released=clean, slot_held_for_question_retries=False)
        trial.atomic(out / 'result.json', result)
        if clean:
            trial.release_slot(Path(spec['slot_path']))


if __name__ == '__main__':
    main()
