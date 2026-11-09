#!/usr/bin/env python3
"""Offline fixed-retry selection, avg@3, and paired question-cluster inference."""
import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path
import statistics
import time
import numpy as np
from analyze_significance import interval, paired_test, holm
from judge_bc_v3_completed import DEFAULT_ROOT, DEFAULT_RETRY, DEFAULT_OUT, namespace, sha, atomic, read

METHODS=('none','discard','sliding_window','summarize','visual')


def select_attempts(parent, retry):
    parent=Path(parent).resolve();retry=Path(retry).resolve();plan=read(parent/'plan.json');ledger=read(retry/'retry-ledger.json')
    if Path(ledger['parent_root']).resolve()!=parent or ledger.get('max_additional_attempts')!=1:
        raise ValueError('Retry lineage or one-additional-attempt policy differs')
    if sha(parent/'cohort.jsonl')!=sha(retry/'cohort.jsonl'):raise ValueError('Retry cohort differs')
    jobs={j['job_id']:j for j in plan['jobs']};mapped={}
    for entry in ledger['entries']:
        jid=entry['job_id']
        if jid not in jobs or jid in mapped:raise ValueError('Retry job mapping is duplicate or unplanned')
        original=parent/'jobs'/jid/'attempts/attempt_001';new=retry/'jobs'/jid/'attempts/attempt_001'
        if Path(entry['parent_attempt']).resolve()!=original or Path(entry['retry_attempt']).resolve()!=new:
            raise ValueError('Retry attempt path differs')
        if entry.get('parent_status')=='completed':raise ValueError('Previously completed result may not be replaced')
        expected=entry.get('parent_result_sha256')
        if expected is not None and (not (original/'result.json').exists() or sha(original/'result.json')!=expected):
            raise ValueError('Original result changed after fixed retry selection')
        mapped[jid]=new
    return plan,ledger,[(j,parent/'jobs'/j['job_id']/'attempts/attempt_001',mapped.get(j['job_id'],parent/'jobs'/j['job_id']/'attempts/attempt_001')) for j in plan['jobs']]


def observation(job, attempt, grading):
    attempt=Path(attempt);root=attempt.parents[5];result_path=attempt/'result.json';score=None;status='no_terminal_result';reason='missing_prediction'
    result=read(result_path) if result_path.exists() else {};status=result.get('status',status)
    lineage=read(attempt/'route-lineage.json') if (attempt/'route-lineage.json').exists() else {}
    route=lineage.get('actual_route') or result.get('model')
    grade_path=grading/'sources'/namespace(root)/'jobs'/job['job_id']/'grade.json'
    grade=read(grade_path) if grade_path.exists() else {}
    if status=='completed':
        reason='ungraded_completed'
        if grade:
            if grade.get('result_sha256')!=sha(result_path) or grade.get('attempt_path')!=str(attempt):reason='grade_source_mismatch'
            elif grade.get('status')=='scored' and type(grade.get('score')) in (int,float) and grade['score'] in (0,1):score=float(grade['score']);reason='judged_completed'
            else:reason=grade.get('status','unresolved_judge')
    elif status in ('failed','timeout') and result.get('slot_released') is True and result.get('unconfirmed_child_termination')==[]:
        score=0.;reason='terminal_noncompletion_counts_as_failure'
    return {'job_id':job['job_id'],'harness':job['harness'],'method':job['strategy'],'question_id':job['question_id'],
        'question_hash':hashlib.sha256(job['question'].encode()).hexdigest(),'repeat':int(job['repeat']),
        'attempt':str(attempt),'prediction_status':status,'failure_category':result.get('failure_category'),
        'score':score,'score_reason':reason,'actual_route':route,'runtime_route_version':lineage.get('runtime_route_version'),
        'judge_model':grade.get('judge_model'),'judge_path':str(grade_path) if grade else None}


