#!/usr/bin/env python3
"""DeepSeek RQ3: shared BC100 x 3, seven scales, reuse the core 1x control.

No changed harness loop or compression policy: existing isolated Hermes workers
read per-scale frozen config copies. Lower priority than the core 16 workers.
Default prepares a plan and makes no model calls.
"""
import argparse
import collections
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import random
import signal
import subprocess
import sys
import time
import urllib.request
from lab import ROOT, environment
from monitor_rebuttal import process_snapshot, read_json
from run_bc_campaign import attempt_state, digest, implementation_hashes
from run_bc_trial import atomic, process_identity
from resume_bc_plan import validate_plan

SCALES=[0.,.125,.25,.5,.7,.8,1.]
CORE=ROOT/'outputs/campaigns/bc100-r3-all-strategies'
DEFAULT_OUT=ROOT/'outputs/campaigns/rq3-deepseek-bc100-r3'


def label(scale):return f'scale_{round(scale*1000):04d}'


def make_plan(rows,cfg,out,core=CORE):
    jobs=[];settings=cfg['bc100_campaign']
    for repeat in range(1,4):
        for row in rows:
            block=[]
            for scale in SCALES:
                j={'job_id':f"hermes/{label(scale)}/{row['id']}_r{repeat:02d}",
                    'harness':'hermes','strategy':'visual','scale':scale,'model':settings['models']['hermes'],
                    'question_id':row['id'],'question':row['question'],'repeat':repeat,
                    'timeout_seconds':settings['timeout_seconds'],
                    'config_path':str(out/'configs'/f'{label(scale)}.json')}
                if scale==1.:j['external_job_dir']=str(core/'jobs/hermes/visual'/f"{row['id']}_r{repeat:02d}")
                block.append(j)
            random.Random(f"{settings['shuffle_seed']}:rq3:{repeat}:{row['id']}").shuffle(block)
            jobs.extend(block)
    return jobs


def directory(out,job):return Path(job['external_job_dir']) if job.get('external_job_dir') else out/'jobs'/job['job_id']


def prepare(out):
    core_plan,cfg=validate_plan(CORE)
    if cfg['visual_renderer']['history_scale']!=1. or cfg['bc100_campaign']['repeats']!=3:
        raise ValueError('Core 1x/avg3 reuse prerequisites not met')
    if cfg['bc100_campaign']['models']['hermes']!=cfg['model']:
        raise ValueError('Core model mismatch')
    cohort=(ROOT/'outputs/cohorts/bc100.jsonl').read_bytes();rows=[json.loads(x) for x in cohort.splitlines()]
    configs={}
    for scale in SCALES:
        per=json.loads(json.dumps(cfg));per['visual_renderer']['history_scale']=scale
        per['rq3']={'scale':scale,'repeats':3,'questions':100,'concurrency':2,
            'source':'New DeepSeek replication; old Table5 mapping unverified',
            'reuse_1x_from_core':True,'process_admission_threshold':100}
        configs[f'{label(scale)}.json']=(json.dumps(per,ensure_ascii=False,indent=2)+'\n').encode()
    renderer={str(p.relative_to(ROOT)):digest(p.read_bytes()) for p in [ROOT/'hermes-agent/plugins/context_engine/visual/__init__.py',ROOT/'hermes-agent/plugins/context_engine/visual/render.py']}
    definition={'cohort_sha256':digest(cohort),'core_plan_sha256':digest((CORE/'plan.json').read_bytes()),
        'controller_sha256':digest(Path(__file__).read_bytes()),
        'judge_implementation_sha256':digest((ROOT/'hermes-agent/Browsecomp_eval/browsecomp_eval/judge.py').read_bytes()),
        'implementation_sha256':implementation_hashes(),'renderer_sha256':renderer,
        'rq3_adapter_sha256':{name:digest((ROOT/'scripts'/name).read_bytes()) for name in
            ['rq3_trial.py','rq3_hermes_worker.py','rq3_pdf_renderer.py']},
        'config_hashes':{k:digest(v) for k,v in configs.items()},'comparison_cells':len(rows)*3*len(SCALES),
        'new_trials':len(rows)*3*(len(SCALES)-1),'reused_trials':len(rows)*3,'concurrency':2,
        'process_admission_threshold':100,'scales':SCALES,'repeats':3,'questions':100}
    plan={'definition':definition,'jobs':make_plan(rows,cfg,out)}
    existing=out/'plan.json'
    if existing.exists():
        if json.loads(existing.read_text())!=plan:raise ValueError('Frozen RQ3 plan changed')
        for name,raw in configs.items():
            if (out/'configs'/name).read_bytes()!=raw:raise ValueError('Frozen scale config changed')
    else:
        (out/'configs').mkdir(parents=True,exist_ok=True)
        for name,raw in configs.items():(out/'configs'/name).write_bytes(raw)
        (out/'cohort.jsonl').write_bytes(cohort)
        (out/'experiment.json').write_bytes((CORE/'experiment.json').read_bytes())
        atomic(existing,plan)
    return plan,cfg


