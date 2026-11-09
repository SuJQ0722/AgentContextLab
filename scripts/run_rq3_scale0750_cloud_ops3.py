#!/usr/bin/env python3
"""Only the explicitly authorized new .75 cohort; no replay of six placeholder scales."""
import argparse
from collections import Counter
import errno
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import traceback
import uuid
import run_rq3_parity_v3 as scientific
import prepare_rq3_scale0750_v1 as scope
from run_bc_campaign_v3 import atomic,identity,release_slot
from bc_route_runtime_v2 import immutable_json
from lab import ROOT

VERSION='rq3-scale0750-cloud-dispatch-ops3'
LABEL_TO_SCALE={'scale_0750':.75}


def normalize_scale(value):
    if isinstance(value,str) and value in LABEL_TO_SCALE:return value
    try:number=float(value)
    except (TypeError,ValueError):raise argparse.ArgumentTypeError('Expected one of the authorized .75 scale')
    for label,scale in LABEL_TO_SCALE.items():
        if number==scale:return label
    raise argparse.ArgumentTypeError('Only scale_0750/.75 is executable in this scope')


def area(root):return Path(root)/'cloud-scale-ops3'


def verify_scope(root,full=True):
    plan,manifest=scope.validate_scope(root,full=full)
    if manifest.get('trial_entry')!='scripts/run_rq3_scale0750_trial.py' or manifest.get('native_entry')!='scripts/rq3_scale0750_worker.py':
        raise ValueError('Wrong explicit .75 native/trial entry')
    return manifest


def verify_launch(root,manifest=None):
    root=Path(root).resolve();manifest=manifest or verify_scope(root)
    record=scientific.read(area(root)/'launch.json')
    if record.get('version')!='rq3-scale0750-cloud-launch-ops3' or record.get('launch_authorized') is not True:
        raise ValueError('Explicit .75 cloud launch authorization is missing')
    expected={'campaign_root':str(root),'plan_sha256':scientific.sha(root/'plan.json'),
        'scope_sha256':scientific.sha(root/scope.MANIFEST),'authorized_job_ids_sha256':manifest['authorized_job_ids_sha256'],
        'allowed_scale':'scale_0750','max_concurrency':16}
    if any(record.get(key)!=value for key,value in expected.items()):raise ValueError('Launch authorization differs from the exact .75 scope')
    return record


def jobs_for_scale(plan,scale):
    label=normalize_scale(scale);value=LABEL_TO_SCALE[label]
    jobs=[j for j in plan['jobs'] if j.get('scale')==value]
    if len(jobs)!=300 or len({j['job_id'] for j in jobs})!=300:raise ValueError('Each scale must contain exactly 100 x three frozen jobs')
    for job in jobs:
        if job.get('harness')!='hermes' or job.get('strategy')!='visual' or job['job_id'].split('/')[1]!=label:
            raise ValueError('Scale selection may not change strategy or harness')
    return jobs


def eligible(jobdir):
    jobdir=Path(jobdir)
    # A partially published specification/staging directory is uncertain, even
    # without a canonical claim, and is never treated as fresh work.
    return not any((jobdir/name).exists() for name in ('claim','attempts','spec.json')) and not any(jobdir.glob('.claim-staging-*'))


def safe_terminal(attempt):
    path=attempt/'result.json'
    if not path.exists():return False
    result=scientific.read(path)
    return result.get('status') in ('completed','failed','timeout','interrupted','not_started') and result.get('slot_released') is True and result.get('unconfirmed_child_termination')==[]


def scale_capacity(root,scale,jobs=None):
    root=Path(root).resolve();label=normalize_scale(scale)
    if jobs is None:jobs=jobs_for_scale(scientific.read(root/'plan.json'),label)
    slots=area(root)/'slots'/label;occupied={p.resolve() for p in slots.glob('[0-9][0-9]') if p.is_dir()}
    legacy=[];states=Counter();pending=[]
    for job in jobs:
        directory=root/'jobs'/job['job_id'];attempt=directory/'attempts/attempt_001'
        if safe_terminal(attempt):states['terminal_confirmed']+=1;continue
        if eligible(directory):pending.append(job);states['pending']+=1;continue
        owner_path=directory/'claim/owner.json';owner=scientific.read(owner_path) if owner_path.exists() else {}
        own_slot=Path(owner.get('slot','/missing')).resolve()
        if own_slot in occupied and own_slot.parent==slots.resolve():states['cloud_claimed_or_inflight']+=1
        else:legacy.append(job['job_id']);states['legacy_inflight_or_unknown']+=1
    return {'scale':label,'legacy_reserved':len(legacy),'legacy_job_ids':legacy,'occupied_cloud_slots':len(occupied),
            'reserved_total':len(legacy)+len(occupied),'states':dict(states),'pending_jobs':pending}


