#!/usr/bin/env python3
"""One SCO BC core cell: inspect by default, or explicitly run the reviewed queue.

Does not create cloud resources, install packages, edit harness code or retry jobs.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from lab import python_for, read_env, runtime_path
from run_bc_campaign_v3 import validate_sources

BASE_ENV = {'PATH', 'HOME', 'USER', 'LOGNAME', 'SHELL', 'LANG', 'LC_ALL', 'LC_CTYPE', 'TZ',
            'TMPDIR', 'TMP', 'TEMP', 'LD_LIBRARY_PATH', 'SSL_CERT_FILE', 'SSL_CERT_DIR',
            'REQUESTS_CA_BUNDLE', 'CURL_CA_BUNDLE', 'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY',
            'NO_PROXY', 'http_proxy', 'https_proxy', 'all_proxy', 'no_proxy'}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def clean_environment(source):
    # Model credentials are loaded by the existing launchers from the existing
    # research dotenv files. SCO credentials/SSH agents are never inherited.
    env = {k: v for k, v in source.items() if k in BASE_ENV}
    env.update(PYTHONUNBUFFERED='1', GIT_OPTIONAL_LOCKS='0', OMP_NUM_THREADS='1',
               OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1', NUMEXPR_NUM_THREADS='1')
    env['NO_PROXY'] = env['no_proxy'] = ','.join(filter(None, [env.get('NO_PROXY', ''), '127.0.0.1', 'localhost', '::1']))
    return env


def reject_cloud_dotenv():
    for relative in ('.env', 'hermes-agent/.env', 'hermes-agent/.env.local', 'deepseekHarness/.env'):
        for name in read_env(ROOT / relative):
            upper = name.upper()
            if upper.startswith(('SCO_', 'AWS_', 'AZURE_', 'CLOUD_', 'SENSETIME_')) or upper in {
                'AK', 'SK', 'ACCESS_KEY_ID', 'ACCESS_KEY_SECRET', 'SECRET_ACCESS_KEY', 'GOOGLE_APPLICATION_CREDENTIALS'}:
                raise RuntimeError('Cloud credential variable present in a research dotenv; separate cloud provisioning credentials before running')


def atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    tmp.write_text(json.dumps(value, indent=2) + '\n')
    tmp.replace(path)


def checked(command, env, timeout=90):
    result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError('Offline runtime command failed: ' + Path(command[0]).name)
    return result.stdout.strip()


def runtime_snapshot(env, reader_python):
    interpreter = Path(python_for(ROOT))
    if not interpreter.exists():
        raise RuntimeError('Shared Hermes venv interpreter symlink is unavailable in this image')
    code = '''import json,sys,hashlib,importlib.metadata
from pathlib import Path
sys.path.insert(0,str(Path.cwd()/"hermes-agent"))
from plugins.context_engine.visual import render
from reportlab.pdfbase import pdfmetrics
name=render._resolve_and_register_font(None)
font=getattr(pdfmetrics.getFont(name).face,"filename",None)
if isinstance(font,bytes):font=font.decode()
print(json.dumps({"python_version":sys.version.split()[0],"python_executable":sys.executable,
"python_resolved":str(Path(sys.executable).resolve()),
"packages":{p:importlib.metadata.version(p) for p in ["openai","Pillow","reportlab"]},
"font_name":name,"font_path":font,"font_sha256":hashlib.sha256(Path(font).read_bytes()).hexdigest() if font else None}))'''
    python = json.loads(checked([str(interpreter), '-c', code], env))
    node = ROOT / '.tools/node-v24.11.0-linux-x64/bin/node'
    version = checked([str(node), '--version'], env)
    if version != 'v24.11.0':
        raise RuntimeError('Expected the shared Node v24.11.0 runtime')
    reader_cfg = ROOT / 'configs/reader-text-v1.json'
    config = json.loads(reader_cfg.read_text())
    if config['host'] != '127.0.0.1' or config['port'] != 18080:
        raise RuntimeError('Expected loopback Reader 127.0.0.1:18080')
    if digest(config['source_path']) != config['source_sha256']:
        raise RuntimeError('Pinned Reader source changed or is inaccessible')
    reader_code = '''import importlib,importlib.metadata,json,sys
from pathlib import Path
cfg=json.loads(Path(sys.argv[1]).read_text());sys.path.insert(0,str(Path(cfg["source_path"]).parent))
for name in ("httpx","tiktoken","trafilatura","uvicorn","yaml","fastapi","pydantic","fetch_url_package"):importlib.import_module(name)
print(json.dumps({"python_version":sys.version.split()[0],"dependencies_imported":True,
"packages":{p:importlib.metadata.version(p) for p in ["httpx","tiktoken","trafilatura","uvicorn","fastapi","pydantic"]}}))'''
    reader = json.loads(checked([reader_python, '-c', reader_code, str(reader_cfg)], env))
    # Execute the actual bundled tools, so missing native libraries fail here.
    poppler = {}
    for binary in ('pdfinfo', 'pdftoppm', 'pdftocairo'):
        path = ROOT / '.tools/poppler/usr/bin' / binary
        checked([str(path), '-v'], env)
        poppler[binary] = digest(path)
    return {'hermes': python, 'node_version': version, 'node_sha256': digest(node),
            'poppler_sha256': poppler, 'reader': reader, 'reader_source_sha256': config['source_sha256']}


def compare_runtime(actual, expected):
    fields = [('node_version',), ('node_sha256',), ('poppler_sha256',), ('reader_source_sha256',),
              ('hermes', 'python_version'), ('hermes', 'packages'), ('hermes', 'font_sha256'),
              ('reader', 'python_version'), ('reader', 'packages')]
    for path in fields:
        a, b = actual, expected
        for key in path:
            a, b = a[key], b[key]
        if a != b:
            raise RuntimeError('Runtime differs from reviewed reference: ' + '.'.join(path))
    if not actual['hermes']['font_sha256']:
        raise RuntimeError('A resolved and hashed font is required; built-in font fallback is not accepted')


def resource_snapshot():
    cpus = float(len(os.sched_getaffinity(0)))
    memory = int(next(line.split()[1] for line in Path('/proc/meminfo').read_text().splitlines()
                      if line.startswith('MemTotal:'))) * 1024
    group = Path('/sys/fs/cgroup')
    if (group/'cpu.max').exists():
        quota, period = (group/'cpu.max').read_text().split()
        if quota != 'max':cpus = min(cpus, int(quota)/int(period))
    if (group/'memory.max').exists():
        limit = (group/'memory.max').read_text().strip()
        if limit != 'max':memory = min(memory, int(limit))
    return {'cpu_capacity': cpus, 'memory_limit_gib': memory/(1024**3),
            'pids_limit': (group/'pids.max').read_text().strip() if (group/'pids.max').exists() else None,
            'minimum_capacity_passed': cpus >= 7.99 and memory >= 30*(1024**3),
            'note':'Checks capacity, not current free memory. Requested SCO allocation remains 8 CPU / 32 GiB; 32 workers include additional child processes/threads.'}


def local_git_wrapper(env, boot):
    # /tmp is node-local. No shared-AFS lock serializes git across machines.
    directory = Path('/tmp') / ('acl-bc-v3-runtime-' + str(os.getuid()) + '-' + boot)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    wrapper = directory / 'git'
    wrapper.write_text('#!/bin/sh\nfor arg do\n  if [ "$arg" = diff ]; then\n'
                       '    exec /usr/bin/flock -x /tmp/agentcontextlab-v3-git-diff.lock /usr/bin/git -c core.preloadIndex=false "$@"\n'
                       '  fi\ndone\nexec /usr/bin/git "$@"\n')
    wrapper.chmod(0o700)
    env['PATH'] = str(directory) + os.pathsep + runtime_path(ROOT)
    lib = ROOT / '.tools/poppler/usr/lib/x86_64-linux-gnu'
    env['LD_LIBRARY_PATH'] = str(lib) + os.pathsep + env.get('LD_LIBRARY_PATH', '')
    return directory


def health(expected):
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open('http://127.0.0.1:18080/health', timeout=2) as response:
            value = json.load(response)
        return value.get('status') == 'ok' and value.get('source_sha256') == expected and value.get('mode') == 'text' and value.get('model_inference') is False
    except Exception:
        return False


def commands(args):
    return {'reader': [args.reader_python, str(ROOT/'scripts/local_reader_text_service.py'), '--config', str(ROOT/'configs/reader-text-v1-workers32.json')],
            'telemetry': [sys.executable,str(ROOT/'scripts/monitor_bc_v3_node.py'),'--watch','--root',str(args.root)],
            'web_preflight': [sys.executable, str(ROOT/'scripts/preflight_bc_v3_web.py'), '--root', str(args.root)],
            'controller': [sys.executable, str(ROOT/('scripts/run_bc_campaign_v3_capacity1.py' if args.harness=='dsh' or args.strategy=='visual' else 'scripts/run_bc_campaign_v3_io2.py')), '--root', str(args.root),
                           '--config', str(args.root/'experiment.json'), '--harness', args.harness, '--strategy', args.strategy,
                           '--concurrency', str(getattr(args,'controller_concurrency',32)), '--resume', '--live']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--harness', required=True, choices=['hermes','dsh'])
    parser.add_argument('--strategy', required=True, choices=['none','summarize','sliding_window','discard','visual'])
    parser.add_argument('--root', type=Path, default=ROOT/'outputs/campaigns/bc100-r3-hermes-parity-v3')
    parser.add_argument('--runtime-reference', type=Path, default=ROOT/'configs/cloud-runtime-v3.json')
    parser.add_argument('--reader-python', default=sys.executable)
    parser.add_argument('--python-stage-manifest',type=Path,default=ROOT/'configs/cloud-python-stage-v3.json')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--live', action='store_true')
    mode.add_argument('--check', action='store_true', help='Hash/import checks only, no network or service/model start')
    mode.add_argument('--capture-runtime-reference', type=Path, help='Offline reference capture; never launches services/models')
    args = parser.parse_args();args.root=args.root.resolve()
    dispatch=json.loads((ROOT/'configs/cloud-dispatch-ops-v2.json').read_text())
    args.controller_concurrency=dispatch['active_workers_per_cloud_instance']
    if not 1 <= args.controller_concurrency <= 32:raise ValueError('Operational dispatch must stay within approved worker ceiling')
    plan = {'mode':'live' if args.live else 'offline_check' if args.check else 'capture_reference' if args.capture_runtime_reference else 'dry_run',
            'cell':args.harness+'/'+args.strategy,'operational_dispatch':dispatch,'required_cloud_allocation':{'cpu':8,'memory_gib':32,'workers':32},
            'mount':'/mnt/afs_agents','repository':str(ROOT),'commands':commands(args),
            'credential_policy':'Provisioning credentials never inherited; research launchers load existing research dotenv only.',
            'git_policy':'Only per-node /tmp git diff lock; no cross-host git lock.',
            'reader_deployment_config':'configs/reader-text-v1-workers32.json',
            'reader_deployment_sha256':digest(ROOT/'configs/reader-text-v1-workers32.json'),
            'network_deployment':'Use explicitly configured research dotenv proxy variables only; provisioning credentials remain excluded.'}
    if not (args.live or args.check or args.capture_runtime_reference):
        print(json.dumps(plan,indent=2));return
    if not ROOT.resolve().is_relative_to(Path('/mnt/afs_agents')):
        raise RuntimeError('Repository must be on the reviewed AFS mount')
    reject_cloud_dotenv()
    env=clean_environment(os.environ)
    network_keys={'http_proxy','https_proxy','no_proxy','HTTP_PROXY','HTTPS_PROXY','NO_PROXY'}
    env.update({key:value for key,value in read_env(ROOT/'.env').items() if key in network_keys})
    boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    from replace_bc_v3_reader import proxy_summary
    plan.update(reader_egress_proxy=proxy_summary(env),hostname=socket.gethostname(),
                boot_id=boot,pid_namespace=os.readlink('/proc/self/ns/pid'))
    local=local_git_wrapper(env,boot)
    # Also protect descendants spawned by validate_sources and Python imports.
    os.environ.clear();os.environ.update(env)
    if args.live and not Path(ROOT/'hermes-agent/.venv/bin/python').exists():
        from cloud_python_stage import restore
        restore(json.loads(args.python_stage_manifest.read_text()))
    actual=runtime_snapshot(env,args.reader_python)
    if args.capture_runtime_reference:
        atomic(args.capture_runtime_reference,actual);print(json.dumps({'captured':str(args.capture_runtime_reference),'model_calls':0}));return
    compare_runtime(actual,json.loads(args.runtime_reference.read_text()))
    scientific=json.loads((args.root/'plan.json').read_text());validate_sources(scientific,args.root)
    plan.update(runtime=actual,resources=resource_snapshot(),plan_sha256=digest(args.root/'plan.json'),
                validated=True,bootstrap_validation_model_calls=0)
    if args.check:
        print(json.dumps(plan,indent=2));return
    if args.root.name!='bc100-r3-hermes-parity-v3':
        raise RuntimeError('Cloud bootstrap is restricted to the reviewed new core campaign')
    if not plan['resources']['minimum_capacity_passed']:
        raise RuntimeError('Insufficient CPU/memory capacity for the reviewed 8 CPU / 32 GiB node')
    host=socket.gethostname()+'-'+boot
    state=args.root/'runtime/nodes'/host/(args.harness+'-'+args.strategy);state.mkdir(parents=True,exist_ok=True)
    # One core cell per instance; a second local cell must not double the
    # reviewed 32-worker resource allocation.
    # Keep prior container epochs when ACP restarts the same job/hostname.
    if (state/'bootstrap.json').exists():
        previous=json.loads((state/'bootstrap.json').read_text())
        epoch=state/'epochs'/str(previous.get('started_at_unix',time.time()))
        epoch.mkdir(parents=True,exist_ok=True)
        for name in ('bootstrap.json','exit.json','reader-failure.json'):
            if (state/name).exists():
                (epoch/name).write_bytes((state/name).read_bytes())
                if name != 'bootstrap.json':(state/name).unlink()
    lock=(local/'core-cell-bootstrap.lock').open('a')
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    stopping=False;controller=None;reader=None;telemetry=None
    def stop(*unused):
        nonlocal stopping
        stopping=True
        if controller and controller.poll() is None:controller.send_signal(signal.SIGTERM)
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    owned_reader=False
    try:
        if not health(actual['reader_source_sha256']):
            with (state/'reader.log').open('a') as log:
                reader=subprocess.Popen(plan['commands']['reader'],cwd=ROOT,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            owned_reader=True
            until=time.monotonic()+90
            while not health(actual['reader_source_sha256']):
                if stopping or reader.poll() is not None or time.monotonic()>until:
                    raise RuntimeError('Pinned local text Reader did not become ready')
                time.sleep(.5)
        if stopping:raise InterruptedError('Stopped before web preflight')
        checked(plan['commands']['web_preflight'],env,timeout=180)
        if stopping:raise InterruptedError('Stopped before controller dispatch')
        with (state/'telemetry.log').open('a') as log:
            telemetry=subprocess.Popen(plan['commands']['telemetry'],cwd=ROOT,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        with (state/'controller.log').open('a') as log:
            controller=subprocess.Popen(plan['commands']['controller'],cwd=ROOT,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        atomic(state/'bootstrap.json',{**plan,'reader_owned':owned_reader,'reader_pid':reader.pid if reader else None,
                                      'controller_pid':controller.pid,'telemetry_pid':telemetry.pid,'started_at_unix':time.time()})
        last_health=time.monotonic()
        while controller.poll() is None:
            reader_failed=reader is not None and reader.poll() is not None
            if time.monotonic()-last_health>15:
                reader_failed=reader_failed or not health(actual['reader_source_sha256']);last_health=time.monotonic()
            if reader_failed and not stopping:
                stop();atomic(state/'reader-failure.json',{'time':time.time(),'action':'stop dispatch and drain; no model retries'})
            time.sleep(1)
        atomic(state/'exit.json',{'controller_exit_code':controller.returncode,'stopped':stopping,'finished_at_unix':time.time()})
        raise SystemExit(controller.returncode)
    finally:
        # Controller SIGTERM drains active immutable trials. Keep Reader alive
        # until they finish; hard platform termination remains a recorded unknown.
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


if __name__=='__main__':main()
