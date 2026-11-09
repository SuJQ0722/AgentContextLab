#!/usr/bin/env python3
"""Low-I/O seven-scale runtime monitor; scientific outcomes remain in final report."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import socket
import time

from lab import ROOT
from run_bc_campaign_v3 import atomic

OLD = ROOT/'outputs/campaigns/rq3-deepseek-bc100-r3-parity-v3'
NEW = ROOT/'outputs/campaigns/rq3-deepseek-bc100-r3-scale0750-v1'
RETRY = ROOT/'outputs/campaigns/rq3-deepseek-bc100-r3-scale0700-paid-retry1'
OUTPUT = ROOT/'outputs/supervision/rq3-final-seven-runtime.json'
SCALES = (0., .25, .5, .7, .75, .8, 1.)


def read(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def snapshot():
    rows = []
    for scale in SCALES:
        root = NEW if scale == .75 else OLD
        label = 'scale_%04d' % round(scale*1000)
        areas = [root/('cloud-scale-ops3' if scale == .75 else 'cloud-scale-ops2')]
        if scale == .7:
            areas.extend([root/'cloud-scale-ops5', RETRY/'paid-retry-ops1'])
        controllers = []
        for area in areas:
            for path in (area/'controllers'/label).glob('*/status.json'):
                value = read(path)
                if not value:
                    continue
                stamp = value.get('at', 0)
                fresh = isinstance(stamp, (int, float)) and -5 <= time.time()-stamp < 180
                controllers.append({'path': str(path), 'fresh': fresh,
                    'placement': 'local' if value.get('hostname') == socket.gethostname() else 'cloud',
                    'status': value})
        active = [c for c in controllers if c['fresh']]
        reported_local = sum(c['status'].get('active_local', 0) for c in active if c['placement'] == 'local')
        reported_cloud = sum(c['status'].get('active_local', 0) for c in active if c['placement'] == 'cloud')
        slot_area = root/('cloud-scale-ops3' if scale == .75 else 'cloud-scale-ops5' if scale == .7 else 'cloud-scale-ops2')
        owners = [read(p) for p in (slot_area/'slots'/label).glob('[0-9][0-9]/owner.json')]
        owners = [o for o in owners if o]
        fresh_ids = {c['status'].get('controller_id') for c in active}
        known = [o for o in owners if o.get('controller_id') in fresh_ids]
        local = sum(o.get('hostname') == socket.gethostname() for o in known)
        cloud = len(known)-local
        rows.append({'scale': scale, 'planned': 300, 'target_workers': 16,
            'active_local': local, 'active_cloud': cloud, 'active_trials': local+cloud,
            'count_definition': 'Occupied slots of fresh controllers, including pre-launch reservations; not native process counts',
            'occupied_slots': len(owners), 'unknown_owner_slots': len(owners)-len(known),
            'reported_active_local': reported_local, 'reported_active_cloud': reported_cloud,
            'controllers': controllers,
            'state': 'active' if active else 'no_fresh_controller',
            'outcome_source': str(ROOT/('outputs/grading/rq3-final-seven-v3/statistics.json' if (ROOT/'outputs/grading/rq3-final-seven-v3/statistics.json').exists() else 'outputs/grading/rq3-final-seven-v2/statistics.json'))})
    return {'version': 'rq3-runtime-ops6', 'as_of': datetime.now(timezone.utc).isoformat(),
        'final_scales': list(SCALES), 'planned': 2100, 'target_workers': 112,
        'active_cloud': sum(r['active_cloud'] for r in rows),
        'active_local': sum(r['active_local'] for r in rows),
        'active_trials': sum(r['active_trials'] for r in rows), 'scales': rows,
        'excluded_scale': .125, 'model_calls_by_monitor': 0,
        'note': 'Runtime uses shared occupied slots of fresh controllers, including pre-launch reservations; not simultaneous HTTP requests or OS processes. Raw per-controller active counts are retained but asynchronous sums can transiently exceed the actual shared cap. Missing heartbeat is not proof of termination. Scientific outcomes and fixed recoveries remain in the statistical report.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--watch', action='store_true')
    args = parser.parse_args()
    while True:
        value = snapshot()
        atomic(OUTPUT, value)
        print(json.dumps({k:value[k] for k in ('as_of', 'active_cloud', 'active_local', 'active_trials')}), flush=True)
        if not args.watch:
            return
        time.sleep(30)


if __name__ == '__main__':
    main()
