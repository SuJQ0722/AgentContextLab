#!/usr/bin/env python3
"""Observe one CCI .7 allocation; stop it once only after verified native drain.

No evaluation/model call, launch marker publication, retry, or other-resource action.
Both --watch and --live are required for an official CCI stop.
"""
import argparse,fcntl,json,time,signal
from pathlib import Path
from lab import ROOT
from run_bc_campaign_v3 import atomic,identity
from bc_route_runtime_v1 import immutable_json
from replace_sco_bc_v3_after_reader_ops import create_cli
from run_rq3_parity_v3 import sha

NAME='acl-rq3-s0700-cci7'
UID='292054d96de64ffa8fbee96e4cb94de9'
CAMPAIGN=ROOT/'outputs/campaigns/rq3-deepseek-bc100-r3-parity-v3'
RECEIPT=ROOT/'outputs/cloud-runtime/rq3-resume-ops5/cci7'
MARKER=RECEIPT.parent/'launch-cloud-ready-ops7.json'
FIELDS=('hostname','boot_id','pid_namespace','controller_id','pid','start_identity')

def read(p):return json.loads(Path(p).read_text())
def require(condition,message):
    if not condition:raise ValueError(message)
def same_identity(a,b):
    return all(a.get(k) is not None and a.get(k)==b.get(k) for k in FIELDS)
def same_host(a,b):
    return all(a.get(k) and a.get(k)==b.get(k)for k in ('hostname','boot_id','pid_namespace'))
def assess_local(root,uid,marker):
    root=Path(root).resolve();marker=Path(marker)
    if not marker.exists():return {'eligible':False,'reason':'launch_marker_absent_observe_only'}
    candidates=list((root/'runtime/nodes').glob('app-'+uid+'-*/scale_0700/bootstrap.json'))
    if not candidates:return {'eligible':False,'reason':'no_bootstrap_evidence_unknown_not_safe_to_stop'}
    require(len(candidates)==1,'Ambiguous node/epoch; no stop')
    bp=candidates[0];b=read(bp);ep=bp.parent/'exit.json'
    require(b.get('hostname','').startswith('app-'+uid+'-'),'Bootstrap host not bound to CCI UID')
    require(bp.parent.parent.name==b['hostname']+'-'+b.get('boot_id',''),'Node-directory identity mismatch')
    require(Path(b.get('campaign_root','/missing')).resolve()==root and b.get('scale_label')=='scale_0700','Bootstrap scope mismatch')
    require(b.get('version')=='rq3-scale0700-bootstrap-ops5','Unexpected bootstrap version')
    if not ep.exists():return {'eligible':False,'reason':'bootstrap_not_exited','bootstrap_path':str(bp)}
    e=read(ep)
    require(e.get('hostname')==b['hostname'] and e.get('boot_id')==b['boot_id'] and e.get('scale')=='scale_0700','Bootstrap exit identity mismatch')
    require(isinstance(e.get('finished_at_unix'),(int,float)) and e['finished_at_unix']>=b.get('started_at_unix',float('inf')),'Bootstrap exit predates current epoch')
    require(isinstance(e.get('bootstrap_exit_code'),int) and not isinstance(e['bootstrap_exit_code'],bool),'Unknown bootstrap exit')
    require(e.get('native_processes_signaled') is False,'Bootstrap native termination unknown')
    controllers=[]
    for p in (root/'cloud-scale-ops5/controllers/scale_0700').glob('*/maintenance.json'):
        m=read(p)
        if m.get('hostname')==b['hostname'] or (m.get('boot_id')==b['boot_id'] and m.get('pid_namespace')==b.get('pid_namespace')):
            controllers.append((p,m))
    claims=[]
    for p in (root/'jobs/hermes/scale_0700').glob('*/claim/owner.json'):
        o=read(p)
        if o.get('hostname')==b['hostname']:claims.append((p,o))
    evidence={'bootstrap_path':str(bp),'bootstrap_sha256':sha(bp),'bootstrap_exit_path':str(ep),'bootstrap_exit_sha256':sha(ep),'hostname':b['hostname'],'boot_id':b['boot_id'],'pid_namespace':b.get('pid_namespace')}
    if b.get('controller_pid') is None:
        require(e.get('controller_exit_code') is None and e['bootstrap_exit_code']!=0,'No proven pre-controller failure')
        require(not controllers and not claims,'Controller/claim evidence exists despite pre-controller failure')
        return {'eligible':True,'reason':'bootstrap_failed_before_controller_no_native_claims','evidence':evidence,'owned_claims':0,'failure_recorded':True}
    require(len(controllers)==1,'Exactly one bound controller required')
    mp,m=controllers[0]
    require(same_host(m,b) and m.get('pid')==b['controller_pid'],'Controller and bootstrap identities differ')
    require(m.get('scale')=='scale_0700' and m.get('controller_id')==mp.parent.name,'Controller scope/directory mismatch')
    xp=mp.parent/'exit.json'
    if not xp.exists():return {'eligible':False,'reason':'controller_exit_missing','evidence':evidence}
    x=read(xp)
    require(same_identity(m,x),'Controller exit identity mismatch')
    require(x.get('drained') is True,'Controller not drained')
    require(isinstance(e.get('controller_exit_code'),int),'Controller exit code unknown')
    require(isinstance(x.get('at'),(int,float)) and b['started_at_unix']<=x['at']<=e['finished_at_unix'],'Controller exit outside bootstrap epoch')
    # A stale pre-exit status may still say >0; the terminal drain proof and all
    # owned attempts are authoritative. A newer nonzero status is contradictory.
    sp=mp.parent/'status.json'
    if sp.exists():
        s=read(sp);require(same_identity(m,s),'Controller status identity mismatch')
        require(not (s.get('at',0)>x['at'] and (s.get('active_local',0)!=0 or s.get('reserved_not_started'))),'Post-exit controller activity')
    verified=[]
    for cp,o in claims:
        require(same_identity(m,o),'Another controller/epoch owns claims on bound host')
        jobdir=cp.parent.parent;attempt=jobdir/'attempts/attempt_001';rp=attempt/'result.json'
        require(rp.exists(),'Owned attempt lacks terminal result')
        r=read(rp)
        require(r.get('job_id')==o.get('job_id'),'Result/claim job mismatch')
        require(r.get('status') in ('completed','failed','timeout','interrupted','not_started'),'Unknown/nonterminal prediction')
        require(r.get('slot_released') is True and r.get('unconfirmed_child_termination')==[],'Native child termination unconfirmed')
        verified.append({'job_id':o['job_id'],'result_path':str(rp),'result_sha256':sha(rp),'claim_sha256':sha(cp)})
    require(isinstance(x.get('launched'),int) and len(claims)>=x['launched'],'Claim coverage below controller launches')
    # No surviving owned slot may hide an unaccounted native task.
    for p in (root/'cloud-scale-ops5/slots/scale_0700').glob('*/owner.json'):
        if read(p).get('hostname')==b['hostname']:raise ValueError('Bound host still owns a scale slot')
    evidence.update(controller_maintenance_path=str(mp),controller_maintenance_sha256=sha(mp),controller_exit_path=str(xp),controller_exit_sha256=sha(xp),controller_identity={k:m[k]for k in FIELDS},owned_attempts=verified)
    return {'eligible':True,'reason':'bootstrap_and_exact_controller_exited_all_owned_native_confirmed_terminal','evidence':evidence,'owned_claims':len(claims),'controller_failed':e['controller_exit_code']!=0}

