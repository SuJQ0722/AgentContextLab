"""Prepare only the three leading-hyphen BC jobs, never select using answers."""
import argparse
import json
from pathlib import Path
import time
from lab import ROOT
from prepare_visual_hosted_retry_v1 import load_validate, sha, immutable, immutable_json, VERSION
from run_bc_campaign_v3 import identity, job_state

ORIGINAL = ROOT / 'outputs/campaigns/visual-hosted-failure-retry-v1/cells/transport-v5/cells/bc_dsh'
DESTINATION = ROOT / 'outputs/campaigns/visual-hosted-failure-retry-v1/cells/dsh-cli-separator-v1'
JOB_IDS = tuple(f'dsh/visual/q_043_r{repeat:02}' for repeat in (1, 2, 3))
NEW_SOURCES = ['scripts/' + name for name in (
    'dsh_inline_bc_worker_v4.py', 'run_dsh_prompt_retry_trial_v1.py', 'run_dsh_prompt_retry_v1.py',
    'prepare_dsh_cli_separator_retry_v1.py', 'wait_dsh_cli_separator_retry_v1.py')]


def read(path):
    return json.loads(Path(path).read_text())


def defer_unclaimed(root, job, *, plan_sha256):
    """Win the very same atomic claim mkdir as acquire_claim, or do nothing.

    If the controller observed pending earlier and reserved a slot, our winning
    mkdir forces its claim mkdir to raise FileExistsError and release that slot.
    Native launch only follows a successful acquire_claim return, so it cannot
    occur after this cancellation wins. A controller that won first is untouched.
    """
    root = Path(root)
    if job['job_id'] not in JOB_IDS or job['harness'] != 'dsh' or not job['question'].startswith('-'):
        raise ValueError('Only identified leading-hyphen DSH jobs may be deferred')
    directory = root / 'jobs' / job['job_id']
    directory.mkdir(parents=True, exist_ok=True)
    if job_state(directory) != 'pending':
        return {'job_id': job['job_id'], 'deferred': False, 'reason': 'already_claimed_or_terminal'}
    claim = directory / 'claim'
    try:
        claim.mkdir()
    except FileExistsError:
        return {'job_id': job['job_id'], 'deferred': False, 'reason': 'controller_won_claim_race'}
    owner = {**identity(), 'job_id': job['job_id'], 'claim_kind': 'CLI_separator_deferred',
             'slot': None, 'controller_id': 'explicit-cli-separator-deferral-v1',
             'claimed_at_unix': time.time(), 'source_plan_sha256': plan_sha256}
    immutable_json(claim / 'owner.json', owner)
    audit = {'job_id': job['job_id'], 'reason': 'CLI_separator_deferred', 'api_calls': 0,
             'native_launch_excluded_by_atomic_claim': True, 'slot_acquired_by_deferral': False,
             'source_plan_sha256': plan_sha256, 'at_unix': time.time(), 'owner': owner}
    immutable_json(directory / 'cli-separator-deferred.json', audit)
    result = {k: job[k] for k in ('job_id', 'harness', 'strategy', 'question_id', 'repeat', 'model')}
    result.update(status='not_started', failure_category='CLI_separator_deferred', api_calls=0,
                  final={}, score=None, evaluation_status='not_judged', slot_released=True,
                  slot_never_acquired_by_deferral=True, unconfirmed_child_termination=[],
                  defer_audit_sha256=sha(directory / 'cli-separator-deferred.json'),
                  finished_at_unix=time.time(), retry_policy='Separate reviewed CLI separator supplement only')
    immutable_json(directory / 'attempts/attempt_001/result.json', result)
    return {'job_id': job['job_id'], 'deferred': True, 'api_calls': 0}


