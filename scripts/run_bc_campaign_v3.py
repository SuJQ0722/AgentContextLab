#!/usr/bin/env python3
"""Frozen v3 BC100 campaign; cross-host durable claims, pending-only resume.

--limit bounds NEW launches in this controller invocation, not the scientific plan.
SIGTERM/STOP stops dispatch and drains children; it never kills running trials.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
import re
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
import uuid
from lab import ROOT

VERSION='hermes-parity-v3'
HARNESSES=('hermes','dsh')
STRATEGIES=('none','summarize','sliding_window','discard','visual')
CELL_CAP=32
DEFAULT_ROOT=ROOT/'outputs/campaigns/bc100-r3-hermes-parity-v3'


def now():return datetime.now(timezone.utc).isoformat()
def digest(raw):return hashlib.sha256(raw).hexdigest()
def atomic(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    with temporary.open('x') as stream:
        json.dump(value,stream,ensure_ascii=False,indent=2);stream.flush();os.fsync(stream.fileno())
    temporary.replace(path)


def identity(pid=None):
    pid=os.getpid() if pid is None else pid
    try:
        fields=Path(f'/proc/{pid}/stat').read_text().split(') ',1)[1].split()
        start=fields[19] if fields[0]!='Z' else None
    except (OSError,IndexError):start=None
    return {'hostname':socket.gethostname(),'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
            'pid_namespace':os.readlink('/proc/self/ns/pid'),'pid':pid,'start_identity':start}


def same_host(owner,local=None):
    local=local or identity()
    return all(owner.get(key)==local.get(key) for key in ('hostname','boot_id','pid_namespace'))


def owner_alive(owner):
    # A PID from another host/boot/namespace is never inspected or signalled.
    if not same_host(owner):return None
    return bool(owner.get('start_identity') and identity(owner['pid'])['start_identity']==owner['start_identity'])


def implementation_hashes():
    names=['run_bc_campaign_v3.py','run_bc_trial_v3.py','hermes_bc_worker_v3.py','run_dsh_eval_v3.py',
      'hermes_bc_worker.py','hermes_native_vision_worker_v2.py','run_dsh_eval.py','local_reader_text_service.py','lab.py','local_web.py','review_execution.py',
      'shared_context_policy.py','hermes_tool_bridge.py','native_image_origins.py','rq3_pdf_renderer.py',
      'dsh_image_preservation.py','dsh_wire_image_guard.mjs','dsh_wire_expectations.mjs','dsh_raw_usage_observer.mjs']
    paths=[ROOT/'scripts'/name for name in names]
    paths+=list((ROOT/'plugins').rglob('*.mjs'))
    paths += [ROOT/'configs/research.dsh.patch.yml',ROOT/'configs/tokenhub.dsh.patch.yml',ROOT/'configs/reader-text-v1.json']
    for pattern in ('packages/*/*/lib/**/*.js','apps/*/lib/**/*.js','vendor/*/lib/**/*.js'):
        paths+=list((ROOT/'deepseekHarness').glob(pattern))
    paths += [ROOT/'deepseekHarness/pnpm-lock.yaml',ROOT/'deepseekHarness/package.json']
    pi=ROOT/'deepseekHarness/packages/llm/llm-pi-ai/node_modules/@earendil-works/pi-ai'
    paths += [pi/'package.json',*list((pi/'dist').rglob('*.js'))]
    # Customized Hermes is not represented solely by its upstream git commit.
    paths+=list((ROOT/'hermes-agent').glob('*.py'))
    for folder in ('agent','plugins/context_engine','tools'):
        paths+=list((ROOT/'hermes-agent'/folder).rglob('*.py'))
    return {str(p.relative_to(ROOT)):digest(p.read_bytes()) for p in sorted(set(paths))}


def validate_sources(plan,root):
    definition=plan['definition']
    if digest((root/'experiment.json').read_bytes())!=definition['config_sha256']:raise ValueError('Frozen configuration changed')
    if digest((root/'cohort.jsonl').read_bytes())!=definition['cohort_sha256']:raise ValueError('Frozen cohort changed')
    if json.loads((ROOT/'harness-lock.json').read_text())!=definition['harness_lock']:raise ValueError('Harness lock changed')
    for name,expected in definition['implementation_sha256'].items():
        if digest((ROOT/name).read_bytes())!=expected:raise ValueError(f'Implementation changed: {name}; use a new lineage')
    pin=definition['harness_lock']['deepseek']['commit']
    actual=subprocess.check_output(['git','-C',str(ROOT/'deepseekHarness'),'rev-parse','HEAD'],text=True).strip()
    if actual!=pin:raise ValueError('Pinned DSH revision changed')
    if subprocess.run(['git','-C',str(ROOT/'deepseekHarness'),'diff','HEAD','--quiet'],check=False).returncode:
        raise ValueError('Pinned DSH tracked source changed')
    if digest(json.dumps(plan['jobs'],sort_keys=True,separators=(',',':')).encode())!=definition['jobs_sha256']:
        raise ValueError('Frozen job list changed')


def make_jobs(rows,cfg):
    c=cfg['bc100_campaign']
    if len(rows)!=100 or len({r['id'] for r in rows})!=100 or c['questions']!=100 or c['repeats']!=3:
        raise ValueError('v3 requires the frozen 100 unique questions and three repeats')
    if set(c['models'])!=set(HARNESSES) or set(c['strategies'])!=set(STRATEGIES):raise ValueError('Expected two harnesses and five strategies')
    if any(model!=cfg['model'] for model in c['models'].values()):raise ValueError('Each harness must use the reviewed route')
    if any(not re.fullmatch(r'[A-Za-z0-9_.-]+',str(r['id'])) for r in rows):raise ValueError('Unsafe question identifier')
    jobs=[]
    for repeat in range(1,4):
        for row in rows:
            for strategy in STRATEGIES:
                for harness in HARNESSES:
                    jobs.append({'job_id':f"{harness}/{strategy}/{row['id']}_r{repeat:02}",
                      'harness':harness,'strategy':strategy,'question_id':row['id'],'question':row['question'],
                      **({'image':row['image']} if row.get('image') else {}),
                      'repeat':repeat,'model':cfg['model'],'timeout_seconds':c['timeout_seconds']})
    return jobs


def prepare(root,config):
    root.mkdir(parents=True,exist_ok=True)
    with (root/'prepare.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        raw=config.read_bytes();cfg=json.loads(raw)
        if cfg.get('execution_version')!=VERSION:raise ValueError('Wrong execution version')
        manifest=json.loads((ROOT/'outputs/cohorts/bc100-manifest.json').read_text())['datasets']['bc100']
        cohort=Path(manifest['cohort_path']).read_bytes()
        if digest(cohort)!=manifest['cohort_sha256']:raise ValueError('Original frozen cohort changed')
        rows=[json.loads(line) for line in cohort.splitlines() if line.strip()];jobs=make_jobs(rows,cfg)
        definition={'execution_version':VERSION,'config_sha256':digest(raw),'cohort_sha256':digest(cohort),
          'planned_runs':3000,'per_cell_concurrency_cap':CELL_CAP,
          'jobs_sha256':digest(json.dumps(jobs,sort_keys=True,separators=(',',':')).encode()),
          'implementation_sha256':implementation_hashes(),'harness_lock':json.loads((ROOT/'harness-lock.json').read_text())}
        path=root/'plan.json';existed=path.exists()
        if existed:
            plan=json.loads(path.read_text())
            if plan['definition']!=definition:raise ValueError('Frozen campaign inputs changed; use a new versioned root')
        else:
            (root/'experiment.json').write_bytes(raw);(root/'cohort.jsonl').write_bytes(cohort)
            plan={'definition':definition,'jobs':jobs};atomic(path,plan)
        validate_sources(plan,root)
        return plan,cfg,existed


def job_state(jobdir):
    if (jobdir/'attempts/attempt_001/result.json').exists():return 'terminal'
    claim=jobdir/'claim'
    if not claim.exists():
        return 'unknown' if (jobdir/'attempts').exists() else 'pending'
    heartbeat=jobdir/'attempts/attempt_001/heartbeat.json'
    if heartbeat.exists():
        try:
            owner=json.loads(heartbeat.read_text());alive=owner_alive(owner)
            if alive is True:return 'running_local'
            if alive is None and time.time()-owner.get('heartbeat_unix',0)<90:return 'running_remote_unverified'
        except (OSError,ValueError,KeyError):pass
    return 'unknown'  # Permanent claim is never recycled, even under --resume.


def acquire_claim(root,job,owner,cap=CELL_CAP):
    """Atomic cross-host exclusion; unknown slots stay occupied until reviewed."""
    jobdir=root/'jobs'/job['job_id'];jobdir.mkdir(parents=True,exist_ok=True)
    if job_state(jobdir)!='pending':return None
    cell=root/'cells'/job['harness']/job['strategy']/'slots';cell.mkdir(parents=True,exist_ok=True)
    slot=None
    for i in range(cap):
        candidate=cell/f'{i:02}'
        try:candidate.mkdir()
        except FileExistsError:continue
        slot=candidate;break
    if slot is None:return None
    try:
        # Slot owner is stored before the job claim. A crash here holds capacity,
        # but cannot cause a duplicate paid attempt.
        atomic(slot/'owner.json',{**owner,'job_id':job['job_id'],'claimed_at':now()})
        (jobdir/'claim').mkdir()
    except FileExistsError:
        (slot/'owner.json').unlink();slot.rmdir();return None
    atomic(jobdir/'claim/owner.json',{**owner,'job_id':job['job_id'],'slot':str(slot),'claimed_at':now()})
    return jobdir,slot


def release_slot(slot):
    # Only the owning trial releases after durable result plus child termination.
    (slot/'owner.json').unlink(missing_ok=True);slot.rmdir()


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root',type=Path,default=DEFAULT_ROOT)
    ap.add_argument('--config',type=Path,default=ROOT/'configs/experiment.v3.review.json')
    ap.add_argument('--harness',choices=HARNESSES,nargs='+',default=list(HARNESSES))
    ap.add_argument('--strategy',choices=STRATEGIES,nargs='+',default=list(STRATEGIES))
    ap.add_argument('--concurrency',type=int,default=1,help='Local controller pool; each harness/strategy cell also has a shared 32-slot cap')
    ap.add_argument('--limit',type=int,help='Maximum new launches this invocation (does not change plan)')
    ap.add_argument('--resume',action='store_true');ap.add_argument('--live',action='store_true')
    args=ap.parse_args()
    if not 1<=args.concurrency<=32 or (args.limit is not None and args.limit<1):ap.error('concurrency 1..32; positive limit')
    root=args.root.resolve();plan,cfg,existed=prepare(root,args.config.resolve())
    selected=[j for j in plan['jobs'] if j['harness'] in args.harness and j['strategy'] in args.strategy]
    print(json.dumps({'root':str(root),'planned_runs':3000,'selected_jobs':len(selected),'live':args.live,'launch_limit':args.limit,
      'local_pool':args.concurrency,'per_cell_cap':32,'resume_policy':'pending only; terminal, unknown and interrupted never retried'}),flush=True)
    if not args.live:return
    if existed and not args.resume:raise ValueError('Existing plan requires --resume; this never retries claimed jobs')
    from review_execution import enforce
    from lab import environment
    from local_web import configure_web
    if os.environ.get('ACL_FIXTURE_BASE_URL'):raise ValueError('Fixture override forbidden in paid campaign')
    env,_=environment(ROOT,'dsh',root/'experiment.json');enforce(cfg,env,root)
    configure_web(ROOT,env,root/'experiment.json')
    # Readiness is a separate real-handler preflight, not a model request.
    readiness_path=root/'web-readiness'/f"{socket.gethostname()}-{identity()['boot_id']}.json"
    if not readiness_path.exists():readiness_path=root/'web-readiness.json'
    if not readiness_path.exists():raise ValueError('Missing host-specific campaign web readiness; validate real search/fetch handlers before dispatch')
    readiness=json.loads(readiness_path.read_text())
    if readiness.get('config_sha256')!=plan['definition']['config_sha256'] or readiness.get('passed') is not True:
        raise ValueError('Readiness must pass for this exact frozen config')
    if readiness.get('hostname')!=socket.gethostname() or readiness.get('boot_id')!=identity()['boot_id'] or time.time()-readiness.get('checked_at_unix',0)>900:
        raise ValueError('Web readiness must be recent and belong to this host/boot (localhost Reader is per host)')
    controller_id=socket.gethostname()+'-'+uuid.uuid4().hex
    control=root/'controllers'/controller_id;control.mkdir(parents=True)
    owner=identity();atomic(control/'owner.json',{**owner,'created_at':now(),'selection':{'harness':args.harness,'strategy':args.strategy},'concurrency':args.concurrency,'limit':args.limit})
    stopping=False;children={};launched=0
    def stop(*unused):
        nonlocal stopping
        stopping=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    while True:
        if (root/'STOP').exists() or (ROOT/'outputs/PAUSED_BY_USER.json').exists():stopping=True
        for jid,child in list(children.items()):
            if child.poll() is not None:children.pop(jid)
        states=Counter(job_state(root/'jobs'/job['job_id']) for job in selected)
        if not stopping and (args.limit is None or launched<args.limit):
            if len(children)<args.concurrency and states.get('pending',0):validate_sources(plan,root)
            for job in selected:
                if stopping or (root/'STOP').exists() or (ROOT/'outputs/PAUSED_BY_USER.json').exists():stopping=True;break
                if len(children)>=args.concurrency or (args.limit is not None and launched>=args.limit):break
                claimed=acquire_claim(root,job,{**owner,'controller_id':controller_id})
                if claimed is None:continue
                jobdir,slot=claimed;attempt=jobdir/'attempts/attempt_001';attempt.mkdir(parents=True)
                spec={**job,'config_path':str(root/'experiment.json'),'campaign_root':str(root),
                      'plan_sha256':digest((root/'plan.json').read_bytes()),'cohort_sha256':plan['definition']['cohort_sha256'],'slot_path':str(slot),'controller_id':controller_id}
                atomic(jobdir/'spec.json',spec)
                with (attempt/'launcher.log').open('a') as log:
                    if stopping or (root/'STOP').exists() or (ROOT/'outputs/PAUSED_BY_USER.json').exists():
                        stopping=True
                        atomic(attempt/'result.json',{'execution_version':VERSION,'job_id':job['job_id'],'status':'not_started','failure_category':'controller_stop_before_spawn','finished_at':now(),'paid_calls':0})
                        release_slot(slot)
                        break
                    child=subprocess.Popen([sys.executable,str(ROOT/'scripts/run_bc_trial_v3.py'),'--spec',str(jobdir/'spec.json'),'--out',str(attempt),'--live'],cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                children[job['job_id']]=child;launched+=1
        atomic(control/'status.json',{**owner,'updated_at':now(),'heartbeat_unix':time.time(),'launches':launched,
          'active_local':len(children),'selected_states':dict(states),'stop_dispatch':stopping,'drain_policy':'wait for active trials; never signal them'})
        if not children:
            if stopping or (args.limit is not None and launched>=args.limit) or not states.get('pending',0):break
        time.sleep(2)
    print(json.dumps({'controller_id':controller_id,'new_launches':launched,'drained':True,'stopped':stopping}),flush=True)


if __name__=='__main__':main()
