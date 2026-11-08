#!/usr/bin/env python3
"""Pending-only capacity1 dispatch with audited, hot-read operational concurrency.

Explicit cloud/local role; invalid policy pauses dispatch, never changes budgets
or signals running workers. Scientific validation and permanent claims remain.
"""
from run_bc_campaign_v3 import *
from run_bc_trial_v3_capacity1 import maintenance_record
import hashlib


class DispatchPolicy:
    def __init__(self,path,role,control=None):
        if role not in ('cloud','local'): raise ValueError('Explicit dispatch role required')
        self.path=Path(path);self.role=role;self.control=control;self.last=None;self.current=None
    def refresh(self):
        sha=None
        try:
            data=self.path.read_bytes();sha=hashlib.sha256(data).hexdigest();config=json.loads(data)
            ceiling=config.get('worker_ceiling_per_instance')
            cloud=config.get('active_workers_per_cloud_instance');local=config.get('local_target_workers')
            if ceiling!=32 or any(not isinstance(v,int) or isinstance(v,bool) or not 0<=v<=32 for v in (cloud,local)):
                raise ValueError('Operational concurrency must be integers 0..32 and approved ceiling32')
            decision={'valid':True,'target':cloud if self.role=='cloud' else local,'error_type':None,
                      'cloud_target':cloud,'local_target':local,'worker_ceiling':32}
        except (OSError,ValueError,TypeError,AttributeError) as exc:
            decision={'valid':False,'target':None,'error_type':type(exc).__name__,'worker_ceiling':32}
        fingerprint=(sha,decision['valid'],decision['target'],decision['error_type'])
        if fingerprint!=self.last:
            decision.update(decided_at=now(),config_sha256=sha,config_path=str(self.path),dispatch_role=self.role,
                            semantics='Only future dispatch; existing children drain naturally; invalid target remains unknown, never zero')
            if self.control is not None:
                atomic(self.control/'dispatch-decisions'/(str(time.time_ns())+'.json'),decision)
                atomic(self.control/'dispatch-policy.json',decision)
            self.last=fingerprint;self.current=decision
        return self.current


def can_dispatch(policy,active_count,stopping=False):
    return bool(not stopping and policy.get('valid') is True and active_count<policy['target'])


def retire_reserved(reserved):
    if reserved is None:return
    job,jobdir,slot,attempt=reserved
    atomic(attempt/'result.json',{'execution_version':VERSION,'job_id':job['job_id'],'status':'not_started',
           'failure_category':'controller_stop_before_spawn','finished_at':now(),'paid_calls':0,
           'slot_released':True,'unconfirmed_child_termination':[]})
    release_slot(slot)


