#!/usr/bin/env python3
"""Operational pending-only takeover after a verified RQ3 controller stops dispatch."""
import argparse
from collections import Counter
import errno
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import traceback
import types
import uuid
import run_rq3_parity_v3 as scientific
from run_bc_campaign_v3 import atomic,identity,owner_alive,acquire_claim,release_slot
from bc_route_runtime_v2 import immutable_json
from lab import ROOT

VERSION='rq3-parity-v3-dispatch-ops1'


def safe_error(error):
    return {'type':type(error).__name__,'errno':getattr(error,'errno',None),
            'trace_frames':[{'file':x.filename,'line':x.lineno,'function':x.name} for x in traceback.extract_tb(error.__traceback__)]}


def verify_cutover(root,now=None):
    now=time.time() if now is None else now;path=root/'status.json';record=scientific.read(path)
    if record.get('stop_dispatch') is not True or not record.get('deferred_error'):
        raise ValueError('Original controller is not confirmed in exception drain')
    if not isinstance(record.get('at'),(int,float)) or not 0<=now-record['at']<=45:
        # An explicitly completed original controller is safe as well.
        exit_path=root/'controller-exit.json'
        end=scientific.read(exit_path) if exit_path.exists() else {}
        if not (end.get('controller_id')==record.get('controller_id') and end.get('drained') is True and end.get('stopped') is True and owner_alive(record) is False):
            raise ValueError('Original stop acknowledgment is stale or exit is unconfirmed')
    elif owner_alive(record) is not True:
        raise ValueError('Fresh original drain must have exact live process identity')
    return {'version':VERSION,'cutover_unix':now,'original_status_path':str(path),'original_status_sha256':scientific.sha(path),
            'original_controller':record,'original_plan_sha256':scientific.sha(root/'plan.json'),
            'condition':'Verified original frozen controller is in exception drain with dispatch permanently stopped; native children are untouched.',
            'new_dispatch':'Only never-claimed pending jobs; all live original and new trials count toward target16 and shared root slots.'}


