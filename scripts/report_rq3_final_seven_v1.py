#!/usr/bin/env python3
"""Read-only final RQ3 scope: reuse six scales, add .75, retain .125 costs separately."""
import argparse
from collections import Counter,defaultdict
import hashlib
import json
import math
from pathlib import Path
import statistics
import time
import numpy as np
from analyze_significance import interval,paired_test,holm
from bc_route_runtime_v2 import immutable_json
from judge_bc_v3_completed import atomic,read,sha,namespace,usage_fields
from report_bc_v3_scored import observation,write_csv
from report_rq3_parity_v3 import exposure,jsonlines,recovery_selection,RECOVERY,RECOVERY2
import run_rq3_parity_v3 as legacy
from lab import ROOT

VERSION='rq3-final-seven-v1'
SCALES=(0.,.25,.5,.7,.75,.8,1.)
LEGACY_SCALES=tuple(s for s in SCALES if s!=.75)
NEW_ROOT=ROOT/'outputs/campaigns/rq3-deepseek-bc100-r3-scale0750-v1'
LEGACY_GRADING=ROOT/'outputs/grading/rq3-parity-v3-deepseek-sfb-v1'
NEW_GRADING=ROOT/'outputs/grading/rq3-scale0750-v1'
OUTPUT=ROOT/'outputs/grading/rq3-final-seven-v1'

class PendingInputs(Exception):pass

def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'))
def object_sha(value):return hashlib.sha256(canonical(value).encode()).hexdigest()
def scientific_config(config):
    cfg=json.loads(json.dumps(config));cfg.pop('rq3',None);cfg['visual_renderer'].pop('history_scale',None);return cfg


