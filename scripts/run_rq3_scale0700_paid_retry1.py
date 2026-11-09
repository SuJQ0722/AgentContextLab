#!/usr/bin/env python3
"""Fixed one additional prediction for15 paid interruptions; share successor16 slots."""
import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import run_rq3_scale_cloud_ops2 as base
import run_rq3_scale0700_resume_ops5 as pending
from bc_route_runtime_v2 import immutable_json
from lab import ROOT

VERSION='rq3-scale0700-paid-interrupted-retry1'
DEFAULT_ROOT=ROOT/'outputs/campaigns/rq3-deepseek-bc100-r3-scale0700-paid-retry1'
GRADING=ROOT/'outputs/grading/rq3-scale0700-paid-retry1'
MANIFEST='paid-retry-authorization.json'
SOURCE_NAMES=('run_rq3_scale0700_paid_retry1.py','run_rq3_paid_retry1_trial.py','judge_rq3_scale0700_paid_retry1.py','report_rq3_final_seven_v2.py')
ORIGINAL_JOBS=base.jobs_for_scale
ORIGINAL_PUBLISH=base.publish_claim


def area(root):return Path(root)/'paid-retry-ops1'
def read(p):return base.scientific.read(p)
def sha(p):return base.scientific.sha(p)


def copy_once(source,target):
    data=Path(source).read_bytes();target=Path(target);target.parent.mkdir(parents=True,exist_ok=True)
    try:
        with target.open('xb') as f:f.write(data)
    except FileExistsError:
        if target.read_bytes()!=data:raise ValueError('Frozen retry input changed')


def prepare(parent,root,grading=GRADING):
    parent=Path(parent).resolve();root=Path(root).resolve();grading=Path(grading).resolve()
    if parent==root or grading.is_relative_to(root):raise ValueError('Separate prediction and private grading roots required')
    pa=pending.verify_authorization(parent);original=read(parent/'plan.json');base.scientific.validate(original,parent)
    ids=pa['excluded_paid_interrupted_job_ids'];entries=[]
    for jid in ids:
        d=parent/'jobs'/jid;a=d/'attempts/attempt_001';claim=read(d/'claim/owner.json');spec=read(d/'spec.json')
        if (a/'result.json').exists():raise ValueError('Interrupted result appeared; no longer approved missing set')
        if not (a/'worker-started.json').exists() or not (a/'native/metrics/call-starts.jsonl').stat().st_size:raise ValueError('This scope requires already paid native attempts')
        job=next(j for j in original['jobs'] if j['job_id']==jid)
        if any(spec.get(k)!=v for k,v in job.items()) or spec['plan_sha256']!=sha(parent/'plan.json'):raise ValueError('Predecessor prediction protocol differs')
        entries.append({'job_id':jid,'question_id':job['question_id'],'repeat':job['repeat'],'scale':.7,
                        'parent_attempt':str(a),'retry_attempt':str(root/'jobs'/jid/'attempts/attempt_001'),
                        'parent_status':'interrupted_unknown_no_result','parent_spec_sha256':sha(d/'spec.json'),
                        'parent_claim_sha256':sha(d/'claim/owner.json'),'original_controller':claim['controller_id'],
                        'original_api_calls_were_started':True,'original_unreturned_usage_and_usd':'unknown; never zero'})
    for name in ['experiment.json','cohort.jsonl',*original['definition']['scale_config_sha256']]:copy_once(parent/name,root/name)
    plan=json.loads(json.dumps(original))
    for job in plan['jobs']:job['config_path']=str(root/Path(job['config_path']).relative_to(parent))
    plan['definition']['jobs_sha256']=pending.object_sha(plan['jobs'])
    plan['definition']['paid_interrupted_retry']={'version':VERSION,'authorized_jobs':ids,'parent_root':str(parent),
        'parent_plan_sha256':sha(parent/'plan.json'),'scientific_change':False,'placeholders_not_authorized':2085}
    immutable_json(root/'plan.json',plan)
    auth={'version':VERSION,'launch_authorized':True,'parent_root':str(parent),'retry_root':str(root),'grading_root':str(grading),
          'parent_plan_sha256':sha(parent/'plan.json'),'retry_plan_sha256':sha(root/'plan.json'),
          'parent_resume_authorization_path':str(pending.authorization_path(parent)),'parent_resume_authorization_sha256':sha(pending.authorization_path(parent)),
          'max_additional_native_attempts_per_job':1,'authorized_job_ids':ids,'authorized_job_ids_sha256':pending.object_sha(ids),'entries':entries,
          'shared_slot_root':str(pending.area(parent)/'slots'/pending.LABEL),'combined_scale_concurrency_ceiling':16,
          'sources_sha256':{str(ROOT/'scripts'/n):sha(ROOT/'scripts'/n) for n in SOURCE_NAMES},
          'selection_policy':'Always choose this one fixed retry for these15 original question/repeat pairs, regardless of either score; never add a repeat. Original paid work and retry costs accumulate.',
          'unknown_accounting':'Original15 have no terminal result; unreturned API usage/charges remain unknown. Retry is additional resource, not first native launch.',
          'authorization_basis':'User requested resume and one retry of failures; exactly the15 interrupted .7 jobs, no other failed or completed job'}
    immutable_json(root/MANIFEST,auth);immutable_json(area(root)/'cutover.json',auth);return auth


