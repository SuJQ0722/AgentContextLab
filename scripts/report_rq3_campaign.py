#!/usr/bin/env python3
"""Read-only RQ3 progress/accounting; inference only for complete 100 x 3 cohorts."""
import argparse,collections,fcntl,hashlib,json,math,time
from datetime import datetime,timezone
from pathlib import Path
import numpy as np
from lab import ROOT
from run_bc_campaign import attempt_state
from run_bc_trial import atomic
from monitor_dsh import read_lines,sum_usage,judge_call,write_csv
from analyze_significance import interval,paired_test,holm
SCALES=[0.,.125,.25,.5,.7,.8,1.]

def question_hash(job):return hashlib.sha256(job['question'].encode()).hexdigest()

def complete_cohort(rows):
    groups=collections.defaultdict(dict)
    for r in rows:
        key=(r['question_id'],int(r['repeat']))
        if key in groups[float(r['scale'])]:return False,'duplicate question/repeat in a scale'
        groups[float(r['scale'])][key]=r
    if set(groups)!=set(SCALES):return False,'seven planned scales required'
    base=groups[1.]
    ids={q for q,rep in base}
    if len(ids)!=100 or set(base)!={(q,r) for q in ids for r in [1,2,3]}:return False,'baseline is not complete 100 questions x 3 repeats'
    for scale,group in groups.items():
        if set(group)!=set(base):return False,'scale cohorts differ'
        for key,r in group.items():
            if r['question_hash']!=base[key]['question_hash']:return False,'question content mismatch'
            if r['model']!=base[key]['model']:return False,'model mismatch'
            score=r.get('score')
            if r['state']!='terminal' or not isinstance(score,(int,float)) or not math.isfinite(score) or not 0<=score<=1:
                return False,'waiting for every terminal prediction and valid grade'
    return True,'complete paired 100 x 3 on all seven scales'


def final_statistics(rows,out):
    ready,reason=complete_cohort(rows)
    if not ready:return
    signature=hashlib.sha256(json.dumps([{k:r[k] for k in ['job_id','scale','question_hash','repeat','score']} for r in rows],sort_keys=True).encode()).hexdigest()
    path=out/'statistics.json'
    if path.exists() and json.loads(path.read_text()).get('input_signature')==signature:return
    rng=np.random.default_rng(20261107);groups=collections.defaultdict(dict)
    for r in rows:groups[float(r['scale'])][(r['question_id'],r['repeat'])]=r['score']
    ids=sorted({q for q,rep in groups[1.]});summaries=[];pairs=[]
    base=np.array([[groups[1.][q,r] for r in [1,2,3]] for q in ids])
    for scale in SCALES:
        values=np.array([[groups[scale][q,r] for r in [1,2,3]] for q in ids]);per_repeat=values.mean(axis=0);ci=interval(values.mean(axis=1),rng)
        summaries.append({'scale':scale,'questions':100,'repeats':3,'accuracy':float(per_repeat.mean()),'repeat_std':float(per_repeat.std(ddof=1)),
                          'repeat_means':per_repeat.tolist(),'bootstrap95_low':ci[0],'bootstrap95_high':ci[1]})
        if scale!=1.:
            d=(values-base).mean(axis=1);dc=interval(d,rng)
            pairs.append({'scale':scale,'reference':1.,'paired_question_clusters':100,'delta_accuracy':float(d.mean()),
                          'bootstrap95_low':dc[0],'bootstrap95_high':dc[1],'paired_signflip_p':paired_test(d,rng)})
    for row,p in zip(pairs,holm([r['paired_signflip_p'] for r in pairs])):row['holm_p_six_prespecified_comparisons']=p
    atomic(path,{'input_signature':signature,'ready':True,'summary':summaries,'paired':pairs,
                 'protocol':'New DeepSeek reproduction, not verified old Table 5. 10,000 question-cluster bootstrap draws; paired question-cluster sign flips; Holm six comparisons.'})
    write_csv(out/'accuracy.csv',summaries);write_csv(out/'paired-tests.csv',pairs)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,ax=plt.subplots(figsize=(7,4));acc=np.array([r['accuracy'] for r in summaries]);lo=np.array([r['bootstrap95_low'] for r in summaries]);hi=np.array([r['bootstrap95_high'] for r in summaries])
    ax.errorbar(SCALES,acc*100,yerr=[(acc-lo)*100,(hi-acc)*100],marker='o',capsize=3)
    ax.set(xlabel='Far-history linear scale parameter',ylabel='Accuracy (%)',title='DeepSeek BC-100 x 3: question-bootstrap 95% CI');ax.grid(alpha=.2);fig.tight_layout()
    fig.savefig(out/'accuracy-with-ci.png',dpi=180);fig.savefig(out/'accuracy-with-ci.pdf');plt.close(fig)


