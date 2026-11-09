#!/usr/bin/env python3
"""Operational coordinator: frozen v4 science, pilot4 then admitted target16."""
import argparse,fcntl,json,os,signal,sys,time
from pathlib import Path
import run_controlled_native_v4 as frozen
from run_controlled_native_v4 import (ROOT,DEFAULT,atomic,process_identity,verify_inputs,
    digest,pilot_gate,usage_snapshot,extract_prefix,active,spawn_admitted)
from experiment_admission_v4 import STATE,processes

VERSION='controlled-v4-concurrency-retry-ops2'
from controlled_attempts_v4 import selected_out,selection,LEDGER
import experiment_admission_v4
import admission_lock_ops1
FROZEN_ENTRY=ROOT/'scripts/run_controlled_native_v4.py'

def target_concurrency(gate):
    return 16 if gate.get('passed') is True else 4

def process_out(record):
    argv=record.get('argv',[])
    if len(argv)<2 or Path(argv[1]).resolve()!=FROZEN_ENTRY.resolve() or '--trial' not in argv:return None
    try:return Path(argv[argv.index('--root')+1]).resolve()
    except (ValueError,IndexError):return None

def unpublished_trials(root,snapshot):
    """A paid child must have its matching durable dispatch before takeover.

    Called while holding the *same* admission flock used by old spawn_admitted,
    so no new child can be admitted during this publication check.
    """
    pending=[]
    for pid,record in snapshot.items():
        out=process_out(record)
        if out is None or not out.is_relative_to(root):continue
        try:d=json.loads((out/'dispatch.json').read_text())
        except (OSError,ValueError):d={}
        if d.get('pid')!=pid or d.get('identity')!=record['identity']:
            pending.append({'pid':pid,'identity':record['identity'],'out':str(out)})
    return pending

def publication_checkpoint(root,barrier_ns):
    # Frozen v4 writes status only after its spawn->dispatch loop. A fresh
    # checkpoint under our admission lock proves even a short-lived child had
    # its dispatch published; merely looking for live children is insufficient.
    path=root/'status.json'
    try:
        return path.stat().st_mtime_ns>barrier_ns and isinstance(json.loads(path.read_text()).get('running_slots'),int)
    except (OSError,ValueError):return False

def verify_old(root,pid,identity,snapshot):
    record=snapshot.get(pid)
    if not record or record.get('identity')!=identity:raise ValueError('Old coordinator PID/start identity mismatch')
    argv=record.get('argv',[])
    if len(argv)<2 or Path(argv[1]).resolve() not in {FROZEN_ENTRY.resolve(),(ROOT/'scripts/run_controlled_native_v4_ops1.py').resolve()} or '--trial' in argv or '--live' not in argv:
        raise ValueError('Refusing to signal anything except the frozen v4 live coordinator')
    try:actual=Path(argv[argv.index('--root')+1]).resolve()
    except (ValueError,IndexError):actual=DEFAULT.resolve()
    if actual!=root:raise ValueError('Old coordinator root mismatch')
    stored=json.loads((root/'coordinator.json').read_text())
    if stored.get('pid')!=pid or stored.get('identity')!=identity:raise ValueError('Coordinator record changed')
    return stored

def ended(pid,identity):
    try:
        fields=Path(f'/proc/{pid}/stat').read_text().split(') ',1)[1].split()
        return fields[0]=='Z' or fields[19]!=identity
    except FileNotFoundError:return True

def pidfd_open(pid):
    if hasattr(os,'pidfd_open'):return os.pidfd_open(pid)
    # This Conda Python lacks the wrappers, while its Linux kernel supports
    # pidfds. Keep identity-safe kernel semantics; never fall back to os.kill.
    import ctypes,platform
    if sys.platform!='linux' or platform.machine()!='x86_64':raise RuntimeError('No verified pidfd syscall ABI')
    libc=ctypes.CDLL(None,use_errno=True)
    result=libc.syscall(ctypes.c_long(434),ctypes.c_int(pid),ctypes.c_uint(0))
    if result<0:
        errno=ctypes.get_errno();raise OSError(errno,os.strerror(errno))
    return result

def pidfd_signal(descriptor,number):
    if hasattr(signal,'pidfd_send_signal'):return signal.pidfd_send_signal(descriptor,number)
    import ctypes,platform
    if sys.platform!='linux' or platform.machine()!='x86_64':raise RuntimeError('No verified pidfd syscall ABI')
    libc=ctypes.CDLL(None,use_errno=True)
    result=libc.syscall(ctypes.c_long(424),ctypes.c_int(descriptor),ctypes.c_int(number),ctypes.c_void_p(0),ctypes.c_uint(0))
    if result<0:
        errno=ctypes.get_errno();raise OSError(errno,os.strerror(errno))

