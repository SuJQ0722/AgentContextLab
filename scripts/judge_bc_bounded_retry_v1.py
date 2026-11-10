#!/usr/bin/env python3
"""Private judging for answer-selected BC retries across Hermes and DSH."""
import argparse,fcntl,json,os,signal,time
from collections import Counter,deque
from concurrent.futures import ThreadPoolExecutor,wait,FIRST_COMPLETED
from pathlib import Path
import judge_mmbc100 as base
from lab import ROOT,environment
import prepare_bc_bounded_retry_v1 as campaign

VERSION='judge-bc-bounded-retry-v1'
DEFAULT_OUT=ROOT/'outputs/grading/bc-bounded-retry-v1'
read,sha,atomic,immutable=base.read,base.sha,base.atomic,base.immutable


def load(root,out):
    root,out=Path(root).resolve(),Path(out).resolve()
    if root==out or root in out.parents or out in root.parents:raise ValueError('Isolated grading namespace required')
    plan,_=campaign.load_validate(root);d=plan['definition'];selection=read(d['selection_path'])
    private=Path(d['gold_path'])
    if sha(private)!=d['gold_sha256']:raise ValueError('Private gold changed')
    secret=read(private);public=base.jsonlines(root/'cohort.jsonl')
    if any(set(r)!={'id','question'} for r in public):raise ValueError('Public cohort includes private fields')
    cohort={r['id']:r for r in public};answers={q:r['answer'] for q,r in secret.items()}
    if len(public)!=100 or len(cohort)!=100 or set(cohort)!=set(secret):raise ValueError('Incomplete private cohort')
    if any(secret[q]['question']!=r['question'] for q,r in cohort.items()):raise ValueError('Gold question mismatch')
    records=selection['records']
    validate_selection(plan,records)
    for job in plan['jobs']:
        if job['model']!=base.MODEL or job['harness'] not in ('hermes','dsh') or job['strategy']!='visual' or job['question']!=cohort[job['question_id']]['question']:
            raise ValueError('Judge route/public question differs')
    selection={**selection,'definition':d}
    binding={'root':str(root),'plan_sha256':sha(root/'plan.json'),'cohort_sha256':sha(root/'cohort.jsonl'),
             'private_source_sha256':sha(private),'selection_sha256':sha(d['selection_path']),
             'config_sha256':sha(root/'experiment.json')}
    immutable(out/'source-binding.json',binding)
    return plan,selection,cohort,answers,binding


def validate_selection(plan,records):
    ix={r['job_id']:r for r in records}
    if len(records)!=600 or len(ix)!=600:raise ValueError('Expected two original300 cells')
    for h in ('hermes','dsh'):
        cell=[r for r in records if r['harness']==h]
        if len(cell)!=300 or len({(r['question_id'],r['repeat']) for r in cell})!=300:raise ValueError('Incomplete original harness cell')
    for r in records:
        if type(r['score']) not in (int,float) or r['score'] not in (0,1) or r['selected_for_retry']!=(r['score']==0):raise ValueError('Changed answer-based retry selection')
    ids=[j['job_id'] for j in plan['jobs']]
    if len(set(ids))!=len(ids) or set(ids)!={j for j,r in ix.items() if r['score']==0}:raise ValueError('Only old noncorrect slots may be selected')
    for j in plan['jobs']:
        if any(j[k]!=ix[j['job_id']][k] for k in ('question_id','repeat','harness')):raise ValueError('New retry identity differs')


