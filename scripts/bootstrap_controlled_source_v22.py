"""Node-local reader/runtime lifecycle for one controlled method, fixed16."""
import argparse
import json
import os
from pathlib import Path
import socket
import sys

from lab import ROOT, python_for, read_env
import bootstrap_mmbc100_cci as base
from bootstrap_bc_retry1 import (compare_runtime, digest, local_git_wrapper,
    reject_cloud_dotenv, resource_snapshot, runtime_snapshot)
from provision_controlled_source_v22 import DEFAULT, METHODS, OUT, require, read, sha


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, default=DEFAULT); p.add_argument('--method', choices=METHODS, required=True)
    p.add_argument('--concurrency', type=int, default=16); p.add_argument('--live', action='store_true')
    p.add_argument('--telemetry-watch', action='store_true'); args = p.parse_args()
    args.root = args.root.resolve(); args.scale = args.method
    require(args.root == DEFAULT.resolve() and args.concurrency == 16, 'One authorized method /16 workers')
    base.ROLE_SCRIPTS = {'controlled_mmbc_source_v22.py': 'controlled_controller_or_worker'}
    if args.telemetry_watch: base.telemetry_watch(args.root, args.method); return
    from controlled_mmbc_source_v22 import validate_plan
    plan = read(args.root / 'plan.json'); validate_plan(args.root, plan)
    receipt = read(OUT / ('acl-controlled22-' + args.method) / 'prepared.json')
    require(receipt['plan_sha256'] == sha(args.root / 'plan.json'), 'Plan changed after provisioning')
    for path, digest_ in receipt['runtime_sources_sha256'].items(): require(sha(path) == digest_, 'Runtime changed after provisioning')
    if not args.live:
        print(json.dumps({'method': args.method, 'concurrency': 16, 'paid_calls': 0, 'cloud_mutations': 0})); return
    binding = read(OUT / ('acl-controlled22-' + args.method) / 'binding.json')
    require(socket.gethostname().startswith('app-' + binding['uid'] + '-'), 'Unexpected cloud node UID')
    reject_cloud_dotenv()
    env = base.research_environment(os.environ, read_env(ROOT / '.env'))
    boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip(); local = local_git_wrapper(env, boot)
    os.environ.clear(); os.environ.update(env)
    if not (ROOT / 'hermes-agent/.venv/bin/python').exists():
        from cloud_python_stage import restore
        restore(read(ROOT / 'configs/cloud-python-stage-v3.json'))
    actual = runtime_snapshot(env, '/opt/conda/bin/python')
    compare_runtime(actual, read(ROOT / 'configs/cloud-runtime-v3.json'))
    capacity = resource_snapshot(); require(capacity['minimum_capacity_passed'], 'Requires8CPU/32GiB')
    config = plan.get('runtime_config_path') or next(j['config_path'] for j in plan['jobs'] if j.get('config_path'))
    commands = {
        'reader': ['/opt/conda/bin/python', str(ROOT / 'scripts/local_reader_text_service.py'), '--config', str(base.READER_CONFIG)],
        'web_preflight': [sys.executable, str(ROOT / 'scripts/preflight_bc_v3_web.py'), '--root', str(args.root), '--config', config],
        'telemetry': [sys.executable, str(Path(__file__).resolve()), '--root', str(args.root), '--method', args.method, '--telemetry-watch'],
        'controller': [python_for(ROOT), str(ROOT / 'scripts/controlled_mmbc_source_v22.py'), '--root', str(args.root),
                       '--method', args.method, '--concurrency', '16', '--live'],
    }
    runtime = {'version': 'controlled-source-bootstrap-v22', 'hostname': socket.gethostname(), 'boot_id': boot,
               'pid_namespace': os.readlink('/proc/self/ns/pid'), 'method': args.method, 'strategy': args.method,
               'campaign_root': str(args.root), 'plan_sha256': sha(args.root / 'plan.json'),
               'bootstrap_sha256': sha(__file__), 'runtime': actual, 'resources': capacity,
               'commands': commands, 'model_calls_before_controller': 0}
    raise SystemExit(base.serve(args, runtime, env, local))


if __name__ == '__main__': main()
