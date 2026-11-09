#!/usr/bin/env python3
"""Only authorized unclaimed .7 predictions in a successor CCI; frozen native science."""
import argparse
from collections import Counter
import fcntl
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time

from bootstrap_bc_retry1 import (ROOT, atomic, checked, clean_environment, compare_runtime,
    digest, health, local_git_wrapper, read_env, reject_cloud_dotenv, resource_snapshot, runtime_snapshot)
from monitor_bc_v3_node import cgroup_snapshot

DEFAULT_ROOT = ROOT/'outputs/campaigns/rq3-deepseek-bc100-r3-parity-v3'
READER_CONFIG = ROOT/'configs/reader-text-v1-workers32.json'
ROLE_SCRIPTS = {
    'run_rq3_scale0700_resume_ops5.py': 'controller',
    'run_rq3_parity_trial.py': 'trial',
    'rq3_hermes_parity_worker.py': 'worker',
}


def normalize_scale(value):
    from run_rq3_scale_cloud_ops2 import normalize_scale as canonical
    return canonical(value)


def scientific_validation(root):
    from run_rq3_parity_v3 import validate
    plan = json.loads((root/'plan.json').read_text())
    validate(plan, root)
    return plan


def research_environment(source, dotenv):
    env = clean_environment(source)
    keys = {'http_proxy', 'https_proxy', 'no_proxy', 'HTTP_PROXY', 'HTTPS_PROXY', 'NO_PROXY'}
    env.update({key:value for key,value in dotenv.items() if key in keys})
    bypass = ','.join(filter(None, [env.get('NO_PROXY', ''), env.get('no_proxy', ''), '127.0.0.1', 'localhost', '::1']))
    env['NO_PROXY'] = env['no_proxy'] = bypass
    return env


def commands(args):
    return {
        'reader': [args.reader_python, str(ROOT/'scripts/local_reader_text_service.py'), '--config', str(READER_CONFIG)],
        'web_preflight': [sys.executable, str(ROOT/'scripts/preflight_bc_v3_web.py'), '--root', str(args.root), '--config', str(args.root/'experiment.json')],
        'telemetry': [sys.executable, str(Path(__file__).resolve()), '--root', str(args.root), '--authorization', str(args.authorization), '--telemetry-watch'],
        'controller': [sys.executable, str(ROOT/'scripts/run_rq3_scale0700_resume_ops5.py'), '--root', str(args.root), '--authorization', str(args.authorization),
                       '--concurrency', '16', '--resume', '--live'],
    }


def resource_telemetry(root, scale):
    """Do not reuse core role totals: classify only this RQ3 root's own argv."""
    roles = Counter(); visible = Counter(); unreadable = 0
    for directory in Path('/proc').iterdir():
        if not directory.name.isdigit():continue
        try:
            state = (directory/'stat').read_text().split(') ', 1)[1].split()[0]
            visible['total'] += 1; visible['zombie' if state == 'Z' else 'live'] += 1
            if state == 'Z':continue
            argv = (directory/'cmdline').read_bytes().split(b'\0')
            if not any(str(root).encode() in arg for arg in argv):continue
            for arg in argv:
                if b' ' in arg or b'\n' in arg:continue
                role = ROLE_SCRIPTS.get(Path(os.fsdecode(arg)).name)
                if role:roles[role] += 1;break
        except (OSError,IndexError):unreadable += 1
    return {'version':'rq3-scale-node-telemetry-ops2','observed_at_unix':time.time(),'hostname':socket.gethostname(),
            'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'pid_namespace':os.readlink('/proc/self/ns/pid'),
            'campaign_root':str(root),'scale_label':scale,'observer_pid':os.getpid(),
            'processes':{'visible_total':visible['total'],'visible_live':visible['live'],'visible_zombie':visible['zombie'],
                         'rq3_roles':dict(roles),'unreadable_processes':unreadable},'cgroup':cgroup_snapshot(),
            'note':'Node-local OS process counts. RQ3 roles require this root in argv; no core-role counts reused. Role counts exclude renderer descendants and are not model HTTP concurrency.',
            'paid_model_calls':0}


def telemetry_watch(root, scale):
    boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    target=root/'runtime/nodes'/(socket.gethostname()+'-'+boot)/'telemetry.json'
    running=True
    def stop(*unused):
        nonlocal running
        running=False
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    while running:
        atomic(target,resource_telemetry(root,scale))
        until=time.monotonic()+30
        while running and time.monotonic()<until:time.sleep(.5)


