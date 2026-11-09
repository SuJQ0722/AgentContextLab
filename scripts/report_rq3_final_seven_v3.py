#!/usr/bin/env python3
"""Add only the held q045r02 first-native recovery to the fixed final-seven report."""
import argparse,json,time
from pathlib import Path
import report_rq3_final_seven_v2 as previous
from recover_rq3_pre_native_third_once import DEFAULT_ROOT,MANIFEST,JOB,validate_scope,exit_proof
from judge_bc_v3_completed import read,sha,atomic,namespace
from bc_route_runtime_v2 import immutable_json
VERSION='rq3-final-seven-v3-pre-native3'
OUTPUT=previous.original.ROOT/'outputs/grading/rq3-final-seven-v3'


def prepare_comparison(old_output,recovery_root,output):
    old_output=Path(old_output).resolve();recovery_root=Path(recovery_root).resolve();output=Path(output).resolve();old=read(old_output/'comparison-plan.json')
    if old.get('scales')!=list(previous.original.SCALES) or len(old.get('entries',[]))!=2100:raise ValueError('Final seven scope changed')
    for path,h in old['source_files_sha256'].items():
        if sha(path)!=h:raise ValueError('Previous comparison binding changed')
    _,a=validate_scope(recovery_root);entry=a['entries'][0];new=json.loads(json.dumps(old));matches=[r for r in new['entries'] if r['job_id']==JOB]
    if len(matches)!=1:raise ValueError('Held observation is not unique')
    row=matches[0]
    if row['scale']!=.7 or row['selected_attempt']!=entry['parent_attempt'] or row['original_attempt']!=entry['parent_attempt']:raise ValueError('Cannot replace another recovery or wrong source')
    row.update(selected_attempt=entry['retry_attempt'],grading_root=a['grading_root'],selection='fixed_pre_native_recovery3_first_launch')
    new['version']=VERSION;new['selection_policy']+=' q045r02 additionally selects exactly one first-native recovery after original exact-owner exit and api_calls0; not an extra repeat.'
    new['source_files_sha256'][str(old_output/'comparison-plan.json')]=sha(old_output/'comparison-plan.json')
    for p in [recovery_root/MANIFEST,recovery_root/'plan.json']:new['source_files_sha256'][str(p)]=sha(p)
    new['pre_native3_root']=str(recovery_root);new['previous_comparison_root']=str(old_output)
    immutable_json(output/'comparison-plan.json',new);return new


def single_cost(comparison):
    root=Path(comparison['pre_native3_root']);a=read(root/MANIFEST);proof,state=exit_proof(a);entry=a['entries'][0];attempt=Path(entry['retry_attempt']);metrics=attempt/'native/metrics'
    calls={r['call_id']:r for r in previous.original.jsonlines(metrics/'calls.jsonl') if r.get('call_id')};starts={r['call_id'] for r in previous.original.jsonlines(metrics/'call-starts.jsonl') if r.get('call_id')}
    gradepath=Path(a['grading_root'])/'sources'/namespace(root)/'jobs'/JOB/'grade.json';grades=[read(gradepath)] if gradepath.exists() else []
    return {'job_id':JOB,'proof_state':state,'original_verified_api_calls':0 if proof else None,'proof':proof,
            'new_prediction_usage':previous.original.usage_summary(list(calls.values())),'starts_without_return':len(starts-set(calls)),
            'judge_usage_separate':previous.original.usage_summary(grades),'usd':None,'meaning':'One first native launch only after original controller exit and explicit not_started/api_calls0. Unmet proof does not authorize a prediction.'}


def snapshot(comparison,output,draws=10000):
    old=previous.VERSION;previous.VERSION=VERSION
    try:r=previous.snapshot(comparison,output,draws)
    finally:previous.VERSION=old
    cost=single_cost(comparison);path=Path(output)/'pre-native-recovery3-cost.json';atomic(path,cost);r['pre_native3_cost_path']=str(path);atomic(Path(output)/'statistics.json',r)
    with (Path(output)/'summary.md').open('a') as f:f.write('\nq045r02 uses one separately authorized first-native recovery, gated on original exact-owner exit and explicit zero-API not_started evidence. See pre-native-recovery3-cost.json.\n')
    return r


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--previous',type=Path,default=previous.OUTPUT);p.add_argument('--recovery-root',type=Path,default=DEFAULT_ROOT);p.add_argument('--output',type=Path,default=OUTPUT);p.add_argument('--watch',action='store_true');args=p.parse_args()
    while True:
        c=prepare_comparison(args.previous,args.recovery_root,args.output);r=snapshot(c,args.output);print(json.dumps({'at':r['scan_finished_unix'],'version':VERSION,'planned':2100}),flush=True)
        if not args.watch:break
        time.sleep(180)
if __name__=='__main__':main()
