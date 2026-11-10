#!/usr/bin/env python3
"""One reserved local worker; visual-first, source-bound, no automatic paid replay."""
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
from prepare_controlled_bounded_v1 import DEFAULT, ROOT, load_validate, read, MODEL
from controlled_native_worker_bounded_v1 import validate_spec, PROTOCOL
from controlled_native_report_v4 import accounting
from run_bc_trial import atomic, process_identity
from lab import environment, python_for


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True); atomic(path, value)


def alive(out):
    for name in ('supervisor.json', 'dispatch.json', 'child.json'):
        path=out/name
        if path.exists():
            r=read(path)
            if r.get('pid') and r.get('identity') and process_identity(r['pid']) == r['identity']: return True
    return False


def reference_valid(control, spec):
    count=control.get('first_actual_prompt_tokens')
    return bool(control.get('passed') and control.get('method')=='visual'
        and isinstance(count,int) and not isinstance(count,bool) and 0<count<=16384
        and control.get('native_identity_verified') and control.get('native_hashes')
        and control.get('actual_route')==MODEL
        and control.get('bounded_native_protocol')==PROTOCOL
        and control.get('bounded_transport_encoding')==spec.get('bounded_transport_encoding'))


def disposition(job, root):
    if not job['eligible']: return 'not_run_original_prefix_unavailable'
    out=Path(job['out'])
    if alive(out): return 'running'
    if (out/'trial-status.json').exists(): return read(out/'trial-status.json')['status']
    if any((out/n).exists() for n in ('dispatch.json','supervisor.json','worker-started.json','result.json')):
        return 'interrupted_unknown_no_replay'
    if job['method']=='visual': return 'ready'
    visual=root/'jobs'/job['prefix_key']/'visual'
    if alive(visual): return 'waiting_visual'
    if not (visual/'trial-status.json').exists():
        return 'not_run_visual_gate_unavailable' if (visual/'dispatch.json').exists() else 'waiting_visual'
    control=read(visual/'compression-control.json') if (visual/'compression-control.json').exists() else {}
    if reference_valid(control,read(job['spec_path'])): return 'ready'
    return 'not_run_visual_gate_unavailable'


def group_gate(rows):
    """Independent actual three-arm control, not accuracy or ceiling-only acceptance."""
    if set(rows)!= {'visual','summary','window'}: return {'passed':False,'reason':'missing_control'}
    states=list(rows.values()); counts=[r.get('first_actual_prompt_tokens') for r in states]
    known=all(isinstance(x,int) and not isinstance(x,bool) and 0<x<=16384 for x in counts)
    native=bool(states[0].get('native_hashes')) and all(r.get('native_hashes')==states[0].get('native_hashes') for r in states)
    prefix=bool(states[0].get('prefix_sha256')) and len({r.get('prefix_sha256') for r in states})==1
    route=all(r.get('actual_route')==MODEL for r in states)
    target=rows['visual'].get('first_actual_prompt_tokens')
    matched=known and all(abs(r['first_actual_prompt_tokens']-target)<=target*.02 for r in states)
    spread=(max(counts)-min(counts))/max(counts) if known else None
    passed=bool(known and matched and spread<=.05 and native and prefix and route
        and len({r.get('bounded_transport_encoding') for r in states})==1
        and all(r.get('passed') and r.get('native_identity_verified') and r.get('bounded_native_protocol')==PROTOCOL for r in states))
    return {'passed':passed,'known_actual_usage':known,'within_visual_two_percent':bool(matched),
        'realized_spread':spread,'identical_native_payloads':native,'identical_prefix':prefix,'same_route':route}


def snapshot(root,plan,pilot_only=False):
    states={j['job_id']:disposition(j,root) if not pilot_only or j['pilot'] else 'outside_pilot_scope' for j in plan['jobs']}
    groups={}; render_records=[]
    for p in plan['prefixes']:
        rows={}
        for method in ('visual','summary','window'):
            out=root/'jobs'/p['key']/method; path=out/'compression-control.json'
            if path.exists():
                c=read(path)
                render_records.append({'group':p['key'],'method':method,'render_seconds':c.get('render_seconds'),
                    'encoding_seconds':c.get('canvas_encoding_seconds'),'effective_scale':c.get('effective_canvas_linear_scale')})
                if (out/'trial-status.json').exists(): rows[method]=c
        groups[p['key']]=group_gate(rows)
    status={'at':time.time(),'state':'monitoring','concurrency_cap':1,'pilot_only':pilot_only,
        'counts':dict(Counter(states.values())),'jobs':states,'group_gates':groups,
        'matched_groups':sum(g['passed'] for g in groups.values()),
        'render_records':render_records, 'original_groups':60,'eligible_groups':sum(p['eligible'] for p in plan['prefixes']),
        'provider_latency_seconds':None,'costs':accounting(root),'old_costs':plan['definition']['old_costs'],
        'interpretation':plan['definition']['interpretation']}
    write(root/'status.json',status)
    return status


