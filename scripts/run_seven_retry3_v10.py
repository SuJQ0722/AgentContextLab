"""Sixteen question slots; each slot runs at most three sequential one-hour attempts."""
import json
from pathlib import Path
import subprocess
from unittest.mock import patch
import run_visual_hosted_retry_v1 as parent
from lab import ROOT
from one_hour_timeout_retry_v10 import validate, VERSION
from run_bc_campaign_v3 import acquire_claim,digest,release_slot,atomic
from bc_route_runtime_v1 import immutable_json
from inline_route_contract_v2 import validate_routes

_original = parent.controller


def selected_jobs(plan, shard):
    if shard not in ('hermes','dsh'):raise ValueError('Unknown controller identity')
    if plan['definition'].get('one_hour_retry_version')!=VERSION:raise ValueError('Wrong plan version')
    jobs=plan['jobs'];ids=set()
    for job in jobs:
        if job['job_id'] in ids or job['harness'] not in ('hermes','dsh') or job['strategy'] not in ('visual','none','discard','summarize','sliding_window'):
            raise ValueError('Invalid job identity/strategy')
        ids.add(job['job_id'])
    if plan['definition'].get('container_group')=='shared_baselines':
        if shard!='hermes':raise ValueError('Mixed baseline queue has a single controller identity')
        return jobs
    return [j for j in jobs if j['harness']==shard]


def publish_spec(root, job, owner, plan):
    dependency=job.get('controlled_dependency')
    blocked=False
    if dependency:
        from controlled_inline_retry_v8 import valid_target
        target=Path(dependency)
        if target.exists():
            if not valid_target(json.loads(target.read_text())):raise ValueError('Invalid measured controlled dependency')
        else:
            reference=Path(job['controlled_reference_job_path'])/'attempts/attempt_001/result.json'
            if not reference.exists():return None
            blocked=True
    # One physical set of 16 slots even for mixed models/harnesses/strategies.
    claim_job={**job,'harness':'shared','strategy':'all'}
    result=acquire_claim(root,claim_job,owner,cap=16)
    if result is None:return None
    jobdir,slot=result;attempt=jobdir/'attempts/attempt_001';attempt.mkdir(parents=True)
    spec={**job,'campaign_root':str(root),'plan_sha256':digest((root/'plan.json').read_bytes()),
          'cohort_sha256':plan['definition']['cohort_sha256'],'slot_path':str(slot),'controller_id':owner['controller_id']}
    immutable_json(jobdir/'spec.json',spec)
    for path in (jobdir/'claim/owner.json',slot/'owner.json'):
        record=json.loads(path.read_text())
        if record.get('controller_id')!=owner['controller_id'] or record.get('job_id')!=job['job_id']:
            raise ValueError('Claim ownership changed')
    if blocked:
        atomic(attempt/'result.json',{'job_id':job['job_id'],'harness':job['harness'],'strategy':job['strategy'],
            'question_id':job['question_id'],'repeat':job['repeat'],'status':'blocked',
            'failure_category':'visual_control_target_unavailable','score':None,'api_calls':0,
            'unconfirmed_child_termination':[],'slot_released':True,
            'controlled_reference_result':str(reference),'reference_sha256':digest(reference.read_bytes())})
        release_slot(slot);return None
    return jobdir,slot,attempt,spec


def launch(command, *args, **kwargs):
    command = list(command)
    if Path(command[1]) != ROOT / 'scripts/run_visual_hosted_retry_trial_v1.py':
        raise ValueError('Unexpected trial entry')
    command[1] = str(ROOT / 'scripts/run_seven_retry3_trial_v10.py')
    return subprocess.Popen(command, *args, **kwargs)


def controller(root, shard, concurrency=16, limit=None):
    if type(concurrency) is not int or concurrency != 16:
        raise ValueError('Exactly sixteen concurrent question slots required')
    from prepare_visual_hosted_retry_v1 import load_validate
    plan, _ = load_validate(root)
    if plan['definition'].get('one_hour_retry_version') != VERSION:
        raise ValueError('Only an independently frozen V10 plan is allowed')
    for job in plan['jobs']:
        config=json.loads(Path(job['config_path']).read_text())
        validate(job, config); validate_routes(job, config)
    with patch.object(parent,'selected_jobs',selected_jobs),patch.object(parent,'publish_spec',publish_spec):
        return _original(root, shard, concurrency, popen=launch, limit=limit)


def main():
    with patch.object(parent, 'controller', controller),patch.object(parent,'selected_jobs',selected_jobs):
        parent.main()


if __name__ == '__main__':
    main()
