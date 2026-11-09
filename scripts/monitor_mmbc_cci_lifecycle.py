#!/usr/bin/env python3
"""Independent MMBC CCI lifecycle observer; no evaluation-code or marker changes."""
import argparse,fcntl,json,time,signal,hashlib
from pathlib import Path
from lab import ROOT
from run_bc_campaign_v3 import atomic,identity
from bc_route_runtime_v1 import immutable_json
from replace_sco_bc_v3_after_reader_ops import create_cli
from provision_mmbc_cci_v1 import RECEIPTS,MARKER,app_name
from run_mmbc100_campaign import DEFAULT_ROOT,METHODS
from monitor_rq3_cci7_lifecycle import read,require,same_identity,same_host,FIELDS

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def assess_local(root,uid,marker,strategy):
    root=Path(root).resolve();marker=Path(marker)
    if not marker.exists():return {'eligible':False,'reason':'launch_marker_absent_observe_only'}
    candidates=list((root/'runtime/nodes').glob('app-'+uid+'-*/'+strategy+'/bootstrap.json'))
    if not candidates:return {'eligible':False,'reason':'no_bootstrap_evidence_unknown_not_safe_to_stop'}
    require(len(candidates)==1,'Ambiguous node/epoch; no stop')
    bp=candidates[0];b=read(bp);ep=bp.parent/'exit.json'
    require(b.get('hostname','').startswith('app-'+uid+'-'),'Bootstrap host not bound to CCI UID')
    require(bp.parent.parent.name==b['hostname']+'-'+b.get('boot_id',''),'Node-directory identity mismatch')
    require(Path(b.get('campaign_root','/missing')).resolve()==root and b.get('strategy')==strategy,'Bootstrap scope mismatch')
    require(b.get('version')=='mmbc100-hermes-cci-bootstrap-v1','Unexpected bootstrap version')
    if not ep.exists():return {'eligible':False,'reason':'bootstrap_not_exited','bootstrap_path':str(bp)}
    e=read(ep)
    require(e.get('hostname')==b['hostname'] and e.get('boot_id')==b['boot_id'] and e.get('scale')==strategy,'Bootstrap exit identity mismatch')
    require(isinstance(e.get('finished_at_unix'),(int,float)) and e['finished_at_unix']>=b.get('started_at_unix',float('inf')),'Bootstrap exit predates current epoch')
    require(isinstance(e.get('bootstrap_exit_code'),int) and not isinstance(e['bootstrap_exit_code'],bool),'Unknown bootstrap exit')
    require(e.get('native_processes_signaled') is False,'Bootstrap native termination unknown')
    controllers=[]
    for p in (root/'controllers'/strategy).glob('*/maintenance.json'):
        m=read(p)
        if m.get('hostname')==b['hostname'] or (m.get('boot_id')==b['boot_id'] and m.get('pid_namespace')==b.get('pid_namespace')):
            controllers.append((p,m))
    claims=[]
    for p in (root/'jobs/hermes'/strategy).glob('*/claim/owner.json'):
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
    require(m.get('strategy')==strategy and m.get('controller_id')==mp.parent.name,'Controller scope/directory mismatch')
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
    for p in (root/'cells/hermes'/strategy/'slots').glob('*/owner.json'):
        if read(p).get('hostname')==b['hostname']:raise ValueError('Bound host still owns a scale slot')
    evidence.update(controller_maintenance_path=str(mp),controller_maintenance_sha256=sha(mp),controller_exit_path=str(xp),controller_exit_sha256=sha(xp),controller_identity={k:m[k]for k in FIELDS},owned_attempts=verified)
    return {'eligible':True,'reason':'bootstrap_and_exact_controller_exited_all_owned_native_confirmed_terminal','evidence':evidence,'owned_claims':len(claims),'controller_failed':e['controller_exit_code']!=0}

def query_app(name,invoke=create_cli):
    x=invoke([str(ROOT/'.tools/sco-tj/cli/sco'),'cci','apps','describe',name,'--workspace-name','rl','--profile','agentcontextlab-tj','-o','json'])
    require(x.get('returncode')==0,'CCI describe unavailable')
    d=json.loads(x['stdout']);require(d.get('name')==name and d.get('uid'),'Application identity unavailable');return d