def trial(root,job_id):
    plan,_=load_validate(root); job=next(j for j in plan['jobs'] if j['job_id']==job_id)
    if not job['eligible']: raise ValueError('Unavailable original prefix')
    out=Path(job['out']); spec_path=Path(job['spec_path']); spec=read(spec_path)
    validate_spec(spec,out)
    lease=(out/'supervisor.lock').open('a'); fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
    if any((out/n).exists() for n in ('supervisor.json','worker-started.json','result.json','trial-status.json')):
        raise ValueError('Existing attempt preserved; no paid replay')
    write(out/'supervisor.json',{'pid':os.getpid(),'identity':process_identity(os.getpid()),'started':time.time()})
    if job['method']!='visual':
        visual=Path(spec['target_reference_path'])
        if alive(visual.parent) or not (visual.parent/'trial-status.json').exists() or not reference_valid(read(visual),spec):
            raise ValueError('Visual target not final or invalid')
    env,_=environment(ROOT,'hermes',Path(spec['config_path']))
    cmd=[python_for(ROOT),str(ROOT/'scripts/controlled_native_worker_bounded_v1.py'),'--spec',str(spec_path),'--out',str(out),'--live']
    start=time.monotonic(); interrupted=False; child=None
    def stop(sig,frame):
        nonlocal interrupted
        interrupted=True
    signal.signal(signal.SIGTERM,stop); signal.signal(signal.SIGINT,stop)
    with (out/'native.log').open('a') as log:
        child=subprocess.Popen(cmd,cwd=ROOT,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        write(out/'child.json',{'pid':child.pid,'identity':process_identity(child.pid),'started':time.time()})
        timed_out=False
        while child.poll() is None:
            if interrupted or time.monotonic()-start>plan['definition']['timeout_seconds']:
                timed_out=not interrupted
                try: os.killpg(child.pid,signal.SIGTERM)
                except ProcessLookupError: pass
                try: child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    try: os.killpg(child.pid,signal.SIGKILL)
                    except ProcessLookupError: pass
                    child.wait()
                break
            time.sleep(.5)
    native=read(out/'result.json') if (out/'result.json').exists() else {}
    status='interrupted' if interrupted else 'timeout' if timed_out else native.get('status','failed')
    write(out/'trial-status.json',{'status':status,'worker_status':native.get('status'),'job_id':job_id,
        'elapsed_seconds':time.monotonic()-start,'exit_code':child.returncode,'worker_reaped':True,
        'unknown_usage_preserved':True,'provider_latency_seconds':None})


def queue(root,pilot_only=False):
    import experiment_admission_v4 as admission
    import admission_lock_ops1
    admission_lock_ops1.install(admission,timeout=30.)
    plan,_=load_validate(root)
    with (root/'queue.lock').open('a') as lease:
        fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
        write(root/'coordinator.json',{'pid':os.getpid(),'identity':process_identity(os.getpid()),'concurrency':1,'pilot_only':pilot_only})
        children=[]
        while True:
            for child in list(children):
                if child.poll() is not None: children.remove(child)
            status=snapshot(root,plan,pilot_only); states=status['jobs']
            if not any(v=='running' for v in states.values()):
                ready=next((j for j in plan['jobs'] if states[j['job_id']]=='ready'),None)
                if ready:
                    # Revalidate all frozen sources and prefixes immediately before paid dispatch.
                    load_validate(root); out=Path(ready['out'])
                    cmd=[sys.executable,str(Path(__file__).resolve()),'--root',str(root),'--trial',ready['job_id'],'--live']
                    # Crash before/after spawn leaves durable intent; never blindly replay.
                    write(out/'dispatch.json',{'state':'reserved_no_automatic_replay','at':time.time()})
                    child,reason=admission.spawn_admitted(cmd,owner='controlled-bounded-v1',job_id=ready['job_id'],log_path=out/'supervisor.log',process_cost=4)
                    if child is None:
                        # Admission made no child: this reservation is explicitly void, safe to retry admission.
                        (out/'dispatch.json').unlink(); write(root/'admission-status.json',{'reason':reason,'at':time.time()})
                    else:
                        children.append(child); write(out/'dispatch.json',{'state':'spawned','pid':child.pid,'identity':process_identity(child.pid),'at':time.time()})
                elif not any(v=='waiting_visual' for v in states.values()):
                    status['state']='finished'; write(root/'status.json',status); return
            time.sleep(10)


def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('--root',type=Path,default=DEFAULT)
    p.add_argument('--live',action='store_true'); p.add_argument('--pilot-only',action='store_true'); p.add_argument('--trial'); a=p.parse_args(); root=a.root.resolve()
    plan,_=load_validate(root)
    if not a.live:
        result=snapshot(root,plan,a.pilot_only)
        print(json.dumps({'live':False,'calls':0,'counts':result['counts'],'concurrency_cap':1})); return
    if a.trial: trial(root,a.trial)
    else: queue(root,a.pilot_only)

if __name__=='__main__': main()
