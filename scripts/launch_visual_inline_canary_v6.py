"""Prepare or release eight local canary controllers; never retry a launch."""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from lab import ROOT
from prepare_visual_inline_canary_v6 import DEST, CELLS
from prepare_visual_hosted_retry_v1 import load_validate
from prepare_mmbc100_campaign import sha, immutable_json
from run_bc_campaign_v3 import identity


def prepare(root):
    rows = []
    for cell in CELLS:
        path = root / 'cells' / cell
        plan, manifest = load_validate(path)
        if len(plan['jobs']) != 1 or plan['definition'].get('canary_version') != 'visual-inline-canary-v6':
            raise ValueError('Only one canary job per cell permitted')
        command = [sys.executable, str(ROOT / 'scripts/run_visual_inline_canary_v6.py'),
                   '--root', str(path), '--harness', manifest['harness'], '--concurrency', '16', '--resume', '--live']
        rows.append({'cell': cell, 'root': str(path), 'plan_sha256': sha(path / 'plan.json'), 'command': command})
    return {'version': 'local-inline-canary-launch-v6', 'execution_host': 'local_shared_host',
            'independent_containers': False, 'concurrency_configuration_per_cell': 16,
            'maximum_total_trials': 8, 'automatic_launch_retry': False, 'cells': rows}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, default=DEST)
    p.add_argument('--live', action='store_true')
    a = p.parse_args(); root = a.root.resolve(); receipt = prepare(root)
    area = root / 'local-launch'
    immutable_json(area / 'prepared.json', receipt)
    if not a.live:
        print(json.dumps({'live': False, 'model_calls': 0, 'cells': len(receipt['cells'])})); return
    release = json.loads((area / 'release.json').read_text())
    hashes = {r['cell']: r['plan_sha256'] for r in receipt['cells']}
    if release.get('approved_plan_hashes') != hashes or release.get('authorized_by') != 'root_review':
        raise ValueError('Explicit matching root review release required')
    for row in receipt['cells']:
        directory = area / row['cell']; request = directory / 'launch-request.json'
        if request.exists():
            raise ValueError('Launch already attempted; never silently repeat or recycle claims')
        load_validate(Path(row['root']))
        immutable_json(request, {**row, 'at': time.time(), 'operator': identity()})
        with (directory / 'controller.log').open('a') as log:
            child = subprocess.Popen(row['command'], cwd=ROOT, stdin=subprocess.DEVNULL,
                                     stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        immutable_json(directory / 'launch-response.json', {'at': time.time(), 'child': identity(child.pid),
                       'pid': child.pid, 'launched': True, 'native_completion_unconfirmed': True})
        print(json.dumps({'cell': row['cell'], 'pid': child.pid}), flush=True)


if __name__ == '__main__': main()
