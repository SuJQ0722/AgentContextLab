"""Observe two controlled CCIs; stop only after exact node/controller drain proof."""
import argparse
from collections import Counter
import fcntl
import json
from pathlib import Path
import time
import yaml
from provision_controlled_source_v20 import DEFAULT, OUT, METHODS, bind, read, sha, require
from bc_route_runtime_v1 import immutable_json
from controlled_mmbc_source_v17 import save
from replace_sco_bc_v3_after_reader_ops import create_cli
from lab import ROOT


def assess(method,uid):
    paths=list((DEFAULT/'runtime/nodes').glob('app-'+uid+'-*/'+method+'/bootstrap.json'))
    if not paths:return {'eligible':False,'reason':'bootstrap_not_observed'}
    require(len(paths)==1,'Ambiguous bootstrap epoch')
    bp=paths[0];b=read(bp);ep=bp.parent/'exit.json'
    require(b['version']=='controlled-source-bootstrap-v20' and b['method']==method,'Wrong bootstrap scope')
    require(b['plan_sha256']==sha(DEFAULT/'plan.json'),'Bootstrap plan changed')
    if not ep.exists():return {'eligible':False,'reason':'bootstrap_running'}
    e=read(ep);require(e['hostname']==b['hostname'] and e['boot_id']==b['boot_id'] and e['scale']==method,'Exit identity differs')
    require(e['finished_at_unix']>=b['started_at_unix'] and e['native_processes_signaled'] is False,'Unknown native exit')
    jobs=[j for j in read(DEFAULT/'plan.json')['jobs']if j['method']==method]
    status_path=DEFAULT/'cells'/method/'status.json'
    if b.get('controller_pid') is None:
        require(e['controller_exit_code'] is None and e['bootstrap_exit_code']!=0,'Unproven pre-controller failure')
        require(not status_path.exists() and not any((Path(j['output_path'])/'dispatch.json').exists() for j in jobs),'Claims after pre-controller failure')
        return {'eligible':True,'reason':'pre_controller_failure','sources':{str(bp):sha(bp),str(ep):sha(ep)}}
    if not status_path.exists():return {'eligible':False,'reason':'controller_status_missing'}
    s=read(status_path)
    require(s['hostname']==b['hostname'] and s['boot_id']==b['boot_id'] and s['pid']==b['controller_pid'],'Controller identity differs')
    require(s['method']==method and s['plan_sha256']==b['plan_sha256'],'Controller scope differs')
    if not(s.get('finished') is True and s.get('drained') is True and s.get('active')==0 and s.get('unknown_prior_claims')==[]):
        return {'eligible':False,'reason':'controller_not_proven_drained'}
    require(s['at']<=e['finished_at_unix'],'Controller activity after bootstrap exit')
    receipts=[]
    for j in jobs:
        p=Path(j['output_path']);claim=p/'dispatch.json'
        if not claim.exists():continue
        c=read(claim);require(c['hostname']==b['hostname'] and c['pid']==b['controller_pid'],'Unowned claim')
        terminal=p/'terminal.json';require(terminal.exists(),'Claim lacks terminal')
        t=read(terminal);require(t['job_id']==j['job_id'] and t['native_cleanup_confirmed'] is True and t['will_retry'] is False,'Native cleanup unconfirmed')
        receipts.append({'claim_path':str(claim),'claim_sha256':sha(claim),'terminal_path':str(terminal),'terminal_sha256':sha(terminal)})
    return {'eligible':True,'reason':'bootstrap_and_controller_drained_all_claims_clean','sources':{str(bp):sha(bp),str(ep):sha(ep),str(status_path):sha(status_path)},'claims':receipts}


def cycle(method,live):
    directory=OUT/('acl-controlled20-'+method);prepared=directory/'prepared.json'
    if not prepared.exists():return {'method':method,'state':'not_prepared'}
    rec=read(prepared)
    if not(directory/'response.json').exists():return {'method':method,'state':'not_created'}
    require(read(directory/'response.json').get('state')=='submitted','Cloud creation unknown')
    platform=bind(rec);row={'method':method,'uid':platform['uid'],'platform_state':platform['state'],'ready':platform.get('ready_replicas')}
    p=DEFAULT/'cells'/method/'status.json'
    if p.exists():row['controller']=read(p)
    jobs=[j for j in read(DEFAULT/'plan.json')['jobs']if j['method']==method];states=Counter()
    for j in jobs:
        t=Path(j['output_path'])/'terminal.json';states[read(t)['status']if t.exists()else'not_terminal']+=1
    row['states']=dict(states)
    if platform['state']in('STOPPED','SUSPENDED'):return {**row,'state':'stopped'}
    assessment=assess(method,platform['uid']);row.update(assessment={k:v for k,v in assessment.items()if k!='claims'})
    area=directory/'lifecycle';area.mkdir(exist_ok=True)
    if assessment['eligible'] and live and not(area/'stop-request.json').exists():
        fresh=bind(rec);require(fresh['uid']==platform['uid'],'UID changed before stop');again=assess(method,platform['uid']);require(again['eligible'],'Drain proof changed')
        immutable_json(area/'stop-request.json',{'at':time.time(),'uid':platform['uid'],'name':rec['name'],'evidence':again,'automatic_retry':False})
        response=create_cli([str(ROOT/'.tools/sco-tj/cli/sco'),'cci','apps','stop',rec['name'],'--workspace-name','rl','--profile','agentcontextlab-tj'])
        save(area/'stop-response.json',{**response,'at':time.time()});row['stop_submitted']=response.get('returncode')==0
    return row


def main():
    p=argparse.ArgumentParser();p.add_argument('--watch',action='store_true');p.add_argument('--live',action='store_true');p.add_argument('--methods',choices=METHODS,nargs='+',default=list(METHODS));a=p.parse_args()
    OUT.mkdir(parents=True,exist_ok=True);lock=(OUT/'observer.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    while True:
        rows=[]
        for method in a.methods:
            try:rows.append(cycle(method,a.live))
            except Exception as e:rows.append({'method':method,'state':'quarantined','error_type':type(e).__name__})
        save(OUT/'status.json',{'at':time.time(),'rows':rows,'no_prediction_retry':True,'model_calls':0})
        if not a.watch or all(r.get('state')=='stopped'for r in rows):return
        time.sleep(60)

if __name__=='__main__':main()
