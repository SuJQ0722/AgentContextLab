#!/usr/bin/env python3
"""Read small campaign metadata only; no native logs, models, retries or controls."""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
import json
import math
import os
from pathlib import Path
import socket
import statistics
import time
import uuid
from lab import ROOT

DEFAULT_ROOT=ROOT/'outputs/campaigns/bc100-r3-hermes-parity-v3'


def read(path):
    try:
        value=json.loads(path.read_text());return value if isinstance(value,dict) else None
    except (OSError,ValueError):return None


def instant(value):
    try:
        if isinstance(value,(float,int)) and not isinstance(value,bool) and math.isfinite(value):return float(value)
        dt=datetime.fromisoformat(value.replace('Z','+00:00'))
        return dt.timestamp() if dt.tzinfo is not None else None
    except (TypeError,ValueError,AttributeError):return None


def stamp(value,offset=0):return datetime.fromtimestamp(value,timezone(timedelta(hours=offset))).isoformat()

def durations(rows):
    values=sorted(r['seconds'] for r in rows if isinstance(r.get('seconds'),(int,float)) and not isinstance(r['seconds'],bool) and math.isfinite(r['seconds']) and r['seconds']>=0)
    return {'count':len(values),'missing_count':len(rows)-len(values),
      'mean_seconds':statistics.mean(values) if values else None,'median_seconds':statistics.median(values) if values else None,
      'p90_seconds':values[max(0,math.ceil(.9*len(values))-1)] if values else None,'max_seconds':max(values) if values else None}


def window(rows,now,seconds):
    recent=[r for r in rows if r.get('finished') is not None and now-seconds<=r['finished']<=now]
    completed=sum(r['status']=='completed' for r in recent)
    return {'window_seconds':seconds,'all_terminal_count':len(recent),'completed_only_count':completed,
      'all_terminal_per_hour':len(recent)*3600/seconds,'completed_only_per_hour':completed*3600/seconds,
      'other_terminal_count':len(recent)-completed}


def local_alive(owner,local):
    if any(owner.get(k)!=local.get(k) for k in ('hostname','boot_id','pid_namespace')):return None
    try:
        fields=Path(f"/proc/{int(owner['pid'])}/stat").read_text().split(') ',1)[1].split()
        return fields[0]!='Z' and fields[19]==owner.get('start_identity')
    except (OSError,ValueError,KeyError,IndexError,TypeError):return False


def classify(jobdir,now,local,cloud_keys):
    attempt=jobdir/'attempts/attempt_001';result=read(attempt/'result.json');heartbeat=read(attempt/'heartbeat.json')
    claim=read(jobdir/'claim/owner.json');started=read(attempt/'worker-started.json')
    owner=(result or {}).get('worker_identity') or heartbeat or started or claim or {}
    key=(owner.get('hostname'),owner.get('boot_id'))
    location='local' if owner.get('hostname')==local['hostname'] else 'cloud' if key in cloud_keys else 'remote_unclassified' if owner.get('hostname') else 'unassigned'
    started_time=instant((started or {}).get('started_at'));start_source='worker-started timestamp'
    if started_time is None:
        started_time=instant((result or {}).get('started_at_unix_estimate'));start_source='wrapper start estimate'
    lineage=read(attempt/'runtime-lineage.json') or {}
    base={'startup_seconds':max(0,started_time-instant((claim or {}).get('claimed_at'))) if started_time is not None and instant((claim or {}).get('claimed_at')) is not None else None, 'capacity1':lineage.get('runtime_version') == 'original-image-bytes-capacity1', 'location':location,'host_key':key,'started':started_time,'start_source':start_source,
          'claimed':instant((claim or {}).get('claimed_at')),'finished':instant((result or {}).get('finished_at')),
          'seconds':(result or {}).get('end_to_end_seconds'),'status':(result or {}).get('status')}
    if result:
        base['state']='terminal' if isinstance(result.get('status'),str) else 'unknown';return base
    if heartbeat:
        alive=local_alive(heartbeat,local);age=now-(instant(heartbeat.get('heartbeat_unix')) or 0)
        if alive is True or (alive is None and -5<=age<=90):base['state']='active';return base
    if claim and base['claimed'] is not None and 0<=now-base['claimed']<=120:
        base['state']='launching';return base
    base['state']='unknown' if (jobdir/'claim').exists() or (jobdir/'attempts').exists() else 'pending'
    return base


