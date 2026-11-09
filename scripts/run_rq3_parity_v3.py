#!/usr/bin/env python3
"""New SFB-only RQ3: seven far-history scales, BC100 x three repeats, native v3."""
import argparse
from collections import Counter
import fcntl
import hashlib
import json
import os
from pathlib import Path
import random
import signal
import sys
import time
import uuid
from lab import ROOT
from run_bc_campaign_v3 import atomic, identity, owner_alive, acquire_claim, release_slot
from bc_route_runtime_v2 import immutable_json

VERSION='rq3-hermes-parity-v3-sfb'
SCALES=(0.,.125,.25,.5,.7,.8,1.)
MODEL='deepseek-v4.1-flash-1017/zijian/sfb'
DEFAULT_ROOT=ROOT/'outputs/campaigns/rq3-deepseek-bc100-r3-parity-v3'
BASE=ROOT/'outputs/campaigns/bc100-r3-hermes-parity-v3'
SOURCE_NAMES=('run_rq3_parity_v3.py','run_rq3_parity_trial.py','rq3_hermes_parity_worker.py',
    'hermes_bc_worker_v3.py','hermes_bc_worker.py','hermes_native_vision_worker_v2.py','run_bc_trial_v3.py',
    'run_bc_campaign_v3.py','shared_context_policy.py','rq3_pdf_renderer.py','route_attribution_routes1.py',
    'native_image_origins.py','run_dsh_eval.py','lab.py','local_web.py','review_execution.py','experiment_admission_v4.py','preflight_bc_v3_web.py','hermes_tool_bridge.py','bc_claim_publication_io3.py')

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def label(scale):return 'scale_'+str(round(scale*1000)).zfill(4)
def read(p):return json.loads(Path(p).read_text())

def sources():
    paths=[ROOT/'scripts'/name for name in SOURCE_NAMES]
    paths+=list((ROOT/'hermes-agent').glob('*.py'))
    for folder in ('agent','plugins/context_engine','tools'):paths+=list((ROOT/'hermes-agent'/folder).rglob('*.py'))
    paths+=[ROOT/'harness-lock.json',ROOT/'configs/reader-text-v1.json']
    return {str(p.relative_to(ROOT)):sha(p) for p in sorted(set(paths))}


