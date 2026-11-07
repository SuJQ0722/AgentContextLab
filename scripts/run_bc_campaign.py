#!/usr/bin/env python3
"""Frozen BC100 x repeats x strategies x harnesses, bounded concurrency and durable resume."""
import argparse
import collections
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import random
import signal
import subprocess
import sys
import time
from lab import ROOT, environment
from local_web import configure_web, validate_web
from run_bc_trial import atomic, process_identity


def digest(data):return hashlib.sha256(data).hexdigest()


def implementation_hashes():
    paths=[ROOT/'scripts'/name for name in ['run_bc_campaign.py','run_bc_trial.py','hermes_bc_worker.py',
           'run_dsh_eval.py','lab.py','local_web.py','render_dsh_history.py']]
    paths+=list((ROOT/'plugins').rglob('*.mjs'))
    paths+=[ROOT/'configs/research.dsh.patch.yml',ROOT/'configs/tokenhub.dsh.patch.yml']
    return {str(p.relative_to(ROOT)):digest(p.read_bytes()) for p in sorted(paths)}


def make_jobs(rows,cfg):
    c=cfg['bc100_campaign'];jobs=[]
    for repeat in range(1,c['repeats']+1):
        for row in rows:
            block=[{'job_id':f"{h}/{s}/{row['id']}_r{repeat:02}",'harness':h,'strategy':s,
                    'model':model,'question_id':row['id'],'question':row['question'],'repeat':repeat,
                    'timeout_seconds':c['timeout_seconds']}
                   for h,model in c['models'].items() for s in c['strategies']]
            random.Random(f"{c['shuffle_seed']}:{repeat}:{row['id']}").shuffle(block)
            jobs.extend(block)
    return jobs