def eta_projection(cells,gate,now):
    """Conditional queue-drain range, never a prediction of 3000 correct answers."""
    if all(c['states'].get('terminal',0)==c['planned'] for c in cells.values()):
        return {'available':True,'already_terminal':True,'remaining_seconds_range':[0,0],
                'utc_range':[stamp(now),stamp(now)],'beijing_range':[stamp(now,8),stamp(now,8)],
                'target':'All jobs already terminal; this is not a claim of successful or correct answers.'}
    reasons=list(gate)
    if any(c['states'].get('unknown',0) for c in cells.values()):reasons.append('claimed attempts with unknown state cannot be automatically retried or assigned an end time')
    if reasons:return {'available':False,'reasons':reasons,'utc_range':None,'beijing_range':None}
    lows=[];highs=[]
    for name,c in cells.items():
        remaining=c['planned']-c['states'].get('terminal',0)
        if not remaining:continue
        windows=list(c.get('throughput_recovery', c['throughput']).values())
        if any(w['all_terminal_count']<3 for w in windows):
            reasons.append(name+': fewer than three terminal observations in a throughput window');continue
        rates=[w['all_terminal_per_hour']/3600 for w in windows]
        lows.append(remaining/max(rates));highs.append(remaining/min(rates)+c['timeout_seconds'])
    if reasons:return {'available':False,'reasons':reasons,'utc_range':None,'beijing_range':None}
    lower,upper=max(lows,default=0),max(highs,default=0)
    return {'available':True,'remaining_seconds_range':[lower,upper],
      'utc_range':[stamp(now+lower),stamp(now+upper)],'beijing_range':[stamp(now+lower,8),stamp(now+upper,8)],
      'method':'Slowest cell determines drain. For each cell use remaining jobs divided by faster/slower observed recovery-generation-only 10/20-minute all-terminal rates; add one declared timeout to the slower bound for in-flight tail. Conditional heuristic, not a confidence interval.',
      'target':'All planned jobs receive terminal outcomes, including failures/timeouts; not all jobs complete successfully or are scored correct.'}


def recovery_rows(rows, binding, cutoff, visual=False):
    if not binding or cutoff is None: return []
    return [row for row in rows if row.get('started') is not None and row['started'] >= cutoff
            and (row.get('host_key') == binding['key'] or row.get('location') == 'local')
            and (not visual or row.get('capacity1') is True)]


def discover_cloud(root, local_hostname, replacements_root):
    cloud_nodes, cell_nodes, generations, earliest = {}, {}, {}, {}
    candidate_dirs=list(replacements_root.glob('*'))+list((replacements_root.parent/'rate-replacements').glob('*'))
    for directory in candidate_dirs:
        if not directory.is_dir(): continue
        request=read(directory/'request.json') or {};response=read(directory/'response.json') or {}
        if response.get('state') != 'submitted': continue
        if request.get('harness') and request.get('strategy'):
            cell=request['harness']+'/'+request['strategy']
            moment=instant(request.get('requested_at_unix'))
            if moment is not None: earliest[cell]=min(earliest.get(cell,moment),moment)
            previous=generations.get(cell)
            if previous is None or (instant(request.get('requested_at_unix')) or 0) > (instant(previous.get('requested_at_unix')) or 0):
                generations[cell]=request
    for path in (root/'runtime/nodes').glob('*/telemetry.json'):
        node=read(path)
        if not node:continue
        key=(node.get('hostname'),node.get('boot_id'))
        if not all(key) or key[0]==local_hostname:continue
        cloud_nodes[key]=node  # Historical owners remain classified as cloud.
        retired=read(path.parent/'retired.json') or {}
        if all(node.get(k) and node.get(k)==retired.get(k) for k in ('hostname','boot_id','pid_namespace')):continue
        for bootstrap_path in path.parent.glob('*/bootstrap.json'):
            boot=read(bootstrap_path)
            if not boot or not isinstance(boot.get('cell'),str):continue
            cell=boot['cell'];generation=generations.get(cell)
            if not generation or (instant(boot.get('started_at_unix')) or 0) <= (instant(generation.get('requested_at_unix')) or float('inf')):continue
            previous=cell_nodes.get(cell)
            if previous and (instant(previous['bootstrap'].get('started_at_unix')) or 0)>=(instant(boot.get('started_at_unix')) or 0):continue
            cell_nodes[cell]={'key':key,'node':node,'telemetry_path':path,'bootstrap':boot,
                              'exit':read(bootstrap_path.parent/'exit.json'),'generation':generation}
    generations={cell:{**value,'calibration_not_before_unix':earliest.get(cell)} for cell,value in generations.items()}
    return cloud_nodes,cell_nodes,generations


