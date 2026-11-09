#!/usr/bin/env python3
"""Audited successor for only the unclaimed .7 cohort; never replays interrupted work."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
import run_rq3_scale_cloud_ops2 as old
from bc_route_runtime_v2 import immutable_json
from lab import ROOT

VERSION='rq3-scale0700-resume-ops5'
LABEL='scale_0700'
OLD_NAME='acl-rq3-s0700-ops2'
OLD_UID='538c1543df1449bdadf1a6d71a3bde9d'
OLD_HOST='pt-'+OLD_UID+'-worker-0'
EXPECTED_PENDING=219
EXPECTED_UNKNOWN=15
SOURCE_NAMES=('run_rq3_scale0700_resume_ops5.py','bootstrap_rq3_scale0700_resume_ops5.py','run_rq3_scale_cloud_ops2.py','bootstrap_rq3_scale_ops2.py')
ORIGINAL_JOBS=old.jobs_for_scale
ORIGINAL_PUBLISH=old.publish_claim


def area(root):return Path(root)/'cloud-scale-ops5'
def authorization_path(root):return area(root)/'scale0700-resume-authorization.json'
def sha(path):return old.scientific.sha(path)
def read(path):return old.scientific.read(path)
def object_sha(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def platform_proof(describe_path,workers_path):
    describe,workers=read(describe_path),read(workers_path)
    if describe.get('returncode')!=0 or workers.get('returncode')!=0:raise ValueError('Platform evidence command failed')
    data=json.loads(describe['stdout'])
    if any(data.get(k)!=v for k,v in {'name':OLD_NAME,'uid':OLD_UID,'state':'SUSPENDED','workspace_name':'rl'}.items()):
        raise ValueError('Exact predecessor must be platform SUSPENDED')
    text=workers.get('stdout','');lines=[]
    for line in text.splitlines():
        if not line.strip().startswith('|'):continue
        parts=[s.strip() for s in line.strip().strip('|').split('|')]
        if len(parts)!=5:raise ValueError('Unsupported workers table layout')
        if parts[0] in ('','WORKER_NAME'):continue
        lines.append(parts)
    if len(lines)!=1 or lines[0][0]!=OLD_HOST or lines[0][-1]!='Deleted':
        raise ValueError('Every predecessor worker must be Deleted; IP columns may be retained historical metadata')
    if not describe.get('at') or not workers.get('at'):raise ValueError('Evidence timestamp missing')
    return {'job_name':OLD_NAME,'uid':OLD_UID,'state':'SUSPENDED','worker':OLD_HOST,'phase':'Deleted',
            'describe_path':str(Path(describe_path).resolve()),'describe_sha256':sha(describe_path),
            'workers_path':str(Path(workers_path).resolve()),'workers_sha256':sha(workers_path),
            'describe_observed_at':describe['at'],'workers_observed_at':workers['at'],
            'namespace_termination_basis':'Exact platform job suspended and sole worker Deleted; not stale heartbeat alone'}


def snapshot_file(root,path):
    path=Path(path).resolve();relative=path.relative_to(Path(root).resolve());target=area(root)/'predecessor-archive'/relative
    data=path.read_bytes();target.parent.mkdir(parents=True,exist_ok=True)
    try:
        with target.open('xb') as f:f.write(data)
    except FileExistsError:
        if target.read_bytes()!=data:raise ValueError('Predecessor archive conflicts')
    return {'original':str(path),'archive':str(target),'sha256':sha(path)}


def prepare(root,describe_path,workers_path):
    root=Path(root).resolve();plan=read(root/'plan.json');old.scientific.validate(plan,root)
    proof=platform_proof(describe_path,workers_path)
    lease=root/'cloud-scale-ops2/leases'/LABEL;owner=read(lease/'owner.json');runtime=read(lease/'runtime.json');run=Path(runtime['directory'])
    if not run.is_relative_to(root/'cloud-scale-ops2/controllers'/LABEL):raise ValueError('Predecessor runtime path outside cell')
    status=read(run/'status.json')
    for key in ('hostname','boot_id','pid_namespace','controller_id','pid','start_identity'):
        if not owner.get(key) or owner.get(key)!=status.get(key):raise ValueError('Predecessor lease/status identity mismatch')
    if owner['hostname']!=OLD_HOST or status.get('stop_dispatch') is not True:raise ValueError('Predecessor identity/stop acknowledgment missing')
    jobs=ORIGINAL_JOBS(plan,LABEL);pending=[];unknown=[];bound=[]
    for j in jobs:
        d=root/'jobs'/j['job_id'];a=d/'attempts/attempt_001'
        if old.eligible(d):pending.append(j['job_id']);continue
        if old.safe_terminal(a):continue
        claim=read(d/'claim/owner.json')
        if any(claim.get(k)!=owner.get(k) for k in ('hostname','boot_id','pid_namespace','controller_id')):raise ValueError('Unexpected unresolved predecessor')
        if (a/'result.json').exists() or not (a/'worker-started.json').exists():raise ValueError('Unexpected interrupted attempt state')
        starts=a/'native/metrics/call-starts.jsonl'
        if not starts.exists() or not starts.stat().st_size:raise ValueError('Interrupted prediction must retain observed paid-request evidence')
        unknown.append(j['job_id'])
        for path in [d/'claim/owner.json',d/'claim/spec.json',d/'spec.json',a/'worker-started.json',a/'heartbeat.json',starts]:
            if path.exists():bound.append(snapshot_file(root,path))
    if len(pending)!=EXPECTED_PENDING or len(unknown)!=EXPECTED_UNKNOWN:raise ValueError('Expected exactly219 pending and15 interrupted predecessors')
    for path in [lease/'owner.json',lease/'runtime.json',run/'status.json',run/'maintenance.json']:
        bound.append(snapshot_file(root,path))
    slots=root/'cloud-scale-ops2/slots'/LABEL
    occupied=list(slots.glob('[0-9][0-9]/owner.json'))
    if len(occupied)!=EXPECTED_UNKNOWN:raise ValueError('Unexpected predecessor reserved slot count')
    for path in occupied:
        if read(path).get('job_id') not in unknown:raise ValueError('Predecessor slot is not one of15 interrupted jobs')
        bound.append(snapshot_file(root,path))
    auth={'version':VERSION,'launch_authorized':True,'campaign_root':str(root),'scale':LABEL,'max_concurrency':16,
          'plan_sha256':sha(root/'plan.json'),'config_sha256':sha(root/'experiment.json'),'cohort_sha256':sha(root/'cohort.jsonl'),
          'pending_job_ids':pending,'pending_job_ids_sha256':object_sha(pending),'excluded_paid_interrupted_job_ids':unknown,
          'predecessor_identity':owner,'platform_termination':proof,'predecessor_files':bound,
          'sources_sha256':{str(ROOT/'scripts'/n):sha(ROOT/'scripts'/n) for n in SOURCE_NAMES},
          'authorization_basis':'User explicitly requested resuming stopped RQ3; this authorization only dispatches original unclaimed219; no paid-interrupted retry',
          'slot_policy':'New namespace16 slots after proven predecessor namespace termination. Old15 slots/claims remain archived and intact; they represent missing outcomes, not active processes.',
          'paid_retry':False,'scientific_change':False}
    immutable_json(authorization_path(root),auth);immutable_json(area(root)/'cutover.json',auth)
    return auth


def verify_authorization(root,path=None):
    root=Path(root).resolve();path=Path(path or authorization_path(root)).resolve()
    if path!=authorization_path(root).resolve():raise ValueError('Authorization must use fixed cell path')
    a=read(path)
    if a.get('version')!=VERSION or a.get('launch_authorized') is not True or a.get('scale')!=LABEL or a.get('max_concurrency')!=16 or Path(a['campaign_root']).resolve()!=root:
        raise ValueError('Unauthorized successor scope')
    for name,key in [('plan.json','plan_sha256'),('experiment.json','config_sha256'),('cohort.jsonl','cohort_sha256')]:
        if sha(root/name)!=a[key]:raise ValueError('Scientific identity changed')
    pending=a['pending_job_ids'];excluded=a['excluded_paid_interrupted_job_ids']
    if len(pending)!=EXPECTED_PENDING or len(set(pending))!=EXPECTED_PENDING or len(excluded)!=EXPECTED_UNKNOWN or set(pending)&set(excluded) or object_sha(pending)!=a['pending_job_ids_sha256']:
        raise ValueError('Successor allowlist changed')
    if any(j.split('/')[0:2]!=['hermes',LABEL] for j in pending+excluded):raise ValueError('Cross-scale authorization prohibited')
    for p,expected in a['sources_sha256'].items():
        if sha(p)!=expected:raise ValueError('Operational source changed')
    proof=a['platform_termination']
    for key in ('describe','workers'):
        if sha(proof[key+'_path'])!=proof[key+'_sha256']:raise ValueError('Termination evidence changed')
    if platform_proof(proof['describe_path'],proof['workers_path'])!=proof:raise ValueError('Termination proof mismatch')
    for record in a['predecessor_files']:
        if sha(record['original'])!=record['sha256'] or sha(record['archive'])!=record['sha256']:raise ValueError('Preserved predecessor evidence changed')
    if read(area(root)/'cutover.json')!=a:raise ValueError('Successor cutover does not match authorization')
    return a


def install(root,authorization):
    root=Path(root).resolve();authorization=Path(authorization).resolve();a=verify_authorization(root,authorization)
    def jobs(plan,scale):
        if old.normalize_scale(scale)!=LABEL:raise ValueError('Only .7 successor authorized')
        selected=[j for j in ORIGINAL_JOBS(plan,scale) if j['job_id'] in set(a['pending_job_ids'])]
        if len(selected)!=EXPECTED_PENDING:raise ValueError('Allowlist does not match frozen plan')
        return selected
    def published(r,job,owner,scale,cap=16):
        verified=verify_authorization(r,authorization)
        if job['job_id'] not in verified['pending_job_ids']:raise ValueError('Refusing preexisting or out-of-scope prediction')
        return ORIGINAL_PUBLISH(r,job,owner,scale,cap)
    old.area=area;old.VERSION=VERSION;old.jobs_for_scale=jobs;old.verify_cutover=lambda r:verify_authorization(r,authorization);old.publish_claim=published
    return a


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=old.scientific.DEFAULT_ROOT);p.add_argument('--authorization',type=Path)
    p.add_argument('--concurrency',type=int,default=16);p.add_argument('--resume',action='store_true');p.add_argument('--live',action='store_true');p.add_argument('--prepare',action='store_true')
    p.add_argument('--describe',type=Path);p.add_argument('--get-workers',type=Path);args=p.parse_args();root=args.root.resolve()
    if not 1<=args.concurrency<=16:p.error('Concurrency must be1–16')
    auth=args.authorization or authorization_path(root)
    if args.prepare:
        if args.live or not args.describe or not args.get_workers:p.error('Prepare requires platform evidence and cannot be live')
        a=prepare(root,args.describe,args.get_workers);print(json.dumps({'prepared':True,'pending':len(a['pending_job_ids']),'authorization':str(authorization_path(root))}));return
    a=install(root,auth);old.scientific.validate(read(root/'plan.json'),root)
    if not args.live:print(json.dumps({'live':False,'version':VERSION,'pending_allowlist':len(a['pending_job_ids']),'interrupted_excluded':len(a['excluded_paid_interrupted_job_ids']),'slot_namespace':str(area(root)/'slots'/LABEL),'target':args.concurrency}));return
    if not args.resume:p.error('--resume required; existing claims never replayed')
    old.controller(root,LABEL,args.concurrency)

if __name__=='__main__':main()