def describe(invoke=create_cli):
    value=invoke([str(ROOT/'.tools/sco-tj/cli/sco'),'cci','apps','describe',NAME,'--workspace-name','rl','--profile','agentcontextlab-tj','-o','json'])
    require(value.get('returncode')==0,'CCI describe failed')
    d=json.loads(value['stdout']);require(d.get('name')==NAME and d.get('uid')==UID,'Platform name/UID mismatch')
    return {k:d.get(k)for k in ('name','uid','state','ready_replicas','replicas','update_time')}

def cycle(area,root=CAMPAIGN,marker=MARKER,live=False,invoke=create_cli):
    platform=describe(invoke);state={'at':time.time(),'platform':platform,'live':live,'paid_model_calls':0}
    request=area/'stop-request.json'
    if request.exists():
        recorded=read(request);require(recorded.get('uid')==UID and recorded.get('name')==NAME,'Stop receipt scope mismatch')
        return {**state,'state':'already_stopped'if platform['state']in ('STOPPED','SUSPENDED')else'stop_already_attempted_never_repeat','stop_attempted':True}
    if platform['state']in ('STOPPED','SUSPENDED'):return {**state,'state':'already_stopped','stop_attempted':False}
    assessment=assess_local(root,UID,marker);state.update(assessment,state='eligible'if assessment['eligible']else'watching')
    if assessment['eligible'] and live:
        # Recheck both platform identity and complete local proofs immediately
        # before the only mutation. Atomic request publication owns the stop.
        describe(invoke);assessment=assess_local(root,UID,marker);require(assessment['eligible'],'Stop evidence changed')
        immutable_json(request,{'at':time.time(),'name':NAME,'uid':UID,'assessment':assessment,'operator':identity(),'source_sha256':sha(__file__),'operation':'stop','automatic_retry':False})
        response=invoke([str(ROOT/'.tools/sco-tj/cli/sco'),'cci','apps','stop',NAME,'--workspace-name','rl','--profile','agentcontextlab-tj'])
        atomic(area/'stop-response.json',{**response,'at':time.time(),'name':NAME,'uid':UID})
        state.update(state='stop_submitted'if response.get('returncode')==0 else'stop_unknown_or_rejected_no_retry',stop_attempted=True)
    return state

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--watch',action='store_true');p.add_argument('--live',action='store_true');a=p.parse_args()
    if a.live and not a.watch:p.error('Only --watch --live permits the one CCI stop')
    area=RECEIPT/'lifecycle';area.mkdir(parents=True,exist_ok=True)
    lock=(area/'observer.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    binding={'name':NAME,'uid':UID,'campaign_root':str(CAMPAIGN),'launch_marker':str(MARKER),'source_sha256':sha(__file__)}
    if (area/'binding.json').exists():require(read(area/'binding.json')==binding,'Observer binding changed')
    else:immutable_json(area/'binding.json',binding)
    atomic(area/'service.json',{**binding,**identity(),'watch':a.watch,'live':a.live,'started_at_unix':time.time()})
    stopping=False
    def stop(*unused):
        nonlocal stopping;stopping=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    while not stopping:
        try:row=cycle(area,live=a.live)
        except Exception as exc:row={'at':time.time(),'state':'blocked_unknown_no_stop','error_type':type(exc).__name__,'reason':str(exc),'live':a.live,'paid_model_calls':0}
        atomic(area/'status.json',row)
        with (area/'history.jsonl').open('a')as f:f.write(json.dumps(row)+'\n')
        print(json.dumps({k:row.get(k)for k in ('at','state','reason')}),flush=True)
        if not a.watch or row.get('state')=='already_stopped':break
        until=time.monotonic()+30
        while not stopping and time.monotonic()<until:time.sleep(.5)
    atomic(area/'observer-exit.json',{'at':time.time(),'stopping':stopping,'identity':identity()})
if __name__=='__main__':main()
