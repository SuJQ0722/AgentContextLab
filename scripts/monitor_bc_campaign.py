#!/usr/bin/env python3
"""Audit both harnesses and every retained attempt without inference calls."""
import argparse
import collections
from datetime import datetime,timezone
import json
from pathlib import Path
import time
from monitor_dsh import read_lines,sum_usage,judge_call,write_csv
from run_bc_trial import atomic,process_identity
from run_bc_campaign import attempt_state


def snapshot(root):
    plan=json.loads((root/'plan.json').read_text());out=root/'monitor';out.mkdir(exist_ok=True)
    rows=[];calls=[];judges=[];issues=[];groups=collections.defaultdict(list);counts=collections.Counter()
    for job in plan['jobs']:
        jobdir=root/'jobs'/job['job_id'];state,last=attempt_state(jobdir);counts[state]+=1
        for attempt in sorted((jobdir/'attempts').glob('attempt_*')):
            rpath=attempt/'result.json';r=json.loads(rpath.read_text()) if rpath.exists() else {}
            c=[c for p in attempt.rglob('metrics/calls.jsonl') for c in read_lines(p)]
            calls.extend(c);groups[f"{job['harness']}/{job['strategy']}"].extend(c)
            web=[w for p in attempt.rglob('metrics/web.jsonl') for w in read_lines(p)]
            compress=[x for p in attempt.rglob('metrics/compression.jsonl') for x in read_lines(p)]
            renders=[x for p in attempt.rglob('metrics/render.jsonl') for x in read_lines(p)]
            usage=sum_usage(c);searches=[w for w in web if w['kind']=='search']
            hits=sum(str(w.get('cache_header')).lower()=='true' for w in searches)
            misses=sum(str(w.get('cache_header')).lower()=='false' for w in searches)
            judgepath=jobdir/'judge.json';judge=json.loads(judgepath.read_text()) if judgepath.exists() else {}
            if attempt==last and judge.get('api_calls'):judges.append(judge_call(judge))
            row={k:job[k] for k in ['job_id','harness','strategy','question_id','repeat','model']}
            row.update(attempt=attempt.name,canonical_terminal=attempt==last and state=='terminal',
                status=r.get('status','running' if attempt==last and state=='running' else 'interrupted'),**usage,
                end_to_end_seconds=r.get('end_to_end_seconds'),native_end_to_end_seconds=r.get('native_end_to_end_seconds'),
                api_client_seconds=sum(v['client_stream_seconds'] for v in c if v.get('client_stream_seconds') is not None) if c else None,
                compression_count=sum(x.get('count_delta',1) for x in compress),
                render_seconds=sum(x['render_seconds'] for x in renders) if renders else None,
                serper_requests=len(searches),serper_cache_hits=hits,serper_cache_misses=misses,
                serper_cache_unknown=len(searches)-hits-misses,serper_cache_hit_rate=hits/(hits+misses) if hits+misses else None,
                web_transport_errors=sum(not w.get('success') for w in web),
                score=judge.get('score') if attempt==last else None,actual_billed_usd=None)
            rows.append(row)
            for key in ['missing_usage','conservation_failures']:
                if usage[key]:issues.append({'job_id':job['job_id'],'attempt':attempt.name,'kind':key,'count':usage[key]})
            if state=='running' and attempt==last:
                metrics=list(attempt.rglob('metrics/*.jsonl'))
                age=time.time()-max((p.stat().st_mtime for p in metrics),default=attempt.stat().st_mtime)
                if age>300:issues.append({'job_id':job['job_id'],'kind':'no_metric_activity_5min','age_seconds':age})
    coordinator=json.loads((root/'coordinator.json').read_text()) if (root/'coordinator.json').exists() else {}
    live=bool(coordinator.get('start_identity')) and process_identity(coordinator['pid'])==coordinator.get('start_identity')
    if not live and counts['terminal']<len(plan['jobs']):issues.append({'kind':'coordinator_not_running','unfinished':len(plan['jobs'])-counts['terminal']})
    totals=sum_usage(calls)
    report={'updated_at':datetime.now(timezone.utc).isoformat(),'coordinator_alive':live,
        'planned_runs':len(plan['jobs']),'concurrency_limit':plan['definition']['concurrency'],'states':dict(counts),
        'attempts_observed':len(rows),'prediction_usage_all_attempts':totals,
        'grading_usage':sum_usage(judges),'all_usage':sum_usage(calls+judges),
        'usage_by_harness_strategy':{k:sum_usage(v) for k,v in groups.items()},'issues':issues,
        'limitations':['Known usage only; failed/interrupted requests may lack provider counters.',
            'SDK/adapter timing includes retries; not provider-internal latency.',
            'Concurrency16 and shared model/web caches affect timing and cache hit rates.',
            'No accuracy claimed for ungraded jobs; both harnesses retain their native policy algorithms.']}
    write_csv(out/'attempts.csv',rows);atomic(out/'status.json',report)
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True);p.add_argument('--watch',action='store_true');a=p.parse_args()
    while True:
        try:
            report=snapshot(a.root);print(json.dumps({k:report[k] for k in ['updated_at','coordinator_alive','states','attempts_observed']}),flush=True)
            (a.root/'monitor/read-error.json').unlink(missing_ok=True)
        except (ValueError,OSError,KeyError) as e:
            (a.root/'monitor').mkdir(exist_ok=True)
            atomic(a.root/'monitor/read-error.json',{'time':datetime.now(timezone.utc).isoformat(),'type':type(e).__name__,'detail':str(e)})
            if not a.watch:raise
        if not a.watch:break
        time.sleep(30)


if __name__=='__main__':main()