def dispatch_loop(args,root,plan,selected,control,owner,controller_id,policy):
    stopping=False;children={};launched=0;reserved=None
    def stop(*unused):
        nonlocal stopping
        stopping=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    while True:
        if (root/'STOP').exists() or (ROOT/'outputs/PAUSED_BY_USER.json').exists():stopping=True
        for jid,child in list(children.items()):
            if child.poll() is not None:children.pop(jid)
        decision=policy.refresh()
        states=Counter(job_state(root/'jobs'/job['job_id']) for job in selected)
        if stopping and reserved is not None:retire_reserved(reserved);reserved=None
        if can_dispatch(decision,len(children),stopping) and (args.limit is None or launched<args.limit):
            if reserved is not None or states.get('pending',0):validate_sources(plan,root)
            candidates=[reserved[0]] if reserved is not None else selected
            for job in candidates:
                if stopping or (root/'STOP').exists() or (ROOT/'outputs/PAUSED_BY_USER.json').exists():stopping=True;break
                decision=policy.refresh()
                if not can_dispatch(decision,len(children),stopping) or (args.limit is not None and launched>=args.limit):break
                if reserved is None:
                    claimed=acquire_claim(root,job,{**owner,'controller_id':controller_id})
                    if claimed is None:continue
                    jobdir,slot=claimed;attempt=jobdir/'attempts/attempt_001';attempt.mkdir(parents=True)
                    spec={**job,'config_path':str(root/'experiment.json'),'campaign_root':str(root),
                          'plan_sha256':digest((root/'plan.json').read_bytes()),'cohort_sha256':plan['definition']['cohort_sha256'],
                          'slot_path':str(slot),'controller_id':controller_id}
                    atomic(jobdir/'spec.json',spec)
                    reserved=(job,jobdir,slot,attempt)
                # If policy changed after the permanent claim, hold this exact
                # reservation until allowed. Never unclaim it or silently retry.
                decision=policy.refresh()
                if not can_dispatch(decision,len(children),stopping):break
                if (root/'STOP').exists() or (ROOT/'outputs/PAUSED_BY_USER.json').exists():stopping=True;break
                _,jobdir,slot,attempt=reserved
                with (attempt/'launcher.log').open('a') as log:
                    if stopping:break
                    child=subprocess.Popen([sys.executable,str(ROOT/'scripts/run_bc_trial_v3_capacity1.py'),
                        '--spec',str(jobdir/'spec.json'),'--out',str(attempt),'--live'],cwd=ROOT,
                        stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                children[job['job_id']]=child;launched+=1;reserved=None
        if stopping and reserved is not None:retire_reserved(reserved);reserved=None
        atomic(control/'status.json',{**owner,'updated_at':now(),'heartbeat_unix':time.time(),'launches':launched,
            'active_local':len(children),'selected_states':dict(states),'stop_dispatch':stopping,
            'dispatch_paused':not decision['valid'] or decision['target']==0,'dispatch_policy':decision,'dispatch_role':args.dispatch_role,
            'initial_concurrency':args.concurrency,'target_concurrency':decision['target'],
            'reserved_not_started_job':reserved[0]['job_id'] if reserved else None,
            'drain_policy':'No worker signals; hot target applies only to new launches; permanent reserved claim held while policy pauses'})
        if not children and reserved is None:
            if stopping or (args.limit is not None and launched>=args.limit) or not states.get('pending',0):break
        time.sleep(2)
    return {'controller_id':controller_id,'new_launches':launched,'drained':True,'stopped':stopping}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root',type=Path,default=DEFAULT_ROOT)
    ap.add_argument('--config',type=Path,default=ROOT/'configs/experiment.v3.review.json')
    ap.add_argument('--harness',choices=HARNESSES,nargs='+',default=list(HARNESSES))
    ap.add_argument('--strategy',choices=STRATEGIES,nargs='+',default=list(STRATEGIES))
    ap.add_argument('--dispatch-role',required=True,choices=['cloud','local'])
    ap.add_argument('--dispatch-config',type=Path,default=ROOT/'configs/cloud-dispatch-ops-v3.json')
    ap.add_argument('--concurrency',type=int,default=1,help='Local controller pool; each harness/strategy cell also has a shared 32-slot cap')
    ap.add_argument('--limit',type=int,help='Maximum new launches this invocation (does not change plan)')
    ap.add_argument('--resume',action='store_true');ap.add_argument('--live',action='store_true')
    args=ap.parse_args()
    if not 1<=args.concurrency<=32 or (args.limit is not None and args.limit<1):ap.error('concurrency 1..32; positive limit')
    if args.dispatch_role=='cloud' and (len(args.harness)!=1 or len(args.strategy)!=1):
        ap.error('Cloud role requires exactly one explicit harness/strategy cell')
    initial_policy=DispatchPolicy(args.dispatch_config,args.dispatch_role).refresh()
    root=args.root.resolve();plan,cfg,existed=prepare(root,args.config.resolve())
    selected=[j for j in plan['jobs'] if j['harness'] in args.harness and j['strategy'] in args.strategy]
    print(json.dumps({'root':str(root),'planned_runs':3000,'selected_jobs':len(selected),'live':args.live,'launch_limit':args.limit,
      'initial_pool':args.concurrency,'dispatch_policy':initial_policy,'per_cell_cap':32,'resume_policy':'pending only; terminal, unknown and interrupted never retried'}),flush=True)
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
    atomic(control/'maintenance.json',{**maintenance_record(),
        'operational_controller':'capacity-ops-hot-policy-v1',
        'operational_controller_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'dispatch_role':args.dispatch_role,'dispatch_config':str(args.dispatch_config)})
    policy=DispatchPolicy(args.dispatch_config,args.dispatch_role,control)
    print(json.dumps(dispatch_loop(args,root,plan,selected,control,owner,controller_id,policy)),flush=True)


if __name__=='__main__':main()
