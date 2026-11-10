#!/usr/bin/env python3
"""Admit core BC, then restore two drained RQ3 scales in new CCI generations."""
import argparse,fcntl,json,time,signal,copy
from pathlib import Path
from unittest.mock import patch
import yaml
from lab import ROOT
from run_bc_campaign_v3 import atomic,identity
from bc_route_runtime_v1 import immutable_json
from release_rq3_bounded_cells_v1 import remaining_count
from monitor_rq3_bounded_cci_v1 import sha,read,require
import monitor_rq3_bounded_cci_v1 as rqmon
import provision_rq3_bounded_retry_v1 as rqcloud
import provision_bc_bounded_retry_v1 as bccloud
from bootstrap_bc_bounded_retry_v1 import DEFAULT_ROOT as BC_ROOT,HARNESSES,load_validate

AREA=ROOT/'outputs/cloud-runtime/bc-priority-ops-v1'
RESTORE=AREA/'restored-rq3'
RQ_ROOT=rqcloud.DEFAULT_ROOT
MM_ROOT=ROOT/'outputs/campaigns/mmbc-vera-bounded-retry-v1'
HELD=('scale_0800','scale_1000')
RESERVE=6

def restore_name(key):
 require(key in HELD,'Unapproved restore scale')
 return 'acl-rq3-bounded-bc-return-s'+key.removeprefix('scale_')

def complete(root,jobs):return bool(jobs) and remaining_count(root,jobs)==0

def scale_bound(root,plan,key):
 jobs=[j for j in plan['jobs'] if j['scale_key']==key]
 require(jobs,'Missing planned scale')
 if complete(root,jobs):return 0
 if (root/'stops'/key).exists():
  owners=list((root/'controllers'/key).glob('*/maintenance.json'))
  if owners and all((p.parent/'exit.json').exists() and read(p.parent/'exit.json').get('drained') is True for p in owners):
   if not list((root/'cells/hermes'/key/'slots').glob('*/owner.json')):return 0
 return 16

def marker_binding(directory,root,key):
 prepared=read(directory/'prepared.json');request=read(directory/'request.json');response=read(directory/'response.json')
 require(response.get('state')=='submitted','Creation unknown/rejected')
 require(prepared['root']==str(root.resolve()) and prepared['plan_sha256']==request['plan_sha256']==sha(root/'plan.json'),'Prepared root/plan changed')
 require(prepared['config_sha256']==request['config_sha256']==sha(prepared['config_path']),'Prepared configuration changed')
 return prepared

def prepare_restore(key):
 name=restore_name(key);directory=RESTORE/name;marker=RESTORE/'markers'/(key+'.json')
 cfg=rqcloud.build_config(yaml.safe_load(rqcloud.base.TEMPLATE.read_text()),key,RQ_ROOT,marker)
 cfg['display_name']=name
 raw=yaml.safe_dump(cfg,sort_keys=False).encode();directory.mkdir(parents=True,exist_ok=True);path=directory/'config.yaml'
 if path.exists():require(path.read_bytes()==raw,'Restore config changed')
 else:
  with path.open('xb') as f:f.write(raw)
 record={'name':name,'scale_key':key,'root':str(RQ_ROOT),'plan_sha256':sha(RQ_ROOT/'plan.json'),'config_path':str(path),'config_sha256':sha(path),'launch_marker':str(marker),'concurrency':16,'source_sha256':sha(__file__),'restores_old_name':rqcloud.app_name(key)}
 immutable_json(directory/'prepared.json',record);return record

