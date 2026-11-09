#!/usr/bin/env python3
"""Bounded retries for zero-model imgBB upload/download only; never model POST."""
import argparse,json,sys,time
from pathlib import Path
from unittest.mock import patch
import httpx
import info_loss_phase4_url as worker
from info_loss_phase4_direct_ops import snapshot,verify_prior

class DownloadClient:
 def __init__(self,client):self.client=client
 def __enter__(self):self.client.__enter__();return self
 def __exit__(self,*a):return self.client.__exit__(*a)
 def post(self,*a,**kw):return self.client.post(*a,**kw) # MODEL POST: exactly one attempt.
 def get(self,*a,**kw):
  for attempt in range(3):
   try:
    response=self.client.get(*a,**kw)
    if response.status_code>=500 and attempt<2:time.sleep(2);continue
    return response
   except httpx.TransportError:
    if attempt==2:raise
    time.sleep(2)

def upload_factory(original,operation):
 def upload(path):
  digest=worker.study.sha(path);receipt=operation/'upload-receipts'/f'{digest}.json'
  if receipt.exists():return worker.study.read(receipt)['url']
  for attempt in range(3):
   url=original(path)
   if url:
    worker.save(receipt,{'source_sha256':digest,'url':url,'at':worker.study.old.now(),'model_calls':0});return url
   if attempt<2:time.sleep(2)
  return None
 return upload

def main():
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,default=worker.DEFAULT);p.add_argument('--deployment',required=True);a=p.parse_args();root=a.output.resolve()
 if not a.deployment.replace('-','').isalnum():raise ValueError('Invalid deployment')
 operation=root/'operations'/a.deployment
 if operation.exists():raise ValueError('Preserve prior deployment')
 starts=list(root.glob('calls/*/started.json'))
 if any(not (p.parent/'response.json').exists() for p in starts):raise ValueError('Cannot recover unresolved inference')
 prior=snapshot(root);operation.mkdir(parents=True)
 worker.save(operation/'deployment.json',{'version':'imgbb-network-recovery-ops1','at':worker.study.old.now(),'source_sha256':worker.study.sha(__file__),'science_manifest_sha256':worker.study.sha(root/'manifest.json'),'prior_call_evidence':prior,'prior_error':worker.study.read(root/'exit-error.json') if (root/'exit-error.json').exists() else None,'upload_attempt_limit':3,'download_attempt_limit':3,'model_post_attempt_limit':1,'scientific_request_changed':False})
 sys.path.insert(0,str(worker.ROOT/'hermes-agent'))
 import tools.image_search_tool as host
 original=httpx.Client
 def factory(*args,**kwargs):return DownloadClient(original(*args,**kwargs))
 try:
  with patch.object(host,'_upload_imgbb',upload_factory(host._upload_imgbb,operation)),patch.object(worker.httpx,'Client',factory),patch.object(sys,'argv',['info_loss_phase4_url','--output',str(root),'--live']):worker.main()
 finally:verify_prior(root,prior);worker.save(operation/'exit.json',{'at':worker.study.old.now(),'prior_model_call_evidence_unchanged':True})
if __name__=='__main__':main()