def serve(args, plan, env, local):
    state=args.root/'runtime/nodes'/(plan['hostname']+'-'+plan['boot_id'])/args.scale
    state.mkdir(parents=True,exist_ok=True)
    # Shared node-local cell lock also excludes accidentally co-located core cells.
    lock=(local/'core-cell-bootstrap.lock').open('a')
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    if (state/'bootstrap.json').exists():
        previous=json.loads((state/'bootstrap.json').read_text());epoch=state/'epochs'/str(previous.get('started_at_unix',time.time()))
        epoch.mkdir(parents=True,exist_ok=True)
        for name in ('bootstrap.json','exit.json','reader-failure.json'):
            if (state/name).exists():(epoch/name).write_bytes((state/name).read_bytes());(state/name).unlink()
    stopping=False;controller=None;reader=None;telemetry=None;owned_reader=False;error=None;exit_code=None
    def stop(*unused):
        nonlocal stopping
        stopping=True
        if controller and controller.poll() is None:controller.send_signal(signal.SIGTERM)
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    def spawn(name):
        with (state/(name+'.log')).open('a') as log:
            return subprocess.Popen(plan['commands'][name],cwd=ROOT,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    atomic(state/'bootstrap.json',{**plan,'bootstrap_pid':os.getpid(),'started_at_unix':time.time(),'state':'starting_services'})
    try:
        if not health(plan['runtime']['reader_source_sha256']):
            reader=spawn('reader');owned_reader=True;until=time.monotonic()+90
            while not health(plan['runtime']['reader_source_sha256']):
                if stopping or reader.poll() is not None or time.monotonic()>until:raise RuntimeError('Pinned loopback Reader unavailable')
                time.sleep(.5)
        if stopping:raise InterruptedError('Stopped before web preflight')
        checked(plan['commands']['web_preflight'],env,timeout=180)
        if stopping:raise InterruptedError('Stopped before RQ3 dispatch')
        telemetry=spawn('telemetry');controller=spawn('controller')
        saved=json.loads((state/'bootstrap.json').read_text())
        atomic(state/'bootstrap.json',{**saved,'state':'controller_started','reader_owned':owned_reader,'reader_pid':reader.pid if reader else None,
                                      'controller_pid':controller.pid,'telemetry_pid':telemetry.pid})
        last_health=time.monotonic()
        while controller.poll() is None:
            failed=reader is not None and reader.poll() is not None
            if not stopping and time.monotonic()-last_health>=15:
                failed=failed or not health(plan['runtime']['reader_source_sha256']);last_health=time.monotonic()
            if failed and not stopping:
                stop();atomic(state/'reader-failure.json',{'at_unix':time.time(),'action':'SIGTERM controller to stop dispatch and naturally drain; no native signal or model retry'})
            time.sleep(.5)
        exit_code=controller.returncode
    except BaseException as exc:
        error=type(exc).__name__;exit_code=1
        raise
    finally:
        # Keep Reader and telemetry alive until controller's own drain completes.
        if controller and controller.poll() is None:
            controller.send_signal(signal.SIGTERM);controller.wait()
        if telemetry and telemetry.poll() is None:
            telemetry.terminate()
            try:telemetry.wait(timeout=5)
            except subprocess.TimeoutExpired:telemetry.kill();telemetry.wait()
        if owned_reader and reader and reader.poll() is None:
            os.killpg(reader.pid,signal.SIGTERM)
            try:reader.wait(timeout=15)
            except subprocess.TimeoutExpired:os.killpg(reader.pid,signal.SIGKILL);reader.wait()
        atomic(state/'exit.json',{'finished_at_unix':time.time(),'controller_exit_code':controller.returncode if controller else None,
              'bootstrap_exit_code':exit_code,'stop_dispatch_requested':stopping,'error_type':error,'reader_owned':owned_reader,
              'native_processes_signaled':False,'hostname':plan['hostname'],'boot_id':plan['boot_id'],'scale':args.scale})
        lock.close()
    return exit_code


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--scale',default='scale_0700',type=normalize_scale,choices=['scale_0700'])
    p.add_argument('--authorization',required=True,type=Path)
    p.add_argument('--root',type=Path,default=DEFAULT_ROOT)
    p.add_argument('--runtime-reference',type=Path,default=ROOT/'configs/cloud-runtime-v3.json')
    p.add_argument('--reader-python',default=sys.executable)
    p.add_argument('--python-stage-manifest',type=Path,default=ROOT/'configs/cloud-python-stage-v3.json')
    modes=p.add_mutually_exclusive_group();modes.add_argument('--live',action='store_true');modes.add_argument('--check',action='store_true');modes.add_argument('--dry',action='store_true');modes.add_argument('--telemetry-watch',action='store_true',help=argparse.SUPPRESS)
    args=p.parse_args();args.root=args.root.resolve();args.authorization=args.authorization.resolve()
    if args.telemetry_watch:telemetry_watch(args.root,args.scale);return
    plan={'version':'rq3-scale0700-bootstrap-ops5','mode':'live' if args.live else 'offline_check' if args.check else 'dry_run',
          'scale_label':args.scale,'campaign_root':str(args.root),'commands':commands(args),
          'required_cloud_allocation':{'cpu':8,'memory_gib':32,'workers':16},'mount':'/mnt/afs_agents','repository':str(ROOT),
          'bootstrap_sha256':digest(__file__),'reader_deployment_config':str(READER_CONFIG),'reader_deployment_sha256':digest(READER_CONFIG),
          'credential_policy':'Inherited provisioning credentials removed; existing research dotenv only. Proxy credentials never printed.',
          'git_policy':'Node-local git diff lock only; no cross-host shared git lock.','bootstrap_validation_model_calls':0}
    if not (args.live or args.check):print(json.dumps(plan,indent=2));return
    if not ROOT.resolve().is_relative_to(Path('/mnt/afs_agents')):raise RuntimeError('Expected reviewed AFS mount')
    if args.root!=DEFAULT_ROOT.resolve():raise RuntimeError('Restricted to the separately reviewed RQ3 campaign')
    reject_cloud_dotenv();env=research_environment(os.environ,read_env(ROOT/'.env'))
    boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip();local=local_git_wrapper(env,boot)
    from replace_bc_v3_reader import proxy_summary
    plan.update(hostname=socket.gethostname(),boot_id=boot,pid_namespace=os.readlink('/proc/self/ns/pid'),reader_egress_proxy=proxy_summary(env))
    os.environ.clear();os.environ.update(env)
    if args.live and not (ROOT/'hermes-agent/.venv/bin/python').exists():
        from cloud_python_stage import restore
        restore(json.loads(args.python_stage_manifest.read_text()))
    actual=runtime_snapshot(env,args.reader_python);compare_runtime(actual,json.loads(args.runtime_reference.read_text()))
    science=scientific_validation(args.root)
    resources=resource_snapshot();resources['note']='Checks8CPU/32GiB capacity; 16RQ3 trials plus native renderer descendants/threads, not16 OS processes.'
    plan.update(runtime=actual,resources=resources,plan_sha256=digest(args.root/'plan.json'),
                scientific_version=science['definition']['version'],controller_sha256=digest(ROOT/'scripts/run_rq3_scale0700_resume_ops5.py'),
                runtime_reference_path=str(args.runtime_reference),runtime_reference_sha256=digest(args.runtime_reference),
                operational_implementation_sha256={name:digest(ROOT/'scripts'/name) for name in ('bootstrap_rq3_scale0700_resume_ops5.py','run_rq3_scale0700_resume_ops5.py','bootstrap_rq3_scale_ops2.py','run_rq3_scale_cloud_ops2.py','bootstrap_bc_retry1.py','monitor_bc_v3_node.py','replace_bc_v3_reader.py','cloud_python_stage.py')},validated=True)
    if args.check:print(json.dumps(plan,indent=2));return
    if not plan['resources']['minimum_capacity_passed']:raise RuntimeError('Requires8CPU/32GiB node capacity')
    from run_rq3_scale0700_resume_ops5 import verify_authorization
    authorization=verify_authorization(args.root,args.authorization)
    plan['authorization_path']=str(args.authorization)
    plan['authorization_sha256']=digest(args.authorization)
    plan['authorized_unclaimed_predictions']=len(authorization['pending_job_ids'])
    plan['excluded_paid_interrupted_predictions']=len(authorization['excluded_paid_interrupted_job_ids'])
    plan['cutover_sha256']=digest(args.root/'cloud-scale-ops5/cutover.json')
    raise SystemExit(serve(args,plan,env,local))

if __name__=='__main__':main()
