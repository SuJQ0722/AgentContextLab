#!/usr/bin/env python3
"""One immutable MMBC Hermes method per controller; pending-only and16 shared slots."""
import argparse,json,os,signal,subprocess,sys,time,uuid
from collections import Counter
from pathlib import Path
from lab import ROOT,environment
from run_bc_campaign_v3 import atomic,identity,job_state,acquire_claim,release_slot,now,digest
from bc_route_runtime_v1 import immutable_json

DEFAULT_ROOT=ROOT/'outputs/campaigns/mmbc100-hermes-vanilla-v1'
METHODS=('visual',)
VERSION='mmbc100-hermes-vanilla-controller-v1'

def selected_jobs(plan,strategy):
    if strategy not in METHODS:raise ValueError('Only vanilla_visual with actual strategy visual is executable')
    jobs=[j for j in plan['jobs']if j['harness']=='hermes'and j['strategy']==strategy]
    if len(jobs)!=300 or len({j['job_id']for j in jobs})!=300:raise ValueError('Expected100 questions x3 repeats per method')
    if len(plan['jobs'])!=300 or any(j.get('method_label')!='vanilla_visual' for j in jobs):raise ValueError('Vanilla-only scope/method label required')
    return jobs

def acquire_lease(root,strategy,owner):
    p=Path(root)/'leases'/strategy;p.parent.mkdir(parents=True,exist_ok=True);p.mkdir()
    atomic(p/'owner.json',owner);return p

def publish_spec(root,job,owner,plan,acquire=acquire_claim):
    result=acquire(root,job,owner,cap=16)
    if result is None:return None
    jobdir,slot=result;attempt=jobdir/'attempts/attempt_001';attempt.mkdir(parents=True)
    spec={**job,'campaign_root':str(root),'config_path':str(root/'experiment.json'),'plan_sha256':digest((root/'plan.json').read_bytes()),'cohort_sha256':plan['definition']['cohort_sha256'],'slot_path':str(slot),'controller_id':owner['controller_id']}
    immutable_json(jobdir/'spec.json',spec)
    # The native trial independently repeats these checks before any API call.
    claim=json.loads((jobdir/'claim/owner.json').read_text());slot_owner=json.loads((slot/'owner.json').read_text())
    if any(o.get('controller_id')!=owner['controller_id']or o.get('job_id')!=job['job_id']for o in (claim,slot_owner)):raise ValueError('Incomplete/different claim ownership')
    if claim.get('slot')!=str(slot):raise ValueError('Claim slot differs')
    return jobdir,slot,attempt,spec

def controller(root,strategy,concurrency=16,popen=subprocess.Popen,limit=None):
    from prepare_mmbc_vanilla import load_validate,validate
    root=Path(root).resolve();plan,manifest=load_validate(root);jobs=selected_jobs(plan,strategy)
    env,cfg=environment(ROOT,'hermes',root/'experiment.json')
    from review_execution import enforce
    enforce(cfg,env,root)
    own={**identity(),'controller_id':uuid.uuid4().hex,'strategy':strategy,'method_label':'vanilla_visual','version':VERSION}
    lease=acquire_lease(root,strategy,own);run=root/'controllers'/strategy/own['controller_id'];run.mkdir(parents=True)
    immutable_json(run/'maintenance.json',{**own,'plan_sha256':digest((root/'plan.json').read_bytes()),'source_sha256':digest(Path(__file__).read_bytes()),'target_concurrency':concurrency,'cell_cap':16,'trial_entry':'scripts/run_mmbc_vanilla_trial.py','pending_only':True})
    atomic(lease/'runtime.json',{'directory':str(run)})
    children={};reserved=None;stopping=False;failure=None;launched=0
    def stop(*unused):
        nonlocal stopping;stopping=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    def should_stop():return stopping or any(p.exists()for p in (root/'STOP',root/'stops'/strategy,ROOT/'outputs/PAUSED_BY_USER.json'))
    def status(states=None):
        atomic(run/'status.json',{**own,'at':time.time(),'heartbeat_unix':time.time(),'active_local':len(children),'target_concurrency':concurrency,'launched':launched,'stop_dispatch':should_stop()or failure is not None,'reserved_not_started':reserved[3]['job_id']if reserved else None,'states':dict(Counter(states.values()))if states else None,'error_type':failure,'paid_process_retry':False})
    try:
        from preflight_bc_v3_web import preflight
        if not preflight(root,root/'experiment.json')['passed']:raise RuntimeError('Actual web readiness failed')
        while not should_stop():
            for jid,child in list(children.items()):
                if child.poll()is not None:children.pop(jid)
            states={j['job_id']:job_state(root/'jobs'/j['job_id'])for j in jobs};pending=[j for j in jobs if states[j['job_id']]=='pending']
            if pending and len(children)<concurrency:validate(plan,root)
            for job in pending:
                if should_stop()or len(children)>=concurrency or limit is not None and launched>=limit:break
                reserved=publish_spec(root,job,own,plan)
                if reserved is None:continue
                jobdir,slot,attempt,spec=reserved
                if should_stop():break
                command=[sys.executable,str(ROOT/'scripts/run_mmbc_vanilla_trial.py'),'--spec',str(jobdir/'spec.json'),'--out',str(attempt),'--live']
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
    if failure:raise RuntimeError('MMBC controller exited after safe drain: '+failure)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=DEFAULT_ROOT);p.add_argument('--strategy',choices=METHODS,required=True);p.add_argument('--concurrency',type=int,default=16);p.add_argument('--resume',action='store_true');p.add_argument('--live',action='store_true');p.add_argument('--limit',type=int);a=p.parse_args()
    if not 1<=a.concurrency<=16 or a.limit is not None and a.limit<1:p.error('Concurrency1..16, positive optional limit')
    from prepare_mmbc_vanilla import load_validate
    plan,manifest=load_validate(a.root.resolve());selected_jobs(plan,a.strategy)
    if not a.live:print(json.dumps({'live':False,'strategy':a.strategy,'jobs':300,'concurrency':a.concurrency,'model_calls':0}));return
    if not a.resume:p.error('Explicit --resume required; never replays claims')
    controller(a.root,a.strategy,a.concurrency,limit=a.limit)
if __name__=='__main__':main()