def prepare(root):
    root=Path(root).resolve();root.mkdir(parents=True,exist_ok=True)
    if (root/'plan.json').exists():
        plan=read(root/'plan.json');validate(plan,root);return plan
    cfg=read(BASE/'experiment.json');cfg['model']=MODEL
    cfg['bc100_campaign']['models']={'hermes':MODEL,'dsh':MODEL};cfg['bc100_campaign']['judge_model']=MODEL
    cfg['visual_renderer']['history_scale']=1.
    if 'history_scale' in cfg.get('shared_policy',{}).get('strategy_configs',{}).get('visual',{}):
        raise ValueError('Unexpected strategy override would defeat the scale intervention')
    cohort=(BASE/'cohort.jsonl').read_bytes();rows=[json.loads(line) for line in cohort.decode().splitlines() if line.strip()]
    if len(rows)!=100 or len({r['id'] for r in rows})!=100:raise ValueError('Exactly 100 unique frozen questions required')
    immutable_json(root/'experiment.json',cfg)
    if (root/'cohort.jsonl').exists():
        if (root/'cohort.jsonl').read_bytes()!=cohort:raise ValueError('Frozen RQ3 cohort changed')
    else:(root/'cohort.jsonl').write_bytes(cohort)
    configs={}
    for scale in SCALES:
        per=json.loads(json.dumps(cfg));per['visual_renderer']['history_scale']=scale
        per['rq3']={'version':VERSION,'far_history_scale':scale,'fixed_repeats':3,
            'intervention':'Only far-history canvas linear scale; recent history retains original resolution',
            'zero_semantics':'0x omits far-history canvases, not recent canvases or retained native images',
            'baseline':'Independent fresh 1x SFB runs; no old result reuse'}
        path=root/'configs'/(label(scale)+'.json');immutable_json(path,per);configs[str(path.relative_to(root))]=sha(path)
    jobs=[]
    for repeat in (1,2,3):
        for row in rows:
            for scale in SCALES:
                jobs.append({'job_id':f"hermes/{label(scale)}/{row['id']}_r{repeat:02d}",
                    'harness':'hermes','strategy':'visual','scale':scale,'question_id':row['id'],'question':row['question'],
                    'repeat':repeat,'model':MODEL,'timeout_seconds':cfg['bc100_campaign']['timeout_seconds'],
                    'config_path':str(root/'configs'/(label(scale)+'.json'))})
    random.Random(20261109).shuffle(jobs)
    definition={'version':VERSION,'questions':100,'repeats':3,'scales':list(SCALES),'planned_runs':2100,
        'model':MODEL,'cohort_sha256':sha(root/'cohort.jsonl'),'config_sha256':sha(root/'experiment.json'),
        'scale_config_sha256':configs,'implementation_sha256':sources(),'base_core_plan_sha256':sha(BASE/'plan.json'),
        'jobs_sha256':hashlib.sha256(json.dumps(jobs,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
        'control':'All seven scales are newly run on one exact SFB route; no legacy external observations',
        'statistics':'Repeat accuracy mean/sample std; 100 question-cluster bootstrap; paired sign flips versus 1x; Holm six comparisons',
        'exposure':'Report triggered compression and old/recent canvas exposure; no compression means no demonstrated scale intervention',
        'runtime_concurrency':'Runtime choice 1–16 with shared local admission; target 16, subordinate to core and shared admission'}
    plan={'definition':definition,'jobs':jobs};immutable_json(root/'plan.json',plan);return plan


def validate(plan,root):
    d=plan['definition'];root=Path(root)
    if d.get('version')!=VERSION or len(plan['jobs'])!=2100 or d['model']!=MODEL:raise ValueError('RQ3 plan identity differs')
    for relative,expected in {'experiment.json':d['config_sha256'],'cohort.jsonl':d['cohort_sha256'],**d['scale_config_sha256']}.items():
        if sha(root/relative)!=expected:raise ValueError('Frozen RQ3 input changed: '+relative)
    for name,expected in d['implementation_sha256'].items():
        if sha(ROOT/name)!=expected:raise ValueError('Frozen RQ3 implementation changed: '+name)
    if hashlib.sha256(json.dumps(plan['jobs'],sort_keys=True,separators=(',',':')).encode()).hexdigest()!=d['jobs_sha256']:
        raise ValueError('RQ3 frozen job list changed')


def state(root,job):
    directory=Path(root)/'jobs'/job['job_id'];attempt=directory/'attempts/attempt_001'
    if (attempt/'result.json').exists():return 'terminal'
    if (directory/'claim').exists():return 'claimed_unknown'
    return 'pending'


def validate_trial(spec,out):
    root=Path(spec['campaign_root']).resolve();plan=read(root/'plan.json');validate(plan,root)
    if sha(root/'plan.json')!=spec['plan_sha256']:raise ValueError('RQ3 plan hash changed')
    job=next((j for j in plan['jobs'] if j['job_id']==spec['job_id']),None)
    if job is None or any(spec.get(k)!=v for k,v in job.items()):raise ValueError('RQ3 trial differs from plan')
    if Path(out).resolve()!=(root/'jobs'/spec['job_id']/'attempts/attempt_001').resolve():raise ValueError('RQ3 output path differs')
    if spec['cohort_sha256']!=plan['definition']['cohort_sha256']:raise ValueError('RQ3 cohort differs')
    from bc_claim_publication_io3 import wait_for_owned_metadata
    wait_for_owned_metadata(spec)
    claim=read(root/'jobs'/spec['job_id']/'claim/owner.json');slot=read(Path(spec['slot_path'])/'owner.json')
    if claim.get('slot')!=spec['slot_path']:raise ValueError('RQ3 claim slot differs')
    for record in (claim,slot):
        if record.get('controller_id')!=spec['controller_id'] or record.get('job_id')!=spec['job_id']:raise ValueError('RQ3 ownership differs')
    return root


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,default=DEFAULT_ROOT)
    parser.add_argument('--concurrency',type=int,default=4);parser.add_argument('--limit',type=int)
    parser.add_argument('--resume',action='store_true');parser.add_argument('--live',action='store_true');args=parser.parse_args()
    if not 1<=args.concurrency<=16:parser.error('Concurrency must be 1–16; shared admission may reduce actual workers')
    root=args.root.resolve();plan=prepare(root)
    if not args.live:print(json.dumps({'live':False,'root':str(root),'planned_runs':2100,'scales':SCALES,'model':MODEL}));return
    from experiment_admission_v4 import spawn_admitted
    from preflight_bc_v3_web import preflight
    lock=(root/'controller.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    readiness=preflight(root,root/'experiment.json')
    if not readiness['passed']:raise RuntimeError('RQ3 real web preflight failed; no native task dispatched')
    if not args.resume and any((root/'jobs').glob('*/*/*/claim')):raise ValueError('Existing claims require --resume')
    controller_id=uuid.uuid4().hex;owner={**identity(),'controller_id':controller_id};active={};reserved=None;launched=0;stopping=False;error=None
    def stop(*unused):
        nonlocal stopping
        stopping=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    # Adopt local trials by exact host/boot/namespace/start identity, never replay a claim.
    for job in plan['jobs']:
        attempt=root/'jobs'/job['job_id']/'attempts/attempt_001'
        if (attempt/'worker-started.json').exists() and not (attempt/'result.json').exists():
            worker=read(attempt/'worker-started.json')
            if owner_alive(worker) is True:active[job['job_id']]={'process':None,'identity':worker}
    try:
        while True:
            if (root/'STOP').exists() or (ROOT/'outputs/PAUSED_BY_USER.json').exists():stopping=True
            for jid,child in list(active.items()):
                alive=child['process'].poll() is None if child['process'] else owner_alive(child['identity']) is True
                if not alive:active.pop(jid)
            states=Counter(state(root,j) for j in plan['jobs'])
            if not stopping and len(active)<args.concurrency and (args.limit is None or launched<args.limit):
                candidates=[reserved[0]] if reserved else [j for j in plan['jobs'] if state(root,j)=='pending']
                for job in candidates:
                    if stopping or (root/'STOP').exists():stopping=True;break
                    if len(active)>=args.concurrency or args.limit is not None and launched>=args.limit:break
                    if reserved is None:
                        validate(plan,root);claimed=acquire_claim(root,job,owner,cap=16)
                        if claimed is None:continue
                        directory,slot=claimed;attempt=directory/'attempts/attempt_001';attempt.mkdir(parents=True)
                        spec={**job,'campaign_root':str(root),'plan_sha256':sha(root/'plan.json'),
                            'cohort_sha256':plan['definition']['cohort_sha256'],'slot_path':str(slot),'controller_id':controller_id}
                        atomic(directory/'spec.json',spec);reserved=(job,directory,slot,attempt)
                    _,directory,slot,attempt=reserved
                    if stopping or (root/'STOP').exists():stopping=True;break
                    child,reason=spawn_admitted([sys.executable,str(ROOT/'scripts/run_rq3_parity_trial.py'),
                        '--spec',str(directory/'spec.json'),'--out',str(attempt),'--live'],owner='rq3-parity-v3',
                        job_id=job['job_id'],log_path=attempt/'launcher.log',process_cost=6)
                    if child is None:break
                    active[job['job_id']]={'process':child,'identity':identity(child.pid)};launched+=1;reserved=None
            atomic(root/'status.json',{**owner,'at':time.time(),'active_local':len(active),'launched':launched,
                'target':args.concurrency,'stop_dispatch':stopping,'states':dict(states),
                'reserved_not_started':reserved[0]['job_id'] if reserved else None,'paid_api_retry':False})
            if not active and (stopping or args.limit is not None and launched>=args.limit or states['pending']==0 and reserved is None):break
            time.sleep(3)
    except BaseException as exc:
        error=type(exc).__name__;stopping=True
        while active:
            for jid,child in list(active.items()):
                alive=child['process'].poll() is None if child['process'] else owner_alive(child['identity']) is True
                if not alive:active.pop(jid)
            atomic(root/'status.json',{**owner,'at':time.time(),'active_local':len(active),'stop_dispatch':True,'deferred_error':error})
            if active:time.sleep(3)
        raise
    finally:
        if reserved:
            job,directory,slot,attempt=reserved
            atomic(attempt/'result.json',{'job_id':job['job_id'],'status':'not_started','failure_category':'controller_stopped_before_native_launch',
                'slot_released':True,'unconfirmed_child_termination':[],'score':None,'model':MODEL,'api_calls':0})
            release_slot(slot)
        atomic(root/'controller-exit.json',{**owner,'at':time.time(),'drained':not active,'stopped':stopping,'error_type':error})


if __name__=='__main__':main()
