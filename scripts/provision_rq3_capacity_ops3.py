#!/usr/bin/env python3
"""Resume two never-started RQ3 allocations and add authorized0.75 in available capacity."""
import argparse
import json
from pathlib import Path
import shlex
import subprocess

from lab import ROOT
from run_bc_campaign_v3 import atomic, now
from run_rq3_parity_v3 import DEFAULT_ROOT, sha, validate, label
from provision_rq3_scale_ops2 import TEMPLATE
from replace_sco_bc_v3_after_reader_ops import create_argv, create_cli, error_reason

NEW_ROOT = ROOT / 'outputs/campaigns/rq3-deepseek-bc100-r3-scale0750-v1'
RECEIPTS = ROOT / 'outputs/cloud-runtime/rq3-capacity-ops3'
SCALES = (.75, .8, 1.)
POOL = 'agentic-rl'


def request_args(template, scale):
    if scale not in SCALES:
        raise ValueError('Only0.75 and the two never-started allocations are in this rollout')
    name = 'acl-rq3-' + label(scale).replace('scale_', 's') + '-ops3'
    argv = create_argv(template, name)
    def value(flag):
        return argv[argv.index(flag)+1]
    if value('--aec2-name') != 'agents' or value('--container-image-url') != 'registry.cn-tj-01.sensecore.cn/ccr-zuhu2026/sjq-dev-cpu:sjq-dev-20261108063401':
        raise ValueError('Unexpected reviewed source deployment')
    if '/mnt/afs_agents' not in value('--storage-mount') or any(k in argv for k in ('--env', '--enable-fault-tolerance', '--retry-times')):
        raise ValueError('AFS/credential/automatic-retry policy differs')
    argv[argv.index('--aec2-name')+1] = POOL
    root = NEW_ROOT if scale == .75 else DEFAULT_ROOT
    entry = 'bootstrap_rq3_scale0750_ops3.py' if scale == .75 else 'bootstrap_rq3_scale_ops2.py'
    command = ['/opt/conda/bin/python', str(ROOT/'scripts'/entry), '--root', str(root),
               '--scale', str(scale), '--reader-python', '/opt/conda/bin/python', '--live']
    argv[argv.index('--command')+1] = 'cd ' + shlex.quote(str(ROOT)) + ' && exec ' + shlex.join(command)
    return name, root, entry, argv


def describe(name):
    result = subprocess.run([str(ROOT/'.tools/sco-tj/cli/sco'), 'acp', 'jobs', 'describe',
        '--profile', 'agentcontextlab-tj', '--workspace-name', 'rl', name, '-o', 'json'],
        capture_output=True, text=True, timeout=90)
    return result


def verify_never_started(scale):
    if scale not in (.8, 1.):
        raise ValueError('Predecessor proof applies only to the two pending nodes')
    old_name = 'acl-rq3-' + label(scale).replace('scale_', 's') + '-ops2'
    directory = RECEIPTS/old_name
    before = json.loads((directory/'before-stop.json').read_text())
    request = json.loads((directory/'stop-request.json').read_text())
    response = json.loads((directory/'stop-response.json').read_text())
    if before.get('state') not in ('STARTING', 'PENDING', 'CREATED') or request.get('uid') != before.get('uid') or response.get('returncode') != 0:
        raise ValueError('Predecessor stop evidence is not a known pre-start allocation')
    current = describe(old_name)
    if current.returncode:
        raise ValueError('Cannot confirm original cloud namespace stopped')
    value = json.loads(current.stdout)
    # ACP reports an explicitly stopped, resumable allocation as SUSPENDED.
    # This is an infrastructure state, never a successful prediction outcome.
    if value.get('uid') != before['uid'] or value.get('state') not in ('SUSPENDED', 'STOPPED', 'FAILED', 'SUCCEEDED'):
        raise ValueError('Predecessor remains non-terminal; no replacement')
    scope = DEFAULT_ROOT/'cloud-scale-ops2'
    if (scope/'leases'/label(scale)).exists() or any((scope/'controllers'/label(scale)).glob('*/maintenance.json')):
        raise ValueError('Predecessor acquired a scientific dispatcher; explicit lineage review required')
    for path in (DEFAULT_ROOT/'runtime/nodes').glob('*'+before['uid']+'*/*/bootstrap.json'):
        raise ValueError('Unexpected predecessor bootstrap evidence: '+str(path))
    atomic(directory/'after-stop.json', value)
    proof = {'name': old_name, 'uid': value['uid'], 'state': value['state'], 'dispatcher_lease_absent': True,
             'bootstrap_absent': True, 'native_prediction_replayed': False,
             'after_stop_sha256': sha(directory/'after-stop.json')}
    atomic(directory/'never-started-proof.json', proof)
    return proof


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scales', type=float, choices=SCALES, nargs='+', default=list(SCALES))
    parser.add_argument('--live', action='store_true')
    args = parser.parse_args()
    if len(args.scales) != len(set(args.scales)):
        raise ValueError('Duplicate allocation selection')
    template = json.loads(TEMPLATE.read_text())
    for scale in args.scales:
        name, root, entry, argv = request_args(template, scale)
        destination = RECEIPTS/name
        if destination.exists():
            print(json.dumps({'name': name, 'state': 'existing_receipt_no_repeat'}), flush=True)
            continue
        if not args.live:
            print(json.dumps({'name': name, 'live': False, 'scale': scale, 'pool': POOL,
                              'cpu': 8, 'memory_gib': 32, 'concurrency': 16, 'root': str(root), 'entry': entry}), flush=True)
            continue
        if scale == .75:
            from run_rq3_scale0750_cloud_ops3 import verify_launch
            verify_launch(root)
            predecessor = None
        else:
            validate(json.loads((root/'plan.json').read_text()), root)
            from run_rq3_scale_cloud_ops2 import verify_cutover
            verify_cutover(root)
            predecessor = verify_never_started(scale)
        current = describe(name)
        if current.returncode == 0 or not error_reason({'stdout': current.stdout, 'stderr': current.stderr}, 'trainingJobNotFound'):
            raise ValueError('New fixed-name allocation absence not established')
        destination.mkdir(parents=True, exist_ok=False)
        atomic(destination/'request.json', {'name': name, 'operation': 'create', 'requested_at': now(),
            'scale': scale, 'pool': POOL, 'cpu': 8, 'memory_gib': 32, 'concurrency': 16, 'argv': argv,
            'campaign_root': str(root), 'plan_sha256': sha(root/'plan.json'),
            'bootstrap_sha256': sha(ROOT/'scripts'/entry), 'provisioner_sha256': sha(__file__),
            'predecessor': predecessor, 'capacity_reason': 'Original agents pool had only6 idle CPUs; same-zone/VPC pool offers identical8c32g SKU',
            'scope': 'User final seven scales,100x3 each; six unchanged scale observations reused; new0.75 only300 native runs',
            'automatic_repeat_allowed': False})
        outcome = create_cli(argv)
        state = 'submitted' if outcome.get('returncode') == 0 else 'unknown' if outcome.get('returncode') is None else 'rejected'
        atomic(destination/'response.json', {**outcome, 'state': state, 'completed_at': now()})
        print(json.dumps({'name': name, 'state': state, 'pool': POOL, 'scale': scale}), flush=True)
        if state != 'submitted':
            raise RuntimeError('Inspect fixed submission outcome; no automatic retry')


if __name__ == '__main__':
    main()
