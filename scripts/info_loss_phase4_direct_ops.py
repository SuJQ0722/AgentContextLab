#!/usr/bin/env python3
"""Explicit direct deployment for never-started phase4 requests; no paid retries."""
import argparse,fcntl,json,os,time
from pathlib import Path
from unittest.mock import patch
import info_loss_phase4 as study

def snapshot(root):
 return {str(p.relative_to(root)):study.sha(p) for pattern in ('calls/*/started.json','calls/*/response.json') for p in root.glob(pattern)}
def verify_prior(root,prior):
 if any(study.sha(root/key)!=digest for key,digest in prior.items()):raise ValueError('Previous call evidence changed')
def factory(real,operation):
 def create(*args,**kwargs):
  kwargs.pop('proxy',None);kwargs['trust_env']=False
  return Transport(real(*args,**kwargs),operation)
 return create
class Transport:
 def __init__(self,client,operation):self.client=client;self.operation=operation
 def __enter__(self):self.client.__enter__();return self
 def __exit__(self,*a):return self.client.__exit__(*a)
 def post(self,url,**kwargs):
  body=kwargs['content'];key=str(time.time_ns());folder=self.operation/'http'/key;start=time.monotonic();result={}
  study.save(folder/'started.json',{'request_sha256':study.hashlib.sha256(body).hexdigest(),'request_bytes':len(body),'transport':'direct_no_environment_proxy','at':study.old.now(),'automatic_retries':0})
  try:
   response=self.client.post(url,**kwargs);result['http_status']=response.status_code;return response
  except BaseException as exc:result['error_type']=type(exc).__name__;raise
  finally:study.save(folder/'terminal.json',{**result,'client_http_seconds':time.monotonic()-start,'at':study.old.now()})
def main():
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,default=study.DEFAULT);p.add_argument('--deployment',required=True);p.add_argument('--gate-only',action='store_true');a=p.parse_args();root=a.output.resolve()
 if not a.deployment.replace('-','').isalnum():raise ValueError('Invalid deployment identifier')
 operation=root/'operations'/a.deployment
 with (root/'run.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);m=study.read(root/'manifest.json');study.verify(root,m)
  if (root/'STOP').exists():raise ValueError('STOP remains active')
  if operation.exists():raise ValueError('Use new explicit deployment, never overwrite old operations')
  hold=root/'quality-hold.json';prior_hold=study.read(hold) if hold.exists() else None
  if prior_hold and prior_hold.get('reason')!='infrastructure_or_model_identity_gate':raise ValueError('Only infrastructure recovery allowed')
  # Never override a model identity mismatch, even if its generic hold reason matches.
  if any(study.read(p).get('status')=='model_identity_mismatch' for p in root.glob('calls/*/response.json')):raise ValueError('Model identity mismatch is not transport-recoverable')
  starts=list(root.glob('calls/*/started.json'))
  if any(not (p.parent/'response.json').exists() for p in starts):raise ValueError('Unresolved call: no transport cutover while in-flight/unknown')
  prior=snapshot(root);operation.mkdir(parents=True)
  record={'version':'phase4-direct-transport-ops1','at':study.old.now(),'pid':os.getpid(),'manifest_sha256':study.sha(root/'manifest.json'),'operational_source_sha256':study.sha(__file__),'previous_call_evidence':prior,'prior_hold':prior_hold,'prior_requests':len(starts),'scope':'Only never-started calls, same exact request payload/timeout/model. Existing failed/unknown requests not resent; all stages retain shared190 cap.'}
  study.save(operation/'deployment.json',record)
  if prior_hold:study.save(operation/'prior-hold.json',prior_hold);hold.unlink()
  original_save=study.save
  def save(path,value):
   if Path(path).name=='request-manifest.json':value={**value,'transport':'direct_no_environment_proxy','operational_deployment':str(operation)}
   return original_save(path,value)
  try:
   with patch.object(study.httpx,'Client',factory(study.httpx.Client,operation)),patch.object(study,'save',save):study.run(root,m,a.gate_only)
  finally:verify_prior(root,prior);study.save(operation/'exit.json',{'at':study.old.now(),'prior_call_evidence_unchanged':True})
if __name__=='__main__':main()
