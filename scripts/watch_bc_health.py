#!/usr/bin/env python3
"""Read-only BC supervision: process identities, usage quality, guards and controller lease."""
import argparse
import collections
from datetime import datetime,timezone
import fcntl
import json
import os
from pathlib import Path
import time
from lab import ROOT
from monitor_dsh import read_lines,normalized_usage
from resume_bc_plan import classify_attempt
from run_bc_trial import atomic,process_identity


def snapshot(root):
    now=time.time();status=json.loads((root/'status.json').read_text());monitor=json.loads((root/'monitor/status.json').read_text())
    cfg=json.loads((root/'experiment.json').read_text());budget=cfg['pilot']['post_compression_budget_tokens']
    identities={}
    for name in ['coordinator.json','resume-controller-service.json']:
        if (root/name).exists():
            r=json.loads((root/name).read_text());identities[name]={'pid':r['pid'],'alive':bool(r.get('start_identity')) and process_identity(r['pid'])==r['start_identity']}
    lease=(root/'coordinator.lock').open('a')
    try:
        fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB);lock_busy=False
        fcntl.flock(lease,fcntl.LOCK_UN)
    except BlockingIOError:lock_busy=True
    finally:lease.close()
    counts=collections.Counter();missing=collections.Counter();active=[];terminal=[]
    for directory in (root/'jobs').glob('*/*/*'):
        attempts=sorted((directory/'attempts').glob('attempt_*'))
        if not attempts:continue
        last=attempts[-1];result=last/'result.json'
        if result.exists():
            label=classify_attempt(last,budget);counts[label]+=1
            if label in ('budget_limit','unexpected_failure'):terminal.append({'job_id':str(directory.relative_to(root/'jobs')),'classification':label})
        else:
            running=last/'running.json'
            if running.exists():
                r=json.loads(running.read_text());alive=process_identity(r['pid'])==r.get('start_identity') and bool(r.get('start_identity'))
                metrics=list(last.rglob('metrics/*.jsonl'))
                active.append({'job_id':str(directory.relative_to(root/'jobs')),'pid':r['pid'],'identity_alive':alive,
                    'metric_age_seconds':round(now-max((p.stat().st_mtime for p in metrics),default=last.stat().st_mtime),1)})
        for attempt in attempts:
            for path in attempt.rglob('metrics/calls.jsonl'):
                for call in read_lines(path):
                    if normalized_usage(call)['total_tokens'] is None:
                        finish=call.get('finish') or {};kind=finish.get('kind','unknown')
                        failure=finish.get('failure') or {};error=call.get('error_type') or failure.get('code') or 'no_error_code'
                        missing[f'{kind}/{error}']+=1
    visible=sum(p.name.isdigit() for p in Path('/proc').iterdir())
    intended_pause=bool(status.get('pause_requested'))
    alerts=[]
    if visible>=128:alerts.append('visible_process_limit_violated')
    if len([a for a in active if a['identity_alive']])>16:alerts.append('core_worker_limit_violated')
    if monitor['prediction_usage_all_attempts']['conservation_failures']:alerts.append('token_conservation_failure')
    if now-(root/'monitor/status.json').stat().st_mtime>120:alerts.append('monitor_stale')
    if not intended_pause and not lock_busy and status.get('states',{}).get('terminal',0)<status.get('planned_runs',3000):alerts.append('coordinator_lease_free_with_pending_jobs')
    if not intended_pause and any(not r['alive'] for r in identities.values()):alerts.append('controller_or_standby_identity_dead')
    for a in active:
        if not a['identity_alive']:alerts.append('dead_worker:'+a['job_id'])
        elif a['metric_age_seconds']>300:alerts.append('no_metric_5min:'+a['job_id'])
    report={'observed_at':datetime.now(timezone.utc).isoformat(),'visible_process_count':visible,'required_process_limit_exclusive':128,
        'coordinator_lease_busy':lock_busy,'intentional_pause':intended_pause,'controller_identities':identities,'controller_reported_states':status['states'],
        'terminal_classifications':dict(counts),'failure_details':terminal,'live_core_workers':sum(a['identity_alive'] for a in active),
        'active_workers':active,'prediction_usage_known_only':monitor['prediction_usage_all_attempts'],
        'missing_usage_reasons':dict(missing),'alerts':alerts,
        'limitations':['Process count is an instantaneous snapshot, not a capacity reservation.',
            'Missing usage is unknown, never zero; totals are known-usage lower bounds.',
            'Lease busy plus controller identities checks exclusion; no controller launch or task retry is performed.']}
    atomic(root/'monitor/core-health.json',report)
    with (root/'monitor/core-health-history.jsonl').open('a') as f:
        f.write(json.dumps({k:report[k] for k in ['observed_at','visible_process_count','live_core_workers','terminal_classifications','prediction_usage_known_only','alerts']})+'\n')
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=ROOT/'outputs/campaigns/bc100-r3-all-strategies');p.add_argument('--watch',action='store_true');a=p.parse_args()
    lock=(a.root/'monitor/core-health.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    while True:
        try:
            r=snapshot(a.root);print(json.dumps({k:r[k] for k in ['observed_at','visible_process_count','live_core_workers','terminal_classifications','alerts']}),flush=True)
        except (OSError,ValueError,KeyError) as e:
            atomic(a.root/'monitor/core-health-read-error.json',{'type':type(e).__name__,'at':datetime.now(timezone.utc).isoformat()})
            if not a.watch:raise
        if not a.watch:break
        time.sleep(60)

if __name__=='__main__':main()
