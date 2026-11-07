#!/usr/bin/env python3
"""Resume frozen BC plan; classify proven budget-guard outcomes without changing trials."""
import argparse
import collections
from datetime import datetime,timezone
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from lab import ROOT
from run_bc_campaign import attempt_state, digest, implementation_hashes, make_jobs
from run_bc_trial import atomic, process_identity

GUARD='Post-compression budget exceeded; controlled run invalid'

def classify_result(result,native=None,compressions=(),expected_budget=16384):
    """Pure structural classifier: tool text/error substrings are never evidence."""
    if result.get('status')!='failed':return result.get('status','unknown')
    category=result.get('failure_category')
    if category in ('output_limit','step_limit'):return category
    native=native or {};final=native.get('final') or {};reason=final.get('reason') or {};error=reason.get('error') or {}
    c=compressions[-1] if compressions else {}
    post=c.get('post_compression_tokens')
    if (result.get('harness')=='dsh' and category=='execution_error' and native.get('status')=='failed'
        and reason.get('kind')=='error' and error.get('message')==GUARD and error.get('code')=='UNKNOWN'
        and c.get('valid') is False and c.get('budget')==expected_budget
        and c.get('token_measurement')=='dsh_token_meter_estimate'
        and isinstance(post,(int,float)) and not isinstance(post,bool) and post>expected_budget
        and c.get('session_id') and c['session_id']==final.get('sessionId')):
        return 'budget_limit'
    return 'unexpected_failure'

def classify_attempt(attempt,budget):
    result=json.loads((attempt/'result.json').read_text());native={};compressions=[]
    native_path=result.get('native_result_path')
    if native_path:
        path=Path(native_path).resolve()
        if path.is_relative_to(attempt.resolve()) and path.exists():
            native=json.loads(path.read_text());m=path.parent/'workspace/metrics/compression.jsonl'
            if m.exists():compressions=[json.loads(x) for x in m.read_text().splitlines() if x.strip()]
    return classify_result(result,native,compressions,budget)

def eligible(state,jid,resumable):
    return state=='pending' or (state=='interrupted' and jid in resumable)