def stop_old(root,pid,identity,diagnostic):
    """Stop only the precisely identified coordinator, never its process group."""
    STATE.mkdir(parents=True,exist_ok=True)
    with (STATE/'experiment-admission.lock').open('a') as admission:
        deadline=time.monotonic()+45
        while True:
            try:fcntl.flock(admission,fcntl.LOCK_EX|fcntl.LOCK_NB);break
            except BlockingIOError:
                if time.monotonic()>deadline:raise TimeoutError('Admission flock busy; no signal sent')
                time.sleep(.25)
        old=verify_old(root,pid,identity,processes());barrier_ns=time.time_ns()
        while True:
            snapshot=processes();verify_old(root,pid,identity,snapshot)
            pending=unpublished_trials(root,snapshot)
            checkpoint=publication_checkpoint(root,barrier_ns)
            if not pending and checkpoint:break
            if time.monotonic()>deadline:
                atomic(diagnostic,{'state':'blocked_unpublished_dispatch','pending':pending,'fresh_post_dispatch_checkpoint':checkpoint,'old_coordinator':old});raise TimeoutError('Unpublished paid supervisor; no signal sent')
            time.sleep(.25)
        children=[{'pid':p,'identity':r['identity'],'out':str(process_out(r))} for p,r in snapshot.items()
                  if process_out(r) is not None and process_out(r).is_relative_to(root)]
        record={'state':'verified_before_signal','version':VERSION,'old_coordinator':old,
            'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
            'pid_namespace':os.readlink('/proc/self/ns/pid'),'preserved_supervisors':children,
            'signal_scope':'Exact coordinator PID only; no process group signal',
            'shared_admission_publication_barrier':True,'fresh_post_dispatch_checkpoint':True,'at':time.time()}
        atomic(diagnostic,record)
        descriptor=pidfd_open(pid)
        try:
            verify_old(root,pid,identity,processes())
            pidfd_signal(descriptor,signal.SIGTERM)
        finally:os.close(descriptor)
        deadline=time.monotonic()+15
        while not ended(pid,identity):
            if time.monotonic()>deadline:raise TimeoutError('Old coordinator has not exited; do not start replacement')
            time.sleep(.1)
        record.update(state='old_coordinator_exited_children_preserved',stopped_at=time.time())
        atomic(diagnostic,record)

