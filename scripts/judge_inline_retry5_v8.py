"""Private V8 judging: exclude calibration, preserve retry costs and gold bindings."""
import copy
import io
import json
from pathlib import Path
import time
import urllib.error
import urllib.request
from unittest.mock import patch
import judge_visual_hosted_retry_v1 as parent
from lab import ROOT
from inline_route_contract_v2 import ROUTES
from visual_inline_route_accounting_v5 import resources as prediction_resources
from monitor_bc_campaign_v3 import aggregate

VERSION='judge-inline-retry5-v8'
DEFAULT=ROOT/'outputs/campaigns/visual-hosted-failure-retry-v1/cells/transport-v8-one-hour-retry5'
OUT=ROOT/'outputs/grading/visual-inline-one-hour-retry5-v8'
PROXY='http://10.120.0.246:7890'
_original_prepare=parent.prepare
_original_inventory=parent.inventory_cell


def prepare(root,out):
    original=parent.immutable
    def immutable(path,value):
        if Path(path).name=='protocol.json':
            value={**value,'version':VERSION,'api_retries':0,
                   'explicit_http_error_route_fallbacks':3,'unknown_acceptance_retries':0,
                   'approved_judge_routes':list(ROUTES),'explicit_proxy':PROXY,
                   'calibration_accuracy_and_judge_excluded':True,
                   'resource_accounting':'All native subattempts including calibration; judge attempts separate',
                   'sources_sha256':{**value['sources_sha256'],'judge_inline_retry5_v8.py':parent.sha(__file__)}}
        return original(path,value)
    with patch.object(parent,'immutable',immutable):cells,cfg=_original_prepare(root,out)
    for cell,data in cells.items():
        data['all_jobs']=data['plan']['jobs']
        data['calibration_jobs']=[j for j in data['all_jobs'] if j.get('calibration_not_scored')]
        data['plan']={**data['plan'],'jobs':[j for j in data['all_jobs'] if not j.get('calibration_not_scored')]}
    return cells,cfg


def blocked_reason(job,result):
    if job.get('experiment_kind')!='controlled':return None
    status=result.get('status','')
    if status in ('blocked','budget_infeasible','not_run_visual_gate_unavailable','not_run_prefix_unavailable'):
        return status
    if any(x in str(result.get('failure_category','')) for x in ('dependency','control_gate','prefix_unavailable')):
        return result.get('failure_category')
    native=result.get('native_result_path')
    if native and Path(native).exists():
        value=parent.read(native);source=value.get('source_controlled_status')
        if source in ('budget_infeasible','not_run_visual_gate_unavailable','not_run_prefix_unavailable'):
            return source
        if value.get('error_type') in ('ControlGateUnavailable','BudgetInfeasible'):
            return value['error_type']
    return None


def inventory_cell(cell,data,out):
    ordinary=[];blocked=[]
    for job in data['plan']['jobs']:
        rp=data['root']/'jobs'/job['job_id']/'attempts/attempt_001/result.json'
        result=parent.read(rp) if rp.exists() else {};reason=blocked_reason(job,result)
        if reason:
            blocked.append({'cell':cell,'job_id':job['job_id'],'question_id':job['question_id'],'repeat':job['repeat'],
                            'prediction_status':result.get('status'),'cleanup_confirmed':parent.base.clean(result),
                            'score':None,'score_reason':'controlled_blocked:'+reason,'excluded_from_accuracy':True})
        else:ordinary.append(job)
    pending,rows=_original_inventory(cell,{**data,'plan':{**data['plan'],'jobs':ordinary}},out)
    return pending,rows+blocked


def report(cells,out,with_cost=False):
    pending=[];allrows=[];summaries={}
    for cell,data in cells.items():
        candidates,rows=inventory_cell(cell,data,out);pending+=candidates;allrows+=rows
        eligible=[r for r in rows if not r.get('excluded_from_accuracy')];known=[r['score'] for r in eligible if r['score'] is not None]
        terminal=sum(r['cleanup_confirmed'] and (r['prediction_status'] in ('completed','failed','timeout') or r.get('excluded_from_accuracy')) for r in rows)
        n=len(eligible);missing=n-len(known)
        calibration_terminal=0
        for job in data['calibration_jobs']:
            path=data['root']/'jobs'/job['job_id']/'attempts/attempt_001/result.json'
            value=parent.read(path) if path.exists() else {}
            calibration_terminal+=int(parent.base.clean(value) and value.get('status') in ('completed','failed','timeout','blocked','not_started'))
        summaries[cell]={'planned':len(rows),'scoring_denominator':n,'calibration_excluded':len(data['calibration_jobs']),
                         'calibration_terminal':calibration_terminal,
                         'controlled_blocked_excluded':len(rows)-n,'terminal':terminal,'known_scores':len(known),'missing_scores':missing,
                         'correct':sum(known),'accuracy':sum(known)/n if n and not missing else None,
                         'accuracy_bounds':[sum(known)/n,(sum(known)+missing)/n] if n else [None,None]}
    result={'at':parent.base.bc.now(),'version':VERSION,'cells':summaries,'ready_to_grade':len(pending),
            'all_terminal':all(x['terminal']==x['planned'] and x['calibration_terminal']==x['calibration_excluded'] for x in summaries.values()),
            'interpretation':'Execution recovery subset only. Calibration excluded; blocked control comparisons are missing/excluded, not incorrect. Clean task failures/timeouts score zero. Retry attempts are not extra seeds.'}
    parent.atomic(out/'observations.json',allrows);parent.atomic(out/'summary.json',result)
    if with_cost:parent.atomic(out/'resources.json',resources(cells,out))
    return pending,result


