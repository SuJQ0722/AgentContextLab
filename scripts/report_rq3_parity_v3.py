#!/usr/bin/env python3
"""Read-only paired RQ3 report; never converts incomplete grading into accuracy."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import statistics
import time
import numpy as np
from analyze_significance import interval, paired_test, holm
from report_bc_v3_scored import observation, write_csv
from judge_bc_v3_completed import atomic, read, sha
from run_rq3_parity_v3 import DEFAULT_ROOT, SCALES, MODEL, label
from lab import ROOT
GRADING=ROOT/'outputs/grading/rq3-parity-v3-deepseek-sfb-v1'
RECOVERY=ROOT/'outputs/campaigns/rq3-deepseek-bc100-r3-parity-v3-pre-native-recovery1'
RECOVERY2=ROOT/'outputs/campaigns/rq3-deepseek-bc100-r3-parity-v3-pre-native-recovery2'
RECOVERY_JOBS={'rq3-pre-native-reservation-recovery1':'hermes/scale_0800/q_085_r03','rq3-pre-native-reservation-recovery2':'hermes/scale_0000/q_043_r01'}


def jsonlines(path):
    if not path.exists():return []
    lines=path.read_text().splitlines();rows=[]
    for index,line in enumerate(lines):
        try:rows.append(json.loads(line))
        except json.JSONDecodeError:
            if index!=len(lines)-1:raise
    return rows


def exposure(attempt):
    metrics=attempt/'native/metrics';events=jsonlines(metrics/'compression.jsonl')
    renders=jsonlines(metrics/'render.jsonl');policy=jsonlines(metrics/'policy.jsonl')
    counts=[x.get('count_delta') for x in events if x.get('valid') is True]
    measured=bool(policy)
    return {'compression_count':sum(counts) if measured and all(type(n) is int and n>=0 for n in counts) else None,
            'render_calls':len(renders) if measured else None,
            'render_seconds':sum(x['render_seconds'] for x in renders) if measured and all(type(x.get('render_seconds')) in (int,float) for x in renders) else None,
            'exposure_note':'No compression means no observed resolution intervention; compressed subgroups are descriptive and post-treatment.'}


def analyze(rows,draws=10000,seed=20261109):
    rng=np.random.default_rng(seed);groups=defaultdict(list);summary=[];per_repeat=[];paired=[]
    for row in rows:groups[row['scale']].append(row)
    indices={}
    for scale in SCALES:
        rs=groups[scale];ix={(r['question_id'],r['repeat']):r for r in rs};indices[scale]=ix
        if len(ix)!=len(rs):raise ValueError('Duplicate question/repeat in RQ3')
        ids=sorted({q for q,r in ix});full=len(ix)==300 and len(ids)==100 and all((q,r) in ix and ix[q,r]['score'] is not None for q in ids for r in [1,2,3])
        repeats=[]
        for repeat in [1,2,3]:
            subset=[r for r in rs if r['repeat']==repeat];scores=[r['score'] for r in subset if r['score'] is not None]
            accuracy=statistics.mean(scores) if len(subset)==len(scores)==100 else None
            if accuracy is not None:repeats.append(accuracy)
            per_repeat.append({'scale':scale,'repeat':repeat,'planned':len(subset),'known':len(scores),'accuracy':accuracy})
        scores=[r['score'] for r in rs if r['score'] is not None];lo=hi=None
        if full:lo,hi=interval([statistics.mean(ix[q,r]['score'] for r in [1,2,3]) for q in ids],rng,draws)
        known_exposure=[r for r in rs if r.get('compression_count') is not None]
        compressed=[r for r in known_exposure if r['compression_count']>0]
        summary.append({'scale':scale,'planned':len(rs),'known_outcomes':len(scores),'missing_outcomes':len(rs)-len(scores),
            'accuracy_lower_bound':sum(scores)/len(rs) if rs else None,
            'accuracy_upper_bound':(sum(scores)+len(rs)-len(scores))/len(rs) if rs else None,
            'avg3_ready':full,'mean_accuracy':statistics.mean(repeats) if full else None,
            'std_across_three_repeats':statistics.stdev(repeats) if full else None,
            'bootstrap95_low':lo,'bootstrap95_high':hi,
            'exposure_instrumented':len(known_exposure),'compression_observed':len(compressed),
            'no_compression_observed_so_far':len(known_exposure)-len(compressed),
            'compression_count_observed':sum(r['compression_count'] for r in known_exposure),
            'prediction_states':dict(Counter(r['prediction_status'] for r in rs)),
            'score_states':dict(Counter(r['score_reason'] for r in rs))})
    reference=indices[1.]
    for scale in SCALES[:-1]:
        sample=indices[scale]
        ready=len(sample)==len(reference)==300 and set(sample)==set(reference) and all(d[k]['score'] is not None for d in [sample,reference] for k in d)
        if not ready:
            paired.append({'scale':scale,'reference_scale':1.,'ready':False,'reason':'Await all 100 paired questions x three scored outcomes at both scales'});continue
        ids=sorted({q for q,r in sample});delta=[statistics.mean(sample[q,r]['score']-reference[q,r]['score'] for r in [1,2,3]) for q in ids]
        lo,hi=interval(delta,rng,draws)
        paired.append({'scale':scale,'reference_scale':1.,'ready':True,'question_clusters':100,'paired_trajectories':300,
            'mean_delta_scale_minus_1x':statistics.mean(delta),'bootstrap95_low':lo,'bootstrap95_high':hi,'paired_signflip_p':paired_test(delta,rng,draws)})
    if all(p['ready'] for p in paired):
        for p,value in zip(paired,holm([p['paired_signflip_p'] for p in paired])):p['holm_p_six_comparisons']=value
    return {'summary':summary,'per_repeat':per_repeat,'paired_tests':paired,'draws':draws,'random_seed':seed}


def recovery_selection(root,recovery):
    path=recovery/'recovery-authorization.json'
    if not path.exists():return {},None
    auth=read(path)
    if auth.get('version') not in RECOVERY_JOBS or auth.get('max_recovery_native_launches')!=1 or len(auth.get('entries',[]))!=1:
        raise ValueError('Invalid fixed pre-native recovery authorization')
    if Path(auth['parent_root']).resolve()!=root or Path(auth['recovery_root']).resolve()!=recovery:
        raise ValueError('Recovery source root differs')
    if auth['parent_plan_sha256']!=sha(root/'plan.json') or auth['recovery_plan_sha256']!=sha(recovery/'plan.json'):
        raise ValueError('Recovery plan changed')
    if sha(root/'cohort.jsonl')!=sha(recovery/'cohort.jsonl'):raise ValueError('Recovery cohort differs')
    entry=auth['entries'][0];jid=entry['job_id']
    if jid!=RECOVERY_JOBS[auth['version']]:raise ValueError('Unapproved RQ3 recovery job')
    old=root/'jobs'/jid/'attempts/attempt_001';new=recovery/'jobs'/jid/'attempts/attempt_001'
    if Path(entry['parent_attempt']).resolve()!=old or Path(entry['retry_attempt']).resolve()!=new:raise ValueError('Recovery attempt path differs')
    if auth['version']=='rq3-pre-native-reservation-recovery2':
        directory=old.parents[1]
        for key,path in [('parent_spec_sha256',directory/'spec.json'),('parent_claim_sha256',directory/'claim/owner.json'),('dispatch_declaration_sha256',old/'dispatch-ops1.json'),('stop_ack_sha256',Path(entry['stop_ack_path']))]:
            if entry[key]!=sha(path):raise ValueError('Recovery2 original evidence changed')
    return {jid:(new,Path(auth['grading_root']).resolve())},{'authorization_sha256':sha(path),'selection':auth['selection'],
        'native_never_started_proof_available':(recovery/'never-started-proof.json').exists(),'job_id':jid,'recovery_root':str(recovery)}


def snapshot(root,grading,output,draws=10000,recovery=RECOVERY,recovery2=None):
    plan=read(root/'plan.json')
    if plan['definition'].get('version')!='rq3-hermes-parity-v3-sfb' or plan['definition']['model']!=MODEL:raise ValueError('Wrong RQ3 generation or route')
    if sha(root/'cohort.jsonl')!=plan['definition']['cohort_sha256']:raise ValueError('RQ3 cohort changed')
    selected,selection_metadata=recovery_selection(root,recovery.resolve());rows=[];first=[]
    recovery2=recovery2 or (RECOVERY2 if root==DEFAULT_ROOT.resolve() else None)
    second,second_metadata=recovery_selection(root,recovery2.resolve()) if recovery2 else ({},None)
    if set(selected)&set(second):raise ValueError('Duplicate fixed recovery selection')
    selected.update(second)
    for job in plan['jobs']:
        original=root/'jobs'/job['job_id']/'attempts/attempt_001'
        before=observation(job,original,grading);before.update(scale=job['scale']);before.update(exposure(original));first.append(before)
        if job['job_id'] in selected:
            attempt,judge=selected[job['job_id']];row=observation(job,attempt,judge)
            row.update(scale=job['scale']);row.update(exposure(attempt));row['selection']='fixed_pre_native_recovery_no_score_choice'
        else:row=dict(before,selection='original_attempt')
        rows.append(row)
    report={'at':time.time(),'plan_sha256':sha(root/'plan.json'),'model':MODEL,'planned_runs':2100,'pre_native_recovery_selection':selection_metadata,'pre_native_recovery2_selection':second_metadata,'first_pass':analyze(first,draws),
        'zero_semantics':'0x removes only far-history canvases; recent five-round canvases and retained head/tail evidence remain.',
        'inference_policy':'All 100 x 3 outcomes at both scales are required for paired inference. Resample 100 question clusters with repeats averaged within each question; sample std is across three repeat accuracies. Six two-sided paired sign-flip comparisons against fresh 1x, Holm only after all six ready.',
        'missing_policy':'Confirmed failed/timeouts count zero operational success. Incomplete/unknown/not-started/ungraded stay missing, with bounds. Exposed-only subgroups are descriptive, not randomized comparisons.',
        'limitations':'Repeat labels do not prove independent RNG seeds; p>0.05 does not prove equivalence. No old RQ3 or external core 1x result is pooled. Model gateway pricing is unknown; judge costs are separate.',
        **analyze(rows,draws)}
    output.mkdir(parents=True,exist_ok=True);atomic(output/'statistics.json',report)
    for name in ('summary','per_repeat','paired_tests'):write_csv(output/(name+'.csv'),report[name])
    write_csv(output/'first-pass-summary.csv',report['first_pass']['summary'])
    (output/'observations.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
    lines=['# RQ3: repaired native vision, fresh SFB runs','',report['zero_semantics'],'',
        '| Far-history scale | Known / 300 | Mean ± sample std | 95% bootstrap CI | Observed compression / instrumented |',
        '|---|---:|---:|---:|---:|']
    for r in report['summary']:
        mean=f"{100*r['mean_accuracy']:.2f} ± {100*r['std_across_three_repeats']:.2f}%" if r['avg3_ready'] else 'NA — incomplete'
        ci=f"[{100*r['bootstrap95_low']:.2f}, {100*r['bootstrap95_high']:.2f}]%" if r['avg3_ready'] else 'NA'
        lines.append(f"| {r['scale']:g}x | {r['known_outcomes']} / 300 | {mean} | {ci} | {r['compression_observed']} / {r['exposure_instrumented']} |")
    lines+=['','Pre-native recovery: '+(json.dumps(selection_metadata) if selection_metadata else 'None authorized.'),'','Migration reservation recovery: '+(json.dumps(second_metadata) if second_metadata else 'None authorized.'),'',report['inference_policy'],'',report['missing_policy'],'',report['limitations']]
    (output/'summary.md').write_text('\n'.join(lines)+'\n');return report


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--root',type=Path,default=DEFAULT_ROOT)
    ap.add_argument('--grading',type=Path,default=GRADING);ap.add_argument('--output',type=Path,default=GRADING/'analysis');ap.add_argument('--watch',action='store_true');args=ap.parse_args()
    while True:
        result=snapshot(args.root.resolve(),args.grading.resolve(),args.output.resolve());print(json.dumps({'at':result['at'],'ready_scales':sum(r['avg3_ready'] for r in result['summary'])}),flush=True)
        if not args.watch:break
        time.sleep(180)


if __name__=='__main__':main()