def inventory(root,out,plan,answers,binding):
    candidates=[];rows=[];terminal=0
    for job in plan['jobs']:
        attempt=root/'jobs'/job['job_id']/'attempts/attempt_001';rp=attempt/'result.json';directory=out/'jobs'/job['job_id']
        result=read(rp) if rp.exists() else {};status=result.get('status','pending');clean=base.clean(result)
        if result and any(result.get(k)!=job[k] for k in ('job_id','harness','strategy','question_id','repeat','model')):raise ValueError('Prediction identity changed')
        score=None;reason='pending_prediction';gp=directory/'grade.json';grade=read(gp) if gp.exists() else None
        if status in ('completed','failed','timeout') and clean:terminal+=1
        if status in ('failed','timeout') and clean:score=0.;reason='confirmed_operational_failure'
        elif status=='completed' and clean:
            final=result.get('final');prediction=final if isinstance(final,str) else (final or {}).get('text','')
            if not isinstance(prediction,str):raise ValueError('Nontext final prediction')
            b={**binding,'job_id':job['job_id'],'harness':job['harness'],'strategy':job['strategy'],
                'question_id':job['question_id'],'repeat':job['repeat'],'attempt_path':str(attempt),'result_path':str(rp),
                'result_sha256':sha(rp),'prediction_sha256':base.bc.sha_bytes(prediction.encode()),
                'question_sha256':base.bc.sha_bytes(job['question'].encode())}
            if (directory/'binding.json').exists() and read(directory/'binding.json')!=b:raise ValueError('Frozen judged prediction changed')
            reason='ungraded_completed'
            if grade:
                if any(grade.get(k)!=v for k,v in b.items()):raise ValueError('Grade binding mismatch')
                if grade.get('status')=='scored' and type(grade.get('score')) in (float,int) and grade['score'] in (0,1):score=float(grade['score']);reason='judged_completed'
                else:reason=grade.get('status','judge_error')
            elif (directory/'request-started.json').exists():reason='unresolved_judge_request'
            elif (directory/'local-error.json').exists():reason='judge_local_error'
            else:candidates.append({'directory':directory,'binding':b,'question':job['question'],'answer':answers[job['question_id']],'prediction':prediction})
        elif result:reason='cleanup_unconfirmed' if not clean else status
        rows.append({'job_id':job['job_id'],'question_id':job['question_id'],'repeat':job['repeat'],'method':'visual',
                     'harness':job['harness'],'attempt':str(attempt),'prediction_status':status,'score':score,'score_reason':reason,
                     'result_sha256':sha(rp) if rp.exists() else None,'grade_sha256':sha(gp) if gp.exists() else None})
    return candidates,rows,{'planned':len(rows),'terminal_cleanup_confirmed':terminal,'all_terminal':terminal==len(rows),
        'ready_to_grade':len(candidates),'prediction_states':dict(Counter(r['prediction_status'] for r in rows)),
        'score_states':dict(Counter(r['score_reason'] for r in rows))}


def summarize(rows,denominator):
    scores=[r['score'] for r in rows if r['score'] is not None];correct=sum(scores);missing=denominator-len(scores)
    return {'planned':denominator,'known':len(scores),'correct':correct,'missing':missing,
            'accuracy':correct/denominator if not missing and denominator else None,
            'accuracy_bounds':[correct/denominator,(correct+missing)/denominator] if denominator else [None,None]}


def repeated_summary(rows,denominator):
    result=summarize(rows,denominator)
    result.update(mean_accuracy=None,std_across_three_repeat_accuracies=None)
    if denominator==300 and len(rows)==300 and result['missing']==0:
        import statistics
        groups=[[r['score'] for r in rows if r['repeat']==rep] for rep in (1,2,3)]
        if all(len(g)==100 for g in groups):
            means=[statistics.mean(g) for g in groups]
            result.update(mean_accuracy=statistics.mean(means),std_across_three_repeat_accuracies=statistics.stdev(means))
    return result


