#!/usr/bin/env python3
"""Prepare/submit three CCI shards for one bounded VERA retry; offline by default."""
import argparse
import json
from pathlib import Path
import shlex
import time
import yaml

import provision_mmbc_cci_v1 as base
from lab import ROOT
from prepare_bounded_vera_retry_v1 import DEFAULT_ROOT, load_validate
from run_bc_campaign_v3 import digest, atomic
from bc_route_runtime_v1 import immutable_json

RECEIPTS = ROOT/'outputs/cloud-runtime/bounded-vera-retry-v1'
MARKER = RECEIPTS/'launch-ready.json'


def app_name(shard):
    if type(shard) is not int or shard not in range(3): raise ValueError('Expected shard0..2')
    return 'acl-mmbc-vera-bounded-r1-s'+str(shard)


def build_config(template, shard, root=DEFAULT_ROOT, marker=MARKER):
    name = app_name(shard); root = Path(root).resolve()
    if root != DEFAULT_ROOT.resolve(): raise ValueError('Wrong bounded campaign root')
    c = base.build_config(template, 'visual', root, marker)
    argv = ['/opt/conda/bin/python', str(ROOT/'scripts/bootstrap_bounded_vera_retry_v1.py'),
            '--root', str(root), '--shard', str(shard), '--concurrency', '16',
            '--reader-python', '/opt/conda/bin/python', '--live']
    # The marker is a separate main-operator action after all bindings are checked.
    shell = 'while [ ! -f '+shlex.quote(str(marker))+' ]; do sleep 5; done; cd '+shlex.quote(str(ROOT))+' && '+shlex.join(argv)+'; exec sleep infinity'
    c['display_name'] = name
    c['template']['containers'][0].update(name='bounded-vera', command=['/bin/bash', '-c', shell])
    return c


def prepare(shards, root=DEFAULT_ROOT, receipts=RECEIPTS):
    if not shards or len(set(shards)) != len(shards): raise ValueError('Unique nonempty shards required')
    root, receipts = Path(root).resolve(), Path(receipts).resolve()
    load_validate(root)
    template = yaml.safe_load(base.TEMPLATE.read_text()); records = []
    for shard in shards:
        directory = receipts/app_name(shard); directory.mkdir(parents=True, exist_ok=True)
        config = build_config(template, shard, root, receipts/'launch-ready.json')
        raw = yaml.safe_dump(config, sort_keys=False).encode(); path = directory/'config.yaml'
        if path.exists():
            if path.read_bytes() != raw: raise ValueError('Prepared configuration changed')
        else:
            with path.open('xb') as f: f.write(raw)
        record = {'name': app_name(shard), 'shard': shard, 'root': str(root),
                  'plan_sha256': digest((root/'plan.json').read_bytes()), 'config_path': str(path),
                  'config_sha256': digest(raw), 'template_sha256': digest(base.TEMPLATE.read_bytes()),
                  'bootstrap_sha256': digest((ROOT/'scripts/bootstrap_bounded_vera_retry_v1.py').read_bytes()),
                  'launcher_sha256': digest(Path(__file__).read_bytes()), 'concurrency': 16, 'cpu': 8, 'memory_gib': 32,
                  'launch_marker': str(receipts/'launch-ready.json'), 'automatic_repeat_allowed': False}
        if (directory/'prepared.json').exists():
            if json.loads((directory/'prepared.json').read_text()) != record: raise ValueError('Prepared inputs changed')
        else: immutable_json(directory/'prepared.json', record)
        records.append(record)
    return records


def submit(record, invoke=base.create_cli):
    # Reuse immutable request marker + existence/ambiguity protection unchanged.
    return base.submit(record, invoke)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--shards', type=int, choices=range(3), nargs='+', default=list(range(3)))
    p.add_argument('--prepare', action='store_true'); p.add_argument('--live', action='store_true')
    p.add_argument('--status', action='store_true'); a = p.parse_args()
    if len(set(a.shards)) != len(a.shards): p.error('Duplicate shard')
    if a.status:
        if a.live or a.prepare: p.error('Status cannot mutate')
        for shard in a.shards:
            result = base.describe(app_name(shard))
            if result.get('returncode') == 0:
                row = json.loads(result['stdout']); print(json.dumps({k:row.get(k) for k in ('name','uid','state','ready_replicas')}))
            else: print(json.dumps({'name':app_name(shard),'state':'absent' if base.error_reason(result,'appNotFound') else 'unknown'}))
        return
    if not (a.prepare or a.live):
        template = yaml.safe_load(base.TEMPLATE.read_text())
        for shard in a.shards: build_config(template, shard)
        print(json.dumps({'live':False,'shards':a.shards,'cci_count':len(a.shards),'workers_per_cci':16,
                          'total_workers':16*len(a.shards),'model_calls':0,'cloud_api_calls':0})); return
    rows = prepare(a.shards)
    if not a.live: print(json.dumps({'prepared':len(rows),'model_calls':0,'cloud_api_calls':0})); return
    for record in rows:
        result = submit(record); print(json.dumps(result), flush=True)
        if result['state'] not in ('submitted','existing_request_never_repeated'):
            raise RuntimeError('Inspect unknown/rejected creation; never resubmit blindly')


if __name__ == '__main__': main()