def prepare_comparison(parent,new_root,grading,new_grading,output,recovery_roots=None):
    parent=Path(parent).resolve();new_root=Path(new_root).resolve();output=Path(output).resolve()
    grading=Path(grading).resolve();new_grading=Path(new_grading).resolve()
    revision=parent/'cloud-scale-ops2/scope-revision-20261109.json';scope_path=new_root/'scale0750-scope.json'
    if not scope_path.exists():raise PendingInputs('Awaiting the explicit .75 source manifest; no old scale is substituted')
    scope=read(scope_path);revised=read(revision);old=read(parent/'plan.json');new=read(new_root/'plan.json')
    if revised.get('final_scales')!=list(SCALES) or revised.get('excluded_scale')!=.125 or revised.get('new_scale')!=.75 or revised.get('planned_observations')!=2100:
        raise ValueError('Final user-authorized scale scope differs')
    if scope.get('version')!='rq3-scale0750-scope-v1' or Path(scope['parent_root']).resolve()!=parent or Path(scope['root']).resolve()!=new_root:
        raise ValueError('New .75 source lineage differs')
    if scope.get('parent_plan_sha256')!=sha(parent/'plan.json') or scope.get('plan_sha256')!=sha(new_root/'plan.json'):
        raise ValueError('New source plan hashes differ')
    if scope.get('final_scales')!=list(SCALES) or scope.get('authorized_scale')!=.75 or scope.get('authorized_runs')!=300 or scope.get('placeholder_execution_authorized') is not False:
        raise ValueError('Only the new 300 .75 observations may be selected from the new source')
    cohort_sha=sha(parent/'cohort.jsonl')
    if cohort_sha!=sha(new_root/'cohort.jsonl') or cohort_sha!=scope.get('cohort_sha256'):raise ValueError('Source question cohorts differ')
    cohort={r['id']:r for r in (json.loads(l) for l in (parent/'cohort.jsonl').read_text().splitlines() if l.strip())}
    if len(cohort)!=100:raise ValueError('Exactly the fixed 100 question cohort is required')
    expected={(q,r) for q in cohort for r in (1,2,3)}
    source_files={str(revision):sha(revision),str(scope_path):sha(scope_path)}
    for root,plan in [(parent,old),(new_root,new)]:
        d=plan['definition']
        if d.get('model')!=legacy.MODEL or d.get('cohort_sha256')!=cohort_sha:raise ValueError('Source model or cohort differs')
        if d.get('config_sha256')!=sha(root/'experiment.json') or d.get('jobs_sha256')!=object_sha(plan['jobs']):raise ValueError('Source definition changed')
        for relative in ('plan.json','experiment.json','cohort.jsonl'):source_files[str(root/relative)]=sha(root/relative)
    authorized=[j['job_id'] for j in new['jobs'] if j.get('scale')==.75]
    if authorized!=scope.get('authorized_job_ids') or object_sha(authorized)!=scope.get('authorized_job_ids_sha256'):raise ValueError('.75 authorized list differs')
    selected_recoveries={};recovery_sources=[]
    for recovery in ((RECOVERY,RECOVERY2) if recovery_roots is None else recovery_roots):
        recovery=Path(recovery).resolve();authorization=recovery/'recovery-authorization.json'
        if not authorization.exists():raise PendingInputs('Awaiting fixed pre-native recovery authorization')
        selected,_=recovery_selection(parent,recovery)
        if set(selected)&set(selected_recoveries):raise ValueError('Two recoveries replace the same observation')
        selected_recoveries.update(selected)
        source_files[str(authorization)]=sha(authorization)
        source_files[str(recovery/'plan.json')]=sha(recovery/'plan.json')
        recovery_sources.append({'root':str(recovery),'authorization_path':str(authorization),'authorization_sha256':sha(authorization)})
    baseline=scientific_config(read(parent/'configs/scale_1000.json'));entries=[];config_cache={}
    for scale in SCALES:
        root,plan,judge=(new_root,new,new_grading) if scale==.75 else (parent,old,grading)
        jobs=[j for j in plan['jobs'] if j.get('scale')==scale]
        if len(jobs)!=300 or {(j['question_id'],j['repeat']) for j in jobs}!=expected:raise ValueError('Each scale must match the same100 x repeats1,2,3')
        for job in sorted(jobs,key=lambda j:(j['question_id'],j['repeat'])):
            if job.get('harness')!='hermes' or job.get('strategy')!='visual' or job.get('model')!=legacy.MODEL or job['question']!=cohort[job['question_id']]['question']:
                raise ValueError('Question, method or route changed across scales')
            if job['job_id']!=f"hermes/{legacy.label(scale)}/{job['question_id']}_r{job['repeat']:02d}":raise ValueError('Unexpected job identity')
            cfgpath=Path(job['config_path']).resolve();relative=str(cfgpath.relative_to(root))
            if cfgpath not in config_cache:config_cache[cfgpath]=(read(cfgpath),sha(cfgpath))
            cfg,cfg_sha=config_cache[cfgpath]
            if cfg_sha!=plan['definition']['scale_config_sha256'].get(relative):raise ValueError('Per-scale frozen config changed')
            if cfg['visual_renderer']['history_scale']!=scale or scientific_config(cfg)!=baseline:raise ValueError('Scientific parameters differ beyond the authorized history scale and rq3 metadata')
            source_files[str(cfgpath)]=cfg_sha
            attempt=root/'jobs'/job['job_id']/'attempts/attempt_001';chosen,chosen_grading=selected_recoveries.get(job['job_id'],(attempt,judge)) if scale!=.75 else (attempt,judge)
            entries.append({'scale':scale,'job_id':job['job_id'],'question_id':job['question_id'],'repeat':job['repeat'],
                'question_sha256':hashlib.sha256(job['question'].encode()).hexdigest(),'source_root':str(root),'original_attempt':str(attempt),
                'selected_attempt':str(chosen),'grading_root':str(chosen_grading),'original_grading_root':str(judge),
                'selection':'fixed_pre_native_recovery' if chosen!=attempt else 'original_planned_attempt'})
    if len(entries)!=2100 or any(e['scale']==.125 for e in entries):raise ValueError('Final comparison must contain2100 entries and exclude .125')
    result={'version':VERSION,'model':legacy.MODEL,'scales':list(SCALES),'planned_observations':2100,'questions':100,'repeats':[1,2,3],
        'legacy_root':str(parent),'new_root':str(new_root),'legacy_grading':str(grading),'new_grading':str(new_grading),
        'excluded_scale':.125,'excluded_scale_policy':'Retain all original trajectories and observed prediction/judge spending separately; never pool .125 scores.',
        'source_files_sha256':source_files,'recovery_sources':recovery_sources,'entries':entries,
        'selection_policy':'Six original scale cohorts are reused without rerun. Only .75 comes from the independent new root. Fixed pre-native recoveries do not add repeats or choose by score.'}
    output.mkdir(parents=True,exist_ok=True);immutable_json(output/'comparison-plan.json',result)
    return result