def conditional_projection(cells, dispatch, now):
    """Transparent planning scenarios before a stable four-worker throughput window.

    The timeout scenario is conditional on successful provisioning and continued
    dispatch, not an unconditional upper bound on an external provider outage.
    """
    workers=dispatch.get('active_workers_per_cloud_instance')
    if not isinstance(workers,int) or workers<=0: return {'available':False,'reason':'Unknown target concurrency'}
    calibrated=[c['calibration_completed_duration']['median_seconds'] for c in cells.values()
                if c.get('calibration_completed_duration',{}).get('median_seconds') is not None]
    if not calibrated:return {'available':False,'reason':'No post-repair completed duration sample for optimistic scenario'}
    fallback=statistics.median(calibrated)
    lower,upper,details,unknown,completed,known_remaining=0,0,{},0,0,0
    for name,c in cells.items():
        states=c['states'];missing=states.get('unknown',0);unknown+=missing
        remaining=sum(states.get(k,0) for k in ('pending','active','launching'));known_remaining+=remaining
        completed+=c['terminal_statuses'].get('completed',0)
        sample=c.get('calibration_completed_duration',{});duration=sample.get('median_seconds')
        source='same-cell post-repair completed median; may include previous 8-worker generation'
        if duration is None:duration=fallback;source='median of other cells post-repair completed medians; no completed sample for this cell'
        startup=c.get('calibration_startup_duration',{})
        median_start=startup.get('median_seconds') or 0
        allowance=max(300,startup.get('p90_seconds') or 0)
        optimistic=remaining/workers*(duration+median_start)
        timeout_scenario=math.ceil(remaining/workers)*(c['timeout_seconds']+allowance)+3600 if remaining else 0
        lower=max(lower,optimistic);upper=max(upper,timeout_scenario)
        details[name]={'remaining_known_work':remaining,'unknown_excluded':missing,'assumed_cloud_workers':workers,
            'completed_sample_n':sample.get('count',0),'duration_seconds_for_optimistic':duration,'duration_source':source,
            'startup_median_seconds':median_start,'startup_allowance_per_wave_seconds':allowance,
            'remaining_seconds_scenarios':[optimistic,timeout_scenario]}
    return {'available':True,'kind':'conditional_planning_scenarios_not_stable_estimate',
        'remaining_seconds_range':[lower,upper],'utc_range':[stamp(now+lower),stamp(now+upper)],
        'beijing_range':[stamp(now+lower,8),stamp(now+upper,8)],'cells':details,'unknown_claims_excluded':unknown,
        'known_remaining_work':known_remaining,'native_completed_so_far':completed,
        'maximum_native_completed_from_known_work_without_retry':completed+known_remaining,
        'all_planned_terminal_guaranteed':False,
        'assumptions':['Each cloud cell maintains the new target concurrency; no extra speedup is credited to the shared local pool.',
            'Optimistic scenario uses early post-repair completed medians and may reuse the preceding 8-worker sample for calibration only; it is not measured stable 4-worker throughput.',
            'Slow scenario assigns every remaining run the declared native timeout plus at least five minutes startup allowance per wave, and one hour for rollover/provisioning. Startup or gateway outages can exceed this allowance.',
            'No failed/timeout/unknown attempts are automatically retried. Unknown claims are excluded from the time target and reported separately.',
            'Early completion favors short questions. These scenarios are neither confidence intervals nor guaranteed earliest/latest completion times.',
            'The target is termination of currently known work, not correct answers, grading completion, or unstarted RQ3/controlled/information-loss experiments.']}