def cycle(method,live=False,invoke=create_cli,receipts=RECEIPTS):
    name=app_name(method);directory=receipts/name;area=directory/'lifecycle';area.mkdir(parents=True,exist_ok=True)
    if not(directory/'response.json').exists():return {'method':method,'name':name,'state':'not_submitted'}
    response=read(directory/'response.json')
    require(response.get('state')=='submitted','Create outcome unknown/rejected; no auto cleanup')
    prepared=read(directory/'prepared.json');request=read(directory/'request.json')
    root=Path(prepared['root']).resolve();require(root==DEFAULT_ROOT.resolve(),'Unexpected MMBC root')
    require(request['name']==name and request['plan_sha256']==prepared['plan_sha256'] and sha(root/'plan.json')==prepared['plan_sha256'],'Deployment plan changed')
    require(sha(prepared['config_path'])==prepared['config_sha256'],'Deployment configuration changed')
    platform=query_app(name,invoke);uid=platform['uid'];binding=area/'binding.json'
    if binding.exists():
        bound=read(binding);require(bound['uid']==uid and bound['name']==name and bound['plan_sha256']==prepared['plan_sha256'],'Existing CCI UID/plan changed')
    else:
        # The successful create receipt precedes binding. Verify the actual
        # container entry/image before trusting a newly observed UID.
        import yaml
        cfg=yaml.safe_load(Path(prepared['config_path']).read_text());expected=cfg['template']['containers'][0];actual=platform['template']['containers'][0]
        require(actual['command']==expected['command'] and actual['image_path']==expected['image_path'],'Platform command/image differs from reviewed submission')
        immutable_json(binding,{'name':name,'uid':uid,'method':method,'plan_sha256':prepared['plan_sha256'],'config_sha256':prepared['config_sha256'],'created_at_unix':time.time()})
    row={'method':method,'name':name,'uid':uid,'platform_state':platform.get('state'),'ready_replicas':platform.get('ready_replicas'),'state':'watching','reported_active':None,'prediction_counts':None}
    for p in (root/'controllers'/method).glob('*/status.json'):
        s=read(p)
        if s.get('hostname','').startswith('app-'+uid+'-'):
            row.update(reported_active=s.get('active_local'),prediction_counts=s.get('states'),controller_heartbeat_unix=s.get('at'),controller_stop_dispatch=s.get('stop_dispatch'))
    if platform.get('state')in ('SUSPENDED','STOPPED'):return {**row,'state':'stopped'}
    if(area/'stop-request.json').exists():return {**row,'state':'stop_already_attempted_never_repeat'}
    assessment=assess_local(root,uid,Path(prepared['launch_marker']),method);row.update(reason=assessment['reason'],eligible=assessment['eligible'])
    if assessment['eligible']and live:
        latest=query_app(name,invoke);require(latest['uid']==uid,'CCI UID changed immediately before stop')
        assessment=assess_local(root,uid,Path(prepared['launch_marker']),method);require(assessment['eligible'],'Drain evidence changed')
        immutable_json(area/'stop-request.json',{'at':time.time(),'name':name,'uid':uid,'method':method,'plan_sha256':prepared['plan_sha256'],'evidence':assessment,'operator':identity(),'source_sha256':sha(__file__),'automatic_retry':False})
        answer=invoke([str(ROOT/'.tools/sco-tj/cli/sco'),'cci','apps','stop',name,'--workspace-name','rl','--profile','agentcontextlab-tj'])
        atomic(area/'stop-response.json',{**answer,'at':time.time()})
        row['state']='stop_submitted'if answer.get('returncode')==0 else'stop_unknown_or_rejected_no_retry'
    return row

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--methods',choices=METHODS,nargs='+',default=list(METHODS));p.add_argument('--watch',action='store_true');p.add_argument('--live',action='store_true');a=p.parse_args()
    if a.live and not a.watch:p.error('Only --watch --live permits cleanup')
    if len(set(a.methods))!=len(a.methods):p.error('Duplicate method')
    area=RECEIPTS/'lifecycle';area.mkdir(parents=True,exist_ok=True);lock=(area/'observer.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    atomic(area/'service.json',{**identity(),'methods':a.methods,'watch':a.watch,'live':a.live,'source_sha256':sha(__file__),'started_at_unix':time.time()})
    stopping=False
    def stop(*unused):
        nonlocal stopping;stopping=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    while not stopping:
        rows=[]
        for method in a.methods:
            try:row=cycle(method,a.live)
            except Exception as exc:row={'method':method,'state':'unknown_no_stop','error_type':type(exc).__name__,'reason':str(exc)}
            rows.append(row)
        result={'at':time.time(),'methods':rows,'live':a.live,'paid_model_calls':0,'definition':'Reported active counts are supervisor children, not simultaneous model requests. Lifecycle observer never publishes launch marker or retries predictions.'}
        atomic(area/'status.json',result)
        with(area/'history.jsonl').open('a')as f:f.write(json.dumps(result)+'\n')
        if not a.watch or all(r['state']=='stopped'for r in rows):break
        until=time.monotonic()+30
        while not stopping and time.monotonic()<until:time.sleep(.5)
    atomic(area/'exit.json',{'at':time.time(),'stopping':stopping,'identity':identity()})
if __name__=='__main__':main()
