#!/usr/bin/env python3
"""Submit one approved Tianjin core cell; default is a no-network dry run."""
import argparse
import datetime
import json
import os
from pathlib import Path
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--harness', required=True, choices=['hermes', 'dsh'])
    parser.add_argument('--strategy', required=True,
                        choices=['none', 'summarize', 'sliding_window', 'discard', 'visual'])
    parser.add_argument('--live', action='store_true')
    args = parser.parse_args()
    config = json.loads((ROOT / 'configs/sco-review-plan.json').read_text())
    cloud = config['cloud']
    if not config.get('launch_authorized'):
        raise SystemExit('Reviewed cloud launch is not authorized')
    if config['instance'] != {'cpu_count': 8, 'memory_gib': 32, 'gpu_count': 0, 'worker_concurrency': 32}:
        raise SystemExit('Unexpected instance allocation')
    if cloud['region'] != 'cn-tj-01' or cloud['workspace'] != 'rl':
        raise SystemExit('Unexpected cloud location')
    name = 'acl-bc-v3-' + args.harness + '-' + args.strategy.replace('_', '-')
    command = 'cd ' + shlex.quote(str(ROOT)) + ' && exec ' + shlex.join([
        '/opt/conda/bin/python', str(ROOT / 'scripts/bootstrap_bc_v3_node.py'),
        '--harness', args.harness, '--strategy', args.strategy,
        '--reader-python', '/opt/conda/bin/python', '--live'])
    argv = [str(ROOT / '.tools/sco-tj/cli/sco'), 'acp', 'jobs', 'create',
            '--profile', cloud['profile'], '--workspace-name', cloud['workspace'],
            '--aec2-name', cloud['resource_pool'], '--job-name', name, '--name', name,
            '--container-image-url', cloud['image'], '--training-framework', 'pytorch',
            '--worker-nodes', '1', '--worker-spec', cloud['worker_spec'],
            '--priority', 'NORMAL', '--quota-type', 'reserved',
            '--storage-mount', cloud['afs_volume_id'] + ':/mnt/afs_agents', '--command', command]
    record = {'name': name, 'harness': args.harness, 'strategy': args.strategy,
              'argv': argv, 'workers': 32, 'mode': 'live' if args.live else 'dry_run'}
    if not args.live:
        print(json.dumps(record, indent=2)); return
    destination = ROOT / 'outputs/cloud-runtime/submissions' / (name + '.json')
    destination.parent.mkdir(parents=True, exist_ok=True)
    # A submission with unknown outcome is inspected, never automatically repeated.
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    record.update(state='submitting', submitted_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
    with os.fdopen(fd, 'w') as stream:
        json.dump(record, stream, indent=2); stream.flush(); os.fsync(stream.fileno())
    result = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, timeout=120)
    output = result.stdout + result.stderr
    # CLI credentials stay in its private profile, never in the job command/env.
    credentials = json.loads((ROOT / '.state/sco/tianjin-credentials.json').read_text())
    for value in credentials.values():
        output = output.replace(value, '<redacted>')
    record.update(state='submitted' if result.returncode == 0 else 'submission_failed',
                  returncode=result.returncode, response=output)
    tmp = destination.with_suffix('.tmp'); tmp.write_text(json.dumps(record, indent=2) + '\n')
    tmp.chmod(0o600); tmp.replace(destination)
    print(json.dumps({'name': name, 'state': record['state'], 'receipt': str(destination), 'response': output}))
    raise SystemExit(result.returncode)


if __name__ == '__main__':
    main()
