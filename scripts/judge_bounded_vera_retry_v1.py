#!/usr/bin/env python3
"""Private, single-request judging for answer-selected bounded VERA retries."""
import argparse,fcntl,json,os,signal,time
from collections import Counter,deque
from concurrent.futures import ThreadPoolExecutor,wait,FIRST_COMPLETED
from pathlib import Path
import judge_mmbc100 as base
from lab import ROOT,environment
import prepare_bounded_vera_retry_v1 as campaign

VERSION='judge-bounded-vera-retry-v1'
DEFAULT_OUT=ROOT/'outputs/grading/mmbc-vera-bounded-retry-v1'
read,sha,atomic,immutable=base.read,base.sha,base.atomic,base.immutable


def load(root,out):
    root,out=Path(root).resolve(),Path(out).resolve()
    if root==out or root in out.parents or out in root.parents:raise ValueError('Isolated grading namespace required')
    plan,_=campaign.load_validate(root);d=plan['definition'];selection=read(d['selection_path'])
    gold=base.DEFAULT_GOLD;mapping=read(gold/'private/source-map.json');private=gold/'private/selected-source.jsonl'
    if mapping['selected_source_sha256']!=sha(private) or mapping['cohort_sha256']!=sha(root/'cohort.jsonl'):raise ValueError('Private gold/cohort changed')
    cohort={r['question_id']:r for r in base.jsonlines(root/'cohort.jsonl')};secret=base.jsonlines(private)
    answers={r['question_id']:r['answer'] for r in secret}
    if len(cohort)!=100 or len(secret)!=100 or set(answers)!=set(cohort):raise ValueError('Incomplete private cohort')
    for row in secret:
        if any(row['source_row'][k]!=cohort[row['question_id']][k] for k in ('question','image')):raise ValueError('Gold question/image binding differs')
    for job in plan['jobs']:
        if job['model']!=base.MODEL or job['harness']!='hermes' or job['strategy']!='visual' or job['question']!=cohort[job['question_id']]['question'] or job['image']!=cohort[job['question_id']]['image']:
            raise ValueError('Judge route or public question/image differs')
    original=selection['records'];retry_ids={j['job_id'] for j in plan['jobs']}
    if len(original)!=300 or len({r['job_id'] for r in original})!=300 or retry_ids!={r['job_id'] for r in original if r['score']==0}:raise ValueError('Retry selection changed')
    binding={'root':str(root),'plan_sha256':sha(root/'plan.json'),'cohort_sha256':sha(root/'cohort.jsonl'),
             'private_source_sha256':sha(private),'private_map_sha256':sha(gold/'private/source-map.json'),'selection_sha256':sha(d['selection_path']),
             'parent_plan_sha256':d['parent_plan_sha256'],'config_sha256':sha(root/'experiment.json')}
    immutable(out/'source-binding.json',binding)
    return plan,selection,cohort,answers,binding


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
                     'attempt':str(attempt),'prediction_status':status,'score':score,'score_reason':reason,
                     'result_sha256':sha(rp) if rp.exists() else None,'grade_sha256':sha(gp) if gp.exists() else None})
    return candidates,rows,{'planned':len(rows),'terminal_cleanup_confirmed':terminal,'all_terminal':terminal==len(rows),
        'ready_to_grade':len(candidates),'prediction_states':dict(Counter(r['prediction_status'] for r in rows)),
        'score_states':dict(Counter(r['score_reason'] for r in rows))}


def summarize(rows,denominator):
    scores=[r['score'] for r in rows if r['score'] is not None];correct=sum(scores);missing=denominator-len(scores)
    return {'planned':denominator,'known':len(scores),'correct':correct,'missing':missing,
            'accuracy':correct/denominator if not missing and denominator else None,
            'accuracy_bounds':[correct/denominator,(correct+missing)/denominator] if denominator else [None,None]}


def three_layers(selection,rows):
    old=selection['records'];retained=[r for r in old if r['score']==1]
    return {'original_first_pass_300':summarize(old,len(old)),
            'selected_new_attempts_conditional':summarize(rows,len(old)-len(retained)),
            'retained_correct_plus_new_oracle_union':summarize(retained+rows,len(old)),
            'selection_uses_prior_answers':True,'mixed_old_and_new_renderer':True,
            'union_is_single_attempt_avg3':False,'paired_significance_valid':False,
            'interpretation':'New attempts are conditional on prior noncorrect outcomes. Union is answer-selected, mixed-renderer oracle retry; no single-attempt avg3 or baseline significance claim. Failed/unknown grades remain missing, never zero.'}