def attempt_state(jobdir):
    attempts=sorted((jobdir/'attempts').glob('attempt_*'))
    if not attempts:return 'pending',None
    last=attempts[-1];result=last/'result.json';running=last/'running.json'
    if result.exists():
        r=json.loads(result.read_text());return ('interrupted' if r['status']=='interrupted' else 'terminal'),last
    if running.exists():
        r=json.loads(running.read_text())
        if r.get('start_identity') and process_identity(r['pid'])==r['start_identity']:return 'running',last
    # A coordinator can die immediately after spawn. Never race a worker that
    # has acquired its lease but has not yet published its PID.
    lease=(last/'lease.lock').open('a')
    try:fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:return 'running',last
    finally:lease.close()
    if time.time()-last.stat().st_mtime<15:return 'running',last
    return 'interrupted',last


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root',type=Path,default=ROOT/'outputs/campaigns/bc100-r3-all-strategies')
    ap.add_argument('--live',action='store_true');ap.add_argument('--resume',action='store_true')
    args=ap.parse_args();out=args.root.resolve();out.mkdir(parents=True,exist_ok=True)
    lease=(out/'coordinator.lock').open('a')
    try:fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise SystemExit('Another coordinator owns this campaign')
    raw=(ROOT/'configs/experiment.json').read_bytes();cfg=json.loads(raw)
    cohort=(ROOT/'outputs/cohorts/bc100.jsonl').read_bytes();rows=[json.loads(l) for l in cohort.splitlines()]
    if len(rows)!=cfg['bc100_campaign']['questions']:raise SystemExit('Frozen BC100 question count mismatch')
    jobs=make_jobs(rows,cfg);definition={'config_sha256':digest(raw),'cohort_sha256':digest(cohort),
        'planned_runs':len(jobs),'concurrency':cfg['bc100_campaign']['concurrency'],
        'implementation_sha256':implementation_hashes(),'harness_lock':json.loads((ROOT/'harness-lock.json').read_text())}
    plan_path=out/'plan.json'
    if plan_path.exists():
        old=json.loads(plan_path.read_text())
        if old['definition']!=definition:raise SystemExit('Frozen campaign changed; use a separately versioned campaign')
        if args.live and not args.resume:raise SystemExit('Existing plan: pass --resume to preserve prior attempts')
    else:
        (out/'experiment.json').write_bytes(raw)
        for job in jobs:job['config_path']=str(out/'experiment.json')
        atomic(plan_path,{'definition':definition,'jobs':jobs})
    plan=json.loads(plan_path.read_text());jobs=plan['jobs']
    print(json.dumps({'planned_runs':len(jobs),'concurrency':definition['concurrency'],'live':args.live,'root':str(out)}),flush=True)
    if not args.live:return
    if os.environ.get('ACL_FIXTURE_BASE_URL'):
        raise SystemExit('Fixture override is not allowed for a paid campaign')
    env,_=environment(ROOT,'dsh',out/'experiment.json');configure_web(ROOT,env,out/'experiment.json');validate_web(ROOT,env)
    paused=False;children={};halt_reason=None;started=time.time()
    resumable={job['job_id'] for job in jobs if attempt_state(out/'jobs'/job['job_id'])[0]=='interrupted'} if args.resume else set()
    atomic(out/'coordinator.json',{'pid':os.getpid(),'start_identity':process_identity(os.getpid()),'started_at':datetime.now(timezone.utc).isoformat()})
    def stop(*unused):
        nonlocal paused
        paused=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    while True:
        if (out/'STOP').exists():paused=True
        states={job['job_id']:attempt_state(out/'jobs'/job['job_id']) for job in jobs}
        running=[(j,a) for j,(s,a) in states.items() if s=='running']
        for key,proc in list(children.items()):
            if proc.poll() is not None:children.pop(key)
        if paused:
            for _,a in running:
                f=a/'running.json'
                if f.exists():
                    r=json.loads(f.read_text())
                    if process_identity(r['pid'])==r.get('start_identity'):
                        try:os.kill(r['pid'],signal.SIGTERM)
                        except ProcessLookupError:pass
            if not running:break
        else:
            # Hold further spending after a cluster of unexpected setup/runtime
            # failures. Time/output/step limits are retained ordinary outcomes.
            failures=[]
            for jid,(state,a) in states.items():
                if state=='terminal':
                    r=json.loads((a/'result.json').read_text())
                    if r['status']=='failed' and r.get('failure_category') not in ('output_limit','step_limit'):
                        failures.append(jid)
            if len(failures)>=16:
                halt_reason='16 unexpected failed jobs; inspect before more spending'
            slots=definition['concurrency']-len(running)
            if not halt_reason:
                for job in jobs:
                    state,last=states[job['job_id']]
                    if slots<=0:break
                    if state not in ('pending','interrupted'):continue
                    jobdir=out/'jobs'/job['job_id'];attempts=jobdir/'attempts';attempts.mkdir(parents=True,exist_ok=True)
                    if state=='interrupted' and job['job_id'] not in resumable:continue
                    if state=='interrupted' and last and not (last/'result.json').exists():
                        atomic(last/'result.json',{'job_id':job['job_id'],'status':'interrupted',
                            'failure_category':'worker_disappeared','usage_note':'Provider usage may be incomplete; preserved, never zero-filled'})
                    # Interrupted jobs restart only under explicit --resume;
                    # a newly interrupted job in this process remains stopped.
                    number=len(list(attempts.glob('attempt_*')))+1
                    a=attempts/f'attempt_{number:03}';a.mkdir()
                    spec=jobdir/'spec.json';atomic(spec,job)
                    with (a/'launcher.log').open('a') as log:
                        proc=subprocess.Popen([sys.executable,str(ROOT/'scripts/run_bc_trial.py'),'--spec',str(spec),'--out',str(a),'--live'],
                            cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                    children[job['job_id']]=proc;slots-=1
                    resumable.discard(job['job_id'])
        counts=collections.Counter(s for s,a in states.values())
        atomic(out/'status.json',{
            'updated_at':datetime.now(timezone.utc).isoformat(),'pid':os.getpid(),'planned_runs':len(jobs),
            'concurrency_limit':definition['concurrency'],'states':dict(counts),'pause_requested':paused,'halt_reason':halt_reason})
        if counts['terminal']==len(jobs) or halt_reason and not running:break
        time.sleep(2)
    atomic(out/'coordinator-exit.json',{'ended_at':datetime.now(timezone.utc).isoformat(),'paused':paused,'halt_reason':halt_reason})


if __name__=='__main__':main()
