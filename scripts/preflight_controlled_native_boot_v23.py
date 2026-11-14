"""Execute a real controlled worker initialization, then intercept first SDK call.

No answer files are read. Predictions stay outside official roots. The SDK stub
is installed before telemetry wrappers; an HTTP send guard additionally denies
any accidental outbound HTTP request in this initialization check.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import time
import traceback
from unittest.mock import patch
import httpx
from openai.resources.chat.completions import Completions
from lab import ROOT
import controlled_mmbc_source_v23 as runner

class ReachedModelBoundary(BaseException):pass
class UnexpectedHTTP(BaseException):pass


def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=runner.DEFAULT);p.add_argument('--method',choices=runner.METHODS,required=True);args=p.parse_args()
    root=args.root.resolve();plan=runner.read(root/'plan.json');runner.validate_plan(root,plan)
    job=copy.deepcopy(next(j for j in plan['jobs']if j['method']==args.method and j['action']=='matched_continuation'))
    out=ROOT/'outputs/preflight'/('controlled-native-init-v23-'+args.method+'-'+str(time.time_ns()));out.mkdir(parents=True)
    job['output_path']=str(out/'worker');calls=[];http=[]
    def intercepted(client,*unused,**kwargs):
        calls.append({'model':kwargs.get('model'),'message_count':len(kwargs.get('messages',[])),'max_tokens':kwargs.get('max_tokens')})
        raise ReachedModelBoundary()
    def denied(client,request,*a,**kw):
        http.append({'method':request.method,'model_route_request':request.url.path.endswith('/chat/completions')})
        raise UnexpectedHTTP()
    error=None;frames=[]
    import capture_multimodal_prefix_v5 as capture
    original=capture.worker
    def traced(*a,**kw):
        try:return original(*a,**kw)
        except BaseException as exc:
            frames.extend({'file':t.filename,'line':t.lineno,'function':t.name,'error_type':type(exc).__name__}for t in traceback.extract_tb(exc.__traceback__))
            raise
    try:
        with patch.object(Completions,'create',intercepted),patch.object(httpx.Client,'send',denied),patch.object(capture,'worker',traced):runner.worker(root,plan,job)
    except BaseException as exc:error=type(exc).__name__
    policy_path=Path(job['output_path'])/'metrics/policy.jsonl'
    policies=[json.loads(line)for line in policy_path.read_text().splitlines()]if policy_path.exists()else[]
    allowed={'web_search','web_extract','image_search','image_crop','image_zoom_in'}
    policy_ok=bool(policies) and all(set(x.get('tools',[]))==allowed and x.get('compression_enabled') is False and x.get('native_vision') is True for x in policies)
    spec=runner.read(job['spec_path']);cfg=runner.read(job['config_path'])
    result={'version':'controlled-native-zero-model-initialization-v23','method':args.method,'job_id':job['job_id'],
        'plan_path':str(root/'plan.json'),'plan_sha256':runner.sha(root/'plan.json'),'source_sha256':runner.sha(__file__),
        'at':time.time(),'first_sdk_boundaries':calls,'http_sends_denied':http,'external_model_calls':0,
        'wrapper_error_type':error,'initialization_frames':frames,'actual_tool_policy':policies,'max_rounds':spec['max_rounds'],'context_window':cfg['context_window'],'config_sha256':runner.sha(job['config_path']),'output_path':str(out),'passed':len(calls)==1 and not http and error is None and policy_ok and spec['max_rounds']==500 and calls[0]['model']==job['model'] and calls[0]['max_tokens']==1,
        'note':'Real source/config/prefix/native staging and Hermes initialization, then first budget calibration intercepted before any HTTP/model call.'}
    runner.save(out/'readiness.json',result)
    print(json.dumps(result,ensure_ascii=False))
    if not result['passed']:raise SystemExit(1)

if __name__=='__main__':main()
