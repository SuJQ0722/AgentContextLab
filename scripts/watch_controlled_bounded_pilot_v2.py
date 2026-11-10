#!/usr/bin/env python3
"""Resume all original eligible groups after clean pilot termination, irrespective of global pilot success."""
import argparse
import fcntl
import json
from pathlib import Path
import subprocess
import sys
import time
from prepare_controlled_bounded_v1 import DEFAULT, ROOT, load_validate, read
from run_controlled_bounded_v1 import group_gate, alive, disposition
from watch_controlled_bounded_pilot_v1 import coordinator_alive
from run_bc_trial import process_identity
from judge_bc_v3_completed import atomic, immutable, sha, now

VERSION='controlled-bounded-pilot-full-watch-v2'
TERMINAL={'completed','failed','timeout','budget_infeasible','interrupted'}
POLICY={
    'version':VERSION,'global_two_pilot_success_required':False,
    'require_all_six_pilot_dispositions_known':True,'require_actual_workers_reaped':True,
    'unknown_or_unconfirmed_cleanup_blocks':True,'accuracy_selection':False,
    'per_group_visual_target_gate_unchanged':True,'per_arm_two_percent_match_unchanged':True,
    'group_five_percent_spread_report_unchanged':True,'failed_groups_marked_passed':False,
    'same_original_40_eligible_groups':True,'replace_questions':False,
    'maximum_full_controller_launches':1,'worker_concurrency':1,
    'existing_attempts_replayed':False,
    'reason':'User authorized all eligible tasks; an individual pilot network failure must not gate unrelated original groups. Existing offline validation and measured MMBC calibration establish implementation readiness; each group still validates its own actual target/native evidence.'}