def acquire_scale_slot(root,scale,owner,job_id,cap=16):
    """Path|None; shared by cloud dispatch and explicit zero-API recoveries.

    Restrict usable indices to cap minus predecessor reservations. Concurrent
    claimants cannot both fill the last free position while older workers drain.
    Old unknowns remain reserved until a confirmed terminal cleanup record.
    """
    if not 1<=cap<=16:raise ValueError('Scale cap must be 1–16')
    root=Path(root).resolve();label=normalize_scale(scale);manifest=verify_scope(root,full=False)
    if job_id not in manifest['authorized_job_ids']:raise ValueError('Slot job outside authorized .75 IDs')
    inventory=scale_capacity(root,label)
    if inventory['reserved_total']>=cap:return None
    slots=area(root)/'slots'/label;slots.mkdir(parents=True,exist_ok=True)
    for i in range(max(0,cap-inventory['legacy_reserved'])):
        slot=slots/f'{i:02}'
        try:slot.mkdir()
        except FileExistsError:continue
        atomic(slot/'owner.json',{**owner,'job_id':job_id,'scale':label,'version':VERSION,'claimed_at_unix':time.time()})
        return slot
    return None


def publish_claim(root,job,owner,scale,cap=16):
    root=Path(root).resolve();label=normalize_scale(scale)
    if job.get('scale')!=LABEL_TO_SCALE[label] or job.get('strategy')!='visual' or job.get('harness')!='hermes':raise ValueError('Cross-scale claim prohibited')
    manifest=verify_scope(root,full=False)
    if job['job_id'] not in manifest['authorized_job_ids']:raise ValueError('Job is outside authorized .75 IDs')
    scope.validate_authorized_spec({**job,'campaign_root':str(root),'plan_sha256':manifest['plan_sha256']})
    directory=root/'jobs'/job['job_id'];directory.mkdir(parents=True,exist_ok=True)
    if not eligible(directory):return None
    slot=acquire_scale_slot(root,label,owner,job['job_id'],cap)
    if slot is None:return None
    spec={**job,'campaign_root':str(root),'plan_sha256':scientific.sha(root/'plan.json'),
          'cohort_sha256':scientific.read(root/'plan.json')['definition']['cohort_sha256'],
          'slot_path':str(slot),'controller_id':owner['controller_id']}
    staging=directory/('.claim-staging-'+uuid.uuid4().hex);staging.mkdir()
    record={**owner,'job_id':job['job_id'],'slot':str(slot),'scale':label,'version':VERSION,'claimed_at_unix':time.time()}
    atomic(staging/'owner.json',record);atomic(staging/'spec.json',spec)
    try:os.rename(staging,directory/'claim')
    except OSError as error:
        # Only a complete competing claim is a known race; otherwise preserve
        # staging and slot evidence for explicit review.
        if error.errno not in (errno.EEXIST,errno.ENOTEMPTY) or not (directory/'claim/owner.json').exists():raise
        (staging/'owner.json').unlink();(staging/'spec.json').unlink();staging.rmdir();release_slot(slot);return None
    immutable_json(directory/'spec.json',spec)
    attempt=directory/'attempts/attempt_001';attempt.mkdir(parents=True)
    return directory,slot,attempt,spec


