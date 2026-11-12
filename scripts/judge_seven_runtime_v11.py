"""Independent grading for seven-page campaigns; operational failures are not task zeros."""
from collections import Counter
from pathlib import Path
from unittest.mock import patch
import judge_inline_model_alias_v9 as previous

base = previous.v8.parent
VERSION = 'judge-seven-runtime-v11'
_original_prepare = previous.prepare
IDENTITY = ('job_id', 'harness', 'strategy', 'question_id', 'repeat', 'model')
TASK_BUDGET_CATEGORIES = {'step_limit', 'output_limit', 'context_limit', 'context_length_exceeded', 'task_budget_exhausted'}


def prepare(root, out):
    cells, config = _original_prepare(root, out)
    base.immutable(Path(out) / 'runtime-grading-protocol-v11.json', {
        'version': VERSION, 'source_sha256': base.sha(__file__),
        'base_protocol_sha256': base.sha(Path(out) / 'protocol.json'),
        'model_alias_protocol_sha256': base.sha(Path(out) / 'model-alias-protocol.json'),
        'completed_identity_policy': 'Exact all six plan fields and original result SHA; no repair of raw result',
        'not_started_policy': 'Zero calls and empty attempts plus cleanup proof; missing fields remain documented, never score zero',
        'noncompletion_policy': 'Explicit task step/output/context budget zero; system failures and unknown timeout remain missing',
        'retry_budget_is_task_budget': False,
    })
    return cells, config


def inspect_result(job, result):
    """Return classification without reading predictions or answer correctness."""
    status = result.get('status', 'pending')
    mismatch = {k: {'expected': job[k], 'observed': result.get(k)}
                for k in IDENTITY if result.get(k) != job[k]}
    clean = base.base.clean(result)
    present_conflict = any(k in result and result[k] != job[k] for k in IDENTITY)
    zero_start = (status == 'not_started' and result.get('job_id') == job['job_id']
                  and result.get('api_calls') == 0 and result.get('attempts') == []
                  and clean and not present_conflict)
    if result and mismatch and not zero_start:
        return 'identity_quarantined', None, False, mismatch
    if status == 'completed':
        return ('completed' if clean else 'cleanup_unconfirmed'), None, False, mismatch
    if zero_start:
        return 'not_executed:' + str(result.get('failure_category', 'not_started')), None, True, mismatch
    if clean and status == 'failed' and result.get('failure_category') in TASK_BUDGET_CATEGORIES:
        return 'explicit_task_budget_exhausted', 0., False, mismatch
    if status == 'failed':
        return 'operational_failure_unscored', None, True, mismatch
    if status == 'blocked':
        return 'blocked_unscored', None, True, mismatch
    if status == 'timeout':
        return 'timeout_cause_unresolved', None, False, mismatch
    return ('cleanup_unconfirmed' if result and not clean else status), None, False, mismatch


def inventory_cell(cell, data, out):
    # Validate frozen plan/config even if all jobs are operational failures.
    base.inventory_cell(cell, {**data, 'plan': {**data['plan'], 'jobs': []}}, out)
    ordinary, rows = [], []
    for job in data['plan']['jobs']:
        path = data['root'] / 'jobs' / job['job_id'] / 'attempts/attempt_001/result.json'
        result = base.read(path) if path.exists() else {}
        reason, score, excluded, mismatch = inspect_result(job, result)
        if reason == 'completed':
            ordinary.append(job)
            continue
        rows.append({'cell': cell, 'job_id': job['job_id'], 'question_id': job['question_id'],
                     'repeat': job['repeat'], 'prediction_status': result.get('status', 'pending'),
                     'cleanup_confirmed': base.base.clean(result), 'score': score,
                     'score_reason': reason, 'excluded_from_accuracy': excluded,
                     'identity_mismatch_fields': mismatch, 'failure_category': result.get('failure_category'),
                     'result_path': str(path), 'result_sha256': base.sha(path) if path.exists() else None})
    pending, completed = base.inventory_cell(cell, {**data, 'plan': {**data['plan'], 'jobs': ordinary}}, out)
    return pending, completed + rows


def report(cells, out, with_cost=False):
    pending, allrows, summaries = [], [], {}
    for cell, data in cells.items():
        candidates, rows = inventory_cell(cell, data, out)
        pending.extend(candidates)
        allrows.extend(rows)
        eligible = [r for r in rows if not r.get('excluded_from_accuracy')]
        known = [r['score'] for r in eligible if r['score'] is not None]
        terminal = sum(r['cleanup_confirmed'] and r['prediction_status'] in
                       ('completed', 'failed', 'timeout', 'blocked', 'not_started', 'interrupted') for r in rows)
        cal_terminal = 0
        for job in data['calibration_jobs']:
            path = data['root'] / 'jobs' / job['job_id'] / 'attempts/attempt_001/result.json'
            value = base.read(path) if path.exists() else {}
            cal_terminal += int(base.base.clean(value) and value.get('status') in
                                ('completed', 'failed', 'timeout', 'blocked', 'not_started', 'interrupted'))
        n = len(eligible)
        summaries[cell] = {'planned': len(rows), 'scoring_denominator': n,
                          'operational_excluded': len(rows) - n, 'terminal': terminal,
                          'calibration_excluded': len(data['calibration_jobs']), 'calibration_terminal': cal_terminal,
                          'known_scores': len(known), 'missing_scores': n - len(known), 'correct': sum(known),
                          'accuracy': sum(known) / n if n and len(known) == n else None,
                          'prediction_states': dict(Counter(r['prediction_status'] for r in rows)),
                          'score_states': dict(Counter(r['score_reason'] for r in rows))}
    result = {'at': base.base.bc.now(), 'version': VERSION, 'cells': summaries,
              'ready_to_grade': len(pending),
              'all_terminal': all(s['terminal'] == s['planned'] and
                                  s['calibration_terminal'] == s['calibration_excluded'] for s in summaries.values()),
              'interpretation': 'Execution namespace only, not pooled avg3. System/not-started failures excluded; '
                                'unknown timeout and identity quarantine remain missing; only explicit task budget failure is zero. '
                                'Completed predictions retain strict identity/SHA and existing gold-equivalence protocol.'}
    base.atomic(out / 'observations.json', allrows)
    base.atomic(out / 'summary.json', result)
    if with_cost:
        base.atomic(out / 'resources.json', previous.v8.resources(cells, out))
    return pending, result


def main():
    with patch.object(previous, 'prepare', prepare), patch.object(previous.v8, 'report', report):
        previous.main()


if __name__ == '__main__':
    main()
