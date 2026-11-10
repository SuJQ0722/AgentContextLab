#!/usr/bin/env python3
"""Freeze the original eligible fixed prefixes for bounded native continuation; no API calls."""
import argparse
import json
from pathlib import Path
from collections import Counter
from lab import ROOT
from prepare_mmbc100_campaign import immutable, immutable_json, sha, implementation_hashes
from controlled_native_worker_bounded_v1 import PROTOCOL, OUTPUT_ROOT
from controlled_native_worker_v5 import native_parts, image_ids
from capture_multimodal_prefix import image_ledger

VERSION = 'controlled-native-bounded-v1'
DEFAULT = OUTPUT_ROOT
SOURCE = ROOT/'outputs/experiment3/controlled-native-v4'
MODEL = 'deepseek-v4.1-flash-1017/huoshan/huoshan'
ENCODING = 'bounded-canvas-lossless-webp-v1'
SOURCES = ('prepare_controlled_bounded_v1.py', 'run_controlled_bounded_v1.py',
    'controlled_native_worker_bounded_v1.py', 'controlled_native_worker_v5.py',
    'capture_multimodal_prefix_v5.py', 'controlled_transport_v5.py',
    'controlled_native_guard_v4.py', 'controlled_native_preflight.py',
    'bounded_multimodal_renderer_v1.py', 'bounded_lossless_transport_v1.py',
    'bounded_visual_request_guard_v1.py', 'rq3_pdf_renderer.py',
    'controlled_native_report_v4.py', 'experiment_admission_v4.py', 'admission_lock_ops1.py')


def read(p): return json.loads(Path(p).read_text())


def audit_prefix(entry):
    p = Path(entry['spec']['prefix_path'])
    record = {'key': entry['key'], 'dataset': entry['spec']['dataset'],
        'pilot': entry['pilot'], 'source_prefix_path': str(p), 'eligible': False}
    if not p.is_file():
        blocked = p.with_name('blocked.json')
        record.update(reason='original_prefix_unavailable',
            original_blocked=read(blocked) if blocked.exists() else None)
        return record
    manifest_path = p.with_name('manifest.json')
    manifest = read(manifest_path)
    if sha(p) != manifest['prefix_sha256']: raise ValueError('Original prefix SHA mismatch')
    request = read(p); native = native_parts(request['messages'])
    ledger = image_ledger(request['messages'])
    if not native or not ledger or any(not r['inline'] for r in ledger):
        raise ValueError('Existing prefix does not contain fully frozen native evidence')
    if ledger != manifest['native_ledger']: raise ValueError('Original native ledger mismatch')
    count = manifest.get('measured_prompt_tokens')
    if not isinstance(count, int) or count < entry['spec']['threshold']:
        raise ValueError('Original prefix threshold measurement absent')
    record.update(eligible=True, prefix_sha256=sha(p), source_model=request.get('model'),
        source_manifest_path=str(manifest_path), source_manifest_sha256=sha(manifest_path),
        measured_prompt_tokens=count, native_hashes=image_ids(native), native_parts=len(native))
    return record