def verify_published(spec,directory):
    # Metadata visibility/ownership only. The untouched native trial performs
    # its complete scientific source validation before any model execution.
    from bc_claim_publication_io3 import wait_for_owned_metadata
    wait_for_owned_metadata(spec)
    if scientific.read(directory/'spec.json')!=spec:raise ValueError('Published specification changed')
    claim=scientific.read(directory/'claim/owner.json');slot=scientific.read(Path(spec['slot_path'])/'owner.json')
    if claim.get('slot')!=spec['slot_path']:raise ValueError('Published claim slot mismatch')
    for record in (claim,slot):
        if record.get('job_id')!=spec['job_id'] or record.get('controller_id')!=spec['controller_id']:
            raise ValueError('Published owner mismatch')


def acquire_lease(root,scale,owner):
    path=area(root)/'leases'/normalize_scale(scale);path.parent.mkdir(parents=True,exist_ok=True)
    try:path.mkdir()
    except FileExistsError:raise ValueError('Scale has a permanent controller lease; no automatic stale takeover')
    atomic(path/'owner.json',owner);return path


def error_record(error):
    return {'type':type(error).__name__,'errno':getattr(error,'errno',None),
            'frames':[{'file':f.filename,'line':f.lineno,'function':f.name} for f in traceback.extract_tb(error.__traceback__)]}


def drain_children(children,on_status=None,sleep=time.sleep):
    """Never signals or retries workers, including after a controller exception."""
    while children:
        for jid,child in list(children.items()):
            if child.poll() is not None:children.pop(jid)
        if on_status:
            try:on_status(len(children))
            except OSError:pass  # A status-file problem must not abandon live workers.
        if children:sleep(3)


