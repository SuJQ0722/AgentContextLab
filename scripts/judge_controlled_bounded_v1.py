#!/usr/bin/env python3
"""Private answer-equivalence judging; all completed bounded arms, matched gates reported separately."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import fcntl
import json
import os
from pathlib import Path
import signal
import statistics
import time
from lab import ROOT, environment
import judge_mmbc100 as approved
from judge_bc_v3_completed import atomic, immutable, sha, sha_bytes, now
from controlled_native_report_v4 import aggregate, accounting
from prepare_controlled_bounded_v1 import DEFAULT, MODEL, load_validate, read
from run_controlled_bounded_v1 import disposition, group_gate, alive

VERSION='judge-controlled-bounded-v1'
OUT=ROOT/'outputs/grading/controlled-native-bounded-v1'
METHODS=('visual','summary','window')
DATASETS=('browsecomp_v3','mmbrowsecomp')
FAILURES={'failed','timeout','budget_infeasible'}


def prepare(root,out):
    root,out=Path(root).resolve(),Path(out).resolve()
    if root==out or root in out.parents or out in root.parents:raise ValueError('Gold must remain outside prediction namespace')
    plan,_=load_validate(root);out.mkdir(parents=True,exist_ok=True);out.chmod(0o700)
    manifest=read(ROOT/'outputs/cohorts/manifest.json');cohorts={};hashes={}
    for ds in DATASETS:
        source=ROOT/'outputs/cohorts'/f'{ds}.jsonl';hashes[ds]=sha(source)
        if hashes[ds]!=manifest['datasets'][ds]['cohort_sha256']:raise ValueError('Frozen gold source changed')
        cohorts[ds]={r['id']:r for r in map(json.loads,source.read_text().splitlines())}
    old=read(plan['definition']['source_plan_path']);sources={p['key']:p['spec'] for p in old['prefixes']}
    gold={}
    for job in plan['jobs']:
        spec=sources[job['prefix_key']];row=cohorts[job['dataset']][spec['question_id']]
        if row['question']!=spec['question']:raise ValueError('Original question/gold identity differs')
        gold[job['job_id']]={'question':row['question'],'answer':row['answer'],'question_id':spec['question_id'],'repeat':spec['repeat']}
    immutable(out/'private/gold.json',gold)
    config={'version':VERSION,'judge_model':MODEL,'max_tokens':8192,'temperature':0,'top_p':1,
        'timeout_seconds':180,'concurrency':1,'api_retries':0,'plan_sha256':sha(root/'plan.json'),
        'config_sha256':sha(root/'experiment.json'),'cohort_sha256':hashes,'gold_sha256':sha(out/'private/gold.json'),
        'sources_sha256':{n:sha(ROOT/'scripts'/n) for n in ('judge_controlled_bounded_v1.py','judge_mmbc100.py','judge_bc_v3_completed.py')},
        'judge_prompt_sha256':sha(ROOT/'hermes-agent/Browsecomp_eval/browsecomp_eval/judge.py'),
        'judge_definition':'Approved Hermes answer equivalence, not an asserted separate official MMBC rubric',
        'score_policy':'Confirmed failed/timeout/budget infeasible is execution score0; ungraded completed/interrupted unknown remains null; gate selection is reported separately',
        'usd':None,'provider_latency_seconds':None}
    immutable(out/'protocol.json',config)
    return plan,gold,config


def summarize(rows):
    known=[r['score'] for r in rows if r['score'] is not None];n=len(rows);correct=sum(known);missing=n-len(known)
    result={'denominator':n,'known':len(known),'missing':missing,'correct':correct,
        'accuracy':correct/n if n and not missing else None,
        'accuracy_bounds':[correct/n,(correct+missing)/n] if n else [None,None],
        'mean_repeat_accuracy':None,'std_repeat_accuracy':None,
        'denominator_by_repeat':{str(rep):sum(r['repeat']==rep for r in rows) for rep in (1,2,3)}}
    groups=[[r['score'] for r in rows if r['repeat']==rep] for rep in (1,2,3)]
    if not missing and all(groups):
        means=[statistics.mean(g) for g in groups]
        result.update(mean_repeat_accuracy=statistics.mean(means),std_repeat_accuracy=statistics.stdev(means))
    return result


def inventory(root,out,plan,gold,config):
    if sha(root/'plan.json')!=config['plan_sha256'] or sha(root/'experiment.json')!=config['config_sha256']:raise ValueError('Source plan/config changed')
    candidates=[];rows=[];groups={};usage=[]
    for p in plan['prefixes']:
        controls={}
        for method in METHODS:
            source=root/'jobs'/p['key']/method
            if (source/'compression-control.json').exists() and (source/'trial-status.json').exists() and not alive(source):
                controls[method]=read(source/'compression-control.json')
        groups[p['key']]=group_gate(controls)
    for job in plan['jobs']:
        jid=job['job_id'];secret=gold[jid];source=Path(job['out']);state=disposition(job,root);dest=out/'jobs'/jid
        row={'job_id':jid,'dataset':job['dataset'],'method':job['method'],'repeat':secret['repeat'],
            'question_id':secret['question_id'],'eligible_prefix':job['eligible'],'status':state,
            'matched_group':groups[job['prefix_key']]['passed'],'score':None,'answer_score':None,'score_reason':state}
        trial=read(source/'trial-status.json') if (source/'trial-status.json').exists() else {}
        confirmed=trial.get('worker_reaped') is True and state!='running'
        if state in FAILURES and confirmed:row.update(score=0.,score_reason='confirmed_execution_failure')
        result=read(source/'result.json') if (source/'result.json').exists() else {}
        if result.get('status')=='completed' and confirmed:
            spec=read(job['spec_path']);control=read(source/'compression-control.json');conversation=read(source/'conversation.json')
            prediction=conversation.get('final_response') or ''
            if not isinstance(prediction,str):raise ValueError('Nontext completed prediction')
            if spec['question']!=secret['question'] or spec['question_id']!=secret['question_id'] or spec['model']!=MODEL:raise ValueError('Source/gold binding mismatch')
            if trial.get('job_id')!=jid or any(result.get(k)!=spec[k] for k in ('question_id','method','repeat')):raise ValueError('Completed result identity differs')
            if control.get('prefix_sha256')!=sha(spec['prefix_path']):raise ValueError('Prefix/control mismatch')
            b={'controlled_grading_version':VERSION,'job_id':jid,'dataset':job['dataset'],'method':job['method'],
                'question_id':secret['question_id'],'repeat':secret['repeat'],'attempt_path':str(source),
                'prediction_sha256':sha_bytes(prediction.encode()),'question_sha256':sha_bytes(secret['question'].encode()),
                'gold_sha256':config['gold_sha256'],'plan_sha256':config['plan_sha256']}
            for name,path in [('result',source/'result.json'),('trial',source/'trial-status.json'),('conversation',source/'conversation.json'),
                ('control',source/'compression-control.json'),('spec',Path(job['spec_path'])),('prefix',Path(spec['prefix_path']))]:
                b.update({name+'_path':str(path),name+'_sha256':sha(path)})
            if (dest/'binding.json').exists() and read(dest/'binding.json')!=b:raise ValueError('Previously graded source changed')
            if (dest/'grade.json').exists():
                grade=read(dest/'grade.json')
                if any(grade.get(k)!=v for k,v in b.items()):raise ValueError('Grade binding changed')
                if grade.get('status')=='scored' and type(grade.get('score')) in (int,float) and grade['score'] in (0,1):
                    row['answer_score']=float(grade['score'])
                    if state=='completed':row.update(score=row['answer_score'],score_reason='judged_completed')
                elif state=='completed':row['score_reason']=grade.get('status','judge_unknown')
            elif (dest/'request-started.json').exists():
                if state=='completed':row['score_reason']='unresolved_judge_request'
            elif (dest/'local-error.json').exists():
                if state=='completed':row['score_reason']='judge_local_error'
            else:
                candidates.append({'directory':dest,'binding':b,'question':secret['question'],'answer':secret['answer'],'prediction':prediction})
                if state=='completed':row['score_reason']='ungraded_completed'
        if (dest/'request-started.json').exists():
            g=read(dest/'grade.json') if (dest/'grade.json').exists() else read(dest/'request-started.json')
            if g.get('api_calls')!=0:usage.append(dict(g,client_stream_seconds=g.get('client_http_seconds')))
        rows.append(row)
    cells={}
    for ds in DATASETS:
        for method in METHODS:
            r=[x for x in rows if x['dataset']==ds and x['method']==method]
            cells[ds+'/'+method]={'original_slots':len(r),'eligible_new':summarize([x for x in r if x['eligible_prefix']]),
                'matched_gate_subset':summarize([x for x in r if x['matched_group']]),
                'all_completed':sum(x['status']=='completed' for x in r),
                'all_completed_judged':sum(x['status']=='completed' and x['answer_score'] is not None for x in r)}
    judge_usage=aggregate(usage)
    judge_usage['latency_definition']='Client HTTP duration, not SDK or provider internal latency'
    summary={'at':now(),'planned_original':len(rows),'eligible_arms':sum(r['eligible_prefix'] for r in rows),
        'ready_to_grade':len(candidates),'states':dict(Counter(r['status'] for r in rows)),
        'score_states':dict(Counter(r['score_reason'] for r in rows)), 'group_gates':groups,'by_cell':cells,
        'judge_usage_separate':judge_usage,'prediction_usage':accounting(root),'old_costs':plan['definition']['old_costs'],
        'records':rows,'gold_or_predictions_in_report':False,
        'interpretation':'Original two-dataset eligible fixed-prefix subset, not full three-benchmark coverage. Matched gates select a measured subset; denominators and unknowns remain explicit. No old/new best-attempt union.'}
    return candidates,summary


def grade_bound(candidate,config,env):
    for name in ('result','trial','conversation','control','spec','prefix'):
        b=candidate['binding']
        if sha(b[name+'_path'])!=b[name+'_sha256']:raise ValueError('Bound source changed before paid grading')
    return approved.judge_one(candidate,config,env)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=DEFAULT);p.add_argument('--output',type=Path,default=OUT)
    p.add_argument('--live',action='store_true');p.add_argument('--watch',action='store_true');p.add_argument('--idle-only',action='store_true');a=p.parse_args()
    root,out=a.root.resolve(),a.output.resolve();plan,gold,cfg=prepare(root,out)
    candidates,summary=inventory(root,out,plan,gold,cfg);atomic(out/'summary.json',summary)
    if not a.live:print(json.dumps({'live':False,'ready':len(candidates),'concurrency':1}));return
    lease=(out/'controller.lock').open('a');fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
    env,_=environment(ROOT,'dsh',root/'experiment.json');stopping=False
    def stop(*args):
        nonlocal stopping
        stopping=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future=None;current=None;next_scan=0
        while True:
            if future and future.done():
                try:future.result()
                except Exception as e:atomic(current['directory']/'local-error.json',{'at':now(),'error_type':type(e).__name__,'automatic_retry':False})
                future=None;next_scan=0
            if future is None and not stopping and time.time()>=next_scan:
                candidates,summary=inventory(root,out,plan,gold,cfg);atomic(out/'summary.json',summary);next_scan=time.time()+15
                idle=not any(alive(Path(j['out'])) for j in plan['jobs'] if j['eligible'])
                if candidates and (idle or not a.idle_only):
                    current=candidates[0];future=pool.submit(grade_bound,current,cfg,env)
            atomic(out/'status.json',{'at':now(),'pid':os.getpid(),'active_requests':int(future is not None),'concurrency':1,'idle_only':a.idle_only,'stopping':stopping})
            if future is None and (stopping or not a.watch):break
            time.sleep(1)

if __name__=='__main__':main()