def cost_rows(selection,root):
    groups={'original_all300':[],'new_selected':[]};seen=set()
    for record in selection['records']:
        original=Path(record['result_path']).parent
        for a in sorted(original.parent.glob('attempt_*')):
            if str(a.resolve()) in seen:raise ValueError('Duplicate original cost attempt')
            seen.add(str(a.resolve()));groups['original_all300'].append({'method':'visual','job_id':record['job_id'],'attempt':str(a)})
        if record['score']==0:
            for a in sorted((root/'jobs'/record['job_id']/'attempts').glob('attempt_*')):
                if str(a.resolve()) in seen:raise ValueError('Duplicate retry cost attempt')
                seen.add(str(a.resolve()));groups['new_selected'].append({'method':'visual','job_id':record['job_id'],'attempt':str(a)})
    return groups


def merge_tokens(items):
    fields={}
    for key in items[0]['fields']:
        parts=[x['fields'][key] for x in items]
        row={k:sum(v[k] for v in parts) for k in ('known_subtotal','known_count','missing_count')}
        row['complete_total']=row['known_subtotal'] if row['known_count'] and not row['missing_count'] else None;fields[key]=row
    issues=Counter()
    for x in items:issues.update(x['conservation_issues'])
    return {'observations':sum(x['observations'] for x in items),'fields':fields,'conservation_issues':dict(issues)}


def resource_report(selection,root,out):
    groups=cost_rows(selection,root);resources={}
    for label,rows in groups.items():
        grading=Path(selection['grading_root']) if label=='original_all300' else out
        # All current protocols allow one attempt; protect future extra-attempt
        # accounting from accidentally duplicating the single judge operation.
        data=base.accounting(rows,Path('/nonexistent-bounded-grading'))
        judge_rows=[];seconds=[];claims=unresolved=0
        for job_id in {r['job_id'] for r in rows}:
            folder=grading/'jobs'/job_id
            if not (folder/'request-started.json').exists():continue
            claims+=1
            if (folder/'grade.json').exists():
                g=read(folder/'grade.json')
                if g.get('api_calls')!=0:judge_rows.append({'raw_provider_usage':g.get('raw_provider_usage')});seconds.append(g.get('client_http_seconds'))
            else:unresolved+=1;judge_rows.append({'raw_provider_usage':None,'_incomplete':True});seconds.append(None)
        resources[label]={'prediction':data['prediction']['visual'],'judge':{'request_claims':claims,'unresolved':unresolved,
            'tokens':base.aggregate(judge_rows),'client_http_seconds_known':sum(x for x in seconds if base.numeric(x)),
            'client_http_seconds_missing':sum(not base.numeric(x) for x in seconds),'provider_api_latency_seconds':None,'usd':None}}
    parts=[v['prediction'] for v in resources.values()]
    resources['cumulative_prediction_all_attempts']={'tokens':merge_tokens([p['tokens'] for p in parts]),
        **{k:sum(p[k] for p in parts) for k in ('observed_attempts','sdk_client_seconds_known','sdk_seconds_missing_calls',
              'end_to_end_seconds_known','end_to_end_missing_attempts','render_seconds_known','render_seconds_missing_records','compression_count_known')}}
    resources['cumulative_judge_tokens']=merge_tokens([resources[k]['judge']['tokens'] for k in groups])
    resources['provider_api_latency_seconds']=None;resources['actual_cost_usd']=None
    resources['interpretation']=data['interpretation']+' All original and new judge operations are included exactly once. No failed attempt or unknown usage is removed.'
    return resources


def report(root,out,selection,rows,info,with_cost=True):
    value={'at':base.bc.now(),'version':VERSION,'inventory':info,'layers':three_layers(selection,rows)}
    if with_cost:
        atomic(out/'resources.json',resource_report(selection,root,out));value['resources_path']=str(out/'resources.json')
    atomic(out/'observations.json',rows);atomic(out/'statistics.json',value)
    lines=['# Bounded VERA answer-selected retry','',value['layers']['interpretation'],'',
           '|Layer|Known / planned|Correct|Accuracy bounds|','|---|---:|---:|---|']
    for key in ('original_first_pass_300','selected_new_attempts_conditional','retained_correct_plus_new_oracle_union'):
        r=value['layers'][key];lines.append(f"|{key}|{r['known']}/{r['planned']}|{r['correct']}|{r['accuracy_bounds']}|")
    lines+=['','Original failed trajectories and all costs remain preserved. Provider internal latency and actual USD are unknown.']
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
            'sources_sha256':{p:sha(ROOT/'scripts'/p) for p in ('judge_bounded_vera_retry_v1.py','judge_mmbc100.py','judge_bc_v3_completed.py','monitor_bc_campaign_v3.py')},
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
