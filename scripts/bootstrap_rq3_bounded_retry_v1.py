#!/usr/bin/env python3
"""Seven bounded RQ3 scales, one16-worker CCI each."""
import argparse
import json
import os
from pathlib import Path
import socket
import sys

import bootstrap_mmbc100_cci as base
from bootstrap_bc_retry1 import (ROOT, compare_runtime, digest, local_git_wrapper,
    read_env, reject_cloud_dotenv, resource_snapshot, runtime_snapshot)
DEFAULT_ROOT = ROOT/'outputs/campaigns/rq3-bounded-failure-retry-v1'
SCALE_KEYS = ('scale_0000','scale_0250','scale_0500','scale_0700','scale_0750','scale_0800','scale_1000')
def load_validate(root):
    from prepare_rq3_bounded_retry_v1 import load_validate as validate
    return validate(root)

VERSION = 'rq3-bounded-retry-bootstrap-v1'
ROLES = {'run_rq3_bounded_retry_v1.py': 'controller',
         'run_rq3_bounded_trial_v1.py': 'trial', 'hermes_bounded_rq3_worker_v1.py': 'worker'}


def commands(args):
    return {
        'reader': [args.reader_python, str(ROOT/'scripts/local_reader_text_service.py'), '--config', str(base.READER_CONFIG)],
        'web_preflight': [sys.executable, str(ROOT/'scripts/preflight_bc_v3_web.py'), '--root', str(args.root), '--config', str(args.root/'experiment.json')],
        'telemetry': [sys.executable, str(Path(__file__).resolve()), '--root', str(args.root), '--scale-key', args.scale_key, '--telemetry-watch'],
        'controller': [sys.executable, str(ROOT/'scripts/run_rq3_bounded_retry_v1.py'), '--root', str(args.root), '--scale-key', args.scale_key, '--concurrency', '16', '--resume', '--live'],
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, default=DEFAULT_ROOT)
    p.add_argument('--scale-key', choices=SCALE_KEYS, required=True)
    p.add_argument('--concurrency', type=int, default=16)
    p.add_argument('--reader-python', default=sys.executable)
    p.add_argument('--runtime-reference', type=Path, default=ROOT/'configs/cloud-runtime-v3.json')
    p.add_argument('--python-stage-manifest', type=Path, default=ROOT/'configs/cloud-python-stage-v3.json')
    mode = p.add_mutually_exclusive_group()
    for name in ('live', 'check', 'dry', 'telemetry-watch'):
        mode.add_argument('--'+name, action='store_true')
    args = p.parse_args(); args.root = args.root.resolve(); args.scale = args.scale_key
    if args.concurrency != 16: p.error('Each CCI is exactly16 workers')
    if args.root != DEFAULT_ROOT.resolve(): p.error('Only the independent bounded retry root is permitted')
    base.ROLE_SCRIPTS = ROLES
    if args.telemetry_watch:
        base.telemetry_watch(args.root, args.scale); return
    plan = {'version': VERSION, 'mode': 'live' if args.live else 'check' if args.check else 'dry',
            'strategy': args.scale, 'scale_key': args.scale_key, 'campaign_root': str(args.root), 'commands': commands(args),
            'required_cloud_allocation': {'cpu': 8, 'memory_gib': 32, 'workers': 16},
            'bootstrap_sha256': digest(__file__), 'bootstrap_validation_model_calls': 0,
            'reader_deployment_config': str(base.READER_CONFIG), 'reader_deployment_sha256': digest(base.READER_CONFIG)}
    if not (args.live or args.check): print(json.dumps(plan, indent=2)); return
    reject_cloud_dotenv(); env = base.research_environment(os.environ, read_env(ROOT/'.env'))
    boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip(); local = local_git_wrapper(env, boot)
    from replace_bc_v3_reader import proxy_summary
    plan.update(hostname=socket.gethostname(), boot_id=boot, pid_namespace=os.readlink('/proc/self/ns/pid'), reader_egress_proxy=proxy_summary(env))
    os.environ.clear(); os.environ.update(env)
    if args.live and not (ROOT/'hermes-agent/.venv/bin/python').exists():
        from cloud_python_stage import restore
        restore(json.loads(args.python_stage_manifest.read_text()))
    actual = runtime_snapshot(env, args.reader_python)
    compare_runtime(actual, json.loads(args.runtime_reference.read_text()))
    load_validate(args.root)
    resources = resource_snapshot()
    plan.update(runtime=actual, resources=resources, plan_sha256=digest(args.root/'plan.json'), validated=True,
                operational_implementation_sha256={n: digest(ROOT/'scripts'/n) for n in (
                    'bootstrap_rq3_bounded_retry_v1.py', 'bootstrap_mmbc100_cci.py',
                    'bootstrap_bc_retry1.py', 'monitor_bc_v3_node.py', 'cloud_python_stage.py')})
    if args.check: print(json.dumps(plan, indent=2)); return
    if not resources['minimum_capacity_passed']: raise RuntimeError('Requires8CPU/32GiB node capacity')
    # Existing service lifecycle provides Reader preflight, node lock, telemetry,
    # health-triggered dispatch stop and natural child drain. No source mutation.
    raise SystemExit(base.serve(args, plan, env, local))


if __name__ == '__main__': main()
