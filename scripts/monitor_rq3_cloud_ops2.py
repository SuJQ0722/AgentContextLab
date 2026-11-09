#!/usr/bin/env python3
"""Read-only consolidated RQ3 deployment status; no dispatch or model calls."""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import time

from run_bc_campaign_v3 import atomic, job_state
from run_rq3_parity_v3 import DEFAULT_ROOT, label


def read(path):
    try:
        return json.loads(Path(path).read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def snapshot(root):
    now = time.time()
    plan = read(root / 'plan.json')
    cells = defaultdict(Counter)
    failures = []
    for job in plan['jobs']:
        directory = root / 'jobs' / job['job_id']
        state = job_state(directory)
        if state == 'terminal':
            result = read(directory / 'attempts/attempt_001/result.json')
            state = result.get('status', 'unknown_terminal') if result else 'unreadable_terminal'
        elif state.startswith('running_'):
            state = 'active'
        cells[label(job['scale'])][state] += 1
        if state in ('unknown', 'unreadable_terminal'):
            failures.append(job['job_id'])
    controllers = []
    for path in (root / 'cloud-scale-ops2/controllers').glob('*/*/status.json'):
        value = read(path)
        if value is None:
            continue
        stamp = value.get('heartbeat_unix', value.get('at', 0))
        controllers.append({'path': str(path), 'fresh': isinstance(stamp, (int, float)) and 0 <= now-stamp < 120,
                            'status': value})
    nodes = []
    for path in (root / 'runtime/nodes').glob('*/telemetry.json'):
        value = read(path)
        if value is None or value.get('version') != 'rq3-scale-node-telemetry-ops2':
            continue
        stamp = value.get('observed_at_unix', 0)
        nodes.append({'path': str(path), 'fresh': 0 <= now-stamp < 120, 'telemetry': value})
    old = read(root / 'status-ops1.json')
    return {'version': 'rq3-cloud-scale-monitor-ops2', 'as_of': datetime.now(timezone.utc).isoformat(),
        'scientific_plan_size': len(plan['jobs']), 'target_nodes': 7, 'target_workers_per_node': 16,
        'target_cloud_workers': 112, 'states_by_scale': {k: dict(v) for k, v in sorted(cells.items())},
        'states': dict(sum(cells.values(), Counter())), 'unresolved_job_ids': failures,
        'cloud_controllers': controllers, 'cloud_nodes': nodes,
        'original_controller': old,
        'original_controller_note': 'stop_dispatch=true means draining, not killed. Consult exact identities and exit record for final state.',
        'interpretation': 'Execution states, not accuracy. Original not_started observations remain preserved; separately authorized pre-native recovery overlays are handled by the existing RQ3 analysis.',
        'instrumentation': 'Frozen native per-attempt metrics preserve raw token/cache usage, compression and image guards. This lightweight deployment view does not re-sum costs or equate SDK duration with provider API latency.',
        'paid_calls_by_monitor': 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=DEFAULT_ROOT)
    parser.add_argument('--watch', action='store_true')
    args = parser.parse_args()
    root = args.root.resolve()
    while True:
        report = snapshot(root)
        atomic(root / 'cloud-scale-ops2/monitor/status.json', report)
        print(json.dumps({k: report[k] for k in ('as_of', 'states')}), flush=True)
        if not args.watch:
            break
        time.sleep(60)


if __name__ == '__main__':
    main()