def snapshot(root):
    plan=json.loads((root/'plan.json').read_text());out=root/'monitor';out.mkdir(exist_ok=True)
    groups=collections.defaultdict(lambda: {'states':collections.Counter(),'scored':0,'calls':[],'judges':[],'api_client_seconds_known':0.,'api_client_seconds_observed_calls':0,
        'render_seconds_known':0.,'render_records':0,'compression_count_logged':0,'far_exposure_confirmed_jobs':0,'far_exposure_unknown_jobs':0,'call_starts_without_returned_metrics':0})
    funding={x:[] for x in ['new_predictions','reused_prediction_observations','new_grading','reused_grading_observations']}
    rows=[];seen=set()
    for job in plan['jobs']:
        scale=float(job['scale']);external=bool(job.get('external_job_dir'));jobdir=Path(job['external_job_dir']) if external else root/'jobs'/job['job_id']
        if jobdir.resolve() in seen:raise ValueError('Duplicate job directory would double-count costs')
        seen.add(jobdir.resolve());state,last=attempt_state(jobdir);g=groups[scale];g['states'][state]+=1
        jpath=jobdir/'judge.json';judge=json.loads(jpath.read_text()) if jpath.exists() else {};score=judge.get('score')
        if isinstance(score,(int,float)) and math.isfinite(score) and 0<=score<=1:g['scored']+=1
        else:score=None
        row={'job_id':job['job_id'],'scale':scale,'question_id':job['question_id'],'question_hash':question_hash(job),'repeat':int(job['repeat']),
             'model':job['model'],'external_reused':external,'job_dir':str(jobdir),'state':state,'score':score,'judge_status':judge.get('status'),
             'end_to_end_seconds':None,'result_status':None,'far_exposure':'unknown','actual_billed_usd':None}
        for attempt in sorted((jobdir/'attempts').glob('attempt_*')):
            calls=[c for p in attempt.rglob('metrics/calls.jsonl') for c in read_lines(p)];g['calls'].extend(calls)
            funding['reused_prediction_observations' if external else 'new_predictions'].extend(calls)
            starts=[c for p in attempt.rglob('metrics/call-starts.jsonl') for c in read_lines(p)]
            g['call_starts_without_returned_metrics']+=max(0,len(starts)-len(calls))
            for c in calls:
                if c.get('client_stream_seconds') is not None:g['api_client_seconds_known']+=c['client_stream_seconds'];g['api_client_seconds_observed_calls']+=1
            renders=[c for p in attempt.rglob('metrics/render.jsonl') for c in read_lines(p)]
            for r in renders:
                if r.get('render_seconds') is not None:g['render_seconds_known']+=r['render_seconds'];g['render_records']+=1
            comps=[c for p in attempt.rglob('metrics/compression.jsonl') for c in read_lines(p)]
            g['compression_count_logged']+=sum(c.get('count_delta',1) for c in comps)
            if attempt==last:
                rpath=attempt/'result.json';result=json.loads(rpath.read_text()) if rpath.exists() else {}
                row['end_to_end_seconds']=result.get('end_to_end_seconds');row['result_status']=result.get('status')
                # Absence is never proof of no far history (especially at scale 0).
                if scale>0 and next(attempt.rglob('old_*.png'),None):row['far_exposure']='confirmed_old_image_artifact'
        if row['far_exposure'].startswith('confirmed'):g['far_exposure_confirmed_jobs']+=1
        else:g['far_exposure_unknown_jobs']+=1
        if judge.get('api_calls'):
            c=judge_call(judge);g['judges'].append(c);funding['reused_grading_observations' if external else 'new_grading'].append(c)
        rows.append(row)
    ready,reason=complete_cohort(rows)
    report={'updated_at':datetime.now(timezone.utc).isoformat(),'planned_jobs':len(rows),'headline_ready':ready,'readiness':reason,
            'new_jobs':sum(not r['external_reused'] for r in rows),'reused_jobs':sum(r['external_reused'] for r in rows),
            'scales':{},'accounting':{k:sum_usage(v) for k,v in funding.items()},
            'limitations':['Known counters only. Missing provider counters and started-without-returned requests are unknown, not zero.',
                'Reused 1x observations belong to core campaign: never add them again to new spend. No actual invoice pricing known.',
                'Client HTTP/stream time is not provider-internal API latency. Partial timing is labeled observed.',
                'Old-image existence confirms far exposure only; absence and scale0 remain unknown.',
                'No interim accuracy headline or repeated partial significance tests. New DeepSeek experiment, not confirmed old Table5.']}
    for scale,g in sorted(groups.items()):
        report['scales'][str(scale)]={k:v for k,v in g.items() if k not in ['calls','judges']}
        report['scales'][str(scale)].update(prediction_usage_known=sum_usage(g['calls']),grading_usage_known=sum_usage(g['judges']))
    write_csv(out/'jobs.csv',rows);atomic(out/'status.json',report)
    if ready:final_statistics(rows,out)
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=ROOT/'outputs/campaigns/rq3-deepseek-bc100-r3');p.add_argument('--watch',action='store_true');a=p.parse_args()
    if a.watch:
        (a.root/'monitor').mkdir(parents=True,exist_ok=True)
        lease=(a.root/'monitor/reporter.lock').open('a')
        fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
    while True:
        try:
            result=snapshot(a.root);print(json.dumps({'updated_at':result['updated_at'],'headline_ready':result['headline_ready'],
               'progress':{s:{'states':g['states'],'scored':g['scored']} for s,g in result['scales'].items()}}),flush=True)
            (a.root/'monitor/read-error.json').unlink(missing_ok=True)
        except (OSError,ValueError,KeyError) as e:
            (a.root/'monitor').mkdir(parents=True,exist_ok=True);atomic(a.root/'monitor/read-error.json',{'error_type':type(e).__name__,'detail':str(e)})
            if not a.watch:raise
        if not a.watch:break
        time.sleep(60)
if __name__=='__main__':main()