def queue(root,plan):
    verify_inputs(root)
    selected=selection(root);selection_sha=digest((root/LEDGER).read_bytes())
    def resolve_job(job_id):
        return Path(selected[job_id]['selected_out']) if job_id in selected else root/'jobs'/job_id
    processes={};worker=ROOT/'scripts/controlled_native_worker_v4.py'
    fingerprint=digest(worker.read_bytes());version=root/'worker-version.json'
    if version.exists() and json.loads(version.read_text())['sha256']!=fingerprint:raise ValueError('Worker changed after campaign start')
    if not version.exists():atomic(version,{'sha256':fingerprint})
    atomic(root/'coordinator.json',{'pid':os.getpid(),'identity':process_identity(os.getpid()),'started':time.time()})
    while True:
        if digest((root/LEDGER).read_bytes())!=selection_sha:raise ValueError('Retry selection changed after launch')
        for pid,p in list(processes.items()):
            if p.poll() is not None:processes.pop(pid)
        pilot=[]
        for j in plan['jobs']:
            f=resolve_job(j['job_id'])/'result.json'
            if j['pilot'] and f.exists():
                value=json.loads(f.read_text());control=f.parent/'compression-control.json'
                if control.exists():value['control_gate']=json.loads(control.read_text())
                pilot.append({**value,'method':j['method'],'dataset':j['dataset']})
        gate=pilot_gate(pilot);target=target_concurrency(gate);atomic(root/'pilot-gate.json',gate)
        if len(pilot)==6 and not gate['passed']:
            atomic(root/'status.json',{'state':'blocked','reason':'pilot_realized_budget_or_native_gate_failed','pilot_gate':gate,'requested_concurrency':4,'post_pilot_target':16,'operational_version':VERSION,'effective_running':0,'new_usage_known':usage_snapshot(root)});return
        tasks=[]
        for p in plan['prefixes']:
            if p['pilot'] or not gate['passed']:continue
            prefix=root/'prefixes'/p['key'];collector=root/'collectors'/p['key']
            if (prefix/'prefix.json').exists() or (prefix/'blocked.json').exists():continue
            if (collector/'result.json').exists():
                try:extract_prefix(collector,prefix)
                except (ValueError,OSError) as e:prefix.mkdir(parents=True,exist_ok=True);atomic(prefix/'blocked.json',{'reason':str(e)})
            else:tasks.append(('capture',collector))
        for j in plan['jobs']:
            if not j['pilot'] and not gate['passed']:continue
            prefix=root/'prefixes'/j['prefix_key'];out=resolve_job(j['job_id'])
            if (prefix/'blocked.json').exists() and not (out/'result.json').exists():
                atomic(out/'result.json',{'status':'not_run_prefix_unavailable','reason':json.loads((prefix/'blocked.json').read_text()),'api_calls':0})
            elif (prefix/'prefix.json').exists():
                if j['method']!='visual':
                    reference=resolve_job(j['prefix_key']+'/visual')/'compression-control.json'
                    ready=root/'fit-worker-ready.json'
                    control=json.loads(reference.read_text()) if reference.exists() else {}
                    if not control.get('passed') or not control.get('first_actual_prompt_tokens'):
                        visual_result=reference.parent/'result.json'
                        if visual_result.exists() and not (out/'result.json').exists():
                            atomic(out/'result.json',{'status':'not_run_visual_gate_unavailable','api_calls':0})
                        continue
                    if not ready.exists():continue
                    version=json.loads(ready.read_text());fit=ROOT/'scripts'/version['worker_script']
                    if fit.name!='controlled_native_worker_v4.py' or digest(fit.read_bytes())!=version['sha256']:raise ValueError('Fitting worker fingerprint changed')
                    runtime={**json.loads((out/'spec.json').read_text()),'worker_script':fit.name,'target_reference_path':str(reference),'worker_sha256':version['sha256']}
                    if (out/'runtime-spec.json').exists() and json.loads((out/'runtime-spec.json').read_text())!=runtime:raise ValueError('Frozen fitting runtime spec changed')
                    if not (out/'runtime-spec.json').exists():atomic(out/'runtime-spec.json',runtime)
                tasks.append(('method',out))
        all_dirs=[resolve_job(j['job_id']) for j in plan['jobs']]+[root/'collectors'/p['key'] for p in plan['prefixes']]
        running=sum(active(out) for out in all_dirs);launched=0;reason=None
        for kind,out in tasks:
            if running>=target:break
            if (out/'result.json').exists() or active(out):continue
            if (out/'dispatch.json').exists():
                atomic(out/'result.json',{'status':'interrupted_unknown','reason':'prior_dispatch_not_alive_no_automatic_retry'});continue
            cmd=[sys.executable,str(FROZEN_ENTRY),'--trial',kind,'--spec',str(out/'runtime-spec.json' if (out/'runtime-spec.json').exists() else out/'spec.json'),'--root',str(out)]
            proc,reason=spawn_admitted(cmd,owner='controlled-baseline',job_id=str(out.relative_to(root)),log_path=out/'supervisor.log',process_cost=4)
            if proc is None:break
            processes[proc.pid]=proc;atomic(out/'dispatch.json',{'pid':proc.pid,'identity':process_identity(proc.pid),'at':time.time()});running+=1;launched+=1
        terminal=sum((resolve_job(j['job_id'])/'result.json').exists() for j in plan['jobs'])
        atomic(root/'status.json',{'state':'running' if gate['passed'] else 'waiting_pilot_gate','formal_arms_eligible':174 if gate['passed'] else 0,'fitting_worker_ready':(root/'fit-worker-ready.json').exists(),'pilot_gate':gate,'arms_terminal':terminal,'planned_arms':180,'running_slots':running,'concurrency':target,'requested_concurrency':target,'post_pilot_target':16,'operational_version':VERSION,'effective_running':running,'new_usage_known':usage_snapshot(root),'admission':reason,'new_launches':launched})
        if terminal==len(plan['jobs']):return
        time.sleep(5)

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,default=DEFAULT)
    parser.add_argument('--live',action='store_true');parser.add_argument('--handoff',action='store_true')
    parser.add_argument('--expected-pid',type=int);parser.add_argument('--expected-identity');args=parser.parse_args()
    root=args.root.resolve();verify_inputs(root);selection(root);plan=json.loads((root/'plan.json').read_text())
    if digest((root/'experiment.json').read_bytes())!=plan['definition']['config_sha256']:raise ValueError('Frozen config changed')
    if not args.live:
        print(json.dumps({'live':False,'pilot_target':4,'post_pilot_target':16,'scientific_entry_unchanged':str(FROZEN_ENTRY),'root':str(root)}));return
    lock_ops=admission_lock_ops1.install(experiment_admission_v4,timeout=30.)
    with (root/'ops2-switch.lock').open('a') as switch:
        fcntl.flock(switch,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if args.handoff:
            if args.expected_pid is None or not args.expected_identity:raise ValueError('Explicit expected old PID and start identity required')
            stop_old(root,args.expected_pid,args.expected_identity,root/'ops2-handoff.json')
        with (root/'queue.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            verify_inputs(root)
            lineage={'version':VERSION,'pid':os.getpid(),'identity':process_identity(os.getpid()),'started_at':time.time(),
                'operational_source_sha256':digest(Path(__file__).read_bytes()),'frozen_plan_sha256':digest((root/'plan.json').read_bytes()),
                'frozen_implementation_sha256':digest((root/'implementation.json').read_bytes()),
                'admission_sha256':digest((ROOT/'scripts/experiment_admission_v4.py').read_bytes()),
                'retry_selection_sha256':digest((root/LEDGER).read_bytes()),'retry_selection_helper_sha256':digest((ROOT/'scripts/controlled_attempts_v4.py').read_bytes()),'admission_lock_ops':lock_ops,
                'pilot_target':4,'post_pilot_target':16,'local_core_reserved':2,'visible_process_limit_exclusive':128,
                'scientific_changes':False,'dispatch_entry':str(FROZEN_ENTRY),'resume':'Existing results, dispatch and supervisor identities preserved; no retry of unknown attempts'}
            atomic(root/'operational-coordinator-ops2.json',lineage)
            queue(root,plan)
if __name__=='__main__':main()
