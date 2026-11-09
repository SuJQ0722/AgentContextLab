#!/usr/bin/env python3
"""Resume only the explicitly authorized retry1 ledger, never replay a claim."""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
import uuid
from bc_retry1 import DEFAULT_ROOT, ROOT, load_ledger, publish_claim, sha
from bc_route_runtime_v1 import RoutePlan, immutable_json
from run_bc_campaign_v3 import atomic, identity, job_state, now, validate_sources
import run_bc_campaign_v3_routes1 as policies


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, default=DEFAULT_ROOT)
    p.add_argument('--harness', choices=['hermes', 'dsh'], nargs='+', default=['hermes', 'dsh'])
    p.add_argument('--strategy', nargs='+', default=['none', 'summarize', 'sliding_window', 'discard', 'visual'])
    p.add_argument('--dispatch-role', choices=['local', 'cloud'], required=True)
    p.add_argument('--dispatch-config', type=Path, default=ROOT / 'configs/cloud-dispatch-routes-v1.json')
    p.add_argument('--limit', type=int)
    p.add_argument('--live', action='store_true')
    args = p.parse_args()
    root = args.root.resolve()
    ledger = load_ledger(root)
    plan = json.loads((root / 'plan.json').read_text())
    ids = {e['job_id'] for e in ledger['entries']}
    selected = [j for j in plan['jobs'] if j['job_id'] in ids and j['harness'] in args.harness and j['strategy'] in args.strategy]
    if args.dispatch_role == 'cloud' and len({(j['harness'], j['strategy']) for j in selected}) != 1:
        raise ValueError('One cloud cell per instance required')
    routes = RoutePlan(root)
    policies.ROUTE_PLAN = routes
    if not args.live:
        print(json.dumps({'selected_jobs': len(selected), 'paid_calls': 0, 'root': str(root)}))
        return
    validate_sources(plan, root)
    from lab import environment
    from review_execution import enforce
    env, cfg = environment(ROOT, 'dsh', root / 'experiment.json')
    enforce(cfg, env, root)
    own = identity()
    readiness = json.loads((root / 'web-readiness' / (socket.gethostname() + '-' + own['boot_id'] + '.json')).read_text())
    if (readiness.get('passed') is not True or readiness.get('config_sha256') != sha(root / 'experiment.json')
            or readiness.get('hostname') != own['hostname'] or readiness.get('boot_id') != own['boot_id']
            or not 0 <= time.time() - readiness.get('checked_at_unix', 0) < 900):
        raise ValueError('Fresh exact-host real web readiness required')
    routes.bind()
    cid = own['hostname'] + '-' + uuid.uuid4().hex
    control = root / 'controllers' / cid
    control.mkdir(parents=True)
    atomic(control / 'owner.json', {**own, 'selection': {'harness': args.harness, 'strategy': args.strategy}})
    policy = policies.DispatchPolicy(args.dispatch_config, args.dispatch_role, control)
    children = {}
    child_routes = {}
    stopping = False
    failure = None
    launches = 0
    def stop(*unused):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        while True:
            stopping = stopping or (root / 'STOP').exists() or (ROOT / 'outputs/PAUSED_BY_USER.json').exists()
            for jid, child in list(children.items()):
                if child.poll() is not None:
                    children.pop(jid)
                    child_routes.pop(jid)
            states = {j['job_id']: job_state(root / 'jobs' / j['job_id']) for j in selected}
            decision = policy.refresh()
            by_route = Counter(child_routes.values())
            if not stopping and (args.limit is None or launches < args.limit):
                for job in policies.route_round_robin([j for j in selected if states[j['job_id']] == 'pending'], routes):
                    if not policies.can_dispatch(decision, len(children), stopping):
                        break
                    if args.limit is not None and launches >= args.limit:
                        break
                    route = routes.assignment(job)
                    if not policies.can_route_dispatch(decision, by_route, route):
                        continue
                    claimed = publish_claim(root, job, {**own, 'controller_id': cid}, routes)
                    if claimed is None:
                        continue
                    jobdir, slot = claimed
                    out = jobdir / 'attempts/attempt_001'
                    out.mkdir(parents=True)
                    spec = {**job, 'campaign_root': str(root), 'config_path': str(root / 'experiment.json'),
                            'plan_sha256': sha(root / 'plan.json'), 'cohort_sha256': plan['definition']['cohort_sha256'],
                            'slot_path': str(slot), 'controller_id': cid}
                    immutable_json(jobdir / 'spec.json', spec)
                    with (out / 'launcher.log').open('a') as log:
                        child = subprocess.Popen([sys.executable, str(ROOT / 'scripts/run_bc_retry1_trial.py'),
                                                  '--spec', str(jobdir / 'spec.json'), '--out', str(out), '--live'],
                                                 cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                                 start_new_session=True)
                    children[job['job_id']] = child
                    child_routes[job['job_id']] = route
                    by_route[route] += 1
                    launches += 1
            atomic(control / 'status.json', {**own, 'updated_at': now(), 'heartbeat_unix': time.time(),
                'active_local': len(children), 'active_by_route': dict(Counter(child_routes.values())),
                'selected_states': dict(Counter(states.values())), 'launches': launches,
                'stop_dispatch': stopping, 'dispatch_policy': decision, 'root': str(root),
                'retry_ledger_sha256': sha(root / 'retry-ledger.json')})
            if not children and (stopping or not any(s == 'pending' for s in states.values()) or args.limit is not None and launches >= args.limit):
                break
            time.sleep(2)
    except BaseException as exc:
        failure = type(exc).__name__
        atomic(control / 'error.json', {'error_type': failure, 'at': now(), 'action': 'Stop new dispatch; drain existing native trials'})
        raise
    finally:
        # Do not kill children if metadata/dispatch fails. They own hard budgets.
        for child in children.values():
            child.wait()
        atomic(control / 'exit.json', {'at': now(), 'error_type': failure, 'drained': True, 'launches': launches})


if __name__ == '__main__':
    main()