def analyze(rows,draws=10000,seed=20261109):
    groups=defaultdict(list);rng=np.random.default_rng(seed);summaries=[];repeats=[];pairs=[];indices={};ready_scales={}
    if any(r['scale'] not in SCALES or r['score'] not in (None,0,1) for r in rows):raise ValueError('Unexpected scale or nonbinary score')
    for row in rows:groups[row['scale']].append(row)
    for scale in SCALES:
        rs=groups[scale];ix={(r['question_id'],r['repeat']):r for r in rs};indices[scale]=ix
        if len(ix)!=len(rs):raise ValueError('Duplicate question/repeat')
        ids=sorted({q for q,r in ix});full=len(rs)==300 and len(ids)==100 and all((q,r) in ix and ix[q,r]['score'] is not None for q in ids for r in (1,2,3));ready_scales[scale]=full
        rep_acc=[]
        for repeat in (1,2,3):
            subset=[r for r in rs if r['repeat']==repeat];known=[r['score'] for r in subset if r['score'] is not None]
            acc=statistics.mean(known) if len(subset)==len(known)==100 else None
            if acc is not None:rep_acc.append(acc)
            repeats.append({'scale':scale,'repeat':repeat,'planned':len(subset),'known':len(known),'accuracy':acc})
        known=[r['score'] for r in rs if r['score'] is not None];correct=sum(known);lo=hi=None
        if full:lo,hi=interval([statistics.mean(ix[q,r]['score'] for r in (1,2,3)) for q in ids],rng,draws)
        instrumented=[r for r in rs if r.get('compression_count') is not None]
        summaries.append({'scale':scale,'planned':len(rs),'known_outcomes':len(known),'correct':correct,'provisional_correct_over_known':correct/len(known) if known else None,
            'coverage':len(known)/len(rs) if rs else None,'accuracy_lower_bound':correct/len(rs) if rs else None,'accuracy_upper_bound':(correct+len(rs)-len(known))/len(rs) if rs else None,
            'avg3_ready':full,'mean_accuracy':statistics.mean(rep_acc) if full else None,'std_across_three_repeats':statistics.stdev(rep_acc) if full else None,
            'bootstrap95_low':lo,'bootstrap95_high':hi,'compression_instrumented':len(instrumented),'compression_observed':sum(r['compression_count']>0 for r in instrumented),
            'prediction_states':dict(Counter(r['prediction_status'] for r in rs)),'score_states':dict(Counter(r['score_reason'] for r in rs))})
    control=indices[1.]
    for scale in SCALES[:-1]:
        sample=indices[scale];ready=ready_scales[scale] and ready_scales[1.] and set(sample)==set(control)
        if not ready:pairs.append({'scale':scale,'reference_scale':1.,'ready':False,'reason':'Requires all100 paired questions x three known outcomes at both scales'});continue
        ids=sorted({q for q,r in sample});delta=[statistics.mean(sample[q,r]['score']-control[q,r]['score'] for r in (1,2,3)) for q in ids]
        lo,hi=interval(delta,rng,draws);pairs.append({'scale':scale,'reference_scale':1.,'ready':True,'question_clusters':100,'paired_trajectories':300,
            'mean_delta_scale_minus_1x':statistics.mean(delta),'bootstrap95_low':lo,'bootstrap95_high':hi,'paired_signflip_p':paired_test(delta,rng,draws)})
    if all(p['ready'] for p in pairs):
        for p,adjusted in zip(pairs,holm([p['paired_signflip_p'] for p in pairs])):p['holm_p_six_comparisons']=adjusted
    return {'summary':summaries,'per_repeat':repeats,'paired_tests':pairs,'draws':draws,'random_seed':seed}