def validate_scope(root):
    root=Path(root).resolve();a=read(root/MANIFEST);parent=Path(a['parent_root']);pa=pending.verify_authorization(parent)
    if a.get('version')!=VERSION or a.get('launch_authorized') is not True or Path(a['retry_root'])!=root or a.get('max_additional_native_attempts_per_job')!=1 or a.get('combined_scale_concurrency_ceiling')!=16:
        raise ValueError('Paid retry scope is not authorized')
    ids=a['authorized_job_ids']
    if len(ids)!=15 or len(set(ids))!=15 or ids!=pa['excluded_paid_interrupted_job_ids'] or pending.object_sha(ids)!=a['authorized_job_ids_sha256']:
        raise ValueError('Paid retry must cover exactly original15 fixed interruptions')
    if sha(parent/'plan.json')!=a['parent_plan_sha256'] or sha(root/'plan.json')!=a['retry_plan_sha256'] or sha(pending.authorization_path(parent))!=a['parent_resume_authorization_sha256']:
        raise ValueError('Retry source binding changed')
    if Path(a['shared_slot_root'])!=pending.area(parent)/'slots'/pending.LABEL:raise ValueError('Retry must share successor16 slots')
    for path,expected in a['sources_sha256'].items():
        if sha(path)!=expected:raise ValueError('Retry operational source changed')
    plan=read(root/'plan.json');base.scientific.validate(plan,root)
    jobs={j['job_id']:j for j in plan['jobs']};original={j['job_id']:j for j in read(parent/'plan.json')['jobs']}
    if len(a['entries'])!=15 or {e['job_id'] for e in a['entries']}!=set(ids):raise ValueError('Retry entries differ')
    for e in a['entries']:
        jid=e['job_id'];d=parent/'jobs'/jid;p=d/'attempts/attempt_001'
        if Path(e['parent_attempt'])!=p or Path(e['retry_attempt'])!=root/'jobs'/jid/'attempts/attempt_001' or (p/'result.json').exists():raise ValueError('Interrupted original changed or mapping differs')
        if sha(d/'spec.json')!=e['parent_spec_sha256'] or sha(d/'claim/owner.json')!=e['parent_claim_sha256']:raise ValueError('Original ownership changed')
        before={k:v for k,v in original[jid].items() if k!='config_path'};after={k:v for k,v in jobs[jid].items() if k!='config_path'}
        if before!=after or sha(original[jid]['config_path'])!=sha(jobs[jid]['config_path']):raise ValueError('Retry changes scientific intervention')
    if read(area(root)/'cutover.json')!=a:raise ValueError('Retry cutover changed')
    return plan,a


def parent_slot_allocator(parent,parent_auth):
    """Independent module globals keep parent219 accounting separate from retry15."""
    spec=importlib.util.spec_from_file_location('_rq3_paid_retry_parent_slots',ROOT/'scripts/run_rq3_scale_cloud_ops2.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    original=module.jobs_for_scale;allowed=set(parent_auth['pending_job_ids'])
    module.area=pending.area
    module.jobs_for_scale=lambda plan,scale:[j for j in original(plan,scale) if j['job_id'] in allowed]
    return lambda ignored,scale,owner,jid,cap=16:module.acquire_scale_slot(parent,scale,owner,jid,16)


def install(root):
    root=Path(root).resolve();plan,a=validate_scope(root);parent=Path(a['parent_root']);pa=pending.verify_authorization(parent);allowed=set(a['authorized_job_ids'])
    def jobs(p,scale):
        if base.normalize_scale(scale)!=pending.LABEL:raise ValueError('Only .7 retry authorized')
        selected=[j for j in ORIGINAL_JOBS(p,scale) if j['job_id'] in allowed]
        if len(selected)!=15:raise ValueError('Missing authorized retry job')
        return selected
    def publish(r,j,owner,scale,cap=16):
        validate_scope(r)
        if j['job_id'] not in allowed:raise ValueError('Prediction outside fixed15 retry scope')
        return ORIGINAL_PUBLISH(r,j,owner,scale,cap)
    base.area=area;base.VERSION=VERSION;base.jobs_for_scale=jobs;base.verify_cutover=lambda r:validate_scope(r)[1]
    base.acquire_scale_slot=parent_slot_allocator(parent,pa);base.publish_claim=publish
    return a


def dispatch(root,concurrency=15,popen=subprocess.Popen):
    root=Path(root).resolve();a=install(root)
    def spawn(command,**kwargs):
        original=str(ROOT/'scripts/run_rq3_parity_trial.py');new=str(ROOT/'scripts/run_rq3_paid_retry1_trial.py')
        if command.count(original)!=1:raise ValueError('Unexpected native trial command')
        command=[new if part==original else part for part in command];attempt=Path(command[command.index('--out')+1])
        immutable_json(attempt/'paid-retry-launch.json',{'version':VERSION,'authorization_sha256':sha(root/MANIFEST),'actual_trial_entry':new,
            'trial_entry_sha256':sha(new),'shared_slot_root':a['shared_slot_root'],'paid_retry':True,'max_additional_attempts':1})
        return popen(command,**kwargs)
    base.controller(root,pending.LABEL,concurrency,popen=spawn)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=DEFAULT_ROOT);p.add_argument('--parent',type=Path,default=base.scientific.DEFAULT_ROOT)
    p.add_argument('--grading',type=Path,default=GRADING);p.add_argument('--prepare',action='store_true');p.add_argument('--live',action='store_true');p.add_argument('--resume',action='store_true');p.add_argument('--concurrency',type=int,default=15);args=p.parse_args()
    if not 1<=args.concurrency<=15:p.error('At most15 additional predictions, combined parent+retry ceiling16')
    if args.prepare:
        if args.live:p.error('Prepare cannot launch')
        a=prepare(args.parent,args.root,args.grading)
    else:_,a=validate_scope(args.root)
    if not args.live:print(json.dumps({'live':False,'version':VERSION,'authorized_retries':len(a['entries']),'shared_scale_cap':16,'root':str(args.root.resolve())}));return
    if not args.resume:p.error('--resume required; no repeated claimed attempt')
    dispatch(args.root,args.concurrency)

if __name__=='__main__':main()
