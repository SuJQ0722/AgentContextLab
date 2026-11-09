#!/usr/bin/env python3
"""Create one explicitly authorized 8CPU/32GiB retry1 node per selected cell."""
import argparse
import json
from pathlib import Path
import subprocess
from bc_retry1 import ROOT, DEFAULT_ROOT, load_ledger, sha
from run_bc_campaign_v3 import atomic, now
from replace_sco_bc_v3_after_reader_ops import create_cli, create_argv, error_reason


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--harness', nargs='+', default=['dsh', 'hermes'])
    parser.add_argument('--strategy', nargs='+', default=['none', 'summarize', 'sliding_window', 'discard', 'visual'])
    parser.add_argument('--live', action='store_true')
    args = parser.parse_args()
    ledger = load_ledger(DEFAULT_ROOT)
    receipts = ROOT / 'outputs/cloud-runtime/retry1-submissions'
    proof = json.loads(Path(ledger['termination_evidence_path']).read_text())
    terminated = {r['name']: r for r in proof['current_cloud']}
    for harness in args.harness:
        for strategy in args.strategy:
            old = 'acl-bc-v3-' + harness + '-' + strategy.replace('_', '-') + '-ops6'
            if old not in terminated:
                raise ValueError('No exact terminated predecessor')
            parent_path = ROOT / 'outputs/cloud-runtime/routes2-replacements' / old / 'request.json'
            parent = json.loads(parent_path.read_text())
            name = old[:-4] + 'retry1'
            argv = create_argv(parent, name)
            index = argv.index('--command') + 1
            old_entry = str(ROOT / 'scripts/bootstrap_bc_v3_node_routes2_io3.py')
            if argv[index].count(old_entry) != 1:
                raise ValueError('Unexpected predecessor bootstrap')
            argv[index] = argv[index].replace(old_entry, str(ROOT / 'scripts/bootstrap_bc_retry1.py'))
            directory = receipts / name
            if directory.exists():
                print(json.dumps({'name': name, 'state': 'existing_receipt_not_repeated'}), flush=True)
                continue
            if not args.live:
                print(json.dumps({'name': name, 'live': False, 'argv': argv}), flush=True)
                continue
            # The fixed name must also be absent at ACP, including after a lost
            # create response. Never create a second resource on uncertainty.
            query = subprocess.run([str(ROOT / '.tools/sco-tj/cli/sco'), 'acp', 'jobs', 'describe',
                                    '--profile', 'agentcontextlab-tj', '--workspace-name', 'rl', name, '-o', 'json'],
                                   capture_output=True, text=True, timeout=90)
            if query.returncode == 0 or not error_reason({'stdout': query.stdout, 'stderr': query.stderr}, 'trainingJobNotFound'):
                raise ValueError('Fixed retry node absence not established: ' + name)
            directory.mkdir(parents=True, exist_ok=False)
            atomic(directory / 'request.json', {'name': name, 'harness': harness, 'strategy': strategy,
                'generation': 'retry1', 'operation': 'create', 'argv': argv, 'requested_at': now(),
                'campaign_root': str(DEFAULT_ROOT), 'retry_ledger_sha256': sha(DEFAULT_ROOT / 'retry-ledger.json'),
                'predecessor': terminated[old], 'parent_request_sha256': sha(parent_path),
                'bootstrap_sha256': sha(ROOT / 'scripts/bootstrap_bc_retry1.py'),
                'workers': 16, 'worker_ceiling': 32, 'resources_unchanged': True})
            outcome = create_cli(argv)
            state = 'submitted' if outcome.get('returncode') == 0 else 'unknown' if outcome.get('returncode') is None else 'rejected'
            atomic(directory / 'response.json', {**outcome, 'state': state, 'completed_at': now()})
            print(json.dumps({'name': name, 'state': state}), flush=True)
            if state != 'submitted':
                raise RuntimeError('Provisioning requires diagnosis; no automatic repeat')


if __name__ == '__main__':
    main()