def analyze(rows,draws=10000,seed=20261109):
    rng=np.random.default_rng(seed);groups=defaultdict(list);summaries=[];repeats=[];pairs=[]
    for r in rows:groups[r['harness'],r['method']].append(r)
    for (h,m),rs in sorted(groups.items()):
        ix={(r['question_id'],r['repeat']):r for r in rs}
        if len(ix)!=len(rs):raise ValueError('Duplicate question/repeat would inflate repeated-run evidence')
        ids=sorted({q for q,rep in ix});labels=sorted({rep for q,rep in ix});rep_acc=[]
        full=labels==[1,2,3] and len(ids)==100 and len(ix)==300 and all(r['score'] is not None for r in rs)
        for rep in labels:
            subset=[r for r in rs if r['repeat']==rep];scored=[r['score'] for r in subset if r['score'] is not None]
            accuracy=statistics.mean(scored) if len(subset)==100 and len(scored)==100 else None
            if accuracy is not None:rep_acc.append(accuracy)
            repeats.append({'harness':h,'method':m,'repeat':rep,'planned_questions':len(subset),'known_outcomes':len(scored),
                'judged_completed':sum(r['score_reason']=='judged_completed' for r in subset),
                'terminal_failure_zeros':sum(r['score_reason']=='terminal_noncompletion_counts_as_failure' for r in subset),
                'accuracy':accuracy,'accuracy_lower_bound':sum(scored)/len(subset),
                'accuracy_upper_bound':(sum(scored)+len(subset)-len(scored))/len(subset)})
        lo=hi=None
        if full:lo,hi=interval([statistics.mean(ix[q,rep]['score'] for rep in [1,2,3]) for q in ids],rng,draws)
        summaries.append({'harness':h,'method':m,'planned':len(rs),'known_outcomes':sum(r['score'] is not None for r in rs),
            'judged_completed':sum(r['score_reason']=='judged_completed' for r in rs),'missing_outcomes':sum(r['score'] is None for r in rs),
            'accuracy_lower_bound':sum(r['score'] for r in rs if r['score'] is not None)/len(rs),
            'accuracy_upper_bound':(sum(r['score'] for r in rs if r['score'] is not None)+sum(r['score'] is None for r in rs))/len(rs),
            'avg3_ready':full,'mean_accuracy':statistics.mean(rep_acc) if full else None,
            'std_across_three_repeats':statistics.stdev(rep_acc) if full else None,
            'bootstrap95_low':lo,'bootstrap95_high':hi,'prediction_states':dict(Counter(r['prediction_status'] for r in rs)),
            'score_states':dict(Counter(r['score_reason'] for r in rs)),'actual_routes':dict(Counter(r['actual_route'] or 'unknown' for r in rs))})
    for harness in sorted({h for h,m in groups}):
        vera={(r['question_id'],r['repeat']):r for r in groups.get((harness,'visual'),[])}
        for method in METHODS:
            if method=='visual':continue
            baseline={(r['question_id'],r['repeat']):r for r in groups.get((harness,method),[])}
            ready=len(vera)==len(baseline)==300 and set(vera)==set(baseline) and all(a[k]['score'] is not None for a in [vera,baseline] for k in a)
            if not ready:
                pairs.append({'harness':harness,'baseline':method,'ready':False,'reason':'Await all 100 questions x 3 scored outcomes in both methods'});continue
            ids=sorted({q for q,rep in vera});deltas=[statistics.mean(vera[q,r]['score']-baseline[q,r]['score'] for r in [1,2,3]) for q in ids]
            lo,hi=interval(deltas,rng,draws);route_mismatch=sum(vera[k]['actual_route']!=baseline[k]['actual_route'] or vera[k]['actual_route'] is None for k in vera)
            pairs.append({'harness':harness,'baseline':method,'ready':True,'question_clusters':100,'paired_trajectories':300,
                'mean_delta_visual_minus_baseline':statistics.mean(deltas),'bootstrap95_low':lo,'bootstrap95_high':hi,
                'paired_signflip_p':paired_test(deltas,rng,draws),'route_mismatch_or_unknown_pairs':route_mismatch})
    if len(pairs)==8 and all(p['ready'] for p in pairs):
        for p,adjusted in zip(pairs,holm([p['paired_signflip_p'] for p in pairs])):p['holm_p_all_eight_comparisons']=adjusted
    return {'summary':summaries,'per_repeat':repeats,'paired_tests':pairs,'draws':draws,'random_seed':seed,
        'method':'100 question clusters resampled; repeat means inside each question. Sample std across three repeat accuracies. Two-sided paired question-level sign-flip test. Holm adjustment only after all eight planned comparisons are ready.',
        'interpretation':'Non-significant p does not establish equivalence. Repeat labels do not prove independent random seeds. Costs require separate validated pricing.'}