def three_layers(selection,rows):
    old=selection['records'];selected={r['job_id'] for r in old if r['selected_for_retry']};new={r['job_id']:r for r in rows}
    if len(new)!=len(rows) or not set(new).issubset(selected):raise ValueError('Unexpected/duplicate new result')
    output=[]
    for harness in ('hermes','dsh'):
        originals=[r for r in old if r['harness']==harness]
        conditional=[new.get(r['job_id'],dict(r,score=None)) for r in originals if r['job_id'] in selected]
        retained=[r for r in originals if r['job_id'] not in selected]
        output.append({'harness':harness,'previous_selected300':repeated_summary(originals,300),
            'new_noncorrect_conditional':summarize(conditional,len(conditional)),
            'retained_correct_plus_new_oracle_union':repeated_summary(retained+conditional,300)})
    return {'per_harness':output,'selection_uses_answer_correctness':True,
            'mixed_old_and_new_renderer_and_route':True,'union_is_clean_single_attempt_avg3':False,
            'paired_significance_claim':False,
            'interpretation':'Correct old slots are retained and every old noncorrect slot selects exactly one new attempt. This is answer-selected mixed-renderer/route recovery, not ordinary single-attempt avg3 or evidence of superiority over baselines. Missing new predictions/grades are unknown, never zero or replaced by best score.'}


def resource_report(selection,root,out):
    from monitor_bc_campaign_v3 import inspect_attempt,aggregate
    directory=out/'private/original-cost-reference-snapshots';directory.mkdir(parents=True,exist_ok=True);refs=[]
    sources=[ROOT/'outputs/grading/bc100-v3-deepseek-sfb-v1/analysis/statistics.json',
             ROOT/'outputs/campaigns/bc100-r3-hermes-parity-v3-retry1/retry-ledger.json']
    for i,source in enumerate(sources):
        target=directory/(str(i)+'-'+source.name)
        if not target.exists() and source.exists():
            with target.open('xb') as stream:stream.write(source.read_bytes())
            target.chmod(0o600)
        refs.append({'source_path':str(source),'snapshot_path':str(target),'sha256':sha(target) if target.exists() else None})
    resources={}
    for harness in ('hermes','dsh'):
        usage=[];details=[];judges=[];requests=Counter();web=Counter();judge_seen=set()
        for r in selection['records']:
            if r['harness']!=harness or not r['selected_for_retry']:continue
            for attempt in (root/'jobs'/r['job_id']/'attempts').glob('attempt_*'):
                info,raw=inspect_attempt(attempt,harness);usage.extend(raw);details.append(info);requests.update(info['requests']);web.update(info['web_cache'])
            gd=out/'jobs'/r['job_id']
            if (gd/'request-started.json').exists():
                if r['job_id'] in judge_seen:raise ValueError('Duplicate judge charge')
                judge_seen.add(r['job_id']);gp=gd/'grade.json'
                if gp.exists():
                    g=read(gp)
                    if g.get('api_calls')!=0:judges.append({'raw_provider_usage':g.get('raw_provider_usage')})
                else:judges.append({'raw_provider_usage':None,'_incomplete':True})
        fields=('sdk_client_seconds_known_subtotal','sdk_client_seconds_missing_count','render_seconds_known_subtotal','render_seconds_missing_count','compression_count_known_subtotal')
        resources[harness]={'prediction_tokens':aggregate(usage),'judge_tokens':aggregate(judges),'observed_attempts':len(details),
            'requests':dict(requests),'web_cache':dict(web),**{k:sum(x.get(k,0) for x in details) for k in fields},
            'provider_api_latency_seconds':None,'actual_cost_usd':None}
    return {'original_cost_reference_snapshots':refs,'new_attempts_raw_accounting':resources,
        'original_costs_reaggregated':False,'combined_old_new_token_total':None,
        'interpretation':'New raw costs use the correct Hermes/DSH extractor and retain unknown usage. Prior first-pass and retry1 costs remain referenced; old tables can overlap and are not blindly summed. No complete cumulative USD/total claim. SDK duration is not provider latency.'}


