#!/usr/bin/env python3
"""Runtime RQ3 concurrency override to16 with frozen scientific plan unchanged."""
import argparse
import collections
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
import fcntl
import json
import os
from pathlib import Path
import signal
import sys
import time
from experiment_admission import spawn_admitted
from lab import ROOT
from run_bc_campaign import attempt_state,digest
from run_bc_trial import atomic,process_identity
from run_rq3_campaign import prepare,directory,core_admission,grade,CORE,DEFAULT_OUT

CONCURRENCY=16

def eligible(state):return state=='pending'  # terminal/interrupted/unknown never retried

def validate(out):
    if not(out/'plan.json').exists():raise ValueError('Existing frozen RQ3 plan required')
    plan,cfg=prepare(out)  # checks original controller, adapters, renderer, core, configs, cohort
    if (out/'cohort.jsonl').read_bytes()!=(ROOT/'outputs/cohorts/bc100.jsonl').read_bytes():raise ValueError('Frozen RQ3 cohort changed')
    if (out/'experiment.json').read_bytes()!=(CORE/'experiment.json').read_bytes():raise ValueError('Frozen RQ3 experiment changed')
    return plan,cfg

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=DEFAULT_OUT)
    p.add_argument('--live',action='store_true');p.add_argument('--resume',action='store_true');p.add_argument('--wait-for-lease',action='store_true');a=p.parse_args()
    out=a.root.resolve();plan,cfg=validate(out)
    print(json.dumps({'live':a.live,'frozen_concurrency':plan['definition']['concurrency'],'runtime_concurrency':CONCURRENCY,
        'new_trials':plan['definition']['new_trials'],'reused_trials':plan['definition']['reused_trials'],
        'scientific_plan_unchanged':True,'retry_terminal_or_unknown':False}),flush=True)
    if not a.live:return
    if not a.resume:raise SystemExit('Existing campaign requires --resume')
    if os.environ.get('ACL_FIXTURE_BASE_URL'):raise SystemExit('Fixture override forbidden')
    with (out/'coordinator.lock').open('a') as lock:
        while True:
            try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);break
            except BlockingIOError:
                if not a.wait_for_lease:raise SystemExit('Existing RQ3 coordinator owns lease')
                time.sleep(5)
        plan,cfg=validate(out)
        if (out/'STOP').exists():raise SystemExit('STOP present; not dispatching')
        stopped=False;children={};halt=None;jobs=plan['jobs'];own=[j for j in jobs if not j.get('external_job_dir')]
        def stop(*unused):
            nonlocal stopped
            stopped=True
        signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
        source={'source':'User explicitly requested RQ3 concurrency16; runtime scheduling only',
            'frozen_concurrency':2,'runtime_concurrency':16,'controller_sha256':digest(Path(__file__).read_bytes()),
            'admission_sha256':digest((ROOT/'scripts/experiment_admission.py').read_bytes()),'changed_at':datetime.now(timezone.utc).isoformat()}
        atomic(out/'runtime-scheduling.json',source)
        if (out/'coordinator.json').exists():atomic(out/f'coordinator-before-migration-{time.time_ns()}.json',json.loads((out/'coordinator.json').read_text()))
        atomic(out/'coordinator.json',{'pid':os.getpid(),'start_identity':process_identity(os.getpid()),'started_at':datetime.now(timezone.utc).isoformat(),
            'controller':'resume_rq3_plan.py','runtime_concurrency':16})
        while True:
            if (out/'STOP').exists():stopped=True
            states={j['job_id']:attempt_state(directory(out,j)) for j in jobs}
            for jid,child in list(children.items()):
                if child.poll() is not None:children.pop(jid)
            active=sum(states[j['job_id']][0]=='running' for j in own)
            failed=sum(states[j['job_id']][0]=='terminal' and json.loads((states[j['job_id']][1]/'result.json').read_text()).get('status')=='failed' for j in own)
            if failed>=16:halt='16 failed new trials; inspect before further spending'
            admit,why=core_admission()
            if admit and not stopped and not halt:
                slots=CONCURRENCY-active
                for j in own:
                    if slots<=0 or stopped:break
                    state,last=states[j['job_id']]
                    if not eligible(state):continue
                    folder=directory(out,j);attempts=folder/'attempts';attempts.mkdir(parents=True,exist_ok=True)
                    spec=folder/'spec.json'
                    if spec.exists() and json.loads(spec.read_text())!=j:raise ValueError('Existing spec changed')
                    if not spec.exists():atomic(spec,j)
                    attempt=attempts/'attempt_001'  # only never-started jobs are eligible
                    # Do not create attempt directory until admission; launcher may create it.
                    child,why=spawn_admitted([sys.executable,str(ROOT/'scripts/rq3_trial.py'),'--spec',str(spec),'--out',str(attempt),'--live'],
                        owner='rq3',job_id=j['job_id'],log_path=attempt/'launcher.log',process_cost=4)
                    if child is None:break
                    children[j['job_id']]=child;slots-=1
            counts=collections.Counter(states[j['job_id']][0] for j in own)
            reused=collections.Counter(states[j['job_id']][0] for j in jobs if j.get('external_job_dir'))
            atomic(out/'status.json',{'updated_at':datetime.now(timezone.utc).isoformat(),'new_states':dict(counts),'reused_control_states':dict(reused),
                'concurrency_limit':16,'frozen_concurrency_limit':2,'runtime_change_source':source['source'],
                'pause_requested':stopped,'halt_reason':halt,'admission':why,'process_limit_exclusive':128,'controller':'resume_rq3_plan.py'})
            if counts['terminal']==len(own):break
            if (stopped or halt) and not active:return
            if not active and not any(eligible(states[j['job_id']][0]) for j in own):return
            time.sleep(5)
        # Preserve original grading stage/concurrency; no overlapping core grading.
        core_jobs=json.loads((CORE/'plan.json').read_text())['jobs']
        while not all((CORE/'jobs'/j['job_id']/'judge.json').exists() for j in core_jobs):
            if stopped or (out/'STOP').exists():return
            atomic(out/'grading-status.json',{'status':'waiting_for_core_grading','new_predictions_terminal':len(own)})
            time.sleep(30)
        with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(lambda j:grade(out,j,cfg),own))
        atomic(out/'grading-status.json',{'status':'finished_attempts','note':'Unknown judge outcomes never retried'})

if __name__=='__main__':main()
