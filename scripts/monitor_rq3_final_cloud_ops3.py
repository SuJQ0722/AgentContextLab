#!/usr/bin/env python3
"""Read-only runtime view of the corrected seven-scale, 2100-observation study."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import time

from lab import ROOT
from run_bc_campaign_v3 import atomic, job_state
from run_rq3_parity_v3 import DEFAULT_ROOT, label
from monitor_rq3_cloud_ops2 import read

SCALES = (0., .25, .5, .7, .75, .8, 1.)
NEW_ROOT = ROOT/'outputs/campaigns/rq3-deepseek-bc100-r3-scale0750-v1'
OUTPUT = ROOT/'outputs/supervision/rq3-final-seven-runtime.json'


def snapshot():
    now = time.time()
    rows = []
    for scale in SCALES:
        root = NEW_ROOT if scale == .75 else DEFAULT_ROOT
        area = root/('cloud-scale-ops3' if scale == .75 else 'cloud-scale-ops2')
        plan = read(root/'plan.json')
        if plan is None:
            rows.append({'scale': scale, 'planned': 300, 'state': 'plan_not_ready', 'active_cloud': 0})
            continue
        jobs = [j for j in plan['jobs'] if j['scale'] == scale]
        if len(jobs) != 300:
            raise ValueError('Final scope must have exactly300 observations per scale')
        counts = Counter()
        for job in jobs:
            directory = root/'jobs'/job['job_id']
            state = job_state(directory)
            if state == 'terminal':
                result = read(directory/'attempts/attempt_001/result.json')
                state = result.get('status', 'unknown_terminal') if result else 'unreadable_terminal'
            elif state.startswith('running_'):
                state = 'active'
            counts[state] += 1
        controllers = []
        for path in (area/'controllers'/label(scale)).glob('*/status.json'):
            value = read(path)
            if value is None:
                continue
            stamp = value.get('at', value.get('heartbeat_unix', 0))
            controllers.append({'path': str(path), 'fresh': isinstance(stamp, (int, float)) and -5 <= time.time()-stamp < 120, 'status': value})
        nodes = []
        for path in (root/'runtime/nodes').glob('*/telemetry.json'):
            value = read(path)
            if value is None or value.get('scale_label') != label(scale):
                continue
            stamp = value.get('observed_at_unix', 0)
            nodes.append({'path': str(path), 'fresh': -5 <= time.time()-stamp < 120, 'telemetry': value})
        rows.append({'scale': scale, 'planned': 300, 'root': str(root), 'states': dict(counts),
                     'target_cloud': 16, 'active_cloud': sum(c['status'].get('active_local', 0) for c in controllers if c['fresh']),
                     'controllers': controllers, 'nodes': nodes})
    recovery = read(ROOT/'outputs/campaigns/rq3-deepseek-bc100-r3-parity-v3-pre-native-recovery2/status.json')
    return {'version': 'rq3-final-seven-runtime-ops3', 'as_of': datetime.now(timezone.utc).isoformat(),
            'final_scales': list(SCALES), 'planned': 2100, 'cloud_target': 112,
            'active_cloud': sum(r.get('active_cloud', 0) for r in rows), 'scales': rows,
            'pre_native_recovery2': recovery, 'excluded_scale': .125,
            'note': 'Exactly six original scales plus newly authorized0.75. Original0.125 attempts/usage retained but excluded. Active cloud trial count is not HTTP request concurrency or OS process count. Separate fixed recovery observations are resolved by the final statistical report.',
            'model_calls_by_monitor': 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--watch', action='store_true')
    args = parser.parse_args()
    while True:
        value = snapshot()
        atomic(OUTPUT, value)
        print(json.dumps({'at': value['as_of'], 'active_cloud': value['active_cloud'],
                          'by_scale': {str(r['scale']): r.get('active_cloud', 0) for r in value['scales']}}), flush=True)
        if not args.watch:
            return
        time.sleep(60)


if __name__ == '__main__':
    main()