def snapshot(root,now=None):
    live_clock=now is None;now=time.time() if live_clock else now;sampling_started=now;plan=read(root/'plan.json')
    if not plan:raise ValueError('Readable frozen plan is required')
    local={'hostname':socket.gethostname(),'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'pid_namespace':os.readlink('/proc/self/ns/pid')}
    cloud_nodes,cell_nodes,generations=discover_cloud(root,local['hostname'],ROOT/'outputs/cloud-runtime/replacement-submissions')
    existing={str(p.relative_to(root/'jobs')):p for p in (root/'jobs').glob('*/*/*') if p.is_dir()}
    cells={};all_rows=[]
    def inspect_job(job):
        return classify(existing[job['job_id']],time.time() if live_clock else now,local,cloud_nodes) if job['job_id'] in existing else {'state':'pending','location':'unassigned','status':None}
    with ThreadPoolExecutor(max_workers=8) as pool:
        observed=list(pool.map(inspect_job,plan['jobs']))
    for job,row in zip(plan['jobs'],observed):
        name=job['harness']+'/'+job['strategy']
        c=cells.setdefault(name,{'planned':0,'timeout_seconds':job['timeout_seconds'],'rows':[]})
        c['planned']+=1
        c['rows'].append(row);all_rows.append(row)
    now=time.time() if live_clock else now
    stability=[];cloud_cells=[]
    desired_dispatch=read(ROOT/'configs/cloud-dispatch-ops-v2.json') or {}
    desired_workers=desired_dispatch.get('active_workers_per_cloud_instance')
    desired_effective=instant(desired_dispatch.get('effective_at'))
    for name,c in cells.items():
        rows=c.pop('rows');terminal=[r for r in rows if r['state']=='terminal'];completed=[r for r in terminal if r['status']=='completed']
        c.update(states=dict(Counter(r['state'] for r in rows)),terminal_statuses=dict(Counter(r['status'] for r in terminal)),
          locations={location:dict(Counter(r['state'] for r in rows if r['location']==location)) for location in ('local','cloud','remote_unclassified','unassigned')},
          duration_all_terminal=durations(terminal),duration_completed_only=durations(completed),
          throughput={str(seconds//60)+'m':window(terminal,now,seconds) for seconds in (600,1200)},
          throughput_by_location={location:{str(seconds//60)+'m':window([r for r in terminal if r['location']==location],now,seconds) for seconds in (600,1200)} for location in ('local','cloud','remote_unclassified')},
          started_worker_count=sum(r.get('started') is not None for r in rows),
          finished_timestamp_missing=sum(r.get('finished') is None for r in terminal))
        binding=cell_nodes.get(name);status={'cell':name,'eligible':False}
        generation=generations.get(name)
        c['cloud_generation']=(generation or {}).get('name')
        c['configured_cloud_workers']=(generation or {}).get('operational_dispatch',{}).get('active_workers_per_cloud_instance')
        c['worker_ceiling']=(generation or {}).get('worker_ceiling')
        c['recovery_cutoff']=None
        calibration_since=(generation or {}).get('calibration_not_before_unix')
        calibration=[r for r in rows if r.get('started') is not None and calibration_since is not None and r['started']>=calibration_since
                     and (not name.endswith('/visual') or r.get('capacity1') is True)]
        c['calibration_completed_duration']=durations([r for r in calibration if r['state']=='terminal' and r['status']=='completed'])
        c['calibration_startup_duration']=durations([{'seconds':r.get('startup_seconds')} for r in calibration])
        c['calibration_cutoff']=stamp(calibration_since) if calibration_since is not None else None
        recovered=[]
        if binding:
            node=(read(binding['telemetry_path']) if live_clock else None) or binding['node'];age=now-(instant(node.get('timestamp')) or 0);roles=(node.get('processes') or {}).get('core_v3_roles',{})
            boot=binding['bootstrap'];commands=boot.get('commands',{}).get('controller',[])
            capacity_ok=name.split('/')[1]!='visual' or any(Path(value).name=='run_bc_campaign_v3_capacity1.py' for value in commands)
            cutoff=max(instant(boot.get('started_at_unix')) or 0,instant(binding['generation'].get('requested_at_unix')) or 0,
                       instant(boot.get('operational_dispatch',{}).get('effective_at')) or 0)
            c['recovery_cutoff']=stamp(cutoff);c['visual_capacity1_controller']=capacity_ok if name.endswith('/visual') else None
            recovered=recovery_rows(rows,binding,cutoff,name.endswith('/visual'))
            starts=[r['started'] for r in rows if r.get('host_key')==binding['key'] and r.get('started') is not None]
            bootstrap_started=instant(binding['bootstrap'].get('started_at_unix'))
            since=now-max(min(starts),bootstrap_started or min(starts)) if starts else None
            status.update(generation=binding['generation'].get('name'),configured_workers=c['configured_cloud_workers'],
                          worker_ceiling=c['worker_ceiling'],capacity1_required_and_verified=capacity_ok,recovery_cutoff=stamp(cutoff),hostname=binding['key'][0],boot_id=binding['key'][1],telemetry_age_seconds=age,
                          cloud_worker_count=roles.get('trial'),cloud_controller_count=roles.get('controller'),
                          cloud_native_worker_count=roles.get('hermes_worker',0)+roles.get('dsh_worker',0),seconds_since_first_cloud_worker=since)
            status['eligible']=bool(capacity_ok and c['configured_cloud_workers']==desired_workers
                                    and (desired_effective is None or bootstrap_started is not None and bootstrap_started>=desired_effective) and -5<=age<=90 and roles.get('trial',0)>0 and roles.get('controller',0)>0 and status['cloud_native_worker_count']>0 and since is not None and since>=1200 and not binding['exit'])
        recovered_terminal=[r for r in recovered if r['state']=='terminal']
        c['throughput_recovery']={str(seconds//60)+'m':window(recovered_terminal,now,seconds) for seconds in (600,1200)}
        c['recovery_states']=dict(Counter(r['state'] for r in recovered))
        c['recovery_duration_all_terminal']=durations(recovered_terminal)
        c['recovery_duration_completed_only']=durations([r for r in recovered_terminal if r['status']=='completed'])
        if not status['eligible']:stability.append(name+': requires the latest dispatch policy and replacement generation, fresh live cloud controller/workers, correct visual capacity1 entry, and 20 minutes since actual workers started')
        cloud_cells.append(status)
    if len(cells)!=10:stability.append('Expected ten harness/strategy cells')
    terminal=[r for r in all_rows if r['state']=='terminal']
    return {'schema':'bc-v3-terminal-eta-v1','as_of':stamp(now),'sampling_started_at':stamp(sampling_started),'as_of_beijing':stamp(now,8),'planned_runs':len(plan['jobs']),
      'states':dict(Counter(r['state'] for r in all_rows)),'terminal_statuses':dict(Counter(r['status'] for r in terminal)),
      'locations':{location:dict(Counter(r['state'] for r in all_rows if r['location']==location)) for location in ('local','cloud','remote_unclassified','unassigned')},
      'throughput':{str(seconds//60)+'m':window(terminal,now,seconds) for seconds in (600,1200)},
      'duration_all_terminal':durations(terminal),'duration_completed_only':durations([r for r in terminal if r['status']=='completed']),
      'conditional_planning_range':conditional_projection(cells,desired_dispatch,now),
      'cells':cells,'desired_operational_dispatch':desired_dispatch,'cloud_stability':cloud_cells,'eta_to_terminal_outcomes':eta_projection(cells,stability,now),
      'limitations':['Early finished samples favor short/fast questions and may understate long-tail durations; startup scale changes make recent throughput nonstationary.',
        'Projection uses only trials started after the current replacement bootstrap/operational cutoff; visual samples additionally require the capacity1 runtime-lineage marker. Old draining trials stay in total progress but not recovery rates.',
        'Cloud stability checks current fresh telemetry and elapsed time since actual worker starts; it is not proof of uninterrupted node uptime.',
        'Completed means native loop returned, not judged correct. All-terminal throughput includes failed/timeout/not_started outcomes; no successful-answer ETA is asserted.',
        'End-to-end seconds are wrapper wall time after validation, not provider API latency. Missing timestamps and unknown attempts are explicit.',
        'This report covers only core BC3000. It assigns no ETA to unstarted RQ3, controlled baselines, or information-loss experiments.'],
      'data_scope':'Frozen plan plus claim, heartbeat, worker-started, result, node telemetry/bootstrap metadata only. No native trajectory or API log reads.'}


def markdown(report):
    lines=['# Core BC3000 metadata snapshot','',report['as_of']+' / Beijing '+report['as_of_beijing'],'',
      'Native completed is not accuracy. All-terminal counts include failures and timeouts. Rates below use only the recovered generation; pre-recovery completions remain in progress counts.','',
      '| Cell | Pending | Active | Launching | Unknown | Terminal | Completed | Terminal/h 10m / 20m | Completed/h 10m / 20m |',
      '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for name,c in sorted(report['cells'].items()):
        s=c['states'];a,b=c['throughput_recovery']['10m'],c['throughput_recovery']['20m']
        lines.append(f"| {name} | {s.get('pending',0)} | {s.get('active',0)} | {s.get('launching',0)} | {s.get('unknown',0)} | {s.get('terminal',0)} | {c['terminal_statuses'].get('completed',0)} | {a['all_terminal_per_hour']:.1f} / {b['all_terminal_per_hour']:.1f} | {a['completed_only_per_hour']:.1f} / {b['completed_only_per_hour']:.1f} |")
    lines+=['','Cloud configured workers / ceiling: '+', '.join(name+'='+str(c.get('configured_cloud_workers'))+'/'+str(c.get('worker_ceiling')) for name,c in sorted(report['cells'].items()))]
    lines+=['','| Execution location | Active | Launching | Unknown | Terminal |','|---|---:|---:|---:|---:|']
    for location,states in report['locations'].items():
        lines.append(f"| {location} | {states.get('active',0)} | {states.get('launching',0)} | {states.get('unknown',0)} | {states.get('terminal',0)} |")
    lines+=['','| Finished duration sample | n | Mean seconds | Median seconds | P90 seconds |','|---|---:|---:|---:|---:|']
    for title,key in [('All terminal','duration_all_terminal'),('Completed only','duration_completed_only')]:
        item=report[key]
        values=[f"{item[k]:.1f}" if item[k] is not None else 'NA' for k in ('mean_seconds','median_seconds','p90_seconds')]
        lines.append(f"| {title} | {item['count']} | {' | '.join(values)} |")
    eta=report['eta_to_terminal_outcomes']
    lines+=['','ETA: '+('UTC '+str(eta['utc_range'])+'; Beijing '+str(eta['beijing_range']) if eta['available'] else 'withheld until all cloud cells have stable measured activity and sufficient per-cell terminal observations.'),'']
    scenario=report.get('conditional_planning_range',{})
    if scenario.get('available'):
        lines+=['Conditional planning range (not stable measured ETA): UTC '+str(scenario['utc_range'])+'; Beijing '+str(scenario['beijing_range']),
                'Known remaining work: '+str(scenario['known_remaining_work'])+'; unknown claims excluded: '+str(scenario['unknown_claims_excluded'])+'.',
                'Native completed so far: '+str(scenario['native_completed_so_far'])+'; maximum from known work without retries: '+str(scenario['maximum_native_completed_from_known_work_without_retry'])+'.','']
        lines+=['- '+value for value in scenario['assumptions']]
    lines+=['- '+value for value in report['limitations']]
    return '\n'.join(lines)+'\n'


def write_report(root, report, history=False):
    out=root/'monitor';out.mkdir(parents=True,exist_ok=True)
    for name,value in [('eta.json',json.dumps(report,indent=2)),('eta.md',markdown(report))]:
        temporary=out/(name+'.'+uuid.uuid4().hex+'.tmp');temporary.write_text(value);temporary.replace(out/name)
    if history:
        directory=out/'eta-samples';directory.mkdir(exist_ok=True)
        (directory/(str(time.time_ns())+'.json')).write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'as_of':report['as_of'],'states':report['states'],'eta_available':report['eta_to_terminal_outcomes']['available'],'output':str(out/'eta.md')}),flush=True)


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--root',type=Path,default=DEFAULT_ROOT)
    ap.add_argument('--watch',action='store_true');ap.add_argument('--interval',type=float,default=120)
    ap.add_argument('--duration',type=float,default=1320,help='Bounded read-only observation seconds in watch mode')
    args=ap.parse_args()
    if args.interval<30 or args.duration<=0:ap.error('interval must be >=30 and duration positive')
    deadline=time.monotonic()+args.duration
    while True:
        write_report(args.root,snapshot(args.root.resolve()),history=args.watch)
        if not args.watch or time.monotonic()>=deadline:break
        time.sleep(min(args.interval,max(0,deadline-time.monotonic())))


if __name__=='__main__':main()
