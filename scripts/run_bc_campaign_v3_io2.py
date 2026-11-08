#!/usr/bin/env python3
"""Explicit controller maintenance v2: frozen v3 functions; dispatch I/O-aware trial.

The main loop is copied from run_bc_campaign_v3.py with only the dispatched
trial filename and independent controller maintenance sidecar changed.
Original source validation, claims, slots and all scientific definitions remain.
"""
from run_bc_campaign_v3 import *
from run_bc_trial_v3_io2 import maintenance_record


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
    atomic(control/'maintenance.json', maintenance_record())
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
                    child=subprocess.Popen([sys.executable,str(ROOT/'scripts/run_bc_trial_v3_io2.py'),'--spec',str(jobdir/'spec.json'),'--out',str(attempt),'--live'],cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                children[job['job_id']]=child;launched+=1
        atomic(control/'status.json',{**owner,'updated_at':now(),'heartbeat_unix':time.time(),'launches':launched,
          'active_local':len(children),'selected_states':dict(states),'stop_dispatch':stopping,'drain_policy':'wait for active trials; never signal them'})
        if not children:
            if stopping or (args.limit is not None and launched>=args.limit) or not states.get('pending',0):break
        time.sleep(2)
    print(json.dumps({'controller_id':controller_id,'new_launches':launched,'drained':True,'stopped':stopping}),flush=True)


if __name__=='__main__':main()
