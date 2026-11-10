#!/usr/bin/env python3
"""Independent bounded VERA retry shards; immutable attempts,16 workers per shard."""
import argparse,fcntl,json,os,signal,subprocess,sys,time,uuid
from collections import Counter
from pathlib import Path
from lab import ROOT,environment
from run_bc_campaign_v3 import atomic,identity,job_state,acquire_claim,release_slot,now,digest,owner_alive
from bc_route_runtime_v1 import immutable_json

VERSION='bounded-vera-retry-controller-v1'
CELL_CAP=48
SHARDS=3

def selected_jobs(plan,shard):
    if type(shard) is not int or not 0<=shard<SHARDS:raise ValueError('Shard must be0..2')
    d=plan['definition']
    if d.get('shards')!=SHARDS or d.get('per_cell_concurrency_cap')!=CELL_CAP:raise ValueError('Expected3shards and48globalslots')
    ids=set()
    for j in plan['jobs']:
        if (j.get('harness')!='hermes' or j.get('strategy')!='visual'
            or type(j.get('shard')) is not int or not 0<=j['shard']<SHARDS
            or j.get('bounded_visual_protocol')!='bounded-multimodal-pages-v1'
            or j['job_id'] in ids):raise ValueError('Invalid bounded retry job')
        ids.add(j['job_id'])
    return [j for j in plan['jobs'] if j['shard']==shard]


def acquire_lease(root,shard,owner):
    """Serialize owners; preserve stale leases and never recycle job claims."""
    p=Path(root)/'leases'/str(shard);p.mkdir(parents=True,exist_ok=True)
    lock=(p/'controller.lock').open('a')
    try:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        previous=p/'owner.json'
        if previous.exists():
            old=json.loads(previous.read_text());alive=owner_alive(old)
            run=Path(old['run_directory']).resolve()
            allowed=(Path(root)/'controllers'/str(shard)).resolve()
            if not run.is_relative_to(allowed):raise ValueError('Previous controller path outside shard')
            exit_path=run/'exit.json';done=json.loads(exit_path.read_text()) if exit_path.exists() else {}
            clean=done.get('controller_id')==old.get('controller_id') and done.get('drained') is True
            if alive is not False and not clean:raise ValueError('Previous controller may still run; no remote PID guessing')
            immutable_json(p/'history'/(old['controller_id']+'.json'),old)
        atomic(p/'owner.json',owner)
        return p,lock
    except BaseException:
        lock.close();raise

def publish_spec(root,job,owner,plan,acquire=acquire_claim):
    result=acquire(root,job,owner,cap=CELL_CAP)
    if result is None:return None
    jobdir,slot=result;attempt=jobdir/'attempts/attempt_001';attempt.mkdir(parents=True)
    spec={**job,'campaign_root':str(root),'config_path':str(root/'experiment.json'),'plan_sha256':digest((root/'plan.json').read_bytes()),'cohort_sha256':plan['definition']['cohort_sha256'],'slot_path':str(slot),'controller_id':owner['controller_id']}
    immutable_json(jobdir/'spec.json',spec)
    # The native trial independently repeats these checks before any API call.
    claim=json.loads((jobdir/'claim/owner.json').read_text());slot_owner=json.loads((slot/'owner.json').read_text())
    if any(o.get('controller_id')!=owner['controller_id']or o.get('job_id')!=job['job_id']for o in (claim,slot_owner)):raise ValueError('Incomplete/different claim ownership')
    if claim.get('slot')!=str(slot):raise ValueError('Claim slot differs')
    return jobdir,slot,attempt,spec