def usage_summary(records):
    sums=Counter();known=Counter();missing=Counter();errors=Counter()
    for record in records:
        usage=usage_fields(record.get('raw_provider_usage'))
        for key in ('prompt_tokens','cached_input_tokens','noncache_input_tokens','output_tokens','total_tokens'):
            value=usage[key]
            if value is None:missing[key]+=1
            else:sums[key]+=value;known[key]+=1
        if usage['conservation'] is not None:known['conservation_checked']+=1;known['conservation_violations']+=int(not usage['conservation'])
        if record.get('error_type'):errors[record['error_type']]+=1
    return {'returned_records':len(records),'observed_subtotals':{k:sums[k] if known[k] else None for k in ('prompt_tokens','cached_input_tokens','noncache_input_tokens','output_tokens','total_tokens')},
        'known_field_counts':dict(known),'missing_field_counts':dict(missing),'error_types':dict(errors),'usd':None,
        'accounting':'Observed returned usage only; missing fields/unreturned requests are unknown, not zero. SDK retries may have unobserved billed work; no claim of complete provider billing.'}


def excluded_cost(comparison):
    root=Path(comparison['legacy_root']);grading=Path(comparison['legacy_grading']);plan=read(root/'plan.json');jobs=[j for j in plan['jobs'] if j.get('scale')==.125]
    records=[];judge_records=[];starts=set();states=Counter();job_records=[];judge_unknown=0
    for job in jobs:
        attempt=root/'jobs'/job['job_id']/'attempts/attempt_001';metrics=attempt/'native/metrics';result=read(attempt/'result.json') if (attempt/'result.json').exists() else {}
        state=result.get('status','no_terminal_result');states[state]+=1
        calls={r['call_id']:r for r in jsonlines(metrics/'calls.jsonl') if r.get('call_id')}
        local_starts={r['call_id'] for r in jsonlines(metrics/'call-starts.jsonl') if r.get('call_id')}
        starts.update((job['job_id'],cid) for cid in local_starts);records.extend(calls.values())
        directory=grading/'sources'/namespace(root)/'jobs'/job['job_id'];grade=read(directory/'grade.json') if (directory/'grade.json').exists() else {}
        if grade and grade.get('api_calls')!=0:judge_records.append(grade)
        elif not grade and (directory/'request-started.json').exists():judge_unknown+=1
        job_records.append({'job_id':job['job_id'],'attempt':str(attempt),'prediction_status':state,'request_starts':len(local_starts),'returned_calls':len(calls),
            'starts_without_return':len(local_starts-set(calls)),'metrics_path':str(metrics),'judge_path':str(directory/'grade.json') if grade else None})
    return {'excluded_scale':.125,'excluded_from_accuracy':True,'planned_original_observations':len(jobs),'prediction_states':dict(states),
        'prediction_sdk_request_starts':len(starts),'prediction_starts_without_return':sum(r['starts_without_return'] for r in job_records),
        'prediction_usage':usage_summary(records),'judge_usage':usage_summary(judge_records),'unresolved_judge_requests':judge_unknown,
        'cost_policy':'All incurred .125 work is retained as a separate project-cost ledger, not reassigned to .75 and not hidden inside the corrected2100 comparison.',
        'jobs':job_records}


def exposure_for(attempt):
    if not (attempt/'native/metrics/policy.jsonl').exists():
        return {'compression_count':None,'render_calls':None,'render_seconds':None}
    return exposure(attempt)


