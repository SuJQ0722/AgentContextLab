#!/usr/bin/env python3
"""Exactly one explicit-proxy diagnostic, retaining the original HTTP body bytes."""
import argparse
import json
import os
from pathlib import Path
import signal
import time
from urllib.parse import urlsplit
from lab import ROOT, environment
from judge_bc_v3_completed import atomic, immutable, sha, now
from bounded_visual_request_guard_v1 import inspect_payload
from controlled_transport_v5 import cause_chain

OUT=ROOT/'outputs/preflight/controlled-native-proxy-diagnostic-v1'
SOURCE=ROOT/'outputs/preflight/controlled-native-calibration-diag-v1'
ATTEMPT=ROOT/'outputs/experiment3/controlled-native-bounded-v1/jobs/browsecomp_v3/q_001_r01/visual'
PROXY='http://10.120.0.246:7890'
MODEL='deepseek-v4.1-flash-1017/huoshan/huoshan'
EXPECTED='59d81eab37301bb8bc21a9ae57cd4b42f5fc278a32ca822b4727ef60f44b8237'

class WallCap(BaseException):pass

def read(path):return json.loads(Path(path).read_text())

def prepare():
    OUT.mkdir(parents=True,exist_ok=True);OUT.chmod(0o700)
    source=SOURCE/'original-body.json';raw=source.read_bytes();payload=json.loads(raw)
    if sha(source)!=EXPECTED or read(SOURCE/'plan.json')['original_body_sha256']!=EXPECTED:raise ValueError('Original wire identity mismatch')
    if payload.get('model')!=MODEL or payload.get('max_tokens')!=1 or payload.get('stream') is not False or 'thinking' in payload or 'tool_choice' in payload:
        raise ValueError('Expected original, not modified three-parameter diagnostic')
    path=OUT/'request-body.json'
    if path.exists() and path.read_bytes()!=raw:raise ValueError('Frozen request bytes changed')
    if not path.exists():
        with path.open('xb') as stream:stream.write(raw)
        path.chmod(0o600)
    result={'version':'controlled-native-proxy-diagnostic-v1','source_body_path':str(source),
        'body_sha256':sha(source),'request_bytes':len(raw),'model':MODEL,'body_byte_identical':True,
        'payload_changes':{},'only_routing_change':{'proxy':PROXY,'trust_env':False},
        'diagnostic_time_limits':{'write_seconds':120,'read_seconds':120,'connect_seconds':30,'total_wall_seconds':180},
        'maximum_post_operations':1,'automatic_retries':0,'redirects':False,
        'source_sha256':sha(__file__),'guard':inspect_payload(raw,rendered_registry=set(),strict_all_images=False)}
    immutable(OUT/'plan.json',result)
    return result


def live():
    plan=prepare();body=(OUT/'request-body.json').read_bytes()
    if (OUT/'started.json').exists() or (OUT/'result.json').exists():raise ValueError('Prior operation retained; never automatically resend')
    env,_=environment(ROOT,'hermes',read(ATTEMPT/'spec.json')['config_path'])
    url=env['TOKENHUB_BASE_URL'].rstrip('/')+'/chat/completions'
    if urlsplit(url).hostname!='tokenhub.sensetime.com' or urlsplit(url).path!='/v1/chat/completions':raise ValueError('Endpoint changed')
    import httpx
    def wall_limit(*args):raise WallCap('180 second total wall cap')
    previous=signal.signal(signal.SIGALRM,wall_limit)
    with (OUT/'started.json').open('x') as stream:
        os.chmod(stream.name,0o600);json.dump({'at':now(),'body_sha256':plan['body_sha256'],'proxy':PROXY,'maximum_posts':1},stream);stream.flush();os.fsync(stream.fileno())
    started=time.monotonic();record={'status':'unknown','body_sha256':plan['body_sha256'],'proxy':PROXY,
        'payload_changes':{},'api_calls':1,'automatic_retries':0,'raw_provider_usage':None,
        'usd':None,'provider_latency_seconds':None,'http_status':None,'response_received':False}
    signal.alarm(180)
    try:
        with httpx.Client(proxy=PROXY,trust_env=False,follow_redirects=False,
                timeout=httpx.Timeout(connect=30,read=120,write=120,pool=10)) as client:
            response=client.post(url,content=body,headers={'Authorization':'Bearer '+env['TOKENHUB_API_KEY'],'Content-Type':'application/json'})
        raw=response.content;path=OUT/'response-body.bin';path.write_bytes(raw);path.chmod(0o600)
        record.update(http_status=response.status_code,response_received=True,response_body_sha256=sha(path),response_bytes=len(raw),provider_request_id=response.headers.get('x-request-id'))
        data=response.json();atomic(OUT/'response.json',data)
        record.update(status='response_received' if response.is_success else 'http_error',raw_provider_usage=data.get('usage'),
            returned_model=data.get('model'),finish_reason=(data.get('choices') or [{}])[0].get('finish_reason'))
    except WallCap as error:record.update(status='total_wall_timeout',error_type=type(error).__name__,cause_chain=cause_chain(error))
    except Exception as error:record.update(status='transport_or_parse_error',error_type=type(error).__name__,cause_chain=cause_chain(error))
    finally:
        signal.alarm(0);signal.signal(signal.SIGALRM,previous)
    record.update(client_http_seconds=time.monotonic()-started,finished_at=now(),timing_definition='Client wall duration, not provider internal latency; token usage/billing unknown if absent')
    atomic(OUT/'result.json',record)
    return record


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--live',action='store_true');a=p.parse_args()
    value=live() if a.live else prepare()
    print(json.dumps({k:value[k] for k in ('body_sha256','request_bytes','payload_changes','only_routing_change','status','http_status','error_type','client_http_seconds','raw_provider_usage') if k in value}))

if __name__=='__main__':main()