def write_csv(path,rows):
    with Path(path).open('w') as stream:
        if rows:
            keys=list(dict.fromkeys(k for row in rows for k in row));writer=csv.DictWriter(stream,keys);writer.writeheader();writer.writerows(rows)


def snapshot(parent,retry,grading,output,draws=10000):
    plan,ledger,selection=select_attempts(parent,retry);first=[];chosen=[]
    for job,original,selected in selection:
        before=observation(job,original,grading);first.append(before)
        after=before.copy() if selected==original else observation(job,selected,grading)
        after['selection']='retained_original_completed' if selected==original else 'fixed_retry_regardless_of_outcome'
        chosen.append(after)
    result={'at':time.time(),'selection_ledger_sha256':sha(Path(retry)/'retry-ledger.json'),'parent_plan_sha256':sha(Path(parent)/'plan.json'),
        'resource_interpretation':'Recovered results conditionally receive a second attempt; they are not a single-attempt fixed-budget experiment. Retain first-pass separately and sum original plus retry prediction usage/wall time for cumulative resource reporting.',
        'policy':'Every listed retry replaces its original outcome regardless of relative scores. Retained original completed results are not rerun. No retry is counted as an extra repeat.',
        'missing_policy':'Unscored completed, not_started, interrupted and unresolved predictions remain missing; explicit failed/timeout with confirmed cleanup count zero as operational failures.',
        'first_pass':analyze(first,draws),'fixed_retry_selected':analyze(chosen,draws)}
    output.mkdir(parents=True,exist_ok=True);atomic(output/'statistics.json',result)
    for label,data,rows in [('first-pass',result['first_pass'],first),('selected',result['fixed_retry_selected'],chosen)]:
        write_csv(output/(label+'-summary.csv'),data['summary']);write_csv(output/(label+'-per-repeat.csv'),data['per_repeat']);write_csv(output/(label+'-paired.csv'),data['paired_tests'])
        (output/(label+'-observations.jsonl')).write_text(''.join(json.dumps(r)+'\n' for r in rows))
    lines=['# BC-100: three-repeat accuracy and fixed-retry accounting','',result['policy'],'',
        '| Harness | Method | Known / planned | Mean ± sample std | 95% question-bootstrap CI |',
        '|---|---|---:|---:|---:|']
    for row in result['fixed_retry_selected']['summary']:
        avg=f"{row['mean_accuracy']*100:.2f} ± {row['std_across_three_repeats']*100:.2f}%" if row['avg3_ready'] else 'NA — grading/runs incomplete'
        ci=f"[{row['bootstrap95_low']*100:.2f}, {row['bootstrap95_high']*100:.2f}]%" if row['avg3_ready'] else 'NA'
        lines.append(f"| {row['harness']} | {row['method']} | {row['known_outcomes']} / {row['planned']} | {avg} | {ci} |")
    lines+=['',result['resource_interpretation'],'',result['missing_policy'],'',result['fixed_retry_selected']['method'],'',result['fixed_retry_selected']['interpretation']]
    (output/'summary.md').write_text('\n'.join(lines)+'\n')
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--parent',type=Path,default=DEFAULT_ROOT)
    parser.add_argument('--retry',type=Path,default=DEFAULT_RETRY);parser.add_argument('--grading',type=Path,default=DEFAULT_OUT)
    parser.add_argument('--output',type=Path,default=DEFAULT_OUT/'analysis');parser.add_argument('--watch',action='store_true');args=parser.parse_args()
    while True:
        result=snapshot(args.parent.resolve(),args.retry.resolve(),args.grading.resolve(),args.output.resolve())
        print(json.dumps({'at':result['at'],'ready_cells':sum(r['avg3_ready'] for r in result['fixed_retry_selected']['summary'])}),flush=True)
        if not args.watch:break
        time.sleep(180)


if __name__=='__main__':main()
