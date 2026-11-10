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
from bootstrap_visual_hosted_retry_v1 import DEFAULT_ROOT, load_validate
from run_bc_campaign_v3 import digest, atomic
from bc_route_runtime_v1 import immutable_json

ORIGINAL_CELLS = ('bc_hermes','bc_dsh','mmbc_vera','mmbc_vanilla','controlled_bc','controlled_mmbc',*('rq3_scale_'+s for s in ('0000','0250','0500','0700','0750','0800','1000')))
CELLS = ('bc_hermes','bc_dsh','mmbc_vanilla','rq3_scale_0000','rq3_scale_0700')
HARNESSES = CELLS
RECEIPTS = ROOT/'outputs/cloud-runtime/visual-hosted-failure-retry-ops2'
def launch_marker(harness, receipts=RECEIPTS):
    app_name(harness)
    return Path(receipts)/'markers'/(harness+'.json')


def app_name(harness):
    if harness not in HARNESSES: raise ValueError('Unapproved RQ3 scale')
    return 'acl-vhost-ops2-'+harness.replace('_','-')


def build_config(template, harness, root=DEFAULT_ROOT, marker=None):
    name = app_name(harness); root = Path(root).resolve()
    marker = Path(marker) if marker is not None else launch_marker(harness)
    if root != DEFAULT_ROOT.resolve(): raise ValueError('Wrong hosted campaign root')
    root = root/'cells'/harness
    selected_harness = 'dsh' if harness=='bc_dsh' else 'hermes'
    c = base.build_config(template, 'visual', root, marker)
    argv = ['/opt/conda/bin/python', str(ROOT/'scripts/bootstrap_visual_hosted_ops2.py'),
            '--root', str(root), '--harness', selected_harness, '--concurrency', '16',
            '--reader-python', '/opt/conda/bin/python', '--live']
    # The marker is a separate main-operator action after all bindings are checked.
    shell = 'while [ ! -f '+shlex.quote(str(marker))+' ]; do sleep 5; done; cd '+shlex.quote(str(ROOT))+' && '+shlex.join(argv)+'; exec sleep infinity'
    c['display_name'] = name
    c['template']['containers'][0].update(name='bounded-bc', command=['/bin/bash', '-c', shell])
    return c


def prepare(harnesses, root=DEFAULT_ROOT, receipts=RECEIPTS):
    if not harnesses or len(set(harnesses)) != len(harnesses): raise ValueError('Unique nonempty harnesses required')
    root, receipts = Path(root).resolve(), Path(receipts).resolve()
    for cell in harnesses: load_validate(root/'cells'/cell)
    template = yaml.safe_load(base.TEMPLATE.read_text()); records = []
    for harness in harnesses:
        directory = receipts/app_name(harness); directory.mkdir(parents=True, exist_ok=True)
        config = build_config(template, harness, root, launch_marker(harness, receipts))
        raw = yaml.safe_dump(config, sort_keys=False).encode(); path = directory/'config.yaml'
        if path.exists():
            if path.read_bytes() != raw: raise ValueError('Prepared configuration changed')
        else:
            with path.open('xb') as f: f.write(raw)
        record = {'name': app_name(harness), 'harness': harness, 'root': str(root/'cells'/harness),
                  'plan_sha256': digest((root/'cells'/harness/'plan.json').read_bytes()), 'config_path': str(path),
                  'config_sha256': digest(raw), 'template_sha256': digest(base.TEMPLATE.read_bytes()),
                  'bootstrap_sha256': digest((ROOT/'scripts/bootstrap_visual_hosted_ops2.py').read_bytes()),
                  'controller_wrapper_sha256':digest((ROOT/'scripts/run_visual_hosted_retry_ops2.py').read_bytes()),
                  'launcher_sha256': digest(Path(__file__).read_bytes()), 'concurrency': 16, 'cpu': 8, 'memory_gib': 32,
                  'launch_marker': str(launch_marker(harness, receipts)), 'automatic_repeat_allowed': False}
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
    p.add_argument('--harnesses', choices=HARNESSES, nargs='+', default=list(HARNESSES))
    p.add_argument('--prepare', action='store_true'); p.add_argument('--live', action='store_true')
    p.add_argument('--status', action='store_true'); a = p.parse_args()
    if len(set(a.harnesses)) != len(a.harnesses): p.error('Duplicate harness')
    if a.status:
        if a.live or a.prepare: p.error('Status cannot mutate')
        for harness in a.harnesses:
            result = base.describe(app_name(harness))
            if result.get('returncode') == 0:
                row = json.loads(result['stdout']); print(json.dumps({k:row.get(k) for k in ('name','uid','state','ready_replicas')}))
            else: print(json.dumps({'name':app_name(harness),'state':'absent' if base.error_reason(result,'appNotFound') else 'unknown'}))
        return
    if not (a.prepare or a.live):
        template = yaml.safe_load(base.TEMPLATE.read_text())
        for harness in a.harnesses: build_config(template, harness)
        print(json.dumps({'live':False,'harnesses':a.harnesses,'cci_count':len(a.harnesses),'workers_per_cci':16,
                          'total_workers':16*len(a.harnesses),'global_inference_cap':None,'individual_markers':True,'model_calls':0,'cloud_api_calls':0})); return
    rows = prepare(a.harnesses)
    if not a.live: print(json.dumps({'prepared':len(rows),'model_calls':0,'cloud_api_calls':0})); return
    for record in rows:
        result = submit(record); print(json.dumps(result), flush=True)
        if result['state'] not in ('submitted','existing_request_never_repeated'):
            raise RuntimeError('Inspect unknown/rejected creation; never resubmit blindly')


if __name__ == '__main__': main()
