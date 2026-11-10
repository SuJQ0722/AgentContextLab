#!/usr/bin/env python3
"""Prepare/submit seven CCI scale instances for bounded RQ3 retries; offline by default."""
import argparse
import json
from pathlib import Path
import shlex
import time
import yaml

import provision_mmbc_cci_v1 as base
from lab import ROOT
from bootstrap_rq3_bounded_retry_v1 import DEFAULT_ROOT, SCALE_KEYS, load_validate
from run_bc_campaign_v3 import digest, atomic
from bc_route_runtime_v1 import immutable_json

RECEIPTS = ROOT/'outputs/cloud-runtime/rq3-bounded-failure-retry-v1'
def launch_marker(scale_key, receipts=RECEIPTS):
    app_name(scale_key)
    return Path(receipts)/'markers'/(scale_key+'.json')


def app_name(scale_key):
    if scale_key not in SCALE_KEYS: raise ValueError('Unapproved RQ3 scale')
    return 'acl-rq3-bounded-r1-s'+scale_key.removeprefix('scale_')


def build_config(template, scale_key, root=DEFAULT_ROOT, marker=None):
    name = app_name(scale_key); root = Path(root).resolve()
    marker = Path(marker) if marker is not None else launch_marker(scale_key)
    if root != DEFAULT_ROOT.resolve(): raise ValueError('Wrong bounded campaign root')
    c = base.build_config(template, 'visual', root, marker)
    argv = ['/opt/conda/bin/python', str(ROOT/'scripts/bootstrap_rq3_bounded_retry_v1.py'),
            '--root', str(root), '--scale-key', str(scale_key), '--concurrency', '16',
            '--reader-python', '/opt/conda/bin/python', '--live']
    # The marker is a separate main-operator action after all bindings are checked.
    shell = 'while [ ! -f '+shlex.quote(str(marker))+' ]; do sleep 5; done; cd '+shlex.quote(str(ROOT))+' && '+shlex.join(argv)+'; exec sleep infinity'
    c['display_name'] = name
    c['template']['containers'][0].update(name='bounded-rq3', command=['/bin/bash', '-c', shell])
    return c


def prepare(scale_keys, root=DEFAULT_ROOT, receipts=RECEIPTS):
    if not scale_keys or len(set(scale_keys)) != len(scale_keys): raise ValueError('Unique nonempty scale_keys required')
    root, receipts = Path(root).resolve(), Path(receipts).resolve()
    load_validate(root)
    template = yaml.safe_load(base.TEMPLATE.read_text()); records = []
    for scale_key in scale_keys:
        directory = receipts/app_name(scale_key); directory.mkdir(parents=True, exist_ok=True)
        config = build_config(template, scale_key, root, launch_marker(scale_key, receipts))
        raw = yaml.safe_dump(config, sort_keys=False).encode(); path = directory/'config.yaml'
        if path.exists():
            if path.read_bytes() != raw: raise ValueError('Prepared configuration changed')
        else:
            with path.open('xb') as f: f.write(raw)
        record = {'name': app_name(scale_key), 'scale_key': scale_key, 'root': str(root),
                  'plan_sha256': digest((root/'plan.json').read_bytes()), 'config_path': str(path),
                  'config_sha256': digest(raw), 'template_sha256': digest(base.TEMPLATE.read_bytes()),
                  'bootstrap_sha256': digest((ROOT/'scripts/bootstrap_rq3_bounded_retry_v1.py').read_bytes()),
                  'launcher_sha256': digest(Path(__file__).read_bytes()), 'concurrency': 16, 'cpu': 8, 'memory_gib': 32,
                  'launch_marker': str(launch_marker(scale_key, receipts)), 'automatic_repeat_allowed': False}
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
    p.add_argument('--scale-keys', choices=SCALE_KEYS, nargs='+', default=list(SCALE_KEYS))
    p.add_argument('--prepare', action='store_true'); p.add_argument('--live', action='store_true')
    p.add_argument('--status', action='store_true'); a = p.parse_args()
    if len(set(a.scale_keys)) != len(a.scale_keys): p.error('Duplicate scale_key')
    if a.status:
        if a.live or a.prepare: p.error('Status cannot mutate')
        for scale_key in a.scale_keys:
            result = base.describe(app_name(scale_key))
            if result.get('returncode') == 0:
                row = json.loads(result['stdout']); print(json.dumps({k:row.get(k) for k in ('name','uid','state','ready_replicas')}))
            else: print(json.dumps({'name':app_name(scale_key),'state':'absent' if base.error_reason(result,'appNotFound') else 'unknown'}))
        return
    if not (a.prepare or a.live):
        template = yaml.safe_load(base.TEMPLATE.read_text())
        for scale_key in a.scale_keys: build_config(template, scale_key)
        print(json.dumps({'live':False,'scale_keys':a.scale_keys,'cci_count':len(a.scale_keys),'workers_per_cci':16,
                          'total_workers':16*len(a.scale_keys),'release_requires_global_inference_cap':128,'individual_markers':True,'model_calls':0,'cloud_api_calls':0})); return
    rows = prepare(a.scale_keys)
    if not a.live: print(json.dumps({'prepared':len(rows),'model_calls':0,'cloud_api_calls':0})); return
    for record in rows:
        result = submit(record); print(json.dumps(result), flush=True)
        if result['state'] not in ('submitted','existing_request_never_repeated'):
            raise RuntimeError('Inspect unknown/rejected creation; never resubmit blindly')


if __name__ == '__main__': main()
