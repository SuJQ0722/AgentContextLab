"""Recover explicit failed judge calls without changing predictions or old grades."""
import argparse
import concurrent.futures
import fcntl
import hashlib
import json
from pathlib import Path
import time
import urllib.request
import judge_visual_hosted_retry_v1 as parent
import judge_mmbc100 as base
from lab import ROOT, environment
from visual_transport_runtime_v3 import ALLOWED_MODELS, initial_route_index

SOURCE = ROOT / 'outputs/grading/visual-inline-failure-retry-v5'
OUT = ROOT / 'outputs/grading/visual-inline-judge-recovery-v1'
VERSION = 'visual-inline-judge-recovery-v1'

def eligible(grade):
    return grade.get('status') == 'http_error' and grade.get('http_status') in (408,429,500,502,503,504)

def prepare(source, out):
    source, out = Path(source).resolve(), Path(out).resolve()
    if source == out or source in out.parents or out in source.parents:
        raise ValueError('Independent private recovery output required')
    out.mkdir(parents=True, exist_ok=True); out.chmod(0o700)
    gold, hashes = parent.gold_sources()
    candidates=[]
    for cell in sorted((source/'cells').iterdir()):
        binding=base.read(cell/'source-binding.json')
        root=Path(binding['root']); plan=base.read(root/'plan.json')
        if base.sha(root/'plan.json')!=binding['plan_sha256']:raise ValueError('Plan changed')
        for job in plan['jobs']:
            gd=cell/'jobs'/job['job_id']; gp=gd/'grade.json'
            if not gp.exists() or not eligible(base.read(gp)):continue
            b=base.read(gd/'binding.json'); result=base.read(b['result_path'])
            if base.sha(b['result_path'])!=b['result_sha256'] or result['status']!='completed' or not base.clean(result):raise ValueError('Prediction changed or incomplete')
            if b['gold_sources_sha256']!=hashes:raise ValueError('Gold source changed')
            secret=gold[parent.gold_key(job)][job['question_id']]
            if secret['question']!=job['question']:raise ValueError('Question mismatch')
            value=result['final']; prediction=value if isinstance(value,str) else value.get('text','')
            original=base.read(gd/'request.json')
            prompt=base.bc.build_judge_prompt(job['question'],prediction,secret['answer'])
            expected={'model':base.MODEL,'messages':[{'role':'user','content':prompt}],'max_tokens':8192,'temperature':0,'top_p':1}
            if original!=expected:raise ValueError('Scoring protocol changed')
            c={'cell':cell.name,'job_id':job['job_id'],'binding':b,'question':job['question'],'answer':secret['answer'],'prediction':prediction,
               'old_grade_path':str(gp),'old_grade_sha256':base.sha(gp),'directory':out/'cells'/cell.name/'jobs'/job['job_id']}
            candidates.append(c)
    manifest={'version':VERSION,'source':str(source),'old_grades_preserved':True,'selection_uses_scores':False,
              'allowed_models':list(ALLOWED_MODELS),'max_tokens':8192,'temperature':0,'top_p':1,'concurrency':4,
              'recovery_seconds_per_job':900,'gold_sources_sha256':hashes,
              'jobs':[{k:c[k] for k in ('cell','job_id','old_grade_path','old_grade_sha256')}for c in candidates]}
    base.immutable(out/'protocol.json',manifest)
    return candidates

def judge_one(candidate, cfg, env):
    result=base.bc.grade(candidate,cfg,env,opener=urllib.request.build_opener(urllib.request.ProxyHandler({})).open)
    if result.get('status')=='already_claimed':return result
    if result.get('status')=='scored' and result.get('api_calls')==1:
        if result.get('finish_reason')!='stop':result.update(status='incomplete_judge_response',score=None)
        elif result.get('returned_model') not in (*ALLOWED_MODELS,'deepseek-v4-1-flash-261017','deepseek-v4.1-flash-1017'):
            result.update(status='judge_model_identity_unverified',score=None)
    result['version']=VERSION
    base.atomic(candidate['directory']/'grade.json',result)
    return result

