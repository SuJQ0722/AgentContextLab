"""Launch the two approved local BC cells exactly once after root review."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from lab import ROOT
from bootstrap_visual_inline_two_hour_v7 import DEFAULT_ROOT, load_validate
from prepare_mmbc100_campaign import sha, immutable_json
from run_bc_campaign_v3 import identity
from warm_visual_inline_worker_v7 import warm

CELLS = {'bc_hermes': ('hermes', '0-7'), 'bc_dsh': ('dsh', '8-15')}


def prepare(root):
    if Path(root).resolve() != DEFAULT_ROOT.resolve(): raise ValueError('Wrong V7 root')
    rows = []
    for cell, (harness, affinity) in CELLS.items():
        path = root / 'cells' / cell
        plan, manifest = load_validate(path)
        if manifest['harness'] != harness: raise ValueError('Harness mismatch')
        command = ['taskset', '-c', affinity, sys.executable,
                   str(ROOT / 'scripts/run_visual_inline_transport_v7.py'), '--root', str(path),
                   '--harness', harness, '--concurrency', '16', '--resume', '--live']
        rows.append({'cell': cell, 'root': str(path), 'harness': harness, 'cpu_affinity': affinity,
                     'plan_sha256': sha(path / 'plan.json'), 'command': command, 'trials': len(plan['jobs'])})
    return {'version': 'local-inline-two-hour-launch-v7', 'execution_host': 'local_shared_host',
            'independent_containers': False, 'concurrency_per_cell': 16, 'global_inference_cap': None,
            'trial_deadline_seconds': 7200, 'automatic_launch_retry': False, 'cells': rows}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, default=DEFAULT_ROOT); p.add_argument('--live', action='store_true')
    a = p.parse_args(); root = a.root.resolve(); receipt = prepare(root); area = root / 'local-launch'
    immutable_json(area / 'prepared.json', receipt)
    if not a.live:
        print(json.dumps({'live': False, 'cells': 2, 'model_calls': 0})); return
    release = json.loads((area / 'release.json').read_text())
    if release.get('approved_plan_hashes') != {r['cell']: r['plan_sha256'] for r in receipt['cells']} or release.get('authorized_by') != 'root_review':
        raise ValueError('Matching root review release required')
    # Validate both cells and import dependencies before either paid dispatch.
    env = dict(os.environ); env.pop('ALL_PROXY', None); env.pop('all_proxy', None)
    os.environ.clear(); os.environ.update(env)
    for row in receipt['cells']:
        if (area / row['cell'] / 'launch-request.json').exists(): raise ValueError('Launch previously attempted')
        load_validate(Path(row['root']))
        warm(Path(row['root']), row['harness'])
        if row['harness'] == 'dsh':
            from preflight_dsh_transport_v6 import check
            check(Path(row['root']))
    for row in receipt['cells']:
        directory = area / row['cell']
        immutable_json(directory / 'launch-request.json', {**row, 'at': time.time(), 'operator': identity()})
        with (directory / 'controller.log').open('a') as log:
            child = subprocess.Popen(row['command'], cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                                     stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        immutable_json(directory / 'launch-response.json', {'at': time.time(), 'child': identity(child.pid),
                       'pid': child.pid, 'cpu_affinity': row['cpu_affinity'], 'launched': True})
        print(json.dumps({'cell': row['cell'], 'pid': child.pid, 'cpu_affinity': row['cpu_affinity']}), flush=True)


if __name__ == '__main__': main()
