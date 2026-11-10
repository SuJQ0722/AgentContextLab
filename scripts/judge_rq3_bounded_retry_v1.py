#!/usr/bin/env python3
"""Private judging for execution-failure RQ3 retries; original completed outcomes retained."""
import argparse,fcntl,json,os,signal,time
from collections import Counter,deque
from concurrent.futures import ThreadPoolExecutor,wait,FIRST_COMPLETED
from pathlib import Path
import judge_mmbc100 as base
from lab import ROOT,environment
import prepare_rq3_bounded_retry_v1 as campaign

VERSION='judge-rq3-bounded-retry-v1'
DEFAULT_OUT=ROOT/'outputs/grading/rq3-bounded-failure-retry-v1'
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
    original=base.jsonlines(d['original_observations_path']);records=selection['records']
    validate_selection(plan,records,original)
    for job in plan['jobs']:
        if job['model']!=base.MODEL or job['harness']!='hermes' or job['strategy']!='visual' or job['question']!=cohort[job['question_id']]['question']:
            raise ValueError('Judge route/public question differs')
    selection={**selection,'original_rows':original,'definition':d}
    binding={'root':str(root),'plan_sha256':sha(root/'plan.json'),'cohort_sha256':sha(root/'cohort.jsonl'),
             'private_source_sha256':sha(private),'selection_sha256':sha(d['selection_path']),
             'original_observations_sha256':sha(d['original_observations_path']),'config_sha256':sha(root/'experiment.json')}
    immutable(out/'source-binding.json',binding)
    return plan,selection,cohort,answers,binding


def validate_selection(plan,records,original):
    ix={r['job_id']:r for r in original};rx={r['job_id']:r for r in records}
    if len(ix)!=2100 or len(rx)!=2100 or len(original)!=2100 or len(records)!=2100 or set(ix)!=set(rx):raise ValueError('Expected complete seven100x3 original rows')
    for jid,r in rx.items():
        old=ix[jid]
        if r['status']!=old['prediction_status'] or r['selected_for_retry']!=(r['status'] in ('failed','timeout')):raise ValueError('Selection changed or depends on score')
        if any(r[k]!=old[k] for k in ('question_id','repeat','scale')):raise ValueError('Original observation identity mismatch')
    ids=[j['job_id'] for j in plan['jobs']]
    if len(set(ids))!=len(ids) or set(ids)!={j for j,r in rx.items() if r['status'] in ('failed','timeout')}:raise ValueError('Completed correct/wrong/ungraded must not be rerun')
    for j in plan['jobs']:
        if any(j[k]!=rx[j['job_id']][k] for k in ('question_id','repeat','scale')):raise ValueError('New retry identity differs')


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
                     'scale':job['scale'],'attempt':str(attempt),'prediction_status':status,'score':score,'score_reason':reason,
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
    old=selection['original_rows'];selected={r['job_id'] for r in selection['records'] if r['selected_for_retry']}
    new={r['job_id']:r for r in rows}
    if len(new)!=len(rows) or not set(new).issubset(selected):raise ValueError('New rows include old completed or duplicate jobs')
    output=[]
    for scale in campaign.SCALES:
        originals=[r for r in old if r['scale']==scale]
        conditional=[new.get(r['job_id'],dict(r,score=None)) for r in originals if r['job_id'] in selected]
        overlay=[new.get(r['job_id'],dict(r,score=None)) if r['job_id'] in selected else r for r in originals]
        output.append({'scale':scale,'original_selected300':repeated_summary(originals,300),
            'new_execution_failure_conditional':summarize(conditional,len(conditional)),
            'fixed_execution_status_overlay':repeated_summary(overlay,300)})
    return {'per_scale':output,'selection_uses_answer_correctness':False,'selection_uses_execution_status':True,
            'mixed_old_and_new_renderer_and_route':True,'overlay_is_clean_new_protocol_avg3':False,
            'paired_significance_claim':False,
            'interpretation':'All original completed outcomes, including wrong and missing grades, remain fixed. Failed/timeout slots always select the one fixed new attempt, never best score. Overlay is mixed-renderer/mixed-route operational recovery, not a clean resolution ablation. Original significance reports remain separate.'}


def resource_report(selection,root,out):
    # Snapshot references preserve original paid interruption recovery attribution.
    # They can overlap; never add these documents as if they were disjoint totals.
    directory=out/'private/original-cost-reference-snapshots';directory.mkdir(parents=True,exist_ok=True)
    refs=[]
    for name in ('statistics.json','comparison-plan.json','paid-interruption-cumulative-cost.json',
                 'pre-native-recovery3-cost.json','excluded-scale0125-cost.json'):
        if any(x['name']==name for x in refs):continue
        source=campaign.SOURCE_REPORT/name;target=directory/name
        if not target.exists() and source.exists():
            with target.open('xb') as stream:stream.write(source.read_bytes())
            target.chmod(0o600)
        refs.append({'name':name,'source_path':str(source),'snapshot_path':str(target),
                     'snapshot_sha256':sha(target) if target.exists() else None,'available':target.exists()})
    rows=[]
    for r in selection['records']:
        if not r['selected_for_retry']:continue
        for attempt in sorted((root/'jobs'/r['job_id']/'attempts').glob('attempt_*')):
            if attempt.name!='attempt_001':raise ValueError('Unexpected additional retry attempt: do not duplicate judge spending')
            rows.append({'method':'visual','job_id':r['job_id'],'attempt':str(attempt)})
    accounting=base.accounting(rows,out)
    return {'original_cost_reference_snapshots':refs,'new_attempts_raw_accounting':accounting,
            'original_costs_reaggregated':False,'combined_old_new_token_total':None,
            'provider_api_latency_seconds':None,'actual_cost_usd':None,
            'interpretation':'New raw calls include missing usage without zero filling. Original cost evidence, including15 prior paid interruption retries, is retained by references; overlapping original reports are NOT summed and no complete cumulative total is claimed. Removed.125 spending stays separately attributed. SDK duration is not provider latency.'}


def report(root,out,selection,rows,info,with_cost=True):
    value={'at':base.bc.now(),'version':VERSION,'inventory':info,'layers':three_layers(selection,rows)}
    if with_cost:
        atomic(out/'resources.json',resource_report(selection,root,out));value['resources_path']=str(out/'resources.json')
    atomic(out/'observations.json',rows);atomic(out/'statistics.json',value)
    lines=['# RQ3 bounded execution-failure recovery','',value['layers']['interpretation'],'',
           '|Scale|Layer|Known / planned|Correct|Accuracy bounds|','|---|---|---:|---:|---|']
    for scale in value['layers']['per_scale']:
        for key in ('original_selected300','new_execution_failure_conditional','fixed_execution_status_overlay'):
            r=scale[key];lines.append(f"|{scale['scale']}|{key}|{r['known']}/{r['planned']}|{r['correct']}|{r['accuracy_bounds']}|")
    lines+=['','All old attempts remain intact. Original cost reports are referenced, not fully reaggregated; combined old+new token total and USD remain unknown.']
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
            'sources_sha256':{p:sha(ROOT/'scripts'/p) for p in ('judge_rq3_bounded_retry_v1.py','judge_mmbc100.py','judge_bc_v3_completed.py','monitor_bc_campaign_v3.py')},
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