def controller(root,scale,concurrency=16,popen=subprocess.Popen):
    root=Path(root).resolve();label=normalize_scale(scale);plan=scientific.read(root/'plan.json')
    manifest=verify_scope(root);verify_launch(root,manifest);jobs=jobs_for_scale(plan,label)
    if [j['job_id'] for j in jobs]!=manifest['authorized_job_ids']:raise ValueError('Dispatch jobs differ from authorized .75 IDs')
    owner={**identity(),'controller_id':uuid.uuid4().hex,'scale':label,'version':VERSION}
    lease=acquire_lease(root,label,owner);run=area(root)/'controllers'/label/owner['controller_id'];run.mkdir(parents=True)
    maintenance={**owner,'scientific_plan_sha256':scientific.sha(root/'plan.json'),'scope_sha256':scientific.sha(root/scope.MANIFEST),'launch_sha256':scientific.sha(area(root)/'launch.json'),'scope_version':scope.VERSION,
        'controller_source_path':str(Path(__file__).resolve()),'controller_source_sha256':scientific.sha(__file__),
        'target_concurrency':concurrency,'ceiling_per_scale':16,'lease_path':str(lease),
        'trial_entry':'scripts/run_rq3_scale0750_trial.py','native_entry':'scripts/rq3_scale0750_worker.py',
        'scientific_change':True,'scope_only_revision':'Explicit .75 replacement; six unchanged scales are placeholders and forbidden here','claim_policy':'Pending only; no prior claim/attempt/spec/staging replay; independent per-scale slots reserve predecessors'}
    immutable_json(run/'maintenance.json',maintenance);atomic(lease/'runtime.json',{'directory':str(run),'maintenance_sha256':scientific.sha(run/'maintenance.json')})
    children={};reserved=None;stopping=False;error=None;launched=0;last_inventory={}
    def stop(*unused):
        nonlocal stopping
        stopping=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    def should_stop():return stopping or any(p.exists() for p in [root/'STOP',area(root)/'STOP',area(root)/'stops'/label,ROOT/'outputs/PAUSED_BY_USER.json'])
    def status(n=None):
        atomic(run/'status.json',{**owner,'at':time.time(),'active_local':len(children) if n is None else n,'launched':launched,
            'target_concurrency':concurrency,'stop_dispatch':should_stop() or error is not None,'error':error,
            'reserved_not_started':reserved[3]['job_id'] if reserved else None,'capacity':last_inventory,
            'maintenance_path':str(run/'maintenance.json'),'paid_process_retry':False})
    try:
        from preflight_bc_v3_web import preflight
        if should_stop():return
        if not preflight(root,root/'experiment.json')['passed']:raise RuntimeError('Host actual web readiness failed before native dispatch')
        while True:
            for jid,child in list(children.items()):
                if child.poll() is not None:children.pop(jid)
            inventory=scale_capacity(root,label,jobs);last_inventory={k:v for k,v in inventory.items() if k!='pending_jobs'}
            if should_stop():stopping=True;break
            if inventory['pending_jobs'] and inventory['reserved_total']<concurrency and len(children)<concurrency:
                verify_scope(root)  # Full frozen scientific source/scope guard before each dispatch round.
            for job in inventory['pending_jobs']:
                if should_stop() or len(children)>=concurrency or inventory['reserved_total']>=concurrency:break
                if scientific.sha(__file__)!=maintenance['controller_source_sha256']:raise ValueError('Operational controller source changed after launch')
                if scientific.sha(area(root)/'launch.json')!=maintenance['launch_sha256'] or scientific.sha(root/scope.MANIFEST)!=maintenance['scope_sha256']:raise ValueError('Scope or launch authorization changed after launch')
                if should_stop():break
                reserved=publish_claim(root,job,owner,label,concurrency)
                if reserved is None:break
                directory,slot,attempt,spec=reserved
                immutable_json(attempt/'cloud-scale-dispatch-ops3.json',maintenance)
                verify_published(spec,directory)
                if should_stop():break
                command=[sys.executable,str(ROOT/'scripts/run_rq3_scale0750_trial.py'),'--spec',str(directory/'spec.json'),'--out',str(attempt),'--live']
                env=os.environ.copy();env.update({k:'1' for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS')})
                with (attempt/'launcher.log').open('a') as stream:
                    if should_stop():break
                    child=popen(command,cwd=ROOT,env=env,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
                    # Track before closing the log handle or any other fallible bookkeeping.
                    children[job['job_id']]=child;reserved=None;launched+=1
                atomic(attempt/'controller-dispatched.json',{**owner,'at':time.time(),'worker':identity(child.pid)})
            status()
            if should_stop():stopping=True;break
            if not children and not inventory['pending_jobs']:break
            time.sleep(3)
    except BaseException as exc:
        error=error_record(exc);stopping=True
        try:atomic(run/'error.json',{**owner,'at':time.time(),'error':error,'spawn_retried':False})
        except OSError:pass
    finally:
        # All exceptions and signals wait for the original deadline supervisor;
        # the cloud bootstrap must not see an exit while paid workers remain.
        drain_children(children,lambda n:status(n))
        if reserved:
            directory,slot,attempt,spec=reserved
            atomic(attempt/'result.json',{'job_id':spec['job_id'],'status':'not_started','failure_category':'cloud_controller_stopped_before_native_launch',
                'slot_released':True,'unconfirmed_child_termination':[],'score':None,'model':spec['model'],'api_calls':0})
            release_slot(slot)
        atomic(run/'exit.json',{**owner,'at':time.time(),'drained':not children,'stopped':stopping,'error':error,'launched':launched})
    if error:raise RuntimeError('RQ3 cloud controller stopped after draining; see error.json for sanitized frames')


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--root',type=Path,default=scope.DEFAULT_ROOT)
    ap.add_argument('--scale',type=normalize_scale,choices=tuple(LABEL_TO_SCALE),required=True)
    ap.add_argument('--concurrency',type=int,default=16);ap.add_argument('--resume',action='store_true');ap.add_argument('--live',action='store_true');args=ap.parse_args()
    if not 1<=args.concurrency<=16:ap.error('Concurrency must be 1–16 per resolution')
    root=args.root.resolve();plan=scientific.read(root/'plan.json');manifest=verify_scope(root);jobs=jobs_for_scale(plan,args.scale)
    if [j['job_id'] for j in jobs]!=manifest['authorized_job_ids']:raise ValueError('Unauthorized placeholder selection')
    if not args.live:
        print(json.dumps({'live':False,'version':VERSION,'scale':args.scale,'jobs':len(jobs),'target':args.concurrency,
            'scientific_plan_sha256':scientific.sha(root/'plan.json'),'independent_scale_capacity':True}));return
    if not args.resume:ap.error('--resume is required; only unclaimed pending work is eligible')
    controller(root,args.scale,args.concurrency)


if __name__=='__main__':main()
