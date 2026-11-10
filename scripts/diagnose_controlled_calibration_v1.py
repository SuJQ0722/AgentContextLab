#!/usr/bin/env python3
"""One source-identical calibration diagnostic; offline capture first, one explicit paid POST maximum."""
import argparse
import copy
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from lab import ROOT, environment, python_for
from judge_bc_v3_completed import atomic, immutable, sha, now
from bounded_visual_request_guard_v1 import inspect_payload

OUT=ROOT/'outputs/preflight/controlled-native-calibration-diag-v1'
SOURCE=ROOT/'outputs/experiment3/controlled-native-bounded-v1/jobs/browsecomp_v3/q_001_r01/visual'
CAPTURE=ROOT/'outputs/experiment3/controlled-native-bounded-v1/diagnostics/calibration-request-capture-v1'
MODEL='deepseek-v4.1-flash-1017/huoshan/huoshan'


def body(payload):return json.dumps(payload,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()
def digest(raw):return hashlib.sha256(raw).hexdigest()
def read(p):return json.loads(Path(p).read_text())


def offline_capture():
    import httpx
    class LocalCapture(BaseException):pass
    def intercept(client,request):
        if not request.url.path.rstrip('/').endswith('/chat/completions'):raise RuntimeError('Offline capture forbids network')
        OUT.mkdir(parents=True,exist_ok=True);OUT.chmod(0o700)
        p=OUT/'captured-body.json'
        with p.open('xb') as f:f.write(request.content)
        p.chmod(0o600)
        atomic(OUT/'capture.json',{'body_sha256':digest(request.content),'body_bytes':len(request.content),'network_sent':False,'at':now()})
        raise LocalCapture()
    httpx.Client._send_single_request=intercept
    import controlled_native_worker_bounded_v1 as worker
    sys.argv=[str(ROOT/'scripts/controlled_native_worker_bounded_v1.py'),'--spec',str(SOURCE/'spec.json'),'--out',str(CAPTURE),'--live']
    worker.main()


def prepare():
    OUT.mkdir(parents=True,exist_ok=True);OUT.chmod(0o700)
    if not (OUT/'captured-body.json').exists():
        env,_=environment(ROOT,'hermes',read(SOURCE/'spec.json')['config_path'])
        with (OUT/'offline-capture.log').open('a') as log:
            subprocess.run([python_for(ROOT),str(Path(__file__).resolve()),'--capture'],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=90)
    captured=read(OUT/'captured-body.json')
    with gzip.open(SOURCE/'metrics/requests-responses.jsonl.gz','rt') as f:
        original=next(json.loads(line) for line in f if json.loads(line).get('type')=='request')
    old=copy.deepcopy(captured);old['messages']=original['messages'];old['model']=original['model'];old['max_tokens']=original['max_tokens']
    oldraw=body(old)
    prior=read(SOURCE/'bounded-protocol.json')
    guard=json.loads((SOURCE/'bounded-wire-guard.jsonl').read_text().splitlines()[0])
    if digest(oldraw)!=guard['body_sha256']:
        atomic(OUT/'reconstruction-error.json',{'reconstructed_sha256':digest(oldraw),'required_sha256':guard['body_sha256'],
            'keys':list(old),'body_bytes':len(oldraw),'required_bytes':guard['body_bytes'],'paid_calls':0})
        raise ValueError('Full original request reconstruction did not match final HTTP SHA; do not call model')
    new=copy.deepcopy(old);new['max_tokens']=64;new['tool_choice']='none';new['thinking']={'type':'disabled'}
    if new['model']!=MODEL or new.get('stream') is not False:raise ValueError('Unexpected source model/stream')
    changed={k:{'before':old.get(k),'after':new.get(k)} for k in set(old)|set(new) if old.get(k)!=new.get(k)}
    if set(changed)!={'max_tokens','tool_choice','thinking'}:raise ValueError('Unexpected parameter diff')
    for name,value in [('original-body.json',old),('diagnostic-body.json',new)]:
        raw=body(value);path=OUT/name
        if path.exists() and path.read_bytes()!=raw:raise ValueError('Frozen diagnostic changed')
        if not path.exists():path.write_bytes(raw);path.chmod(0o600)
    report={'version':'controlled-calibration-diagnostic-v1','source_attempt':str(SOURCE),
        'source_spec_sha256':sha(SOURCE/'spec.json'),'original_body_sha256':digest(oldraw),'original_body_matches_wire_sha':True,
        'diagnostic_body_sha256':digest(body(new)),'changes':changed,
        'messages_identical':new['messages']==old['messages'],'tools_identical':new.get('tools')==old.get('tools'),
        'model_identical':new['model']==old['model'],'sdk_extra_body_translation':{'thinking':{'type':'disabled'}},
        'source_max_tokens':old['max_tokens'],'source_tool_choice':old.get('tool_choice','absent_provider_default'),
        'source_thinking':old.get('thinking','absent_provider_default'),'source_stream':old.get('stream'),
        'maximum_paid_requests':1,'automatic_retries':0,'guard':inspect_payload(body(new),rendered_registry=set(),strict_all_images=False)}
    immutable(OUT/'plan.json',report)
    return report


def live():
    plan=prepare();payload=(OUT/'diagnostic-body.json').read_bytes()
    if sha(OUT/'diagnostic-body.json')!=plan['diagnostic_body_sha256']:raise ValueError('Diagnostic changed')
    if (OUT/'started.json').exists() or (OUT/'result.json').exists():raise ValueError('Prior request retained; no retry')
    import httpx
    from controlled_transport_v5 import cause_chain
    env,_=environment(ROOT,'hermes',read(SOURCE/'spec.json')['config_path'])
    # Same reviewed direct gateway route: source bypasses proxy for this host.
    url=env['TOKENHUB_BASE_URL'].rstrip('/')+'/chat/completions'
    from urllib.parse import urlsplit
    if urlsplit(url).hostname!='tokenhub.sensetime.com':raise ValueError('Unexpected endpoint host')
    with (OUT/'started.json').open('x') as f:
        os.chmod(f.name,0o600);json.dump({'at':now(),'body_sha256':digest(payload),'maximum_requests':1},f);f.flush();os.fsync(f.fileno())
    started=time.monotonic();result={'status':'unknown','raw_provider_usage':None,'usd':None,'provider_latency_seconds':None,
        'body_sha256':digest(payload),'api_calls':1,'automatic_retries':0,'guard':plan['guard']}
    try:
        with httpx.Client(trust_env=False,timeout=httpx.Timeout(300,connect=30),follow_redirects=False) as client:
            response=client.post(url,content=payload,headers={'Authorization':'Bearer '+env['TOKENHUB_API_KEY'],'Content-Type':'application/json'})
        result.update(http_status=response.status_code,provider_request_id=response.headers.get('x-request-id'))
        data=response.json();atomic(OUT/'response.json',data)
        result.update(status='response_received' if response.is_success else 'http_error',raw_provider_usage=data.get('usage'),returned_model=data.get('model'),
            finish_reason=(data.get('choices') or [{}])[0].get('finish_reason'))
    except Exception as e:result.update(status='transport_or_parse_error',error_type=type(e).__name__,cause_chain=cause_chain(e))
    result.update(client_http_seconds=time.monotonic()-started,finished_at=now(),timing_definition='Client request plus body duration, not provider internal latency')
    atomic(OUT/'result.json',result)
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--capture',action='store_true');p.add_argument('--prepare',action='store_true');p.add_argument('--live',action='store_true');a=p.parse_args()
    if a.capture:return offline_capture()
    result=live() if a.live else prepare()
    print(json.dumps({k:result[k] for k in ('status','original_body_sha256','diagnostic_body_sha256','changes','client_http_seconds','raw_provider_usage','returned_model') if k in result}))

if __name__=='__main__':main()