def evaluate(root,plan):
    pilots=[p for p in plan['prefixes'] if p['pilot']]
    if len(pilots)!=2 or not all(p['eligible'] for p in pilots):return {'state':'blocked','reason':'original_pilot_inventory_changed'}
    jobs={j['job_id']:j for j in plan['jobs']};states={};bindings={};groups={};waiting=[]
    for p in pilots:
        controls={}
        for method in ('visual','summary','window'):
            key=p['key']+'/'+method
            if key not in jobs:return {'state':'blocked','reason':'original_pilot_arm_missing','job_id':key}
            job=jobs[key];out=Path(job['out']);state=disposition(job,root);states[key]=state
            if alive(out) or state=='running':waiting.append(key);continue
            terminal=out/'trial-status.json';control=out/'compression-control.json'
            if terminal.exists():
                t=read(terminal)
                if t.get('worker_reaped') is not True:return {'state':'blocked','reason':'worker_cleanup_unconfirmed','job_id':key,'pilot_states':states}
                if t.get('status') not in TERMINAL or state not in TERMINAL:return {'state':'blocked','reason':'unknown_pilot_execution','job_id':key,'pilot_states':states}
                bindings[key]={'kind':'actual_attempt','trial_sha256':sha(terminal),
                    'control_sha256':sha(control) if control.exists() else None,
                    'result_sha256':sha(out/'result.json') if (out/'result.json').exists() else None}
                controls[method]=read(control) if control.exists() else {}
            elif state=='not_run_visual_gate_unavailable' and method!='visual':
                visual=root/'jobs'/p['key']/'visual';vt=visual/'trial-status.json'
                if not vt.exists() or read(vt).get('worker_reaped') is not True or read(vt).get('status') not in TERMINAL:
                    return {'state':'blocked','reason':'derived_not_run_without_known_reaped_visual','job_id':key}
                if any((out/n).exists() for n in ('dispatch.json','worker-started.json','supervisor.json','result.json')):
                    return {'state':'blocked','reason':'not_run_arm_has_attempt_evidence','job_id':key}
                vc=visual/'compression-control.json'
                bindings[key]={'kind':'derived_not_run_visual_gate_unavailable','visual_trial_sha256':sha(vt),
                    'visual_control_sha256':sha(vc) if vc.exists() else None,'new_model_calls':0}
            elif state in ('ready','waiting_visual'):waiting.append(key)
            else:return {'state':'blocked','reason':'unknown_or_unconfirmed_pilot_disposition','job_id':key,'pilot_states':states}
        groups[p['key']]=group_gate(controls)
    return {'state':'waiting' if waiting else 'ready','waiting_jobs':waiting,'pilot_states':states,
        'groups':groups,'bindings':bindings,'all_pilot_groups_passed':all(g['passed'] for g in groups.values()),
        'global_group_success_required':False,'selection_by_accuracy':False,
        'scope':'Continue all original eligible slots. Existing failed/not-run attempts retained; no question replacement.'}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=DEFAULT)
    p.add_argument('--live',action='store_true');p.add_argument('--watch',action='store_true');a=p.parse_args();root=a.root.resolve()
    plan,_=load_validate(root);directory=root/'pilot-full-handoff-v2';directory.mkdir(exist_ok=True)
    old=root/'pilot-full-handoff-v1'
    old.mkdir(exist_ok=True)
    # Hold the old watcher lock throughout v2 supervision, preventing concurrent v1 handoff.
    old_lease=(old/'watch.lock').open('a');fcntl.flock(old_lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
    if (old/'launch.json').exists():raise ValueError('Prior v1 launch exists; investigate before any v2 launch')
    prior=read(old/'status.json') if (old/'status.json').exists() else {}
    if prior.get('state')!='blocked':raise ValueError('Confirm v1 watcher ended blocked before replacing its policy')
    immutable(directory/'protocol.json',{'policy':POLICY,'plan_sha256':sha(root/'plan.json'),
        'watcher_sha256':sha(__file__),'controller_sha256':sha(ROOT/'scripts/run_controlled_bounded_v1.py'),
        'v1_status_sha256':sha(old/'status.json'),'v1_had_no_launch':True})
    lease=(directory/'watch.lock').open('a');fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
    while True:
        decision=evaluate(root,plan);decision['at']=now();atomic(directory/'status.json',decision)
        if not a.live:print(json.dumps(dict(decision,live=False)));return
        launch=directory/'launch.json'
        if launch.exists():
            atomic(directory/'status.json',{'state':'prior_full_launch_retained_no_relaunch','launch':read(launch),'at':now()});return
        if decision['state']=='blocked':return
        if decision['state']=='ready' and not coordinator_alive(root):
            with (root/'queue.lock').open('a') as lock:
                try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                except BlockingIOError:
                    if not a.watch:return
                    time.sleep(2);continue
                load_validate(root);fresh=evaluate(root,plan)
                if fresh['state']!='ready' or fresh['bindings']!=decision['bindings']:raise ValueError('Pilot evidence changed during handoff')
                if (old/'launch.json').exists():raise ValueError('Unexpected prior v1 launch')
                immutable(directory/'terminal-pilot-evidence.json',fresh)
                immutable(launch,{'state':'reserved_before_spawn','at':now(),'automatic_relaunch':False})
            cmd=[sys.executable,str(ROOT/'scripts/run_controlled_bounded_v1.py'),'--root',str(root),'--live']
            try:
                with (directory/'full-controller.log').open('a') as log:
                    child=subprocess.Popen(cmd,cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                atomic(launch,{'state':'spawned','pid':child.pid,'identity':process_identity(child.pid),'at':now(),'command':cmd,'automatic_relaunch':False})
            except BaseException as e:
                atomic(directory/'launch-error.json',{'error_type':type(e).__name__,'automatic_retry':False,'at':now()});raise
            atomic(directory/'status.json',{'state':'full_controller_launched_once','launch':read(launch),'at':now(),
                'all_pilot_groups_passed':fresh['all_pilot_groups_passed'],'failed_group_gates_preserved':True});return
        if not a.watch:return
        time.sleep(10)

if __name__=='__main__':main()