def validate_plan(out):
    plan=json.loads((out/'plan.json').read_text());definition=plan['definition']
    raw=(out/'experiment.json').read_bytes();cfg=json.loads(raw)
    if digest(raw)!=definition['config_sha256']:raise ValueError('Frozen config hash mismatch')
    if digest((ROOT/'configs/experiment.json').read_bytes())!=definition['config_sha256']:raise ValueError('Root config changed')
    cohort=(ROOT/'outputs/cohorts/bc100.jsonl').read_bytes()
    if digest(cohort)!=definition['cohort_sha256']:raise ValueError('Frozen cohort hash mismatch')
    if implementation_hashes()!=definition['implementation_sha256']:raise ValueError('Frozen implementation hashes mismatch')
    lock=json.loads((ROOT/'harness-lock.json').read_text())
    if lock!=definition['harness_lock']:raise ValueError('Harness lock changed')
    actual=subprocess.check_output(['git','-C',str(ROOT/lock['deepseek']['path']),'rev-parse','HEAD'],text=True).strip()
    if actual!=lock['deepseek']['commit']:raise ValueError('Actual DSH revision differs from harness lock')
    rows=[json.loads(x) for x in cohort.splitlines() if x.strip()]
    if len(rows)!=cfg['bc100_campaign']['questions']:raise ValueError('Question count mismatch')
    expected=make_jobs(rows,cfg)
    for j in expected:j['config_path']=str(out/'experiment.json')
    if plan['jobs']!=expected:raise ValueError('Frozen jobs changed')
    if len(expected)!=definition['planned_runs'] or definition['concurrency']!=cfg['bc100_campaign']['concurrency']:raise ValueError('Plan size/concurrency mismatch')
    return plan,cfg

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root',type=Path,default=ROOT/'outputs/campaigns/bc100-r3-all-strategies')
    ap.add_argument('--live',action='store_true');ap.add_argument('--resume',action='store_true')
    ap.add_argument('--wait-for-lease',action='store_true')
    a=ap.parse_args();out=a.root.resolve();plan,cfg=validate_plan(out);jobs=plan['jobs'];limit=plan['definition']['concurrency']
    budget=cfg['pilot']['post_compression_budget_tokens']
    if not a.live:
        # Do not call attempt_state in dry-run: it may create a missing lease file.
        classifications=collections.Counter()
        for j in jobs:
            attempts=sorted((out/'jobs'/j['job_id']/'attempts').glob('attempt_*'))
            if attempts and (attempts[-1]/'result.json').exists():classifications[classify_attempt(attempts[-1],budget)]+=1
        print(json.dumps({'live':False,'planned_runs':len(jobs),'concurrency':limit,'validated_implementation_files':len(plan['definition']['implementation_sha256']),
            'classifications':dict(classifications),'terminal_jobs_retried':False,'budget_changed':False}));return
    if not a.resume:raise SystemExit('Existing frozen plan requires --resume')
    if os.environ.get('ACL_FIXTURE_BASE_URL'):raise SystemExit('Fixture override forbidden')
    lease=(out/'coordinator.lock').open('a')
    while True:
        try:fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB);break
        except BlockingIOError:
            if not a.wait_for_lease:raise SystemExit('Existing coordinator holds lease')
            time.sleep(5)
    # Revalidate after waiting, before spawning or changing controller metadata.
    plan,cfg=validate_plan(out)
    if (out/'STOP').exists():raise SystemExit('STOP is present; preserve stop request, do not dispatch')
    exit_path=out/'coordinator-exit.json'
    if a.wait_for_lease and exit_path.exists() and json.loads(exit_path.read_text()).get('paused'):
        raise SystemExit('Previous coordinator was explicitly paused; automatic takeover is cancelled')
    stop_requested=False;children={};halt_reason=None
    def stop(*unused):
        nonlocal stop_requested
        stop_requested=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    resumable={j['job_id'] for j in jobs if attempt_state(out/'jobs'/j['job_id'])[0]=='interrupted'}
    stamp={'pid':os.getpid(),'start_identity':process_identity(os.getpid()),'started_at':datetime.now(timezone.utc).isoformat(),
           'controller':'resume_bc_plan.py','controller_sha256':digest(Path(__file__).read_bytes()),'budget_and_trial_code_unchanged':True}
    # Keep the previous coordinator metadata for audit; canonical metadata is for monitors.
    if (out/'coordinator.json').exists():atomic(out/'monitor'/f'coordinator-before-takeover-{time.time_ns()}.json',json.loads((out/'coordinator.json').read_text()))
    atomic(out/'coordinator.json',stamp)
    while True:
        if (out/'STOP').exists():stop_requested=True
        states={j['job_id']:attempt_state(out/'jobs'/j['job_id']) for j in jobs}
        running=[(jid,p) for jid,(state,p) in states.items() if state=='running']
        for jid,p in list(children.items()):
            if p.poll() is not None:children.pop(jid)
        classified=[];unexpected=[]
        for jid,(state,p) in states.items():
            if state!='terminal':continue
            label=classify_attempt(p,budget)
            classified.append({'job_id':jid,'attempt':str(p),'observed_classification':label,'original_result_unchanged':True})
            if label=='unexpected_failure':unexpected.append(jid)
        atomic(out/'monitor/resume-classification.json',{'updated_at':datetime.now(timezone.utc).isoformat(),
            'expected_post_compression_budget':budget,'classifications':classified,'unexpected_failure_count':len(unexpected)})
        if len(unexpected)>=16:halt_reason='16 unexpected failed jobs; proven budget-limit outcomes excluded'
        if not stop_requested and not halt_reason:
            slots=limit-len(running)
            for j in jobs:
                if slots<=0:break
                jid=j['job_id'];state,last=states[jid]
                if not eligible(state,jid,resumable):continue
                directory=out/'jobs'/jid;attempts=directory/'attempts';attempts.mkdir(parents=True,exist_ok=True)
                if state=='interrupted' and last and not (last/'result.json').exists():
                    atomic(last/'result.json',{'job_id':jid,'status':'interrupted','failure_category':'worker_disappeared',
                        'usage_note':'Prior attempt preserved; provider usage may be incomplete'})
                number=len(list(attempts.glob('attempt_*')))+1;attempt=attempts/f'attempt_{number:03}';attempt.mkdir()
                spec=directory/'spec.json'
                if spec.exists() and json.loads(spec.read_text())!=j:raise RuntimeError('Existing job spec differs from frozen plan')
                if not spec.exists():atomic(spec,j)
                with (attempt/'launcher.log').open('a') as log:
                    child=subprocess.Popen([sys.executable,str(ROOT/'scripts/run_bc_trial.py'),'--spec',str(spec),'--out',str(attempt),'--live'],
                        cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                children[jid]=child;slots-=1;resumable.discard(jid)
        counts=collections.Counter(state for state,p in states.values())
        atomic(out/'status.json',{'updated_at':datetime.now(timezone.utc).isoformat(),'pid':os.getpid(),'planned_runs':len(jobs),
            'concurrency_limit':limit,'states':dict(counts),'pause_requested':stop_requested,'halt_reason':halt_reason,
            'controller':'resume_bc_plan.py','unexpected_failure_count':len(unexpected),
            'budget_limit_count':sum(r['observed_classification']=='budget_limit' for r in classified)})
        # Stop dispatch and drain existing work; no killed workers or silent retry.
        if counts['terminal']==len(jobs) or ((stop_requested or halt_reason) and not running):break
        if not running and not any(eligible(s,j,resumable) for j,(s,p) in states.items()):break
        time.sleep(2)
    atomic(out/'coordinator-exit.json',{'ended_at':datetime.now(timezone.utc).isoformat(),'paused':stop_requested,
        'halt_reason':halt_reason,'controller':'resume_bc_plan.py'})

if __name__=='__main__':main()
