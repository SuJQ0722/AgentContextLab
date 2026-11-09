#!/usr/bin/env python3
"""Final seven-scale report with fixed15 paid-interrupted retry selection and costs."""
import argparse
import json
from pathlib import Path
import time
import report_rq3_final_seven_v1 as original
from run_rq3_scale0700_paid_retry1 import DEFAULT_ROOT,MANIFEST,validate_scope
from judge_bc_v3_completed import atomic,read,sha,namespace
from bc_route_runtime_v2 import immutable_json

VERSION='rq3-final-seven-v2-paid-retry1'
OUTPUT=original.ROOT/'outputs/grading/rq3-final-seven-v2'


def prepare_comparison(previous,retry_root,output):
    previous=Path(previous).resolve();retry_root=Path(retry_root).resolve();output=Path(output).resolve()
    old=read(previous/'comparison-plan.json')
    if old.get('scales')!=list(original.SCALES) or old.get('planned_observations')!=2100 or len(old.get('entries',[]))!=2100:
        raise ValueError('Original comparison is not the authorized final seven2100')
    for path,expected in old['source_files_sha256'].items():
        if sha(path)!=expected:raise ValueError('Original final-seven binding changed')
    _,auth=validate_scope(retry_root);mapping={e['job_id']:e for e in auth['entries']}
    if Path(old['legacy_root'])!=Path(auth['parent_root']):raise ValueError('Paid retry parent differs from final comparison')
    new=json.loads(json.dumps(old));matched=set()
    for entry in new['entries']:
        if entry['job_id'] not in mapping:continue
        source=mapping[entry['job_id']]
        if entry['scale']!=.7 or entry['selected_attempt']!=source['parent_attempt'] or entry['original_attempt']!=source['parent_attempt']:
            raise ValueError('Paid retry would replace another selected recovery or different source')
        entry['selected_attempt']=source['retry_attempt'];entry['grading_root']=auth['grading_root'];entry['selection']='fixed_paid_interruption_retry1_no_score_choice';matched.add(entry['job_id'])
    if len(new['entries'])!=2100 or matched!=set(mapping):raise ValueError('Fixed15 comparison mapping incomplete')
    new['version']=VERSION;new['selection_policy']=old['selection_policy']+' Additionally, exactly15 paid-interrupted .7 observations always select their single authorized retry; old+retry resource costs accumulate. No score-based choice or extra seed.'
    new['source_files_sha256'][str(previous/'comparison-plan.json')]=sha(previous/'comparison-plan.json')
    for path in [retry_root/MANIFEST,retry_root/'plan.json']:new['source_files_sha256'][str(path)]=sha(path)
    new['paid_retry_root']=str(retry_root);new['paid_retry_grading_root']=auth['grading_root'];new['original_comparison_root']=str(previous)
    immutable_json(output/'comparison-plan.json',new);return new


def cumulative_cost(comparison):
    auth=read(Path(comparison['paid_retry_root'])/MANIFEST);all_records=[];judge_records=[];by_job=[]
    for entry in auth['entries']:
        phases=[]
        for phase,key in [('original','parent_attempt'),('retry','retry_attempt')]:
            attempt=Path(entry[key]);metrics=attempt/'native/metrics';calls={r['call_id']:r for r in original.jsonlines(metrics/'calls.jsonl') if r.get('call_id')}
            starts={r['call_id'] for r in original.jsonlines(metrics/'call-starts.jsonl') if r.get('call_id')};records=list(calls.values());all_records.extend(records)
            result=read(attempt/'result.json') if (attempt/'result.json').exists() else {}
            phases.append({'phase':phase,'attempt':str(attempt),'sdk_starts':len(starts),'returned_calls':len(calls),'starts_without_return':len(starts-set(calls)),
                'prediction_status':result.get('status','unknown_or_pending'),'end_to_end_seconds':result.get('end_to_end_seconds'),
                'usage':original.usage_summary(records),'original_status_missing_not_zero_calls':phase=='original' and not result})
        grade=Path(auth['grading_root'])/'sources'/namespace(Path(auth['retry_root']))/'jobs'/entry['job_id']/'grade.json'
        if grade.exists():judge_records.append(read(grade))
        by_job.append({'job_id':entry['job_id'],'phases':phases})
    return {'version':VERSION,'fixed_retries':15,'prediction_usage_cumulative':original.usage_summary(all_records),
            'retry_judge_usage_separate':original.usage_summary(judge_records),'jobs':by_job,'usd':None,
            'interpretation':'Cumulative costs retain original interrupted work plus one additional prediction; original durations/unreturned usage and gateway prices are unknown, never filled with0. Recovered accuracy therefore has conditional added resources.'}


def snapshot(comparison,output,draws=10000):
    original_version=original.VERSION;original.VERSION=VERSION
    try:report=original.snapshot(comparison,Path(output),draws)
    finally:original.VERSION=original_version
    costs=cumulative_cost(comparison);atomic(Path(output)/'paid-interruption-cumulative-cost.json',costs)
    report['paid_retry_cost_path']=str(Path(output)/'paid-interruption-cumulative-cost.json');atomic(Path(output)/'statistics.json',report)
    with (Path(output)/'summary.md').open('a') as f:f.write('\n15 interrupted .7 predictions use one fixed retry. Cumulative original + retry costs are in paid-interruption-cumulative-cost.json; missing costs remain unknown. First-pass statistics are retained.\n')
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--previous',type=Path,default=original.OUTPUT);p.add_argument('--retry-root',type=Path,default=DEFAULT_ROOT);p.add_argument('--output',type=Path,default=OUTPUT);p.add_argument('--watch',action='store_true');a=p.parse_args()
    while True:
        comparison=prepare_comparison(a.previous,a.retry_root,a.output);r=snapshot(comparison,a.output)
        print(json.dumps({'at':r['scan_finished_unix'],'version':VERSION,'ready_scales':sum(row['avg3_ready'] for row in r['summary'])}),flush=True)
        if not a.watch:break
        time.sleep(180)

if __name__=='__main__':main()