def prepare(original=ORIGINAL, destination=DESTINATION, defer=False):
    original, destination = Path(original).resolve(), Path(destination).resolve()
    plan, _ = load_validate(original)
    selected = [j for j in plan['jobs'] if j['job_id'] in JOB_IDS]
    if {j['job_id'] for j in selected} != set(JOB_IDS):
        raise ValueError('Expected all three original q043 repeats')
    if defer:
        for job in selected:
            defer_unclaimed(original, job, plan_sha256=sha(original / 'plan.json'))
    lineage = []; eligible = []
    for job in selected:
        p = original / 'jobs' / job['job_id'] / 'attempts/attempt_001/result.json'
        if not p.exists():
            return {'prepared': False, 'waiting_job': job['job_id'], 'reason': 'No confirmed terminal result'}
        result = read(p)
        if result.get('slot_released') is not True or result.get('unconfirmed_child_termination') != []:
            return {'prepared': False, 'waiting_job': job['job_id'], 'reason': 'Cleanup unconfirmed'}
        if result['status'] == 'completed':
            lineage.append({'job_id': job['job_id'], 'result': str(p), 'sha256': sha(p), 'retained_completed': True})
            continue
        if result['status'] not in ('failed', 'timeout') and not (result['status'] == 'not_started' and result.get('failure_category') == 'CLI_separator_deferred' and result.get('api_calls') == 0):
            raise ValueError('Unapproved terminal state')
        eligible.append(job)
        lineage.append({'job_id': job['job_id'], 'result': str(p), 'sha256': sha(p), 'status': result['status']})
    cell = destination / 'cells/bc_dsh'
    config = read(original / 'experiment.json');config['dsh_cli_prompt_separator'] = 'before-task-v1'
    immutable_json(cell / 'experiment.json', config)
    immutable(cell / 'cohort.jsonl', (original / 'cohort.jsonl').read_bytes())
    jobs = [{**j, 'config_path': str(cell / 'experiment.json'), 'config_sha256': sha(cell / 'experiment.json'),
             'dsh_cli_prompt_separator': 'before-task-v1', 'cell': 'bc_dsh'} for j in eligible]
    implementation = dict(plan['definition']['implementation_sha256'])
    implementation.update({p: sha(ROOT / p) for p in NEW_SOURCES})
    bindings = dict(plan['definition']['source_results_sha256'])
    for path in [original / 'plan.json', original / 'campaign-manifest.json', original / 'experiment.json']:
        bindings[str(path)] = sha(path)
    for row in lineage:
        bindings[row['result']] = row['sha256']
        directory = Path(row['result']).parents[2]
        audit = directory / 'cli-separator-deferred.json'
        if audit.exists():
            for p in (audit, directory / 'claim/owner.json'):
                bindings[str(p)] = sha(p)
    definition = {**plan['definition'], 'cell': 'bc_dsh', 'planned_runs': len(jobs),
                  'config_sha256': sha(cell / 'experiment.json'), 'cohort_sha256': sha(cell / 'cohort.jsonl'),
                  'implementation_sha256': implementation, 'source_results_sha256': bindings,
                  'selection_uses_answers': False, 'dsh_cli_prompt_separator': 'before-task-v1',
                  'supplement_requires_original_controller_drained': str(original)}
    immutable_json(cell / 'plan.json', {'definition': definition, 'jobs': jobs})
    manifest = {'root': str(cell), 'cell': 'bc_dsh', 'harness': 'dsh', 'planned_runs': len(jobs),
                'plan_sha256': sha(cell / 'plan.json'), 'version': VERSION}
    immutable_json(cell / 'campaign-manifest.json', manifest)
    immutable_json(destination / 'source-lineage.json', {'original': str(original), 'selected_by': 'CLI parsing failure only', 'rows': lineage})
    immutable_json(destination / 'inventory.json', {'version': VERSION, 'cells': [manifest], 'planned_runs': len(jobs), 'selection_uses_answers': False})
    load_validate(cell)
    return {'prepared': True, 'root': str(destination), 'planned_runs': len(jobs), 'model_calls': 0}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--original', type=Path, default=ORIGINAL)
    p.add_argument('--destination', type=Path, default=DESTINATION)
    p.add_argument('--defer-unclaimed', action='store_true')
    a = p.parse_args();print(json.dumps(prepare(a.original, a.destination, a.defer_unclaimed)))