def report(root,out,selection,rows,info,with_cost=True):
    value={'at':base.bc.now(),'version':VERSION,'inventory':info,'layers':three_layers(selection,rows)}
    if with_cost:
        atomic(out/'resources.json',resource_report(selection,root,out));value['resources_path']=str(out/'resources.json')
    atomic(out/'observations.json',rows);atomic(out/'statistics.json',value)
    lines=['# BC bounded answer-selected recovery','',value['layers']['interpretation'],'',
        '|Harness|Layer|Known / planned|Correct|Accuracy bounds|','|---|---|---:|---:|---|']
    for cell in value['layers']['per_harness']:
        for key in ('previous_selected300','new_noncorrect_conditional','retained_correct_plus_new_oracle_union'):
            r=cell[key];lines.append(f"|{cell['harness']}|{key}|{r['known']}/{r['planned']}|{r['correct']}|{r['accuracy_bounds']}|")
    (out/'summary.md').write_text('\n'.join(lines)+'\n');return value


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,default=campaign.DEFAULT_ROOT)
    parser.add_argument('--output',type=Path,default=DEFAULT_OUT);parser.add_argument('--live',action='store_true');parser.add_argument('--watch',action='store_true')
    parser.add_argument('--concurrency',type=int,default=2);parser.add_argument('--timeout',type=int,default=180)
    args=parser.parse_args()
    if not 1<=args.concurrency<=2 or args.timeout<=0:parser.error('Concurrency1–2; positive timeout')
    root,out=args.root.resolve(),args.output.resolve();out.mkdir(parents=True,exist_ok=True);out.chmod(0o700)
    plan,selection,cohort,answers,binding=load(root,out)
    config={'version':VERSION,'judge_model':base.MODEL,'max_tokens':8192,'temperature':0,'top_p':1,'timeout_seconds':args.timeout,
            'source_binding':binding,'api_retries':0,'concurrency_cap':2,
            'sources_sha256':{p:sha(ROOT/'scripts'/p) for p in ('judge_bc_bounded_retry_v1.py','judge_mmbc100.py','judge_bc_v3_completed.py','monitor_bc_campaign_v3.py')},
            'hermes_judge_sha256':sha(ROOT/'hermes-agent/Browsecomp_eval/browsecomp_eval/judge.py')}
    immutable(out/'protocol.json',config)
    if not args.live:
        candidates,rows,info=inventory(root,out,plan,answers,binding);report(root,out,selection,rows,info)
        print(json.dumps({'live':False,'ready_to_grade':len(candidates),'inventory':info}));return
    lease=(out/'controller.lock').open('a');fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
    env,_=environment(ROOT,'hermes',root/'experiment.json');pending=deque();futures={};stopped=False;next_scan=0;last_report=0
    def stop(*unused):
        nonlocal stopped
        stopped=True
    signal.signal(signal.SIGINT,stop);signal.signal(signal.SIGTERM,stop)
    rows=[];info={}
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        while True:
            if not stopped and time.time()>=next_scan and not pending:
                plan,selection,cohort,answers,current=load(root,out)
                if current!=binding:raise ValueError('Frozen grading source changed')
                candidates,rows,info=inventory(root,out,plan,answers,binding)
                pending.extend(c for c in candidates if str(c['directory']) not in futures.values());next_scan=time.time()+60
                if time.time()-last_report>=300 or info['all_terminal']:
                    report(root,out,selection,rows,info);last_report=time.time()
            while not stopped and pending and len(futures)<args.concurrency:
                c=pending.popleft();futures[pool.submit(base.judge_one,c,config,env)]=str(c['directory'])
            if futures:
                done,_=wait(futures,timeout=1,return_when=FIRST_COMPLETED)
                for future in done:
                    directory=Path(futures.pop(future))
                    try:future.result()
                    except Exception as exc:atomic(directory/'local-error.json',{'at':base.bc.now(),'error_type':type(exc).__name__,'automatic_retry':False})
            atomic(out/'status.json',{'at':base.bc.now(),'pid':os.getpid(),'active':len(futures),'pending':len(pending),'stopping':stopped,'inventory':info})
            if not futures and not pending and (stopped or not args.watch or info.get('all_terminal')):break
            if not futures:time.sleep(1)
    candidates,rows,info=inventory(root,out,plan,answers,binding);report(root,out,selection,rows,info)
    atomic(out/'status.json',{'at':base.bc.now(),'pid':os.getpid(),'active':0,'pending':0,'finished':True,'inventory':info,'remaining_unissued_grade_candidates':len(candidates)})

if __name__=='__main__':main()
