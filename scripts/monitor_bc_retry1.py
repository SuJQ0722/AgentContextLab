#!/usr/bin/env python3
"""Read-only retry ledger/usage monitor; unselected originals are not pending."""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
import time
from bc_retry1 import DEFAULT_ROOT, ROOT, load_ledger
from run_bc_campaign_v3 import atomic, job_state, owner_alive
from monitor_bc_campaign_v3 import inspect_attempt, aggregate, route_accounting, read_json


def snapshot(root):
    ledger = load_ledger(root)
    states = Counter()
    cells = defaultdict(Counter)
    observations = []
    attempts = []
    for e in ledger['entries']:
        jobdir = root / 'jobs' / e['job_id']
        state = job_state(jobdir)
        if state == 'unknown':
            owner = read_json(jobdir / 'claim/owner.json') or {}
            controller = read_json(root / 'controllers' / owner.get('controller_id', '_missing') / 'status.json') or {}
            if (owner_alive(owner) is True or time.time() - controller.get('heartbeat_unix', 0) < 90):
                if not (jobdir / 'attempts/attempt_001/worker-started.json').exists():
                    state = 'launching'
        if state.startswith('running_'):
            state = 'active'
        if state == 'terminal':
            state = read_json(jobdir / 'attempts/attempt_001/result.json').get('status', 'unknown')
        states[state] += 1
        cell = '/'.join(e['job_id'].split('/')[:2])
        cells[cell][state] += 1
        out = jobdir / 'attempts/attempt_001'
        if out.exists():
            row, usage = inspect_attempt(out, e['job_id'].split('/')[0])
            row['job_id'] = e['job_id']
            attempts.append(row)
            observations.extend(usage)
    nodes = []
    for path in (root / 'runtime/nodes').glob('*/telemetry.json'):
        value = read_json(path)
        nodes.append({'path': str(path), 'mtime_unix': path.stat().st_mtime,
                      'fresh': time.time() - path.stat().st_mtime < 90,
                      'processes': value.get('processes'), 'cgroup': value.get('cgroup')})
    return {'version': 'bc-retry1-monitor-v1', 'as_of': datetime.now(timezone.utc).isoformat(),
            'selected_jobs': len(ledger['entries']), 'states': dict(states),
            'cells': {k: dict(v) for k, v in cells.items()}, 'usage': aggregate(observations),
            'route_accounting': route_accounting(observations), 'attempts': attempts,
            'web_cache': dict(sum((Counter(a['web_cache']) for a in attempts), Counter())),
            'controllers': [{'path': str(p), 'status': read_json(p)} for p in (root / 'controllers').glob('*/status.json')],
            'nodes': nodes, 'usd': None, 'note': 'Retry consumption only; original incurred cost remains separate and must be included. completed is not accuracy.'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--watch', action='store_true')
    args = parser.parse_args()
    out = DEFAULT_ROOT / 'monitor'
    while True:
        report = snapshot(DEFAULT_ROOT)
        atomic(out / 'status.json', report)
        print(json.dumps({k: report[k] for k in ('as_of', 'states')}), flush=True)
        if not args.watch:
            break
        time.sleep(30)


if __name__ == '__main__':
    main()
