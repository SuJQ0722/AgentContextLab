#!/usr/bin/env python3
"""Read-only process/resource census for rebuttal work; never prints argv or keys."""
import argparse
import collections
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
from lab import ROOT

SCRIPT_GROUPS={
    'run_rq3_campaign.py':'rq3','report_rq3_campaign.py':'rq3','rq3_trial.py':'rq3','rq3_hermes_worker.py':'rq3',
    'run_bc_campaign.py':'core_bc','resume_bc_plan.py':'core_bc','run_bc_trial.py':'core_bc',
    'hermes_bc_worker.py':'core_bc','run_dsh_eval.py':'core_bc',
    'monitor_bc_campaign.py':'core_bc','judge_bc_campaign.py':'core_bc','watch_bc_health.py':'core_bc',
    'controlled_native_preflight.py':'experiment3_calibration',
    'capture_multimodal_prefix.py':'experiment3_capture',
    'info_loss_eval.py':'experiment6','info_loss_report.py':'experiment6','info_loss_campaign.py':'experiment6',
    'run_rebuttal_queue.py':'supplement_queue','monitor_rebuttal.py':'resource_monitor','monitor_experiment3.py':'resource_monitor'}


def process_snapshot():
    processes={}
    for directory in Path('/proc').iterdir():
        if not directory.name.isdigit():continue
        try:
            stat=(directory/'stat').read_text();fields=stat.split(') ',1)[1].split()
            argv=(directory/'cmdline').read_bytes().split(b'\0')
            group=None
            for item in argv:
                # Match exact script arguments, never a shell command's contents.
                if b'\n' in item or b' ' in item:continue
                name=Path(os.fsdecode(item)).name
                if name in SCRIPT_GROUPS:group=SCRIPT_GROUPS[name];break
            if any(b'/rq3-deepseek-bc100-r3/' in x for x in argv) and any(Path(os.fsdecode(x)).name in ('run_bc_trial.py','hermes_bc_worker.py') for x in argv if b' ' not in x and b'\n' not in x):group='rq3'
            processes[int(directory.name)]={'ppid':int(fields[1]),'state':fields[0],
                'name':stat.split('(',1)[1].rsplit(')',1)[0], 'start_identity':fields[19], 'group':group}
        except (OSError,ValueError,IndexError):continue
    changed=True
    while changed:
        changed=False
        for value in processes.values():
            parent=processes.get(value['ppid'],{})
            if not value['group'] and parent.get('group'):
                value['group']=parent['group'];changed=True
    return processes


def read_json(path):
    try:return json.loads(path.read_text())
    except (OSError,ValueError):return None


def census():
    processes=process_snapshot();live={p:v for p,v in processes.items() if v['state']!='Z'}
    experiment={p:v for p,v in live.items() if v['group']}
    bc=read_json(ROOT/'outputs/campaigns/bc100-r3-all-strategies/status.json')
    rq3=read_json(ROOT/'outputs/campaigns/rq3-deepseek-bc100-r3/status.json')
    info=read_json(ROOT/'outputs/experiment6/real-trajectory-pilot-v2/results.json') or {}
    phase2=read_json(ROOT/'outputs/experiment6/full-canvas-phase2/results.json') or {}
    phase2_manifest=read_json(ROOT/'outputs/experiment6/full-canvas-phase2/manifest.json') or {}
    phase2_calls=ROOT/'outputs/experiment6/full-canvas-phase2/calls'
    phase2_started=list(phase2_calls.glob('*/started.json'))
    phase2_pending=sum(not (p.parent/'response.json').exists() for p in phase2_started)
    native=read_json(ROOT/'outputs/experiment3/status.json') or {}
    core_usage=(read_json(ROOT/'outputs/campaigns/bc100-r3-all-strategies/monitor/status.json') or {}).get('prediction_usage_all_attempts')
    return {'as_of':datetime.now(timezone.utc).isoformat(),
        'visible_os_processes':len(processes),'visible_os_live_processes':len(live),
        'zombie_processes':len(processes)-len(live),
        'experiment_live_processes':len(experiment),
        'by_experiment':dict(collections.Counter(v['group'] for v in experiment.values())),
        'experiment_pids':{str(p):{'name':v['name'],'group':v['group'],'start_identity':v['start_identity']} for p,v in experiment.items()},
        'under_128_visible_live_processes':len(live)<128,
        'under_128_experiment_live_processes':len(experiment)<128,
        'core_bc_status':bc,'core_trajectory_limit':16,'supplement_trajectory_limit':6,
        'rq3_status':rq3,'experiment6_status':info.get('status'),
        'experiment6_phase2_status':phase2.get('status','not_started'),
        'experiment6_phase2_frozen_cases':len(phase2_manifest.get('cases',[])),
        'experiment6_phase2_started_calls':len(phase2_started),
        'experiment6_phase2_calls_without_response':phase2_pending,
        'experiment3_captures':{k:{'result':v.get('result'), 'prefix_captured':bool(v.get('prefix'))} for k,v in native.get('captures',{}).items()},
        'experiment3_formal_baseline_started':native.get('formal_baseline_started',False),
        'core_prediction_usage_known_only':core_usage,
        'scope':'Linux processes visible in this /proc namespace, not host-wide processes or threads. Counts are instantaneous; request concurrency is separate.'}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--watch',action='store_true');a=p.parse_args()
    out=ROOT/'outputs/rebuttal-monitor';out.mkdir(parents=True,exist_ok=True)
    while True:
        row=census();tmp=out/'status.tmp';tmp.write_text(json.dumps(row,indent=2));tmp.replace(out/'status.json')
        summary={k:v for k,v in row.items() if k not in ('experiment_pids',)}
        core=(row.get('core_bc_status') or {}).get('states',{})
        rq=(row.get('rq3_status') or {}).get('new_states',{})
        text=f"""# Rebuttal live status

Snapshot: {row['as_of']}

Visible OS processes: **{row['visible_os_processes']}** ({row['visible_os_live_processes']} live); experiment live processes: **{row['experiment_live_processes']}**. Live processes below 128: **{row['under_128_visible_live_processes']}**. Counts concern this `/proc` namespace, not threads or model requests.

| Work | State | Model-worker limit |
|---|---|---:|
| Core DeepSeek × DSH/Hermes, 3,000 trials | {core.get('terminal',0)} terminal, {core.get('running',0)} running | 16 shared |
| Native-image prefix capture | {json.dumps(row['experiment3_captures'],ensure_ascii=False)} | 2 |
| New RQ3, 1,800 new + 300 reused controls | {rq.get('terminal',0)} new terminal, {rq.get('running',0)} new running | 2 |
| Information-loss single-trajectory pilot | {row['experiment6_status']} | 0 after completion |
| Information-loss full-canvas phase 2 | {row['experiment6_phase2_status']}; {row['experiment6_phase2_frozen_cases']} frozen trajectories | 1 |
| Historical text statistics / failure analysis | Offline outputs available; no new model requests | 0 |

Formal three-benchmark native-image baseline started: **{row['experiment3_formal_baseline_started']}**. Capture/calibration do not count as scored controlled-baseline results; AgenticDataBench is still blocked by the process sandbox.

Core provider counters below are known subtotals, not actual billed USD; missing usage is not zero.

```json
{json.dumps(row['core_prediction_usage_known_only'],indent=2)}
```
"""
        md=out/'status.md.tmp';md.write_text(text);md.replace(out/'status.md')
        with (out/'history.jsonl').open('a') as f:f.write(json.dumps(summary)+'\n')
        print(json.dumps(summary),flush=True)
        if not a.watch:return
        time.sleep(30)


if __name__=='__main__':main()
