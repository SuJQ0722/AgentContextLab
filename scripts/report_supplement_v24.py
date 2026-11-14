"""Private first-attempt scoring and public progress for timeout-only recovery."""
import argparse,fcntl,json,time
from collections import Counter
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from lab import ROOT,environment
from supplement_recovery_v24 import DEFAULT,read,sha,save,validate_plan
import judge_bc_v3_completed as bc
from judge_visual_hosted_retry_v1 import gold_sources
from judge_inline_retry5_v8 import explicit_proxy_open
from judge_inline_model_alias_v9 import ACCEPTED_RETURNED_MODELS
from judge_controlled_source_v20 import valid_control

GRADES=ROOT/'outputs/grading/supplement-timeout-v24'
REPORT=ROOT/'outputs/reports/supplement-timeout-v24'
def inventory(root,plan,gold,hashes):
    rows=[];pending=[]
    for job in plan['jobs']:
        attempt=root/'jobs'/job['job_id']/'attempts/attempt_001';rp=attempt/'result.json'
        result=read(rp)if rp.exists()else{}
        if result and result.get('supplement_version')!=plan['version'] and result.get('failure_category')!='launcher_error':
            result={}  # Base supervisor writes first; wait for the finalized supplement receipt.
        row={k:job.get(k)for k in ('job_id','scope','slot_id','question_id','repeat','method','harness','experiment_kind','scale')}
        row.update(status=result.get('status','active'if(attempt/'dispatch.json').exists()else'pending'),score=None,
            protocol='200turn/3h/8workers/3physical-sends',end_to_end_seconds=result.get('end_to_end_seconds'))
        if result.get('status')=='completed' and result.get('slot_released')is True:
            valid=True
            if job['scope']=='controlled':
                native=read(result['native_result_path']);target=read(job['controlled_job']['target_path'])
                valid=valid_control(native.get('control_gate')or{},target)
                row['control_valid']=valid
            if valid:
                key='mmbc'if job.get('experiment_kind')=='mmbc'or job['scope']=='controlled'else'bc'
                secret=gold[key][job['question_id']]
                spec=read(job['controlled_job']['spec_path'])if job['scope']=='controlled'else job
                if spec['question']!=secret['question']:raise ValueError('Gold/prediction question mismatch')
                final=result.get('final');prediction=final if isinstance(final,str)else(final or{}).get('text','')
                directory=GRADES/'jobs'/job['job_id'];binding={'job_id':job['job_id'],'result_path':str(rp),'result_sha256':sha(rp),'gold_sources_sha256':hashes,'prediction_sha256':bc.sha_bytes(prediction.encode())}
                gp=directory/'grade.json'
                if gp.exists():
                    grade=read(gp)
                    if any(grade.get(k)!=v for k,v in binding.items()):raise ValueError('Grade binding changed')
                    row['grade_status']=grade.get('status')
                    if grade.get('status')=='scored':row['score']=grade['score']
                elif not(directory/'request-started.json').exists():pending.append({'directory':directory,'binding':binding,'question':secret['question'],'answer':secret['answer'],'prediction':prediction})
        rows.append(row)
    return rows,pending

def grade(candidate,cfg,env):
    result=bc.grade(candidate,cfg,env,opener=explicit_proxy_open)
    if result.get('status')=='scored'and result.get('api_calls'):
        if result.get('returned_model')not in ACCEPTED_RETURNED_MODELS or result.get('finish_reason')!='stop':result.update(status='unverified_judge_response',score=None)
    if result.get('status')!='already_claimed':bc.atomic(candidate['directory']/'grade.json',result)
    return result

def report(root,rows):
    groups={}
    for row in rows:
        key='/'.join(str(row.get(k))for k in ('scope','experiment_kind','harness','method','scale'))
        groups.setdefault(key,[]).append(row)
    summary={key:{'selected_timeouts':len(rr),'states':dict(Counter(r['status']for r in rr)),
        'scored':sum(r['score']is not None for r in rr),'correct':sum(r['score']or 0 for r in rr)}for key,rr in groups.items()}
    save(REPORT/'latest.json',{'at':time.time(),'groups':summary,'observations':rows,'selected':len(rows),
         'states':dict(Counter(r['status']for r in rows)),
         'interpretation':'Only latest timeout slots retried once. Retained old completions use historical 500-turn protocol; merged coverage is mixed-protocol, never a uniform 200-turn result.',
         'failed_and_timeout_scores':'Separate operational failures; report fixed-denominator lower bounds, not observed task accuracy.',
         'missing_cost_is_zero':False,'provider_internal_latency_measured':False})

def main():
    p=argparse.ArgumentParser();p.add_argument('--watch',action='store_true');p.add_argument('--live',action='store_true');a=p.parse_args()
    root=DEFAULT;plan=validate_plan(root);gold,hashes=gold_sources()
    GRADES.mkdir(parents=True,exist_ok=True);GRADES.chmod(0o700)
    lock=(GRADES/'controller.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    cfg={'judge_model':bc.MODEL,'max_tokens':8192,'temperature':0,'top_p':1,'timeout_seconds':180}
    env,_=environment(ROOT,'hermes')
    while True:
        rows,pending=inventory(root,plan,gold,hashes);report(root,rows)
        if a.live and pending:
            with ThreadPoolExecutor(max_workers=2)as pool:list(pool.map(lambda c:grade(c,cfg,env),pending))
        if not a.watch or all(r['status']not in ('pending','active')for r in rows)and not pending:break
        time.sleep(30)
if __name__=='__main__':main()
