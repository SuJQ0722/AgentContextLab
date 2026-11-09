#!/usr/bin/env python3
"""One explicitly authorized, never-started RQ3 reservation; original evidence is immutable."""
import argparse
import fcntl
import hashlib
import json
from pathlib import Path
import signal
import subprocess
import sys
import time
import uuid
import run_rq3_parity_v3 as scientific
from run_bc_campaign_v3 import atomic,identity,owner_alive,release_slot
from bc_route_runtime_v2 import immutable_json
from lab import ROOT

VERSION='rq3-pre-native-reservation-recovery1'
JOB='hermes/scale_0800/q_085_r03'
DEFAULT_ROOT=ROOT/'outputs/campaigns/rq3-deepseek-bc100-r3-parity-v3-pre-native-recovery1'
GRADING=ROOT/'outputs/grading/rq3-parity-v3-pre-native-recovery1'


def no_native_evidence(attempt,allow_result=False):
    allowed={'result.json'} if allow_result else set()
    names={p.name for p in attempt.iterdir()} if attempt.exists() else set()
    if names-allowed:raise ValueError('Original reservation has native/worker/unknown evidence; recovery prohibited')


def prepare(parent,root,grading):
    parent=Path(parent).resolve();root=Path(root).resolve();grading=Path(grading).resolve()
    if root==parent:raise ValueError('Recovery must have a separate root')
    plan=scientific.read(parent/'plan.json');scientific.validate(plan,parent)
    job=next(j for j in plan['jobs'] if j['job_id']==JOB);directory=parent/'jobs'/JOB;attempt=directory/'attempts/attempt_001'
    no_native_evidence(attempt,allow_result=True)
    source_claim=scientific.read(directory/'claim/owner.json');source_spec=scientific.read(directory/'spec.json')
    if source_claim.get('job_id')!=JOB or source_spec.get('controller_id')!=source_claim.get('controller_id'):raise ValueError('Original ownership differs')
    if any(source_spec.get(k)!=v for k,v in job.items()) or source_spec.get('plan_sha256')!=scientific.sha(parent/'plan.json'):
        raise ValueError('Original specification differs from frozen job')
    root.mkdir(parents=True,exist_ok=True)
    for relative in ['experiment.json','cohort.jsonl',*plan['definition']['scale_config_sha256']]:
        target=root/relative;target.parent.mkdir(parents=True,exist_ok=True);raw=(parent/relative).read_bytes()
        if target.exists():
            if target.read_bytes()!=raw:raise ValueError('Recovery frozen input differs')
        else:
            with target.open('xb') as stream:stream.write(raw)
    overlay=json.loads(json.dumps(plan))
    for j in overlay['jobs']:
        j['config_path']=str(root/Path(j['config_path']).relative_to(parent))
    overlay['definition']['jobs_sha256']=hashlib.sha256(json.dumps(overlay['jobs'],sort_keys=True,separators=(',',':')).encode()).hexdigest()
    overlay['definition']['pre_native_recovery']={'version':VERSION,'authorized_jobs':[JOB],
        'parent_root':str(parent),'parent_plan_sha256':scientific.sha(parent/'plan.json'),
        'scientific_change':False,'all_other_jobs':'Unscheduled placeholders preserving frozen full-cohort scientific definition'}
    immutable_json(root/'plan.json',overlay)
    authorization={'version':VERSION,'parent_root':str(parent),'recovery_root':str(root),'grading_root':str(grading),
        'parent_plan_sha256':scientific.sha(parent/'plan.json'),'recovery_plan_sha256':scientific.sha(root/'plan.json'),
        'implementation_sha256':scientific.sha(__file__),'max_recovery_native_launches':1,
        'selection':'Always select the authorized recovery observation, never compare scores; same question/repeat, no extra seed',
        'entries':[{'job_id':JOB,'parent_attempt':str(attempt),'retry_attempt':str(root/'jobs'/JOB/'attempts/attempt_001'),
            'parent_spec_sha256':scientific.sha(directory/'spec.json'),'parent_claim_sha256':scientific.sha(directory/'claim/owner.json'),
            'original_controller':source_claim,'reason':'Reserved before native launch; explicit one-time completion of missing planned observation'}]}
    immutable_json(root/'recovery-authorization.json',authorization)
    return authorization


