#!/usr/bin/env python3
"""One explicitly authorized 8 CPU / 32 GiB cloud node per frozen RQ3 scale."""
import argparse
import json
from pathlib import Path
import shlex
import subprocess

from lab import ROOT
from run_bc_campaign_v3 import atomic, now
from run_rq3_parity_v3 import DEFAULT_ROOT, SCALES, label, sha, validate
from replace_sco_bc_v3_after_reader_ops import create_argv, create_cli, error_reason

TEMPLATE = ROOT / 'outputs/cloud-runtime/retry1-submissions/acl-bc-v3-hermes-visual-retry1/request.json'
RECEIPTS = ROOT / 'outputs/cloud-runtime/rq3-scale-ops2-submissions'


def request_args(template, scale, root=DEFAULT_ROOT):
    if scale not in SCALES:
        raise ValueError('Only the seven frozen scales are authorized')
    name = 'acl-rq3-' + label(scale).replace('scale_', 's') + '-ops2'
    argv = create_argv(template, name)
    expected_image = 'registry.cn-tj-01.sensecore.cn/ccr-zuhu2026/sjq-dev-cpu:sjq-dev-20261108063401'
    if argv[argv.index('--container-image-url') + 1] != expected_image:
        raise ValueError('Unexpected reviewed private image')
    mount = argv[argv.index('--storage-mount') + 1]
    if '/mnt/afs_agents' not in mount:
        raise ValueError('Reviewed AFS mount required')
    if any(flag in argv for flag in ('--enable-fault-tolerance', '--retry-times', '--env')):
        raise ValueError('Automatic resource retries or inherited secret env are not allowed')
    command = ['/opt/conda/bin/python', str(ROOT / 'scripts/bootstrap_rq3_scale_ops2.py'),
               '--root', str(Path(root).resolve()), '--scale', str(scale),
               '--reader-python', '/opt/conda/bin/python', '--live']
    argv[argv.index('--command') + 1] = 'cd ' + shlex.quote(str(ROOT)) + ' && exec ' + shlex.join(command)
    return name, argv


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=DEFAULT_ROOT)
    parser.add_argument('--scales', type=float, nargs='+', choices=SCALES, default=list(SCALES))
    parser.add_argument('--live', action='store_true')
    args = parser.parse_args()
    if len(set(args.scales)) != len(args.scales):
        raise ValueError('Repeated scale allocation is not authorized')
    root = args.root.resolve()
    plan = json.loads((root / 'plan.json').read_text())
    validate(plan, root)
    template = json.loads(TEMPLATE.read_text())
    if args.live:
        from run_rq3_scale_cloud_ops2 import verify_cutover
        verify_cutover(root)
    for scale in args.scales:
        name, argv = request_args(template, scale, root)
        destination = RECEIPTS / name
        if destination.exists():
            print(json.dumps({'name': name, 'state': 'existing_receipt_no_repeat'}), flush=True)
            continue
        if not args.live:
            print(json.dumps({'name': name, 'live': False, 'scale': scale,
                              'workers': 16, 'cpu': 8, 'memory_gib': 32, 'argv': argv}), flush=True)
            continue
        query = subprocess.run([str(ROOT / '.tools/sco-tj/cli/sco'), 'acp', 'jobs', 'describe',
                                '--profile', 'agentcontextlab-tj', '--workspace-name', 'rl', name, '-o', 'json'],
                               capture_output=True, text=True, timeout=90)
        if query.returncode == 0 or not error_reason({'stdout': query.stdout, 'stderr': query.stderr}, 'trainingJobNotFound'):
            raise ValueError('Fixed resource absence not established: ' + name)
        destination.mkdir(parents=True, exist_ok=False)
        sources = ('bootstrap_rq3_scale_ops2.py', 'run_rq3_scale_cloud_ops2.py', 'provision_rq3_scale_ops2.py')
        atomic(destination / 'request.json', {'name': name, 'operation': 'create', 'requested_at': now(),
            'argv': argv, 'scale': scale, 'workers': 16, 'cpu': 8, 'memory_gib': 32,
            'campaign_root': str(root), 'plan_sha256': sha(root / 'plan.json'),
            'cutover_sha256': sha(root / 'cloud-scale-ops2/cutover.json'),
            'template_sha256': sha(TEMPLATE), 'source_sha256': {n: sha(ROOT / 'scripts' / n) for n in sources},
            'resume': 'Only unclaimed jobs at this scale; prior evidence preserved', 'automatic_repeat_allowed': False})
        outcome = create_cli(argv)
        state = 'submitted' if outcome.get('returncode') == 0 else 'unknown' if outcome.get('returncode') is None else 'rejected'
        atomic(destination / 'response.json', {**outcome, 'state': state, 'completed_at': now()})
        print(json.dumps({'name': name, 'scale': scale, 'state': state}), flush=True)
        if state != 'submitted':
            raise RuntimeError('Inspect the fixed submission receipt before any further action')


if __name__ == '__main__':
    main()