def core_admission():
    status=read_json(CORE/'status.json') or {};health=read_json(CORE/'monitor/core-health.json') or {}
    if status.get('halt_reason') or status.get('pause_requested'):return False,'core paused or halted'
    fatal={'token_conservation_failure','core_worker_limit_violated','visible_process_limit_violated','coordinator_lease_free_with_pending_jobs'}
    if fatal.intersection(health.get('alerts',[])):return False,'core health alert'
    if status.get('states',{}).get('terminal',0)<3000:
        c=read_json(CORE/'coordinator.json') or {}
        if not c.get('start_identity') or process_identity(c.get('pid',0))!=c['start_identity']:return False,'core coordinator unavailable'
    live=sum(p['state']!='Z' for p in process_snapshot().values())
    return (live<100,'available' if live<100 else 'process reserve for core')


def grade(out,job,cfg):
    """Only new trajectories. Borrowed control uses its original core judge."""
    if job.get('external_job_dir'):return
    folder=directory(out,job);target=folder/'judge.json';marker=folder/'judge-started.json'
    if target.exists() or marker.exists():return
    state,attempt=attempt_state(folder)
    if state!='terminal':return
    result=json.loads((attempt/'result.json').read_text());answer=(result.get('final') or {}).get('text') or ''
    record={'job_id':job['job_id'],'model':cfg['bc100_campaign']['judge_model'],'score':None,'usage':None,'api_calls':0}
    with marker.open('x') as f:json.dump(record,f)
    if not answer.strip():record.update(status='scored',score=0.,rule='no_final_answer_within_fixed_budget')
    else:
        sys.path.insert(0,str(ROOT/'hermes-agent/Browsecomp_eval'))
        from browsecomp_eval.judge import build_judge_prompt,analyse_judgemodel_res
        row=next(json.loads(x) for x in (out/'cohort.jsonl').read_text().splitlines() if json.loads(x)['id']==job['question_id'])
        prompt=build_judge_prompt(row['question'],answer,row['answer'])
        env,_=environment(ROOT,'hermes',out/'experiment.json')
        payload={'model':record['model'],'messages':[{'role':'user','content':prompt}],'max_tokens':cfg['max_output_tokens']}
        request=urllib.request.Request(env['TOKENHUB_BASE_URL'].rstrip('/')+'/chat/completions',data=json.dumps(payload).encode(),
            headers={'Authorization':'Bearer '+env['TOKENHUB_API_KEY'],'Content-Type':'application/json'})
        start=time.monotonic();record['api_calls']=1
        try:
            with urllib.request.urlopen(request,timeout=180) as response:raw=json.load(response)
            record.update(response=raw,usage=raw.get('usage'))
            score=analyse_judgemodel_res(raw['choices'][0]['message'].get('content') or '')
            record.update(status='scored' if score is not None else 'invalid_judge_response',score=score)
        except Exception as error:record.update(status='judge_error',error_type=type(error).__name__)
        record['client_http_seconds']=time.monotonic()-start
    atomic(target,record)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=DEFAULT_OUT)
    p.add_argument('--live',action='store_true');p.add_argument('--resume',action='store_true');a=p.parse_args()
    out=a.root.resolve();out.mkdir(parents=True,exist_ok=True);lock=(out/'coordinator.lock').open('a')
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);existed=(out/'plan.json').exists();plan,cfg=prepare(out)
    print(json.dumps({'live':a.live,**{k:plan['definition'][k] for k in ['comparison_cells','new_trials','reused_trials','concurrency','scales']}}),flush=True)
    if not a.live:return
    if existed and not a.resume:raise SystemExit('Existing frozen plan requires --resume')
    if os.environ.get('ACL_FIXTURE_BASE_URL'):raise SystemExit('Fixture override forbidden')
    jobs=plan['jobs'];own=[j for j in jobs if not j.get('external_job_dir')]
    resumable={j['job_id'] for j in own if attempt_state(directory(out,j))[0]=='interrupted'}
    stopped=False;children={};halt=None
    def stop(*unused):
        nonlocal stopped
        stopped=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    atomic(out/'coordinator.json',{'pid':os.getpid(),'start_identity':process_identity(os.getpid()),'started_at':datetime.now(timezone.utc).isoformat()})
    while True:
        if (out/'STOP').exists():stopped=True
        states={j['job_id']:attempt_state(directory(out,j)) for j in jobs}
        for jid,child in list(children.items()):
            if child.poll() is not None:children.pop(jid)
        active=sum(states[j['job_id']][0]=='running' for j in own)
        failures=0
        for j in own:
            state,attempt=states[j['job_id']]
            if state=='terminal' and json.loads((attempt/'result.json').read_text()).get('status')=='failed':failures+=1
        if failures>=16:halt='16 failed new trials; inspect before further spending'
        admit,why=core_admission()
        if admit and not stopped and not halt:
            slots=2-active
            for j in own:
                if slots<=0:break
                state,last=states[j['job_id']]
                if state!='pending' and not(state=='interrupted' and j['job_id'] in resumable):continue
                folder=directory(out,j);attempts=folder/'attempts';attempts.mkdir(parents=True,exist_ok=True)
                if last and state=='interrupted' and not(last/'result.json').exists():
                    atomic(last/'result.json',{'job_id':j['job_id'],'status':'interrupted','usage_note':'Prior attempt preserved; unknown usage remains unknown'})
                attempt=attempts/f'attempt_{len(list(attempts.glob("attempt_*")))+1:03d}';attempt.mkdir()
                spec=folder/'spec.json';atomic(spec,j)
                with (attempt/'launcher.log').open('a') as log:
                    child=subprocess.Popen([sys.executable,str(ROOT/'scripts/rq3_trial.py'),'--spec',str(spec),'--out',str(attempt),'--live'],cwd=ROOT,
                        stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                children[j['job_id']]=child;slots-=1;resumable.discard(j['job_id'])
        counts=collections.Counter(states[j['job_id']][0] for j in own)
        reused=collections.Counter(states[j['job_id']][0] for j in jobs if j.get('external_job_dir'))
        atomic(out/'status.json',{'updated_at':datetime.now(timezone.utc).isoformat(),'new_states':dict(counts),'reused_control_states':dict(reused),
            'concurrency_limit':2,'process_admission_threshold':100,'pause_requested':stopped,'halt_reason':halt,'admission':why})
        if counts['terminal']==len(own):break
        if (stopped or halt) and not active:return
        time.sleep(5)
    # No overlap with core grading/prediction: only start supplementary grading
    # after all original core grades have terminal artifacts.
    core_jobs=json.loads((CORE/'plan.json').read_text())['jobs']
    while not all((CORE/'jobs'/j['job_id']/'judge.json').exists() for j in core_jobs):
        if stopped or (out/'STOP').exists():return
        atomic(out/'grading-status.json',{'status':'waiting_for_core_grading','new_predictions_terminal':len(own)})
        time.sleep(30)
    with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(lambda j:grade(out,j,cfg),own))
    atomic(out/'grading-status.json',{'status':'finished_attempts','note':'Invalid/failed judge responses remain unknown, never silently retried'})


if __name__=='__main__':main()