def resources(cells,out):
    all_cells={k:{**v,'plan':{**v['plan'],'jobs':v['all_jobs']}} for k,v in cells.items()}
    result=prediction_resources(all_cells,out)
    for cell,data in cells.items():
        usage=[];count=0
        for job in data['all_jobs']:
            directory=out/'cells'/cell/'jobs'/job['job_id']/'http-attempts'
            for folder in directory.glob('attempt_*'):
                if not (folder/'started.json').exists():continue
                count+=1;p=folder/'terminal.json';value=parent.read(p) if p.exists() else {}
                usage.append({'raw_provider_usage':value.get('raw_provider_usage'),'_incomplete':not bool(value)})
        if count:
            result['cells'][cell]['judge']=aggregate(usage)
            result['cells'][cell]['judge_http_attempt_count']=count
    return result


def explicit_proxy_open(request,timeout):
    # Explicit routing must not be bypassed by inherited NO_PROXY settings.
    import httpx
    with httpx.Client(proxy=PROXY,trust_env=False,timeout=timeout,follow_redirects=False) as client:
        response=client.post(request.full_url,content=request.data,headers=dict(request.header_items()))
    if response.status_code>=400:
        raise urllib.error.HTTPError(request.full_url,response.status_code,'provider response',response.headers,io.BytesIO(response.content))
    value=io.BytesIO(response.content);value.status=response.status_code;value.headers=response.headers
    return value


def route_opener(directory,opener=None):
    opener=opener or explicit_proxy_open
    def send(request,timeout):
        payload=json.loads(request.data)
        if payload.get('model') not in ROUTES:raise ValueError('Unapproved judge model')
        for index,route in enumerate(ROUTES,1):
            folder=directory/'http-attempts'/f'attempt_{index:03d}'
            body=json.dumps({**payload,'model':route},ensure_ascii=False).encode();started=time.monotonic()
            parent.immutable(folder/'started.json',{'actual_model':route,'body_sha256':parent.base.bc.sha_bytes(body),'at':parent.base.bc.now()})
            terminal={'actual_model':route,'raw_provider_usage':None,'provider_internal_latency_seconds':None}
            wire=urllib.request.Request(request.full_url,data=body,headers=dict(request.header_items()),method='POST')
            try:
                with opener(wire,timeout=timeout) as response:
                    raw=response.read();status=getattr(response,'status',200);headers=response.headers
                try:terminal['raw_provider_usage']=json.loads(raw).get('usage')
                except (ValueError,AttributeError):pass
                terminal.update(status='response',http_status=status)
                result=io.BytesIO(raw);result.status=status;result.headers=headers
                return result
            except urllib.error.HTTPError as error:
                raw=error.read()
                try:terminal['raw_provider_usage']=json.loads(raw).get('usage')
                except (ValueError,AttributeError):pass
                terminal.update(status='http_error',http_status=error.code,error_type=type(error).__name__)
                if error.code not in (403,404,408,429,500,502,503,504) or index==len(ROUTES):raise
            except BaseException as error:
                terminal.update(status='acceptance_unknown',error_type=type(error).__name__)
                raise  # Never resubmit a potentially billed unknown request.
            finally:
                terminal['client_http_seconds']=time.monotonic()-started
                parent.atomic(folder/'terminal.json',terminal)
        raise AssertionError('Missing terminal judge outcome')
    return send


def grade_bound(candidate,cfg,env):
    binding=candidate['binding']
    if parent.sha(binding['result_path'])!=binding['result_sha256']:raise ValueError('Prediction changed before judge')
    for path,digest in binding['gold_sources_sha256'].items():
        if parent.sha(path)!=digest:raise ValueError('Gold changed before judge')
    result=parent.base.bc.grade(candidate,cfg,env,opener=route_opener(candidate['directory']))
    if result.get('status')=='already_claimed':return result
    if result.get('status')=='scored' and result.get('api_calls'):
        if result.get('finish_reason')!='stop':result.update(status='incomplete_judge_response',score=None)
        elif result.get('returned_model') not in (*ROUTES,'deepseek-v4-1-flash-261017'):
            result.update(status='judge_model_identity_unverified',score=None)
    attempts=list((candidate['directory']/'http-attempts').glob('attempt_*/started.json'))
    result.update(version=VERSION,api_calls=len(attempts),judge_http_attempts=len(attempts),
                  inherited_judge_protocol='Hermes answer-equivalence + numeric JSON score 0/1')
    parent.atomic(candidate['directory']/'grade.json',result)
    return result


def main():
    import sys
    if '--dry' in sys.argv:sys.argv.remove('--dry')
    with patch.object(parent,'prepare',prepare),patch.object(parent,'report',report),patch.object(parent,'resources',resources),\
         patch.object(parent,'grade_bound',grade_bound),patch.object(parent,'VERSION',VERSION),\
         patch.object(parent,'DEFAULT',DEFAULT),patch.object(parent,'OUT',OUT):
        parent.main()


if __name__=='__main__':main()