def prepare(root=DEFAULT):
    root = Path(root).resolve()
    if root != DEFAULT.resolve(): raise ValueError('Fixed independent namespace required')
    source_plan = SOURCE/'plan.json'; old = read(source_plan)
    if len(old['prefixes']) != 60 or len(old['jobs']) != 180: raise ValueError('Original cohort differs')
    records = [audit_prefix(p) for p in old['prefixes']]
    by_key = {r['key']: r for r in records}
    cfg = read(SOURCE/'experiment.json')
    if read(ROOT/'configs/experiment.json')['model'] != MODEL: raise ValueError('Unexpected reviewed route')
    cfg.update(model=MODEL, controlled_protocol=VERSION)
    immutable_json(root/'experiment.json', cfg)
    immutable_json(root/'prefix-selection.json', {'records': records,
        'selection': 'All available original measured prefixes; no correctness or old fitting outcome selection',
        'no_replacement_questions': True})
    jobs = []
    for p in old['prefixes']:
        rec = by_key[p['key']]
        if rec['eligible']:
            dest = root/'prefixes'/p['key']/'prefix.json'
            immutable(dest, Path(rec['source_prefix_path']).read_bytes())
    for j in old['jobs']:
        rec = by_key[j['prefix_key']]
        source = next(p['spec'] for p in old['prefixes'] if p['key'] == j['prefix_key'])
        job = dict(j, eligible=rec['eligible'], out=str(root/'jobs'/j['job_id']))
        if rec['eligible']:
            spec = dict(source, model=MODEL, config_path=str(root/'experiment.json'),
                method=j['method'], source_prefix_model=rec['source_model'],
                explicit_route_migration=rec['source_model'] != MODEL,
                protocolversion=VERSION, bounded_native_protocol=PROTOCOL,
                bounded_transport_encoding=ENCODING,
                prefix_path=str(root/'prefixes'/j['prefix_key']/'prefix.json'),
                source_parent_plan_path=str(source_plan), source_parent_plan_sha256=sha(source_plan),
                source_parent_job_id=j['job_id'])
            if j['method'] != 'visual':
                spec['target_reference_path'] = str(root/'jobs'/j['prefix_key']/'visual/compression-control.json')
            path = Path(job['out'])/'spec.json'; immutable_json(path, spec)
            job.update(spec_path=str(path), spec_sha256=sha(path))
        jobs.append(job)
    sources = implementation_hashes()
    sources.update({'scripts/'+n: sha(ROOT/'scripts'/n) for n in SOURCES})
    definition = {'version': VERSION, 'source_plan_path': str(source_plan), 'source_plan_sha256': sha(source_plan),
        'config_sha256': sha(root/'experiment.json'), 'selection_sha256': sha(root/'prefix-selection.json'),
        'implementation_sha256': sources, 'planned_original_arms': 180,
        'eligible_arms': sum(j['eligible'] for j in jobs), 'local_concurrency_cap': 1,
        'timeout_seconds': 3600, 'new_attempts_per_arm': 1, 'model': MODEL,
        'protocol': PROTOCOL, 'transport_encoding': ENCODING,
        'interpretation': 'New fixed-prefix conditional subset; single intervention, no old/new best-attempt union',
        'old_costs': {'source_root': str(SOURCE), 'all_prior_attempts_retained': True,
            'original_costs_reaggregated': False, 'combined_old_new_total': None}}
    immutable_json(root/'plan.json', {'definition': definition, 'prefixes': records, 'jobs': jobs})
    immutable_json(root/'manifest.json', {'version': VERSION, 'plan_sha256': sha(root/'plan.json'),
        'eligible_groups': sum(r['eligible'] for r in records), 'eligible_arms': definition['eligible_arms'],
        'by_dataset': {ds: dict(Counter('eligible' if r['eligible'] else 'unavailable' for r in records if r['dataset']==ds))
            for ds in {r['dataset'] for r in records}}, 'paid_calls': 0})
    return load_validate(root)[1]


def load_validate(root=DEFAULT):
    root = Path(root).resolve(); plan = read(root/'plan.json'); manifest = read(root/'manifest.json'); d = plan['definition']
    if root != DEFAULT.resolve() or manifest['plan_sha256'] != sha(root/'plan.json'): raise ValueError('Plan binding changed')
    for path, expected in [(root/'experiment.json', d['config_sha256']),
        (root/'prefix-selection.json', d['selection_sha256']), (Path(d['source_plan_path']), d['source_plan_sha256'])]:
        if sha(path) != expected: raise ValueError('Frozen input changed: '+str(path))
    if d['version'] != VERSION or d['protocol'] != PROTOCOL or d['model'] != MODEL: raise ValueError('Protocol differs')
    for n, expected in d['implementation_sha256'].items():
        if sha(ROOT/n) != expected: raise ValueError('Frozen implementation changed: '+n)
    for r in plan['prefixes']:
        if r['eligible']:
            for p in [Path(r['source_prefix_path']), root/'prefixes'/r['key']/'prefix.json']:
                if sha(p) != r['prefix_sha256']: raise ValueError('Frozen prefix changed')
            if sha(r['source_manifest_path']) != r['source_manifest_sha256']: raise ValueError('Source manifest changed')
    for j in plan['jobs']:
        if j['eligible'] and sha(j['spec_path']) != j['spec_sha256']: raise ValueError('Spec changed')
    return plan, manifest


def main():
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('--prepare', action='store_true'); p.add_argument('--validate', action='store_true'); a=p.parse_args()
    print(json.dumps(prepare() if a.prepare else load_validate()[1] if a.validate else {'live':False, 'model_calls':0}))

if __name__ == '__main__': main()