def proof(authorization):
    entry=authorization['entries'][0];parent=Path(authorization['parent_root']);attempt=Path(entry['parent_attempt']);directory=attempt.parents[1]
    if scientific.sha(parent/'plan.json')!=authorization['parent_plan_sha256']:raise ValueError('Original plan changed')
    if scientific.sha(directory/'spec.json')!=entry['parent_spec_sha256'] or scientific.sha(directory/'claim/owner.json')!=entry['parent_claim_sha256']:
        raise ValueError('Original reservation identity changed')
    no_native_evidence(attempt,allow_result=True)
    owner=entry['original_controller']
    if owner_alive(owner) is not False:return None,'waiting_exact_original_controller_exit'
    exit_path=parent/'controller-exit.json';result_path=attempt/'result.json'
    if not exit_path.exists() or not result_path.exists():return None,'waiting_durable_exit_and_not_started_result'
    end=scientific.read(exit_path);result=scientific.read(result_path)
    if not(end.get('controller_id')==owner['controller_id'] and end.get('drained') is True and end.get('stopped') is True):
        raise ValueError('Original controller did not prove clean termination of its drain')
    if not(result.get('job_id')==JOB and result.get('status')=='not_started' and result.get('api_calls')==0 and
           result.get('slot_released') is True and result.get('unconfirmed_child_termination')==[] and
           result.get('failure_category')=='controller_stopped_before_native_launch'):
        raise ValueError('Original result is not explicit never-started with zero calls and released slot')
    status=scientific.read(parent/'status.json')
    if status.get('controller_id')!=owner['controller_id'] or status.get('stop_dispatch') is not True:
        raise ValueError('Original final dispatch stop is not proven')
    slot_owner=Path(owner['slot'])/'owner.json'
    if slot_owner.exists() and scientific.read(slot_owner).get('controller_id')==owner['controller_id']:
        raise ValueError('Original slot is still owned by the stopped controller')
    return {'version':VERSION,'checked_unix':time.time(),'original_identity_dead':True,'original_native_never_started':True,
        'exit_path':str(exit_path),'exit_sha256':scientific.sha(exit_path),'result_path':str(result_path),'result_sha256':scientific.sha(result_path),
        'status_path':str(parent/'status.json'),'status_sha256':scientific.sha(parent/'status.json'),
        'no_model_retry':'First native launch for this reserved observation; original attempt records api_calls=0'},'ready'


