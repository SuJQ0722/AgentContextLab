#!/usr/bin/env python3
"""Independent 16-slot dispatcher for frozen controlled native trials; no paid replay."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from collections import Counter
from prepare_controlled_bounded_v1 import DEFAULT, ROOT, load_validate, read
from run_controlled_bounded_v1 import disposition, snapshot, alive
from run_bc_trial import process_identity
from judge_bc_v3_completed import atomic, immutable, sha, now
import experiment_admission_v4 as admission
from run_controlled_native_v5_ops3 import pidfd_open, pidfd_signal

VERSION='controlled-bounded-ops16-v1'
MARKER_VERSION='controlled-bounded-ops16-capacity-v1'
CAPACITY=16
ALLOWED_STOPS={558793:('897942253','run_controlled_bounded_v1.py'),
               566980:('898169066','watch_controlled_bounded_pilot_v2.py')}
THREAD_ENV={k:'1' for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS',
    'NUMEXPR_NUM_THREADS','VECLIB_MAXIMUM_THREADS','BLIS_NUM_THREADS')}
PENDING={'ready','waiting_visual','running','interrupted_unknown_no_replay'}
LOCAL_ADMISSION_DEPLOYMENT={'reserved_future_local_bc_workers':0,
    'inherited_default_future_local_bc_workers':2,'reason':'BC prediction trials run on two CCI instances; no future local BC slots are reserved by this dispatcher',
    'actual_existing_local_bc_growth_preserved':True,'visible_os_process_limit':127,
    'memory_capacity_check_unchanged':True,'admission_module_file_modified':False}


def configure_local_admission():
    # Only remove hypothetical future local BC slots. admission.capacity still
    # sums CORE_COST minus actual descendants for every existing local BC trial.
    admission.CORE_WORKERS=0
    return dict(LOCAL_ADMISSION_DEPLOYMENT)


def validate_marker(path,root):
    marker=read(path)
    if marker.get('version')!=MARKER_VERSION or marker.get('ready') is not True:raise ValueError('Global capacity not ready')
    if marker.get('controlled_native_slots')!=16 or marker.get('global_cap')!=128 or marker.get('judge_reserve')!=6:raise ValueError('Capacity contract differs')
    total=marker.get('global_reserved_total')
    if type(total)!=int or not 16<=total<=128:raise ValueError('Global reserved capacity exceeds128 or unknown')
    if marker.get('controlled_plan_sha256')!=sha(root/'plan.json') or marker.get('dispatcher_source_sha256')!=sha(__file__):raise ValueError('Marker/source binding mismatch')
    stops=marker.get('coordinator_stops',[])
    if len(stops)!=2 or {(s.get('pid'),s.get('identity')) for s in stops}!={(p,v[0]) for p,v in ALLOWED_STOPS.items()}:raise ValueError('Unexpected handoff identities')
    return marker


def process_record(pid):
    ident=process_identity(pid)
    if not ident:return None
    try:argv=[v.decode() for v in Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0') if v]
    except FileNotFoundError:return None
    return {'pid':pid,'identity':ident,'argv':argv}


def verify_coordinator(pid,identity,root):
    current=process_record(pid)
    if current is None:return None
    required_identity,script=ALLOWED_STOPS[pid]
    if current['identity']!=identity or identity!=required_identity:raise ValueError('Coordinator PID reused or identity changed')
    argv=current['argv'];entry=str(ROOT/'scripts'/script)
    if entry not in argv or '--live' not in argv or '--trial' in argv or '-c' in argv:raise ValueError('Refusing non-coordinator signal')
    if '--root' in argv and Path(argv[argv.index('--root')+1]).resolve()!=root:raise ValueError('Coordinator root differs')
    if script=='run_controlled_bounded_v1.py' and '--pilot-only' not in argv:raise ValueError('Unexpected old full coordinator')
    return current


def takeover(root,marker,directory):
    preserved=[{'job_id':j['job_id'],'out':j['out']} for j in read(root/'plan.json')['jobs'] if j['eligible'] and alive(Path(j['out']))]
    records=[]
    # Stop the handoff watcher first, then only the old coordinator PID. Never signal a process group.
    for pid in (566980,558793):
        identity=ALLOWED_STOPS[pid][0];current=verify_coordinator(pid,identity,root)
        if current is None:records.append({'pid':pid,'identity':identity,'state':'already_exited'});continue
        descriptor=pidfd_open(pid)
        try:
            verify_coordinator(pid,identity,root);pidfd_signal(descriptor,signal.SIGTERM)
        finally:os.close(descriptor)
        deadline=time.monotonic()+20
        while process_identity(pid)==identity:
            if time.monotonic()>deadline:raise TimeoutError('Old coordinator did not exit; no dispatcher takeover')
            time.sleep(.1)
        records.append({**current,'state':'exact_pid_exited_after_SIGTERM','signal_scope':'coordinator PID only'})
    proof={'at':now(),'stopped_coordinators':records,'preserved_native_attempts_before_handoff':preserved,
        'native_process_groups_signalled':False,'dispatcher_source_sha256':sha(__file__)}
    atomic(directory/'handoff.json',proof)
    return proof


def inspect(plan,root):
    states={j['job_id']:disposition(j,root) for j in plan['jobs']}
    eligible=[j for j in plan['jobs'] if j['eligible']]
    running=sum(states[j['job_id']]=='running' for j in eligible)
    unknown=sum(states[j['job_id']]=='interrupted_unknown_no_replay' for j in eligible)
    pending=sum(states[j['job_id']] in PENDING for j in eligible)
    return {'states':states,'running_native':running,'unknown_reserved_slots':unknown,
        'occupied_slots':running+unknown,'pending_eligible':pending,'terminal_eligible':len(eligible)-pending,
        'eligible_arms':len(eligible),'unavailable_original_arms':len(plan['jobs'])-len(eligible),
        'all_eligible_resolved':pending==0,'no_active_native':running==0,'counts':dict(Counter(states.values()))}


def ready_jobs(plan,info):
    slots=max(0,CAPACITY-info['occupied_slots'])
    return [j for j in plan['jobs'] if info['states'][j['job_id']]=='ready'][:slots]


def spawn_one(job,command):
    """Publish durable intent under shared admission lock, only after known capacity approval.

    An admission denial starts no child and creates no dispatch. Any exception
    after dispatch publication is unknown and cannot be automatically replayed.
    """
    admission.STATE.mkdir(parents=True,exist_ok=True)
    with (admission.STATE/'experiment-admission.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        ledger=admission.STATE/'experiment-admission.json'
        reservations=read(ledger).get('reservations',[]) if ledger.exists() else []
        ok,report,existing=admission.capacity(admission.processes(),reservations,4)
        memory_ok,memory=admission.memory_capacity(existing);report['memory']=memory
        if not ok or not memory_ok:return None,{'admitted':False,**report}
        out=Path(job['out'])
        if any((out/n).exists() for n in ('dispatch.json','supervisor.json','worker-started.json','result.json','trial-status.json')):raise ValueError('Prior attempt exists')
        with (out/'dispatch.json').open('x') as stream:
            json.dump({'state':'reserved_no_automatic_replay','at':now(),'operational_version':VERSION},stream)
            stream.flush();os.fsync(stream.fileno())
        with (out/'supervisor.log').open('a') as log:
            child=subprocess.Popen(command,cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        identity=process_identity(child.pid)
        existing.append({'pid':child.pid,'identity':identity,'owner':VERSION,'job_id':job['job_id'],'process_cost':4})
        atomic(ledger,{'updated_unix':time.time(),'reservations':existing,'last_decision':dict(report,admitted=True,owner=VERSION,job_id=job['job_id'])})
        atomic(out/'dispatch.json',{'state':'spawned','pid':child.pid,'identity':identity,'at':now(),'operational_version':VERSION,'automatic_replay':False})
        return child,{'admitted':True,**report}


def queue(root,plan,directory,marker_path,marker_sha):
    children=[];last_report=0.;last_admission=None
    atomic(root/'coordinator-ops16.json',{'pid':os.getpid(),'identity':process_identity(os.getpid()),'version':VERSION,'started':now(),'capacity':16})
    while True:
        if sha(marker_path)!=marker_sha:raise ValueError('Published capacity marker changed; stop dispatch')
        for child in list(children):
            if child.poll() is not None:children.remove(child)
        info=inspect(plan,root)
        for job in ready_jobs(plan,info):
            # Recheck inherited live/unknown attempts before each spawn.
            current=inspect(plan,root)
            if current['occupied_slots']>=CAPACITY or current['states'][job['job_id']]!='ready':continue
            command=[sys.executable,str(ROOT/'scripts/run_controlled_bounded_v1.py'),'--root',str(root),'--trial',job['job_id'],'--live']
            try:child,last_admission=spawn_one(job,command)
            except Exception as error:
                atomic(directory/'last-dispatch-error.json',{'at':now(),'job_id':job['job_id'],'error_type':type(error).__name__,'automatic_replay':False})
                # Its durable intent, if published, now consumes an unknown slot.
                continue
            if child is None:break
            children.append(child)
        info=inspect(plan,root)
        state='finished' if info['all_eligible_resolved'] and info['no_active_native'] else 'blocked_unknown' if info['unknown_reserved_slots'] and not ready_jobs(plan,info) and info['no_active_native'] else 'running'
        status={**info,'state':state,'pid':os.getpid(),'identity':process_identity(os.getpid()),'at':now(),
            'queue_lock_owned':True,'capacity':16,'capacity_marker_sha256':marker_sha,'admission':last_admission,
            'thread_environment':THREAD_ENV,'local_admission_deployment':LOCAL_ADMISSION_DEPLOYMENT,
            'operational_version':VERSION,'provider_latency_seconds':None}
        atomic(directory/'status.json',status)
        if time.monotonic()-last_report>=60 or state=='finished':
            report=snapshot(root,plan,False)
            report.update(concurrency_cap=16,operational_dispatcher=VERSION,ops_status_path=str(directory/'status.json'))
            atomic(root/'status.json',report);last_report=time.monotonic()
        if state=='finished':return
        time.sleep(5)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=DEFAULT)
    p.add_argument('--capacity-marker',type=Path,required=True);p.add_argument('--live',action='store_true')
    p.add_argument('--takeover',action='store_true');p.add_argument('--watch-marker',action='store_true');a=p.parse_args();root=a.root.resolve()
    plan,_=load_validate(root);directory=root/'ops16-v1';directory.mkdir(exist_ok=True)
    if not a.live:
        info=inspect(plan,root);print(json.dumps({'live':False,'capacity':16,'inventory':info,'marker_exists':a.capacity_marker.exists()}));return
    with (directory/'dispatcher.lock').open('a') as own_lock:
        fcntl.flock(own_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        while not a.capacity_marker.exists():
            if not a.watch_marker:raise ValueError('Global capacity marker missing')
            atomic(directory/'status.json',{'state':'waiting_capacity_marker','pid':os.getpid(),'identity':process_identity(os.getpid()),'at':now(),'capacity':16,'queue_lock_owned':False})
            time.sleep(5)
        marker=validate_marker(a.capacity_marker,root);marker_sha=sha(a.capacity_marker)
        immutable(directory/'protocol.json',{'version':VERSION,'plan_sha256':sha(root/'plan.json'),'source_sha256':sha(__file__),
            'frozen_trial_sha256':sha(ROOT/'scripts/run_controlled_bounded_v1.py'),'capacity_marker_sha256':marker_sha,
            'capacity':16,'unknown_attempts_reserve_slots':True,'new_paid_retry_loop':False,'thread_environment':THREAD_ENV,
            'local_admission_deployment':LOCAL_ADMISSION_DEPLOYMENT})
        if a.takeover:takeover(root,marker,directory)
        else:
            if any(verify_coordinator(pid,v[0],root) for pid,v in ALLOWED_STOPS.items()):raise ValueError('Old coordinator live; explicit takeover required')
        with (root/'queue.lock').open('a') as queue_lock:
            fcntl.flock(queue_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            load_validate(root);os.environ.update(THREAD_ENV);configure_local_admission()
            queue(root,plan,directory,a.capacity_marker,marker_sha)

if __name__=='__main__':main()
