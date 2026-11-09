#!/usr/bin/env python3
"""Durable direct upload / proxy CDN download retries; model POST is never retried here."""
import argparse,base64,fcntl,hashlib,json,logging,os,sys,time
from datetime import datetime,timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from unittest.mock import patch
import httpx,requests
import info_loss_phase4_url as worker
from info_loss_phase4_direct_ops import snapshot,verify_prior

class HostingExhausted(RuntimeError):pass

def retry_delay(value,attempt):
 delay=min(120,30*2**min(attempt,3))
 if value:
  try:server=max(0,float(value))
  except ValueError:
   try:server=max(0,parsedate_to_datetime(value).timestamp()-time.time())
   except (ValueError,TypeError,OverflowError):server=0
  delay=max(delay,server)
 return delay

class State:
 def __init__(self,operation):self.operation=operation
 def check_stop(self):
  if (self.operation.parent.parent/'STOP').exists():raise HostingExhausted('Stopped before next zero-model network request')
 def path(self,key):return self.operation/'network-state'/f'{key}.json'
 def load(self,key):
  p=self.path(key);return worker.study.read(p) if p.exists() else {'first_started_unix':time.time(),'attempts':[]}
 def reserve(self,key,kind):
  self.check_stop();state=self.load(key)
  if len(state['attempts'])>=12 or time.time()-state['first_started_unix']>=7200:raise HostingExhausted('Per-image12attempt/2h zero-model limit reached')
  due=state.get('next_attempt_unix') or 0;remaining=7200-(time.time()-state['first_started_unix'])
  if due>time.time():
   if due-time.time()>remaining:raise HostingExhausted('Retry-After exceeds remaining2h window')
   remaining_wait=due-time.time()
   while remaining_wait>0:
    self.check_stop();interval=min(1,remaining_wait);time.sleep(interval);remaining_wait-=interval
  state['attempts'].append({'started_at_unix':time.time(),'kind':kind,'model_calls':0,'route':'proxy' if kind=='image_download' else 'direct'});worker.save(self.path(key),state);return state
 def finish(self,key,state,status=None,error=None,retry_after=None,success=False):
  state['attempts'][-1].update(ended_at_unix=time.time(),http_status=status,error_type=error,retry_after=retry_after,success=success)
  state['next_attempt_unix']=time.time()+retry_delay(retry_after,len(state['attempts'])-1) if not success else None
  worker.save(self.path(key),state)

class DirectClient:
 def __init__(self,client,state):self.client=client;self.state=state
 def __enter__(self):self.client.__enter__();return self
 def __exit__(self,*a):return self.client.__exit__(*a)
 def post(self,*a,**kw):return self.client.post(*a,**kw) # Inference: ONE HTTP attempt only.
 def get(self,url,**kwargs):
  key='download-'+hashlib.sha256(url.encode()).hexdigest()
  while True:
   state=self.state.reserve(key,'image_download')
   try:
    response=self.client.get(url,**kwargs);good=response.status_code==200;self.state.finish(key,state,response.status_code,retry_after=response.headers.get('retry-after'),success=good)
    if good:return response
    if response.status_code not in (408,429,500,502,503,504):return response
   except httpx.TransportError as exc:self.state.finish(key,state,error=type(exc).__name__)

def uploader(original,host,state,root):
 def upload(path):
  digest=worker.study.sha(path);receipt=state.operation/'upload-receipts'/f'{digest}.json'
  if receipt.exists():return worker.study.read(receipt)['url']
  candidates=list((root/'operations').glob(f'*/upload-receipts/{digest}.json'))+list((root/'operations').glob('imgbb-*-upload.json'))
  for p in candidates:
   record=worker.study.read(p)
   if record.get('source_sha256')==digest and record.get('url'):
    worker.save(receipt,record);return record['url']
  key='upload-'+digest
  while True:
   record=state.reserve(key,'image_upload');observed={}
   def direct_post(url,**kwargs):
    if url!=host.IMGBB_ENDPOINT:raise ValueError('Unexpected hosted upload endpoint')
    try:
     with requests.Session() as client:
      client.trust_env=False;response=client.post(url,**kwargs)
     observed.update(status=response.status_code,retry_after=response.headers.get('Retry-After'));return response
    except requests.RequestException as exc:observed['error']=type(exc).__name__;raise
   with patch.object(host.requests,'post',direct_post):url=original(path)
   state.finish(key,record,status=observed.get('status'),error=observed.get('error'),retry_after=observed.get('retry_after'),success=bool(url))
   if url:
    worker.save(receipt,{'source_sha256':digest,'url':url,'at':worker.study.old.now(),'transport':'direct_no_environment_proxy','model_calls':0});return url
   if observed.get('status') in (400,401,403,404):raise HostingExhausted('Nontransient image-host rejection; not a model call')
 return upload

def main():
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,default=worker.DEFAULT);a=p.parse_args();root=a.output.resolve();operation=root/'operations/imgbb-split-ops3';operation.mkdir(parents=True,exist_ok=True)
 with (operation/'run.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);prior=snapshot(root)
  if any(not (x.parent/'response.json').exists() for x in root.glob('calls/*/started.json')):raise ValueError('Unresolved inference is never retried')
  path=operation/'deployment.json';source_sha=worker.study.sha(__file__)
  if path.exists():
   if worker.study.read(path)['source_sha256']!=source_sha:raise ValueError('Frozen hosting maintenance source changed')
  else:worker.save(path,{'version':'durable-split-image-host-ops3','source_sha256':source_sha,'at':worker.study.old.now(),'pid':os.getpid(),'science_manifest_sha256':worker.study.sha(root/'manifest.json'),'upload_download_attempts_per_image':12,'deadline_per_image_seconds':7200,'retry_after_respected':True,'base_backoff_seconds':[30,60,120],'model_post_retries':0,'prior_call_evidence':prior})
  # Continue the previous per-image counters/deadlines across this deployment.
  for prior_state in (root/'operations/imgbb-direct-ops2/network-state').glob('*.json'):
   destination=operation/'network-state'/prior_state.name
   if not destination.exists():worker.save(destination,worker.study.read(prior_state))
  state=State(operation);sys.path.insert(0,str(worker.ROOT/'hermes-agent'));import tools.image_search_tool as host
  original=httpx.Client
  def client(*args,**kwargs):
   # Frozen URL worker explicitly supplies proxy only to CDN GET clients.
   # Model clients omit proxy and remain direct with exactly one POST.
   kwargs['trust_env']=False;return DirectClient(original(*args,**kwargs),state)
  try:
   with patch.object(host,'_upload_imgbb',uploader(host._upload_imgbb,host,state,root)),patch.object(worker.httpx,'Client',client),patch.object(sys,'argv',['info_loss_phase4_url','--output',str(root),'--live']):worker.main()
  finally:verify_prior(root,prior);worker.save(operation/'exit.json',{'at':worker.study.old.now(),'prior_model_call_evidence_unchanged':True})
if __name__=='__main__':main()
