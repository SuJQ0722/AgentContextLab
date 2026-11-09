#!/usr/bin/env python3
"""Explicit transport-only recovery; reuse frozen phase3 call ledger, never retry a call."""
import argparse,fcntl,hashlib,json,os,sys,time
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urlparse
import httpx
import info_loss_phase3 as study
from lab import ROOT,environment

def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def now():return datetime.now(timezone.utc).isoformat()

def snapshot_calls(root):
    return {str(p.relative_to(root)):digest(p) for pattern in ('calls/*/started.json','calls/*/response.json') for p in root.glob(pattern)}

def verify_prior(root,records):
    for name,sha in records.items():
        if digest(root/name)!=sha:raise ValueError('Existing call evidence changed: '+name)

class TrackedClient:
    def __init__(self,client,out):self.client=client;self.out=out
    def __enter__(self):self.client.__enter__();return self
    def __exit__(self,*args):return self.client.__exit__(*args)
    def post(self,url,**kwargs):
        body=kwargs.get('content');key=hashlib.sha256(body).hexdigest();folder=self.out/'http'/(str(time.time_ns())+'-'+key)
        # The frozen per-call started/response ledger, not body equality, prevents paid retries.
        folder.mkdir(parents=True,exist_ok=True)
        with (folder/'started.json').open('x') as f:json.dump({'started_at':now(),'request_sha256':key,'request_bytes':len(body),'pid':os.getpid(),'transport':'configured_explicit_proxy','automatic_retries':0},f)
        start=time.monotonic();result={}
        try:
            response=self.client.post(url,**kwargs);result={'http_status':response.status_code};return response
        except BaseException as exc:result={'error_type':type(exc).__name__};raise
        finally:study.save(folder/'terminal.json',{'ended_at':now(),'client_http_seconds':time.monotonic()-start,**result})

def factory(real,proxy,out):
    def create(*args,**kwargs):
        kwargs['trust_env']=False;kwargs['proxy']=proxy
        return TrackedClient(real(*args,**kwargs),out)
    return create

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,default=study.DEFAULT_OUT);p.add_argument('--deployment',required=True);a=p.parse_args();root=a.output.resolve()
    if not a.deployment.replace('-','').replace('_','').isalnum():p.error('deployment must be a simple unique identifier')
    deployment=root/'operations'/a.deployment
    if deployment.exists():raise ValueError('Use a new explicit deployment; operational evidence is immutable')
    manifest=json.loads((root/'manifest.json').read_text())
    if digest(root/'manifest.json')!=(root/'manifest.sha256').read_text().strip() or study.hashes()!=manifest['implementation_sha256']:raise ValueError('Frozen scientific implementation or manifest changed')
    env,_=environment(ROOT,'dsh');proxy=env.get('https_proxy') or env.get('HTTPS_PROXY') or env.get('http_proxy')
    if not proxy or not urlparse(proxy).hostname:raise ValueError('No existing configured proxy; no inferred endpoint')
    with (root/'run.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);prior=snapshot_calls(root);deployment.mkdir(parents=True)
        study.save(deployment/'deployment.json',{'version':'information-loss-phase3-transport-ops1','started_at':now(),'pid':os.getpid(),'proxy_hostname':urlparse(proxy).hostname,'proxy_port':urlparse(proxy).port,'manifest_sha256':digest(root/'manifest.json'),'operational_script_sha256':digest(Path(__file__)),'frozen_scientific_sha256':manifest['implementation_sha256'],'prior_call_evidence_sha256':prior,'prior_requests_started':len(list((root/'calls').glob('*/started.json'))),'prior_responses':len(list((root/'calls').glob('*/response.json'))),'scope':'Only future never-started requests use the configured proxy. Existing completed/error/unknown calls are reused, never sent again. Prompt/image bytes/detail/model/output budget/read/write limits unchanged. This explicitly starts a new transport deployment after the old three-error hold; no automatic recovery of further holds.'})
        original=httpx.Client;httpx.Client=factory(original,proxy,deployment)
        study.save(root/'running.json',{'pid':os.getpid(),'started_at':now(),'model':manifest['model'],'concurrency':1,'operational_deployment':str(deployment)})
        code=0
        try:study.run(root,manifest)
        except BaseException as exc:code=1;study.save(deployment/'error.json',{'error_type':type(exc).__name__,'at':now()});raise
        finally:
            httpx.Client=original;verify_prior(root,prior);study.save(deployment/'exit.json',{'at':now(),'exit_code':code,'prior_call_evidence_unchanged':True,'total_requests_started':len(list((root/'calls').glob('*/started.json')))})
if __name__=='__main__':main()
