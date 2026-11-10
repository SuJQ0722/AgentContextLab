"""Private continuous scoring of fixed execution-failure retries; never selects tasks."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
import fcntl
import json
import os
from pathlib import Path
import signal
import time
import judge_mmbc100 as base
from lab import ROOT, environment

VERSION='judge-visual-hosted-failure-retry-v1'
DEFAULT=ROOT/'outputs/campaigns/visual-hosted-failure-retry-v1'
OUT=ROOT/'outputs/grading/visual-hosted-failure-retry-v1'
read,sha,atomic,immutable=base.read,base.sha,base.atomic,base.immutable

def gold_sources():
    paths={'bc':ROOT/'outputs/grading/bc-bounded-retry-v1/private/gold.json',
           'mmbc':ROOT/'outputs/grading/mmbc100-hermes-deepseek-v1/private/selected-source.jsonl'}
    gold={'bc':read(paths['bc'])}
    gold['mmbc']={r['question_id']:{'question':r['source_row']['question'],'answer':r['answer']}
                  for r in base.jsonlines(paths['mmbc'])}
    manifest_path=ROOT/'outputs/cohorts/manifest.json';manifest=read(manifest_path)
    for dataset in ('browsecomp_v3','mmbrowsecomp'):
        p=ROOT/'outputs/cohorts'/f'{dataset}.jsonl'
        if sha(p)!=manifest['datasets'][dataset]['cohort_sha256']:raise ValueError('Controlled gold cohort changed')
        paths[dataset]=p;gold[dataset]={r['id']:{'question':r['question'],'answer':r['answer']}for r in base.jsonlines(p)}
    paths['controlled_manifest']=manifest_path
    return gold,{str(p):sha(p)for p in paths.values()}

def gold_key(job):
    if job['experiment_kind']=='controlled':
        p=Path(job['controlled_spec_path'])
        if sha(p)!=job['controlled_spec_sha256']:raise ValueError('Controlled spec changed')
        return read(p)['dataset']
    return 'mmbc'if job['experiment_kind']=='mmbc'else'bc'

def prepare(root,out):
    root,out=Path(root).resolve(),Path(out).resolve()
    if root==out or root in out.parents or out in root.parents:raise ValueError('Private grading must be outside prediction tree')
    from prepare_visual_hosted_retry_v1 import load_validate
    inventory=read(root/'inventory.json');gold,gold_hashes=gold_sources();cells={}
    out.mkdir(parents=True,exist_ok=True);out.chmod(0o700)
    for item in inventory['cells']:
        cell=item['cell'];source=root/'cells'/cell
        plan,_=load_validate(source)
        if sha(source/'plan.json')!=item['plan_sha256']:raise ValueError('Inventory plan binding changed')
        answers={}
        for job in plan['jobs']:
            if job['model']!=base.MODEL:raise ValueError('Judge model mismatch')
            secret=gold[gold_key(job)][job['question_id']]
            if secret['question']!=job['question']:raise ValueError('Prediction question differs from gold')
            if job['job_id'] in answers:raise ValueError('Duplicate prediction identity')
            answers[job['job_id']]=secret['answer']
        binding={'root':str(source),'cell':cell,'plan_sha256':sha(source/'plan.json'),
                 'config_sha256':sha(source/'experiment.json'),'gold_sources_sha256':gold_hashes}
        immutable(out/'cells'/cell/'source-binding.json',binding)
        cells[cell]={'root':source,'plan':plan,'answers':answers,'binding':binding}
    cfg={'version':VERSION,'judge_model':base.MODEL,'max_tokens':8192,'temperature':0,'top_p':1,
         'timeout_seconds':180,'api_retries':0,'concurrency_cap':4,
         'inventory_sha256':sha(root/'inventory.json'),'sources_sha256':{n:sha(ROOT/'scripts'/n)for n in
         ('judge_visual_hosted_retry_v1.py','judge_mmbc100.py','judge_bc_v3_completed.py','monitor_bc_campaign_v3.py')},
         'hermes_judge_sha256':sha(ROOT/'hermes-agent/Browsecomp_eval/browsecomp_eval/judge.py')}
    immutable(out/'protocol.json',cfg)
    return cells,cfg

def inventory_cell(cell,data,out):
    source=data['root'];binding=data['binding'];candidates=[];rows=[]
    if sha(source/'plan.json')!=binding['plan_sha256'] or sha(source/'experiment.json')!=binding['config_sha256']:
        raise ValueError('Frozen prediction plan/config changed')
    for job in data['plan']['jobs']:
        attempt=source/'jobs'/job['job_id']/'attempts/attempt_001';rp=attempt/'result.json'
        directory=out/'cells'/cell/'jobs'/job['job_id'];result=read(rp)if rp.exists()else{}
        status=result.get('status','pending');score=None;reason='pending_prediction';clean=base.clean(result)
        if result and any(result.get(k)!=job[k]for k in ('job_id','harness','strategy','question_id','repeat','model')):
            raise ValueError('Result identity changed')
        if clean and status in ('failed','timeout'):score=0.;reason='confirmed_operational_failure'
        elif clean and status=='completed':
            final=result.get('final');prediction=final if isinstance(final,str)else(final or{}).get('text','')
            if not isinstance(prediction,str):raise ValueError('Prediction must be text')
            b={**binding,'job_id':job['job_id'],'harness':job['harness'],'strategy':job['strategy'],
               'question_id':job['question_id'],'repeat':job['repeat'],'result_path':str(rp),
               'attempt_path':str(attempt),'result_sha256':sha(rp),
               'question_sha256':base.bc.sha_bytes(job['question'].encode()),
               'prediction_sha256':base.bc.sha_bytes(prediction.encode())}
            if (directory/'binding.json').exists() and read(directory/'binding.json')!=b:raise ValueError('Judged source changed')
            reason='ungraded_completed'
            if (directory/'grade.json').exists():
                grade=read(directory/'grade.json')
                if any(grade.get(k)!=v for k,v in b.items()):raise ValueError('Grade source binding mismatch')
                if grade.get('status')=='scored'and type(grade.get('score'))in(int,float)and grade['score']in(0,1):
                    score=float(grade['score']);reason='judged_completed'
                else:reason=grade.get('status','judge_error')
            elif (directory/'request-started.json').exists():reason='unresolved_judge_request'
            elif (directory/'local-error.json').exists():reason='judge_local_error'
            else:candidates.append({'directory':directory,'binding':b,'question':job['question'],
                 'answer':data['answers'][job['job_id']],'prediction':prediction})
        elif result:reason='cleanup_unconfirmed'if not clean else status
        rows.append({'cell':cell,'job_id':job['job_id'],'question_id':job['question_id'],'repeat':job['repeat'],
                     'prediction_status':status,'cleanup_confirmed':clean,'score':score,'score_reason':reason})
    return candidates,rows

def report(cells,out,with_cost=False):
    candidates=[];allrows=[];summary={}
    for cell,data in cells.items():
        pending,rows=inventory_cell(cell,data,out);candidates.extend(pending);allrows.extend(rows)
        known=[r['score']for r in rows if r['score']is not None];n=len(rows);missing=n-len(known)
        summary[cell]={'planned':n,'terminal':sum(r['cleanup_confirmed']and r['prediction_status']in('failed','timeout','completed')for r in rows),
          'prediction_states':dict(Counter(r['prediction_status']for r in rows)),
          'score_states':dict(Counter(r['score_reason']for r in rows)),'known_scores':len(known),'missing_scores':missing,
          'correct':sum(known),'accuracy':sum(known)/n if n and not missing else None,
          'accuracy_bounds':[sum(known)/n,(sum(known)+missing)/n]if n else[None,None]}
    value={'at':base.bc.now(),'version':VERSION,'cells':summary,'ready_to_grade':len(candidates),
           'all_terminal':all(v['terminal']==v['planned']for v in summary.values()),
           'interpretation':'New fixed execution-failure retries only; no answer-based selection. Completed old attempts retained elsewhere. Not independent avg3; failures and missing grades distinct. Controlled visual outcomes do not establish new matched three-arm groups.'}
    atomic(out/'observations.json',allrows);atomic(out/'summary.json',value)
    if with_cost:atomic(out/'resources.json',resources(cells,out))
    return candidates,value

def resources(cells,out):
    from monitor_bc_campaign_v3 import inspect_attempt,aggregate
    result={}
    for cell,data in cells.items():
        usage=[];judges=[];details=[]
        for job in data['plan']['jobs']:
            for attempt in (data['root']/'jobs'/job['job_id']/'attempts').glob('attempt_*'):
                info,raw=inspect_attempt(attempt,job['harness']);usage.extend(raw);details.append(info)
            gd=out/'cells'/cell/'jobs'/job['job_id']
            if (gd/'request-started.json').exists():
                g=read(gd/'grade.json')if(gd/'grade.json').exists()else{}
                if g.get('api_calls')!=0:judges.append({'raw_provider_usage':g.get('raw_provider_usage'),'_incomplete':not bool(g)})
        result[cell]={'new_prediction_all_attempts':aggregate(usage),'judge':aggregate(judges),'observed_attempts':len(details),
                      'actual_usd':None,'provider_api_latency_seconds':None}
    return {'at':base.bc.now(),'cells':result,'scope':'All attempts in this new campaign including failures; previous campaigns preserved separately, not silently added or treated as zero. Tokens are raw observed cached/non-cache/output; incomplete calls remain unknown.'}

def grade_bound(candidate,cfg,env):
    b=candidate['binding']
    if sha(b['result_path'])!=b['result_sha256']:raise ValueError('Prediction changed before paid judging')
    for p,h in b['gold_sources_sha256'].items():
        if sha(p)!=h:raise ValueError('Gold source changed before paid judging')
    return base.judge_one(candidate,cfg,env)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=DEFAULT);p.add_argument('--output',type=Path,default=OUT)
    p.add_argument('--live',action='store_true');p.add_argument('--watch',action='store_true');p.add_argument('--concurrency',type=int,default=4);a=p.parse_args()
    if not 1<=a.concurrency<=4:p.error('Concurrency must be 1..4')
    cells,cfg=prepare(a.root,a.output);pending,summary=report(cells,a.output,True)
    if not a.live:print(json.dumps({'live':False,'ready_to_grade':len(pending),'cells':summary['cells']}));return
    lock=(a.output/'controller.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    env,_=environment(ROOT,'hermes');stopping=False;next_scan=0;last_cost=time.time();futures={}
    def stop(*args):
        nonlocal stopping
        stopping=True
    signal.signal(signal.SIGINT,stop);signal.signal(signal.SIGTERM,stop)
    with ThreadPoolExecutor(max_workers=a.concurrency)as pool:
        while True:
            if time.time()>=next_scan and not stopping:
                pending,summary=report(cells,a.output,time.time()-last_cost>=300)
                if time.time()-last_cost>=300:last_cost=time.time()
                occupied={str(c['directory'])for c in futures.values()};pending=[c for c in pending if str(c['directory'])not in occupied];next_scan=time.time()+20
            while pending and not stopping and len(futures)<a.concurrency:
                c=pending.pop(0);futures[pool.submit(grade_bound,c,cfg,env)]=c
            if futures:
                done,_=wait(futures,timeout=1,return_when=FIRST_COMPLETED)
                for f in done:
                    c=futures.pop(f)
                    try:f.result()
                    except Exception as e:atomic(c['directory']/'local-error.json',{'at':base.bc.now(),'error_type':type(e).__name__,'automatic_retry':False})
                    next_scan=0
            atomic(a.output/'status.json',{'at':base.bc.now(),'pid':os.getpid(),'active':len(futures),'pending':len(pending),
                 'concurrency':a.concurrency,'stopping':stopping,'all_terminal':summary['all_terminal']})
            if not futures and(stopping or(not pending and(summary['all_terminal']or not a.watch))):break
            if not futures:time.sleep(1)
    _,summary=report(cells,a.output,True)
    atomic(a.output/'status.json',{'at':base.bc.now(),'pid':os.getpid(),'active':0,'pending':0,'finished':True,'all_terminal':summary['all_terminal']})

if __name__=='__main__':main()