def cycle(live=False):
 bcplan,_=load_validate(BC_ROOT);rqplan,_=rqcloud.load_validate(RQ_ROOT);mmplan=read(MM_ROOT/'plan.json')
 require(read(MM_ROOT/'campaign-manifest.json')['plan_sha256']==sha(MM_ROOT/'plan.json'),'MMBC plan changed')
 mm=min(48,remaining_count(MM_ROOT,mmplan['jobs']));rq=sum(scale_bound(RQ_ROOT,rqplan,k) for k in rqcloud.SCALE_KEYS)
 bcactive=0;rows=[]
 for h in HARNESSES:
  jobs=[j for j in bcplan['jobs'] if j['harness']==h];marker=bccloud.launch_marker(h)
  if marker.exists():
   require(read(marker).get('plan_sha256')==sha(BC_ROOT/'plan.json'),'BC marker changed')
   if not complete(BC_ROOT,jobs):bcactive+=16
 for h in HARNESSES:
  marker=bccloud.launch_marker(h)
  if marker.exists():rows.append({'harness':h,'state':'already_released'});continue
  bound=mm+rq+bcactive+16+RESERVE
  if bound>128:rows.append({'harness':h,'state':'held_for_capacity','projected':bound});continue
  directory=bccloud.RECEIPTS/bccloud.app_name(h)
  if not(directory/'response.json').exists():rows.append({'harness':h,'state':'not_submitted'});continue
  prepared=marker_binding(directory,BC_ROOT,h)
  require(prepared['harness']==h and Path(prepared['launch_marker'])==marker,'BC scope mismatch')
  if live:immutable_json(marker,{'plan_sha256':sha(BC_ROOT/'plan.json'),'harness':h,'at':time.time(),'combined_inference_upper':bound,'judge_reserve':RESERVE,'source_sha256':sha(__file__)})
  bcactive+=16;rows.append({'harness':h,'state':'released' if live else 'would_release','projected':bound})
 restored=[]
 if complete(BC_ROOT,bcplan['jobs']):
  for key in HELD:
   if complete(RQ_ROOT,[j for j in rqplan['jobs'] if j['scale_key']==key]):
    restored.append({'scale_key':key,'state':'stopped','reason':'all_jobs_terminal_no_restore_needed'});continue
   marker=RESTORE/'markers'/(key+'.json');directory=RESTORE/restore_name(key)
   if marker.exists():
    with patch.object(rqmon,'app_name',restore_name):restored.append(rqmon.cycle(key,live,receipts=RESTORE))
    continue
   bound=mm+sum(scale_bound(RQ_ROOT,rqplan,k) for k in rqcloud.SCALE_KEYS)+16+RESERVE
   if bound>128:restored.append({'scale_key':key,'state':'restore_capacity_hold','projected':bound});continue
   platform=rqmon.query_app(rqcloud.app_name(key));require(platform['state'] in ('SUSPENDED','STOPPED'),'Old RQ3 allocation not yet stopped')
   old_marker=rqcloud.launch_marker(key)
   proof=rqmon.assess_local(RQ_ROOT,platform['uid'],old_marker,key);require(proof['eligible'],'Old scale drain unconfirmed')
   if not live:restored.append({'scale_key':key,'state':'would_restore_in_new_cci'});continue
   record=prepare_restore(key);rqcloud.submit(record)
   marker_binding(directory,RQ_ROOT,key)
   stop=RQ_ROOT/'stops'/key
   require(stop.exists(),'Missing priority stop marker before restoration')
   immutable_json(directory/'prior-drain-proof.json',proof)
   archive=directory/'prior-stop-marker.json';require(not archive.exists(),'Restore transition already started; inspect manually')
   archive.write_bytes(stop.read_bytes());stop.unlink()
   immutable_json(marker,{'plan_sha256':sha(RQ_ROOT/'plan.json'),'scale_key':key,'at':time.time(),'source_sha256':sha(__file__),'bc_completed':True,'combined_inference_upper':bound})
   restored.append({'scale_key':key,'state':'new_restore_cci_released','name':restore_name(key)})
 return {'at':time.time(),'live':live,'mmbc_capacity_upper':mm,'rq3_capacity_upper':rq,'bc_capacity_upper':bcactive,'judge_reserved':RESERVE,'rows':rows,'restored':restored,'paid_model_calls':0}

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--watch',action='store_true');p.add_argument('--live',action='store_true');a=p.parse_args();AREA.mkdir(parents=True,exist_ok=True)
 with (AREA/'observer.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);generation=AREA/'generations'/str(time.time_ns());generation.mkdir(parents=True)
  immutable_json(generation/'service.json',{**identity(),'source_sha256':sha(__file__),'at':time.time(),'live':a.live})
  stopping=False
  def stop(*unused):
   nonlocal stopping;stopping=True
  signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
  while not stopping:
   try:row=cycle(a.live)
   except Exception as e:row={'at':time.time(),'state':'unknown_no_release','error_type':type(e).__name__,'reason':str(e)}
   atomic(AREA/'status.json',row)
   with (generation/'history.jsonl').open('a') as f:f.write(json.dumps(row)+'\n')
   if not a.watch:print(json.dumps(row));break
   if len(row.get('restored',[]))==2 and all(x['state']=='stopped' for x in row['restored']):break
   until=time.monotonic()+30
   while not stopping and time.monotonic()<until:time.sleep(.5)
  atomic(generation/'exit.json',{'at':time.time(),'stop_requested':stopping})
if __name__=='__main__':main()