def adopt(root,plan):
    active={}
    for job in plan['jobs']:
        path=root/'jobs'/job['job_id']/'attempts/attempt_001'
        if (path/'worker-started.json').exists():
            worker=scientific.read(path/'worker-started.json')
            if owner_alive(worker) is True:active[job['job_id']]={'process':None,'identity':worker,'adopted':True}
    return active


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--root',type=Path,default=scientific.DEFAULT_ROOT)
    ap.add_argument('--concurrency',type=int,default=16);ap.add_argument('--resume',action='store_true');ap.add_argument('--live',action='store_true');args=ap.parse_args()
    if not 1<=args.concurrency<=16:ap.error('Target must be 1–16')
    root=args.root.resolve();plan=scientific.prepare(root)
    if not args.live:
        print(json.dumps({'live':False,'version':VERSION,'root':str(root),'target':args.concurrency,'claimed_jobs_retried':0}));return
    if not args.resume:raise ValueError('Explicit --resume is required for operational takeover')
    lock=(root/'controller-ops1.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    ack=root/'cutover-ops1.json'
    if not ack.exists():immutable_json(ack,verify_cutover(root))
    else:
        old=scientific.read(ack)
        if old.get('original_plan_sha256')!=scientific.sha(root/'plan.json'):raise ValueError('Cutover plan changed')
    import experiment_admission_v4 as admission
    import admission_lock_ops1
    lock_record=admission_lock_ops1.install(admission)
    source_paths=[Path(__file__).resolve(),ROOT/'scripts/admission_lock_ops1.py']
    maintenance={'version':VERSION,'admission_lock_maintenance':lock_record,'plan_sha256':scientific.sha(root/'plan.json'),
        'implementation_sha256':{str(p.relative_to(ROOT)):scientific.sha(p) for p in source_paths},
        'scientific_sources_unchanged':True,'model_or_strategy_changed':False,
        'claim_policy':'Existing claims are never replayed; only pending jobs admitted',
        'lock_retry_scope':'Only explicit admission blocking flock EAGAIN; no spawn or paid API retries'}
    immutable_json(root/'maintenance-ops1.json',maintenance)
    from preflight_bc_v3_web import preflight
    if not preflight(root,root/'experiment.json')['passed']:raise RuntimeError('Real web readiness failed before dispatch')
    owner={**identity(),'controller_id':uuid.uuid4().hex};active=adopt(root,plan);reserved=None;launched=0;stopping=False;last_denial=None
    def stop(*unused):
        nonlocal stopping
        stopping=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    def alive(child):return child['process'].poll() is None if child['process'] else owner_alive(child['identity']) is True
    # Observe Popen returning inside admission without retrying it. If a later
    # ledger write fails, the already-created child still enters our drain set.
    observed=[];original_subprocess=admission.subprocess
    def tracked_popen(*a,**kw):
        p=original_subprocess.Popen(*a,**kw);observed.append(p);return p
    admission.subprocess=types.SimpleNamespace(Popen=tracked_popen,DEVNULL=subprocess.DEVNULL,STDOUT=subprocess.STDOUT)
    status_path=root/'status-ops1.json'
    try:
        while True:
            if (root/'STOP').exists() or (ROOT/'outputs/PAUSED_BY_USER.json').exists():stopping=True
            for jid,child in list(active.items()):
                if not alive(child):active.pop(jid)
            states=Counter(scientific.state(root,j) for j in plan['jobs'])
            if not stopping and len(active)<args.concurrency:
                candidates=[reserved[0]] if reserved else [j for j in plan['jobs'] if scientific.state(root,j)=='pending']
                for job in candidates:
                    if stopping or (root/'STOP').exists():stopping=True;break
                    if len(active)>=args.concurrency:break
                    if reserved is None:
                        scientific.validate(plan,root);claimed=acquire_claim(root,job,owner,cap=16)
                        if claimed is None:continue
                        directory,slot=claimed;attempt=directory/'attempts/attempt_001';attempt.mkdir(parents=True)
                        spec={**job,'campaign_root':str(root),'plan_sha256':scientific.sha(root/'plan.json'),
                              'cohort_sha256':plan['definition']['cohort_sha256'],'slot_path':str(slot),'controller_id':owner['controller_id']}
                        atomic(directory/'spec.json',spec);reserved=(job,directory,slot,attempt)
                    _,directory,slot,attempt=reserved
                    if stopping or (root/'STOP').exists():stopping=True;break
                    immutable_json(attempt/'dispatch-ops1.json',maintenance)
                    observed.clear()
                    try:
                        child,reason=admission.spawn_admitted([sys.executable,str(ROOT/'scripts/run_rq3_parity_trial.py'),
                            '--spec',str(directory/'spec.json'),'--out',str(attempt),'--live'],owner='rq3-parity-v3',
                            job_id=job['job_id'],log_path=attempt/'launcher.log',process_cost=6)
                    except BaseException:
                        if observed:
                            active[job['job_id']]={'process':observed[-1],'identity':identity(observed[-1].pid),'adopted':False}
                            reserved=None
                        raise
                    if child is None:last_denial=reason;break
                    active[job['job_id']]={'process':child,'identity':identity(child.pid),'adopted':False};launched+=1;reserved=None;last_denial=None
            atomic(status_path,{**owner,'at':time.time(),'version':VERSION,'active_local':len(active),
                'adopted_original_active':sum(v['adopted'] for v in active.values()),'launched':launched,'target':args.concurrency,
                'stop_dispatch':stopping,'states':dict(states),'admission_denial':last_denial,
                'reserved_not_started':reserved[0]['job_id'] if reserved else None})
            if not active and (stopping or states['pending']==0 and reserved is None):break
            time.sleep(3)
    except BaseException as error:
        stopping=True;detail=safe_error(error)
        atomic(root/'ops1-error.json',{**owner,'at':time.time(),'error':detail,'spawn_retried':False})
        while active:
            for jid,child in list(active.items()):
                if not alive(child):active.pop(jid)
            atomic(status_path,{**owner,'at':time.time(),'active_local':len(active),'stop_dispatch':True,'deferred_error':detail})
            if active:time.sleep(3)
        raise
    finally:
        admission.subprocess=original_subprocess
        if reserved:
            job,directory,slot,attempt=reserved
            atomic(attempt/'result.json',{'job_id':job['job_id'],'status':'not_started','failure_category':'ops_controller_stopped_before_native_launch',
                'slot_released':True,'unconfirmed_child_termination':[],'score':None,'model':scientific.MODEL,'api_calls':0})
            release_slot(slot)
        atomic(root/'controller-exit-ops1.json',{**owner,'at':time.time(),'drained':not active,'stopped':stopping})


if __name__=='__main__':main()
