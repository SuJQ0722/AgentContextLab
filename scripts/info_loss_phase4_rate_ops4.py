#!/usr/bin/env python3
"""Pace never-started evaluations; preserve every old inference attempt, without retries."""
import argparse,fcntl,hashlib,json,os,sys,time
from pathlib import Path
from unittest.mock import patch
import httpx
import info_loss_phase4_url_ops3 as network
worker=network.worker
INFRA={'provider_error','transport_error'}

class Pace:
 def __init__(self,root,operation):self.root=root;self.operation=operation;self.path=operation/'rate-state.json';self.retry_after=None
 def load(self):return worker.study.read(self.path) if self.path.exists() else {'first_started_unix':time.time(),'infra_failures':0,'streak':0,'next_allowed_unix':0,'events':[]}
 def before(self,boundary):
  s=self.load()
  if s['infra_failures']>=12 or time.time()-s['first_started_unix']>=86400:raise worker.study.Hold('ops4_bounded_infrastructure_budget_exhausted')
  while time.time()<s['next_allowed_unix']:
   boundary();time.sleep(min(1,s['next_allowed_unix']-time.time()))
  boundary();self.retry_after=None
 def after(self,key,response):
  s=self.load();failed=response.get('status') in INFRA
  s['streak']=s['streak']+1 if failed else 0;s['infra_failures']+=int(failed)
  delay=min(900,60*2**min(max(s['streak']-1,0),4)) if failed else 20
  if self.retry_after:delay=max(delay,network.retry_delay(self.retry_after,0))
  s['next_allowed_unix']=time.time()+delay
  s['events'].append({'key':key,'at':worker.study.old.now(),'status':response.get('status'),'http_status':response.get('http_status'),'error_type':response.get('error_type'),'retry_after':self.retry_after,'delay_seconds':delay,'model_request_retried':False,'response_sha256':worker.study.sha(self.root/'calls'/key/'response.json')})
  worker.save(self.path,s)

def paced_client(base,pace):
 class Paced(base):
  def call(self,key,*args,**kwargs):
   folder=self.out/'calls'/key
   # Includes explicit 429 and unknown/interrupted: immutable historical observations.
   if (folder/'started.json').exists() or (folder/'response.json').exists():return super().call(key,*args,**kwargs)
   pace.before(self.boundary)
   try:response=super().call(key,*args,**kwargs)
   except worker.study.Hold as exc:
    if str(exc)!='infrastructure_or_model_identity_gate' or not (folder/'response.json').exists():raise
    response=worker.study.read(folder/'response.json')
    if response.get('status') not in INFRA:raise
   pace.after(key,response);self.errors=0
   return response
 return Paced

class ObservedClient(network.DirectClient):
 def __init__(self,client,state,pace):super().__init__(client,state);self.pace=pace
 def post(self,*args,**kwargs):
  response=self.client.post(*args,**kwargs) # Exactly one POST. Never retry 429 or unknown.
  self.pace.retry_after=response.headers.get('retry-after')
  return response

def release_expected_hold(root,operation):
 p=root/'quality-hold.json'
 if not p.exists():return
 d=worker.study.read(p)
 if d.get('reason')!='infrastructure_or_model_identity_gate' or d.get('inflight')!=0:raise ValueError('Scientific/model identity/other hold not authorized for release')
 responses=[worker.study.read(p) for p in root.glob('calls/*/response.json')]
 if any(r.get('status')=='model_identity_mismatch' for r in responses):raise ValueError('Model identity mismatch cannot resume')
 worker.save(operation/'prior-quality-hold.json',d);p.unlink()

def main():
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,default=worker.DEFAULT);a=p.parse_args();root=a.output.resolve();op=root/'operations/neverstarted-rate-ops4';op.mkdir(parents=True,exist_ok=True)
 with (op/'run.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  # Acquire scientific root once here through the worker below; ensure prior process ended.
  running=root/'running.json'
  if running.exists():
   pid=worker.study.read(running).get('pid');cmd=Path(f'/proc/{pid}/cmdline')
   if cmd.exists() and b'info_loss_phase4' in cmd.read_bytes():raise ValueError('Previous worker is still alive')
  if any(not (p.parent/'response.json').exists() for p in root.glob('calls/*/started.json')):raise ValueError('Unresolved inference remains: no automatic retransmission')
  prior=network.snapshot(root);deploy=op/'deployment.json'
  hashes={name:worker.study.sha(Path(__file__).parent/name) for name in [Path(__file__).name,'info_loss_phase4_url_ops3.py','info_loss_phase4_url.py','info_loss_phase4.py']}
  if deploy.exists():
   if worker.study.read(deploy)['implementation_sha256']!=hashes:raise ValueError('Operational source changed')
  else:worker.save(deploy,{'version':'neverstarted-rate-ops4','at':worker.study.old.now(),'pid':os.getpid(),'implementation_sha256':hashes,'science_manifest_sha256':worker.study.sha(root/'manifest.json'),'model_retries':0,'max_new_infra_failures':12,'deadline_seconds':86400,'minimum_success_interval_seconds':20,'prior_call_evidence':prior})
  release_expected_hold(root,op)
  # Reuse prior hosting receipts and persistent per-image retry budget; no new copies.
  state=network.State(root/'operations/imgbb-split-ops3');pace=Pace(root,op)
  sys.path.insert(0,str(worker.ROOT/'hermes-agent'));import tools.image_search_tool as host
  original=httpx.Client
  def client(*args,**kwargs):kwargs['trust_env']=False;return ObservedClient(original(*args,**kwargs),state,pace)
  try:
   with patch.object(host,'_upload_imgbb',network.uploader(host._upload_imgbb,host,state,root)),patch.object(worker.httpx,'Client',client),patch.object(worker,'Client',paced_client(worker.Client,pace)),patch.object(sys,'argv',['info_loss_phase4_url','--output',str(root),'--live']):worker.main()
  finally:network.verify_prior(root,prior);worker.save(op/'exit.json',{'at':worker.study.old.now(),'prior_model_call_evidence_unchanged':True})
if __name__=='__main__':main()