def controller(root,shard,concurrency=16,popen=subprocess.Popen,limit=None):
    if type(concurrency) is not int or not 1<=concurrency<=16 or limit is not None and (type(limit) is not int or limit<1):raise ValueError('Concurrency1..16 and positive optional limit required')
    from prepare_bounded_vera_retry_v1 import load_validate,validate_sources
    root=Path(root).resolve();plan,manifest=load_validate(root);jobs=selected_jobs(plan,shard)
    env,cfg=environment(ROOT,'hermes',root/'experiment.json')
    from review_execution import enforce
    enforce(cfg,env,root)
    own={**identity(),'controller_id':uuid.uuid4().hex,'shard':shard,'version':VERSION}
    run=root/'controllers'/str(shard)/own['controller_id'];own['run_directory']=str(run)
    lease,lease_lock=acquire_lease(root,shard,own);run.mkdir(parents=True)
    immutable_json(run/'maintenance.json',{**own,'plan_sha256':digest((root/'plan.json').read_bytes()),'source_sha256':digest(Path(__file__).read_bytes()),'target_concurrency':concurrency,'cell_cap':CELL_CAP,'trial_entry':'scripts/run_bounded_vera_trial_v1.py','pending_only':True})
    atomic(lease/'runtime.json',{'directory':str(run)})
    children={};reserved=None;stopping=False;failure=None;launched=0
    def stop(*unused):
        nonlocal stopping;stopping=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    def should_stop():return stopping or any(p.exists()for p in (root/'STOP',root/'stops'/str(shard),ROOT/'outputs/PAUSED_BY_USER.json'))
    def status(states=None):
        atomic(run/'status.json',{**own,'at':time.time(),'heartbeat_unix':time.time(),'active_local':len(children),'target_concurrency':concurrency,'launched':launched,'stop_dispatch':should_stop()or failure is not None,'reserved_not_started':reserved[3]['job_id']if reserved else None,'states':dict(Counter(states.values()))if states else None,'error_type':failure,'paid_process_retry':False})
    try:
        from preflight_bc_v3_web import preflight
        if not preflight(root,root/'experiment.json')['passed']:raise RuntimeError('Actual web readiness failed')
        while not should_stop():
            for jid,child in list(children.items()):
                if child.poll()is not None:children.pop(jid)
            states={j['job_id']:job_state(root/'jobs'/j['job_id'])for j in jobs};pending=[j for j in jobs if states[j['job_id']]=='pending']
            if pending and len(children)<concurrency:validate_sources(plan,root)
            for job in pending:
                if should_stop()or len(children)>=concurrency or limit is not None and launched>=limit:break
                reserved=publish_spec(root,job,own,plan)
                if reserved is None:continue
                jobdir,slot,attempt,spec=reserved
                if should_stop():break
                command=[sys.executable,str(ROOT/'scripts/run_bounded_vera_trial_v1.py'),'--spec',str(jobdir/'spec.json'),'--out',str(attempt),'--live']
                child_env=os.environ.copy();child_env.update({key:'1'for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS')})
                with (attempt/'launcher.log').open('a')as log:
                    if should_stop():break
                    child=popen(command,cwd=ROOT,env=child_env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                    children[job['job_id']]=child;reserved=None;launched+=1
                atomic(attempt/'controller-dispatched.json',{**own,'at':time.time(),'worker':identity(child.pid)})
            status(states)
            if not children and (not pending or limit is not None and launched>=limit):break
            time.sleep(3)
    except BaseException as exc:
        failure=type(exc).__name__;stopping=True
        try:atomic(run/'error.json',{**own,'at':time.time(),'error_type':failure,'action':'stop dispatch and naturally drain; no spawn retry'})
        except OSError:pass
    finally:
        while children:
            for jid,child in list(children.items()):
                if child.poll()is not None:children.pop(jid)
            try:status()
            except OSError:pass
            if children:time.sleep(3)
        if reserved:
            jobdir,slot,attempt,spec=reserved
            # Reserved but no Popen returned; preserve immutable zero-native result.
            if not (attempt/'worker-started.json').exists():
                atomic(attempt/'result.json',{'job_id':spec['job_id'],'status':'not_started','failure_category':'controller_stopped_before_native_launch','api_calls':0,'slot_released':True,'unconfirmed_child_termination':[],'score':None})
                release_slot(slot)
        atomic(run/'exit.json',{**own,'at':time.time(),'drained':not children,'stopped':stopping,'error_type':failure,'launched':launched})
        lease_lock.close()
    if failure:raise RuntimeError('Bounded retry controller exited after safe drain: '+failure)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,required=True);p.add_argument('--shard',type=int,required=True)
    p.add_argument('--concurrency',type=int,default=16);p.add_argument('--resume',action='store_true')
    p.add_argument('--live',action='store_true');p.add_argument('--limit',type=int);a=p.parse_args()
    if not 1<=a.concurrency<=16 or a.limit is not None and a.limit<1:p.error('Concurrency1..16, positive optional limit')
    from prepare_bounded_vera_retry_v1 import load_validate
    plan,manifest=load_validate(a.root.resolve());jobs=selected_jobs(plan,a.shard)
    if not a.live:print(json.dumps({'live':False,'shard':a.shard,'jobs':len(jobs),'concurrency':a.concurrency,'global_cap':CELL_CAP,'model_calls':0}));return
    if not a.resume:p.error('Explicit --resume required; never replays claims')
    controller(a.root,a.shard,a.concurrency,limit=a.limit)
if __name__=='__main__':main()
