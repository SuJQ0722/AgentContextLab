#!/usr/bin/env python3
"""Independent inline retry cells: one16-worker CCI each, no global cap."""
import argparse
import json
import os
from pathlib import Path
import socket
import sys
import time

import bootstrap_mmbc100_cci as base
from bootstrap_bc_retry1 import (ROOT, compare_runtime, digest, local_git_wrapper,
    read_env, reject_cloud_dotenv, resource_snapshot, runtime_snapshot)
DEFAULT_ROOT = ROOT/'outputs/campaigns/visual-hosted-failure-retry-v1/cells/seven-page-retry3-v10'
HARNESSES = ('hermes','dsh')
def load_validate(root):
    from prepare_visual_hosted_retry_v1 import load_validate as validate
    plan,manifest=validate(root)
    if any(j.get('timeout_seconds') != 3600 for j in plan['jobs']):raise ValueError('Every V10 attempt must retain the authorized 3600s deadline')
    if plan['definition'].get('one_hour_retry_version')!='visual-inline-seven-page-retry3-v10':raise ValueError('Wrong retry protocol')
    from one_hour_timeout_retry_v10 import validate as contract
    for job in plan['jobs']:
        contract(job, json.loads(Path(job['config_path']).read_text()))
    return plan,manifest

VERSION = 'seven-page-retry3-bootstrap-v10'
ROLES = {'run_seven_transport_v10.py': 'controller',
         'run_seven_retry3_trial_v10.py': 'trial', 'hermes_visual_inline_retry_worker_v4.py': 'worker', 'controlled_visual_inline_worker_v5.py':'worker', 'dsh_retry3_worker_v10.py': 'worker','dsh_baseline_inline_worker_v8.py':'worker','hermes_baseline_retry3_v10.py':'worker'}


def commands(args):
    return {
        'reader': [args.reader_python, str(ROOT/'scripts/local_reader_text_service.py'), '--config', str(base.READER_CONFIG)],
        'web_preflight': [sys.executable, str(ROOT/'scripts/preflight_bc_v3_web.py'), '--root', str(args.root), '--config', str(args.root/'experiment.json')],
        'telemetry': [sys.executable, str(Path(__file__).resolve()), '--root', str(args.root), '--harness', args.harness, '--telemetry-watch'],
        'controller': [sys.executable, str(ROOT/'scripts/run_seven_transport_v10.py'), '--root', str(args.root), '--harness', args.harness, '--concurrency', '16', '--resume', '--live'],
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, default=DEFAULT_ROOT)
    p.add_argument('--harness', choices=HARNESSES, required=True)
    p.add_argument('--concurrency', type=int, default=16)
    p.add_argument('--reader-python', default=sys.executable)
    p.add_argument('--runtime-reference', type=Path, default=ROOT/'configs/cloud-runtime-v3.json')
    p.add_argument('--python-stage-manifest', type=Path, default=ROOT/'configs/cloud-python-stage-v3.json')
    mode = p.add_mutually_exclusive_group()
    for name in ('live', 'check', 'dry', 'telemetry-watch'):
        mode.add_argument('--'+name, action='store_true')
    args = p.parse_args(); args.root = args.root.resolve(); args.scale = args.harness
    if args.concurrency != 16: p.error('Each CCI is exactly16 workers')
    if args.root.parent != (DEFAULT_ROOT/'cells').resolve(): p.error('Only independent hosted cell roots permitted')
    base.ROLE_SCRIPTS = ROLES
    if args.telemetry_watch:
        base.telemetry_watch(args.root, args.scale); return
    plan = {'version': VERSION, 'mode': 'live' if args.live else 'check' if args.check else 'dry',
            'strategy': args.scale, 'harness': args.harness, 'campaign_root': str(args.root), 'commands': commands(args),
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
                    'bootstrap_seven_retry3_v10.py', 'run_seven_transport_v10.py', 'preflight_dsh_transport_v6.py', 'preflight_dsh_hosted_dispatcher_v4.mjs', 'bootstrap_mmbc100_cci.py',
                    'bootstrap_bc_retry1.py', 'monitor_bc_v3_node.py', 'cloud_python_stage.py', 'warm_visual_inline_worker_v7.py')})
    if args.check: print(json.dumps(plan, indent=2)); return
    if not resources['minimum_capacity_passed']: raise RuntimeError('Requires8CPU/32GiB node capacity')
    # Existing service lifecycle provides Reader preflight, node lock, telemetry,
    # health-triggered dispatch stop and natural child drain. No source mutation.
    checked=base.checked
    def retry_readiness(argv,*pos,**kw):
        is_web=any(str(x).endswith('preflight_bc_v3_web.py')for x in argv)
        for attempt in range(1,6):
            try:
                result=checked(argv,*pos,**kw)
                break
            except Exception:
                if not is_web or attempt==5:raise
                time.sleep(3)
        if is_web and any(j['harness']=='dsh' for j in load_validate(args.root)[0]['jobs']):
            from preflight_dsh_transport_v6 import check as node_check
            node_check(args.root)
        if is_web:
            from warm_visual_inline_worker_v7 import warm
            for harness in sorted({j['harness'] for j in load_validate(args.root)[0]['jobs']}):warm(args.root,harness)
        return result
    base.checked=retry_readiness
    try:raise SystemExit(base.serve(args, plan, env, local))
    finally:base.checked=checked


if __name__ == '__main__': main()