def recover(c, env, call=judge_one, sleep=time.sleep, monotonic=time.monotonic):
    directory=c['directory'];directory.mkdir(parents=True,exist_ok=True)
    lock=(directory/'controller.lock').open('a')
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    try:
        if (directory/'resolved.json').exists():return base.read(directory/'resolved.json')
        deadline=monotonic()+900; start=initial_route_index(c['cell']+'/'+c['job_id']); attempt=0
        while monotonic()<deadline:
            route=ALLOWED_MODELS[(start+attempt)%4];ad=directory/'attempts'/f'attempt_{attempt+1:03d}'
            if (ad/'request-started.json').exists() and not (ad/'grade.json').exists():
                raise RuntimeError('Unresolved previous paid request requires audit')
            if (ad/'grade.json').exists():g=base.read(ad/'grade.json')
            else:
                if base.sha(c['old_grade_path'])!=c['old_grade_sha256']:raise ValueError('Old grade changed')
                for p,h in c['binding']['gold_sources_sha256'].items():
                    if base.sha(p)!=h:raise ValueError('Gold changed')
                candidate={k:c[k]for k in ('binding','question','answer','prediction')};candidate['directory']=ad
                cfg={'judge_model':route,'max_tokens':8192,'temperature':0,'top_p':1,'timeout_seconds':min(180,max(1,int(deadline-monotonic())))}
                g=call(candidate,cfg,env)
            grade_path=ad/'grade.json'
            if g.get('status')=='judge_model_identity_unverified' and g.get('returned_model')=='deepseek-v4.1-flash-1017':
                raw=base.read(ad/'response.json');choice=raw['choices'][0]
                score=base.bc.strict_score(choice.get('message',{}).get('content'))
                if raw.get('model')=='deepseek-v4.1-flash-1017' and choice.get('finish_reason')=='stop' and score is not None:
                    g={**g,'status':'scored','score':score,'identity_revalidation':'Exact configured base model ID, no new model call',
                       'original_grade_sha256':base.sha(ad/'grade.json'),'response_sha256':base.sha(ad/'response.json')}
                    grade_path=ad/'identity-validated-grade.json';base.immutable(grade_path,g)
            if g.get('status')=='scored':
                resolved={'version':VERSION,'cell':c['cell'],'job_id':c['job_id'],'score':g['score'],
                          'grade_path':str(grade_path),'actual_route':route,'old_grade_path':c['old_grade_path'],
                          'old_grade_sha256':c['old_grade_sha256'],'status':'scored','at':base.bc.now()}
                base.immutable(directory/'resolved.json',resolved);return resolved
            # Retry service/transport errors only; never resample a score or judge formatting verdict.
            if not eligible(g) and g.get('status')!='judge_error':return {'status':g.get('status'),'cell':c['cell'],'job_id':c['job_id']}
            attempt+=1
            if attempt%4==0:
                delay=min(60*(2**min(attempt//4-1,1)),120)
                if monotonic()+delay>=deadline:break
                began=monotonic();sleep(delay)
                base.atomic(directory/f'backoff_{attempt:03d}.json',{'actual_wait_seconds':monotonic()-began,'planned_wait_seconds':delay})
        return {'status':'retry_deadline','cell':c['cell'],'job_id':c['job_id']}
    finally:lock.close()

def merged_report(source,out):
    rows=base.read(source/'observations.json'); usage=[]
    for row in rows:
        directory=out/'cells'/row['cell']/'jobs'/row['job_id']
        if (directory/'resolved.json').exists():
            resolved=base.read(directory/'resolved.json')
            if base.sha(resolved['old_grade_path'])!=resolved['old_grade_sha256']:raise ValueError('Resolved grade source changed')
            row.update(score=resolved['score'],score_reason='judged_completed_recovered',recovery_grade=resolved['grade_path'])
        for p in (directory/'attempts').glob('attempt_*/grade.json'):
            g=base.read(p)
            if g.get('api_calls')!=0:usage.append({'raw_provider_usage':g.get('raw_provider_usage'),'_incomplete':g.get('raw_provider_usage') is None})
    base.atomic(out/'observations-merged.json',rows)
    base.atomic(out/'resources.json',{'scope':'Additional judging only; old judging and predictions excluded',
                                     'usage':base.aggregate(usage),'usd':None})
    base.atomic(out/'merged-summary.json',{'at':base.bc.now(),'scope':'V5 conditional retry population only; CLI supplement remains separate',
        'rows':len(rows),'completed':sum(r['prediction_status']=='completed'for r in rows),
        'completed_missing_grade':sum(r['prediction_status']=='completed'and r['score'] is None for r in rows),
        'original_files_preserved':True})

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,default=SOURCE);p.add_argument('--output',type=Path,default=OUT);p.add_argument('--live',action='store_true');a=p.parse_args()
    candidates=prepare(a.source,a.output)
    if not a.live:print(json.dumps({'live':False,'eligible':len(candidates),'model_calls':0}));return
    env,_=environment(ROOT,'hermes');results=[]
    with (a.output/'controller.lock').open('a')as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        with concurrent.futures.ThreadPoolExecutor(max_workers=4)as pool:
            tasks={pool.submit(recover,c,env):c for c in candidates}
            for future in concurrent.futures.as_completed(tasks):
                c=tasks[future]
                try:results.append(future.result())
                except Exception as exc:results.append({'cell':c['cell'],'job_id':c['job_id'],'status':'local_error','error_type':type(exc).__name__})
                base.atomic(a.output/'summary.json',{'at':base.bc.now(),'planned':len(candidates),'finished':len(results),'scored':sum(r['status']=='scored'for r in results),'results':results})
    merged_report(a.source,a.output)
    print(json.dumps({'finished':len(results),'scored':sum(r['status']=='scored'for r in results)}))
if __name__=='__main__':main()