def snapshot(comparison,output,draws=10000):
    started=time.time();output=Path(output);sources=comparison['source_files_sha256']
    for path,expected in sources.items():
        if sha(path)!=expected:raise ValueError('Bound comparison source changed: '+path)
    plans={root:{j['job_id']:j for j in read(Path(root)/'plan.json')['jobs']} for root in [comparison['legacy_root'],comparison['new_root']]}
    rows=[];first=[]
    for entry in comparison['entries']:
        job=plans[entry['source_root']][entry['job_id']];original=Path(entry['original_attempt']);chosen=Path(entry['selected_attempt'])
        before=observation(job,original,Path(entry['original_grading_root']));before.update(scale=entry['scale']);before.update(exposure_for(original));first.append(before)
        after=dict(before) if original==chosen else observation(job,chosen,Path(entry['grading_root']))
        after.update(scale=entry['scale'],selection=entry['selection'])
        if original!=chosen:after.update(exposure_for(chosen))
        rows.append(after)
    cost=excluded_cost(comparison)
    report={'version':VERSION,'scan_started_unix':started,'scan_finished_unix':time.time(),'comparison_plan_sha256':sha(output/'comparison-plan.json'),
        'scales':list(SCALES),'planned_observations':2100,'first_pass':analyze(first,draws),**analyze(rows,draws),
        'zero_semantics':'0x omits far-history canvases only; recent five-round canvases and retained head/tail native evidence remain.',
        'selection_policy':comparison['selection_policy'],'excluded_scale_cost_path':str(output/'excluded-scale0125-cost.json'),
        'inference_policy':'Complete100x3 outcomes at both scales before paired inference. Bootstrap100 question clusters with repeats averaged within each; sample std across three repeat accuracies. Six two-sided sign-flip comparisons against1x; Holm correction once all six ready.',
        'missing_policy':'Confirmed failed/timeouts with cleanup count operational failure0. Unknown/not-started/incomplete grading remain missing with300-denominator bounds. Provisional correct/known is not full-cohort accuracy.',
        'limitations':'Repeat labels do not prove independent random seeds; p>0.05 does not prove equivalence. Exposed-only comparisons are post-treatment descriptive. USD pricing unknown; excluded-scale and judge spending remain separate.'}
    atomic(output/'statistics.json',report);atomic(output/'excluded-scale0125-cost.json',cost)
    for name in ('summary','per_repeat','paired_tests'):write_csv(output/(name+'.csv'),report[name])
    write_csv(output/'first-pass-summary.csv',report['first_pass']['summary'])
    (output/'observations.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
    lines=['# RQ3 final seven-scale comparison','',comparison['selection_policy'],'',report['zero_semantics'],'',
        '| Scale | Known /300 | Provisional correct /known | Full300 accuracy bounds | Avg@3 ± sample std | Bootstrap95% CI |',
        '|---|---:|---:|---:|---:|---:|']
    for r in report['summary']:
        provisional=f"{r['correct']:g}/{r['known_outcomes']} ({r['provisional_correct_over_known']*100:.2f}%)" if r['known_outcomes'] else 'NA'
        mean=f"{r['mean_accuracy']*100:.2f} ± {r['std_across_three_repeats']*100:.2f}%" if r['avg3_ready'] else 'NA — incomplete'
        ci=f"[{r['bootstrap95_low']*100:.2f}, {r['bootstrap95_high']*100:.2f}]%" if r['avg3_ready'] else 'NA'
        lines.append(f"| {r['scale']:g}x | {r['known_outcomes']}/300 | {provisional} | [{100*r['accuracy_lower_bound']:.2f}, {100*r['accuracy_upper_bound']:.2f}]% | {mean} | {ci} |")
    lines+=['','0.125x is excluded from these scores. Its original logs and observed spending are preserved in excluded-scale0125-cost.json.','',report['inference_policy'],'',report['missing_policy'],'',report['limitations']]
    (output/'summary.md').write_text('\n'.join(lines)+'\n');return report


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--legacy-root',type=Path,default=legacy.DEFAULT_ROOT);ap.add_argument('--new-root',type=Path,default=NEW_ROOT)
    ap.add_argument('--legacy-grading',type=Path,default=LEGACY_GRADING);ap.add_argument('--new-grading',type=Path,default=NEW_GRADING);ap.add_argument('--output',type=Path,default=OUTPUT);ap.add_argument('--watch',action='store_true');args=ap.parse_args()
    while True:
        try:
            comparison=prepare_comparison(args.legacy_root,args.new_root,args.legacy_grading,args.new_grading,args.output)
            result=snapshot(comparison,args.output.resolve());print(json.dumps({'at':result['scan_finished_unix'],'ready_scales':sum(r['avg3_ready'] for r in result['summary']),'final_scales':SCALES}),flush=True)
        except PendingInputs as error:
            args.output.mkdir(parents=True,exist_ok=True);atomic(args.output/'status.json',{'at':time.time(),'state':'awaiting_frozen_inputs','detail':str(error),'paid_calls':0});print(json.dumps({'state':'awaiting_frozen_inputs'}),flush=True)
        if not args.watch:break
        time.sleep(180)


if __name__=='__main__':main()
