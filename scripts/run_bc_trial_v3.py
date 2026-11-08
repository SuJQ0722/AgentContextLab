#!/usr/bin/env python3
"""One immutable v3 native attempt, heartbeat and explicit unknown/interruption handling."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from lab import ROOT,environment,python_for
from run_bc_campaign_v3 import atomic,identity,owner_alive,now,digest,validate_sources,release_slot,VERSION


def native_command(spec,out):
    if spec['harness']=='hermes':
        return ([python_for(ROOT),str(ROOT/'scripts/hermes_bc_worker_v3.py'),'--spec',str(spec['_spec_path']),
          '--out',str(out/'native'),'--live'],out/'native/native-result.json',spec['timeout_seconds'])
    strategy={'visual':'visual_native','sliding_window':'sliding_window_native'}.get(spec['strategy'],spec['strategy'])
    return ([sys.executable,str(ROOT/'scripts/run_dsh_eval_v3.py'),'--dataset','bc100','--strategies',strategy,
      '--question-id',spec['question_id'],'--repeat',str(spec['repeat']),'--limit','100','--timeout',str(spec['timeout_seconds']),
      '--output-root',str(out/'native'),'--config',spec['config_path'],
      '--cohort-file',str(Path(spec['campaign_root'])/'cohort.jsonl'),'--cohort-sha256',spec['cohort_sha256'],'--web-prevalidated','--live'],
      out/'native'/strategy/spec['question_id']/'result.json',spec['timeout_seconds']+240)


def validate_spec(spec,out):
    root=Path(spec['campaign_root']);plan_path=root/'plan.json'
    if digest(plan_path.read_bytes())!=spec['plan_sha256']:raise ValueError('Plan identity changed')
    plan=json.loads(plan_path.read_text());validate_sources(plan,root)
    expected=next((j for j in plan['jobs'] if j['job_id']==spec['job_id']),None)
    if spec.get('cohort_sha256')!=plan['definition']['cohort_sha256']:raise ValueError('Trial cohort SHA differs from frozen plan')
    if expected is None or any(spec.get(k)!=v for k,v in expected.items()):raise ValueError('Trial differs from frozen scientific job')
    if out.resolve()!= (root/'jobs'/spec['job_id']/'attempts/attempt_001').resolve():raise ValueError('Trial output outside immutable job path')
    if Path(spec['config_path']).resolve()!=(root/'experiment.json').resolve():raise ValueError('Trial must use frozen config')
    claim=json.loads((root/'jobs'/spec['job_id']/'claim/owner.json').read_text())
    if claim['controller_id']!=spec['controller_id'] or claim['slot']!=spec['slot_path']:raise ValueError('Claim ownership mismatch')
    slot=Path(spec['slot_path']);slot_owner=json.loads((slot/'owner.json').read_text())
    if slot_owner['job_id']!=spec['job_id'] or slot_owner['controller_id']!=spec['controller_id']:raise ValueError('Slot ownership mismatch')
    return root


def descendants(pid):
    children={}
    for path in Path('/proc').glob('[0-9]*/stat'):
        try:
            fields=path.read_text().split(') ',1)[1].split();children.setdefault(int(fields[1]),[]).append(int(path.parent.name))
        except (OSError,ValueError,IndexError):continue
    found=set();queue=[pid]
    while queue:
        for child in children.get(queue.pop(),[]):
            if child not in found:found.add(child);queue.append(child)
    return found


def enable_subreaper():
    # DSH launches the native process in a separate session. Linux adoption,
    # unlike a process-group kill, retains it if its immediate launcher dies.
    libc=ctypes.CDLL(None,use_errno=True)
    if libc.prctl(36,1,0,0,0)!=0:raise OSError(ctypes.get_errno(),'Cannot enable child subreaper; refusing untracked native launch')


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--spec',type=Path,required=True);ap.add_argument('--out',type=Path,required=True);ap.add_argument('--live',action='store_true')
    args=ap.parse_args();spec=json.loads(args.spec.read_text());out=args.out.resolve();spec['_spec_path']=str(args.spec.resolve())
    if not args.live:
        print(json.dumps({'job_id':spec['job_id'],'live':False,'execution_version':VERSION}));return
    validate_spec(spec,out)
    if (out/'result.json').exists():return
    out.mkdir(parents=True,exist_ok=True)
    owner=identity()
    try:
        with (out/'worker-started.json').open('x') as f:json.dump({**owner,'started_at':now()},f)
    except FileExistsError:raise ValueError('Worker was already started: preserve unknown attempt, never retry')
    enable_subreaper()
    child=None;interrupt=False;timed_out=False;started=time.monotonic();native_result=None;known={};error_type=None
    def stopping(*unused):
        nonlocal interrupt
        interrupt=True
    signal.signal(signal.SIGTERM,stopping);signal.signal(signal.SIGINT,stopping)
    def remember():
        if child:
            for pid in descendants(os.getpid())|{child.pid}:
                record=identity(pid)
                if record['start_identity']:known[pid]=record
    def terminate(sig):
        remember()
        # Same boot/host/namespace and start identity required; never kill a
        # same-numbered process from an old attempt or a different host.
        for pid,record in reversed(list(known.items())):
            if owner_alive(record):
                try:os.kill(pid,sig)
                except ProcessLookupError:pass
    try:
        env,cfg=environment(ROOT,spec['harness'],spec['config_path'])
        env.update({name:'1' for name in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS')})
        from review_execution import enforce
        enforce(cfg,env,out)
        cmd,native_result,hard_timeout=native_command(spec,out)
        (out/'native').mkdir(exist_ok=True)
        atomic(out/'command.json',{'argv':cmd,'execution_version':VERSION})
        with (out/'worker.log').open('a') as log:
            if interrupt:raise InterruptedError('Trial interrupted before native process launch')
            child=subprocess.Popen(cmd,env=env,cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            atomic(out/'running.json',{**owner,'job_id':spec['job_id'],'child':identity(child.pid),'started_at':now()})
            while child.poll() is None:
                remember()
                atomic(out/'heartbeat.json',{**owner,'job_id':spec['job_id'],'heartbeat_at':now(),'heartbeat_unix':time.time(),
                  'elapsed_seconds':time.monotonic()-started,'child':identity(child.pid),'known_children':list(known.values())})
                if interrupt or time.monotonic()-started>hard_timeout:
                    timed_out=not interrupt;terminate(signal.SIGTERM)
                    try:child.wait(timeout=15)
                    except subprocess.TimeoutExpired:terminate(signal.SIGKILL);child.wait()
                    break
                time.sleep(2)
        # A prematurely exited native launcher must not leave model workers
        # sending requests after a terminal result/slot release.
        remember()
        remaining=[r for r in known.values() if owner_alive(r)]
        if remaining:
            terminate(signal.SIGTERM);time.sleep(.3);terminate(signal.SIGKILL)
    except BaseException as exc:
        error_type=type(exc).__name__
        if child:
            terminate(signal.SIGTERM)
            if child.poll() is None:
                try:child.wait(timeout=15)
                except subprocess.TimeoutExpired:terminate(signal.SIGKILL);child.wait()
            time.sleep(.3);terminate(signal.SIGKILL)
    native={}
    if native_result and native_result.exists():
        try:native=json.loads(native_result.read_text())
        except (ValueError,OSError):error_type=error_type or 'MalformedNativeResult'
    status='interrupted' if interrupt else 'timeout' if timed_out else native.get('status','failed')
    failure='explicit_worker_signal' if interrupt else 'timeout' if timed_out else native.get('failure_category')
    if status!='completed' and not failure:failure='execution_error'
    result={'execution_version':VERSION,'job_id':spec['job_id'],'harness':spec['harness'],'strategy':spec['strategy'],
      'question_id':spec['question_id'],'repeat':spec['repeat'],'model':spec['model'],'status':status,'failure_category':failure,
      'final':native.get('final'),'score':None,'evaluation_status':'not_judged','error_type':error_type,
      'exit_code':child.returncode if child else None,'end_to_end_seconds':time.monotonic()-started,
      'native_end_to_end_seconds':native.get('end_to_end_seconds',native.get('agent_loop_seconds')),
      'native_result_path':str(native_result) if native_result and native_result.exists() else None,
      'native_artifact_root':str(out/'native'),'usage_accounting':'Read raw native metrics; missing usage is unknown, never zero-filled',
      'worker_identity':owner,'started_at_unix_estimate':time.time()-(time.monotonic()-started),'finished_at':now(),
      'retry_policy':'Terminal/interrupted outcomes and unknown claimed attempts are not automatically retried'}
    remember()
    orphaned=[record for record in known.values() if owner_alive(record)]
    result['unconfirmed_child_termination']=orphaned
    result['slot_released']=not orphaned
    atomic(out/'result.json',result)
    atomic(out/'heartbeat.json',{**owner,'heartbeat_at':now(),'heartbeat_unix':time.time(),'finished':True,'status':status})
    if not orphaned:release_slot(Path(spec['slot_path']))


if __name__=='__main__':main()
