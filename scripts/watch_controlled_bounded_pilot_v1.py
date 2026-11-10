#!/usr/bin/env python3
"""One-shot operational pilot-to-full handoff; no worker/plan mutation or blind relaunch."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from prepare_controlled_bounded_v1 import DEFAULT, ROOT, load_validate, read
from run_controlled_bounded_v1 import group_gate, alive
from run_bc_trial import process_identity
from judge_bc_v3_completed import atomic, immutable, sha, now

VERSION='controlled-bounded-pilot-full-watch-v1'


def evaluate(root,plan):
    pilots=[p for p in plan['prefixes'] if p['pilot']]
    if len(pilots)!=2 or not all(p['eligible'] for p in pilots):return {'state':'blocked','reason':'original_two_pilot_groups_not_eligible'}
    checks={};bindings={};waiting=[]
    for p in pilots:
        controls={}
        for method in ('visual','summary','window'):
            key=p['key']+'/'+method;out=root/'jobs'/key
            if alive(out):waiting.append(key);continue
            terminal=out/'trial-status.json';control=out/'compression-control.json'
            if not terminal.exists():
                if any((out/n).exists() for n in ('dispatch.json','worker-started.json','supervisor.json')):
                    return {'state':'blocked','reason':'pilot_interrupted_unknown_no_replay','job_id':key}
                # Text arms may be deliberately unstarted after visual control failure.
                visual=root/'jobs'/p['key']/'visual'
                if method!='visual' and (visual/'trial-status.json').exists():
                    v=read(visual/'compression-control.json') if (visual/'compression-control.json').exists() else {}
                    if not v.get('passed'):return {'state':'blocked','reason':'visual_control_failed','group':p['key'],'control':v}
                waiting.append(key);continue
            t=read(terminal)
            if t.get('worker_reaped') is not True:return {'state':'blocked','reason':'pilot_worker_cleanup_unconfirmed','job_id':key}
            bindings[key]={'trial_sha256':sha(terminal),'control_sha256':sha(control) if control.exists() else None}
            controls[method]=read(control) if control.exists() else {}
        if len(controls)==3:checks[p['key']]=group_gate(controls)
    if waiting:return {'state':'waiting','waiting_jobs':waiting,'groups':checks}
    if not all(c['passed'] for c in checks.values()) or len(checks)!=2:
        return {'state':'blocked','reason':'pilot_actual_budget_native_gate_failed','groups':checks,'bindings':bindings}
    return {'state':'ready','groups':checks,'bindings':bindings,'selection_by_accuracy':False}


def coordinator_alive(root):
    path=root/'coordinator.json'
    if not path.exists():return False
    r=read(path)
    return bool(r.get('identity') and process_identity(r['pid'])==r['identity'])


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=DEFAULT);p.add_argument('--live',action='store_true');p.add_argument('--watch',action='store_true');a=p.parse_args();root=a.root.resolve()
    plan,_=load_validate(root);directory=root/'pilot-full-handoff-v1';directory.mkdir(exist_ok=True)
    immutable(directory/'protocol.json',{'version':VERSION,'plan_sha256':sha(root/'plan.json'),
        'watcher_sha256':sha(__file__),'controller_sha256':sha(ROOT/'scripts/run_controlled_bounded_v1.py'),
        'new_worker_concurrency':1,'judge_accuracy_not_a_gate':True,'maximum_full_controller_launches':1})
    lease=(directory/'watch.lock').open('a');fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
    while True:
        decision=evaluate(root,plan);decision['at']=now();atomic(directory/'status.json',decision)
        if not a.live:print(json.dumps(dict(decision,live=False)));return
        launch=directory/'launch.json'
        if launch.exists():
            r=read(launch);atomic(directory/'status.json',{'state':'prior_full_launch_retained_no_relaunch','launch':r,'at':now()});return
        if decision['state']=='blocked':return
        if decision['state']=='ready' and not coordinator_alive(root):
            # Check the same controller lock before committing a one-shot launch intent.
            with (root/'queue.lock').open('a') as lock:
                try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                except BlockingIOError:
                    if not a.watch:return
                    time.sleep(2);continue
                load_validate(root)
                fresh=evaluate(root,plan)
                if fresh['state']!='ready' or fresh['bindings']!=decision['bindings']:raise ValueError('Pilot source changed during handoff')
                immutable(directory/'passed-gates.json',fresh)
                immutable(launch,{'state':'reserved_before_spawn','at':now(),'automatic_relaunch':False})
            cmd=[sys.executable,str(ROOT/'scripts/run_controlled_bounded_v1.py'),'--root',str(root),'--live']
            try:
                with (directory/'full-controller.log').open('a') as log:
                    child=subprocess.Popen(cmd,cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                atomic(launch,{'state':'spawned','pid':child.pid,'identity':process_identity(child.pid),'at':now(),'command':cmd,'automatic_relaunch':False})
            except BaseException as e:
                atomic(directory/'launch-error.json',{'error_type':type(e).__name__,'automatic_retry':False,'at':now()});raise
            atomic(directory/'status.json',{'state':'full_controller_launched_once','launch':read(launch),'at':now()});return
        if not a.watch:return
        time.sleep(10)

if __name__=='__main__':main()