def claim(root,parent,job,owner):
    directory=root/'jobs'/JOB;directory.mkdir(parents=True,exist_ok=True)
    if (directory/'claim').exists() or (directory/'attempts').exists():raise ValueError('Recovery was already claimed; never automatically replay it')
    slots=parent/'cells/hermes/visual/slots';slots.mkdir(parents=True,exist_ok=True)
    for i in range(16):
        slot=slots/f'{i:02}'
        try:slot.mkdir()
        except FileExistsError:continue
        atomic(slot/'owner.json',{**owner,'job_id':JOB,'recovery_root':str(root),'claimed_at_unix':time.time()})
        try:(directory/'claim').mkdir()
        except FileExistsError:release_slot(slot);raise ValueError('Recovery claim raced; do not replay')
        atomic(directory/'claim/owner.json',{**owner,'job_id':JOB,'slot':str(slot),'claimed_at_unix':time.time()})
        return directory,slot
    return None


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--parent',type=Path,default=scientific.DEFAULT_ROOT)
    ap.add_argument('--root',type=Path,default=DEFAULT_ROOT);ap.add_argument('--grading',type=Path,default=GRADING)
    ap.add_argument('--live',action='store_true');ap.add_argument('--watch',action='store_true');args=ap.parse_args()
    parent=args.parent.resolve();root=args.root.resolve();grading=args.grading.resolve();authorization=prepare(parent,root,grading)
    if not args.live:
        evidence,reason=proof(authorization);print(json.dumps({'live':False,'state':reason,'authorized_native_launches':1,'root':str(root)}));return
    lock=(root/'recovery.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    if (root/'jobs'/JOB/'claim').exists():
        atomic(root/'status.json',{'state':'already_claimed_no_automatic_retry','at':time.time()});return
    from preflight_bc_v3_web import preflight
    import experiment_admission_v4 as admission
    import admission_lock_ops1
    lock_record=admission_lock_ops1.install(admission);immutable_json(root/'admission-maintenance.json',lock_record)
    stopped=False;child=None;reserved=None;owner={**identity(),'controller_id':uuid.uuid4().hex}
    def stop(*unused):
        nonlocal stopped
        stopped=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    try:
        while not stopped:
            evidence,reason=proof(authorization)
            atomic(root/'status.json',{**owner,'at':time.time(),'state':reason,'native_launches':0,'paid_api_retry':False})
            if evidence:break
            if not args.watch:return
            time.sleep(5)
        if stopped:return
        immutable_json(root/'never-started-proof.json',evidence)
        if not preflight(root,root/'experiment.json')['passed']:raise RuntimeError('Actual web readiness failed before recovery')
        plan=scientific.read(root/'plan.json');job=next(j for j in plan['jobs'] if j['job_id']==JOB)
        while not stopped:
            scientific.validate(plan,root);scientific.validate(scientific.read(parent/'plan.json'),parent)
            if reserved is None:
                claimed=claim(root,parent,job,owner)
                if claimed is None:
                    atomic(root/'status.json',{**owner,'at':time.time(),'state':'waiting_shared_original_16_slots'});time.sleep(5);continue
                directory,slot=claimed;attempt=directory/'attempts/attempt_001';attempt.mkdir(parents=True)
                spec={**job,'campaign_root':str(root),'plan_sha256':scientific.sha(root/'plan.json'),
                    'cohort_sha256':plan['definition']['cohort_sha256'],'slot_path':str(slot),'controller_id':owner['controller_id']}
                atomic(directory/'spec.json',spec);reserved=(directory,slot,attempt)
            directory,slot,attempt=reserved
            if stopped:break
            # Never wrap this call in a retry: a failure after Popen may be ambiguous.
            child,reason=admission.spawn_admitted([sys.executable,str(ROOT/'scripts/run_rq3_parity_trial.py'),
                '--spec',str(directory/'spec.json'),'--out',str(attempt),'--live'],owner='rq3-pre-native-recovery1',
                job_id=JOB,log_path=attempt/'launcher.log',process_cost=6)
            if child is None:
                atomic(root/'status.json',{**owner,'at':time.time(),'state':reason,'native_launches':0});time.sleep(5);continue
            atomic(root/'dispatched.json',{**owner,'at':time.time(),'worker':identity(child.pid),'native_launches':1})
            atomic(root/'status.json',{**owner,'at':time.time(),'state':'running_once','worker':identity(child.pid),'native_launches':1})
            reserved=None
            while child.poll() is None:time.sleep(3)
            result=scientific.read(attempt/'result.json') if (attempt/'result.json').exists() else {}
            command=[sys.executable,str(ROOT/'scripts/judge_bc_v3_completed.py'),'--root',str(root),'--output',str(grading),
                '--concurrency','1','--limit','1','--live']
            with (root/'judge.log').open('a') as log:
                judged=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL)
            atomic(root/'status.json',{**owner,'at':time.time(),'state':'finished','native_launches':1,'prediction_status':result.get('status','unknown'),
                'judge_exit_code':judged.returncode,'grading_root':str(grading)})
            return
    finally:
        # Existing or ambiguous claims are never recycled. Leave an unlaunched
        # reservation for explicit review rather than inventing a second retry.
        if reserved:atomic(root/'held-reservation.json',{'at':time.time(),'job_id':JOB,'reason':'Supervisor stopped before a confirmed spawn; no automatic replay'})


if __name__=='__main__':main()
