"""Inline-only, lossless transport for V14 stages that have never started.

Every old scientific stage is checked before encoding/fingerprint generation.
Old success, failure and unknown acceptance all consume its one-call allowance.
No old result, image, dimensions, detail, model or scientific prompt is changed.
"""
import argparse
import copy
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

import httpx
import info_loss_single_pass_v14 as base
from bounded_lossless_transport_v1 import encode
from lab import ROOT

VERSION = 'info-loss-inline-lossless-ops-v15'
PARENT = base.DEFAULT
DEFAULT = ROOT / 'outputs/experiment6/single-pass-inline-lossless-v15'
EXIT = ROOT / 'outputs/cloud-runtime/deepseek-once24h-v15-info/worker-exited.json'
REQUEST_WALL_SECONDS = 630
ORIGINAL_CALL = base.call_once
ORIGINAL_PAYLOAD = base.payload


def stage_id(condition, stage): return condition['case'] + '/' + condition['method'] + '/' + stage


def previous_stage(plan, condition, stage):
    """Logical identity precedes any new wire encoding or payload fingerprint."""
    entry = plan['prior_stage_ledger'].get(stage_id(condition, stage))
    if entry is None: return None
    if entry.get('response'):
        return base.bound_read(entry['response'])
    return {'status': 'unknown_prior_start', 'content': '', 'usage': None,
            'previous_started': entry['started'], 'new_api_call': False}


def prepare(root):
    if (root / 'plan.json').exists(): raise ValueError('Plan already frozen')
    if not (PARENT / 'STOP').exists() or not EXIT.exists(): raise ValueError('Old CCI must drain before ledger freeze')
    retired = base.read(EXIT); launched = base.read(EXIT.with_name('worker-started.json'))
    if retired.get('worker_reaped') is not True or retired.get('pid') != launched.get('pid') or retired.get('hostname') != launched.get('hostname'):
        raise ValueError('Old worker exit identity not confirmed')
    if launched.get('plan_sha256') != base.sha(PARENT / 'plan.json'):
        raise ValueError('Old worker did not use this scientific plan')
    old = base.read(PARENT / 'plan.json'); ledger = {}
    for start in PARENT.glob('calls/*/*/*/started.json'):
        key = '/'.join(start.relative_to(PARENT / 'calls').parts[:3]); response = start.parent / 'response.json'
        ledger[key] = {'started': base.binding(start), 'response': base.binding(response) if response.exists() else None}
    needed = {}; maximum = 0
    for c in old['conditions']:
        for stage in ['qa', 'reconstruction', 'judge']:
            eligible = stage == 'judge' or c['reuse'][stage] is None
            if not eligible or stage_id(c, stage) in ledger: continue
            maximum += 1
            if stage != 'judge':
                for item in c['representation'].get('images', []): needed[item['sha256']] = item
    if maximum + len(ledger) > old['maximum_new_calls']: raise ValueError('Original 90-stage cap exceeded')
    images = {}; proofs = []; started = time.monotonic()
    for digest, item in sorted(needed.items()):
        if base.sha(item['path']) != digest: raise ValueError('Frozen source PNG changed')
        raw, proof = encode(Path(item['path']).read_bytes())
        if proof['dimensions'] != [item['width'], item['height']]: raise ValueError('Original dimension metadata differs from actual pixels')
        path = root / 'wire-images' / (digest + '.webp'); path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as stream: stream.write(raw)
        images[digest] = {**item, 'path': str(path), 'sha256': proof['output_sha256'], 'media_type': 'image/webp'}
        proofs.append({**proof, 'source_path': item['path'], 'output_path': str(path), 'detail': item['detail']})
    plan = copy.deepcopy(old)
    plan.update(operational_version=VERSION, operational_parent=base.binding(PARENT / 'plan.json'),
        old_exit_proof=base.binding(EXIT), prior_stage_ledger=ledger, wire_images=images,
        encoding_proofs=proofs, offline_encoding_seconds=time.monotonic()-started,
        maximum_new_calls=maximum, prior_v14_started_calls=len(ledger), combined_v14_v15_call_cap=old['maximum_new_calls'],
        write_timeout_seconds=300, read_timeout_seconds=300, request_hard_wall_seconds=REQUEST_WALL_SECONDS,
        original_dimensions_detail_order_preserved=True, image_hosting=False, url_transport=False)
    plan['source_sha256'] = {name: base.sha(ROOT / 'scripts' / name) for name in
        [Path(__file__).name, 'info_loss_single_pass_v14.py', 'bounded_lossless_transport_v1.py', 'network_entry_v13.py']}
    base.save(root / 'plan.json', plan)
    return plan


def converted_payload(plan, prompt, images, model):
    converted = []
    for item in images:
        if base.sha(item['path']) != item['sha256']: raise ValueError('Original PNG changed')
        replacement = plan['wire_images'][item['sha256']]
        for key in ['width', 'height', 'detail']:
            if replacement[key] != item[key]: raise ValueError('Scientific image setting changed')
        converted.append(replacement)
    return ORIGINAL_PAYLOAD(prompt, converted, model)


def child(root, specpath):
    plan = base.read(root / 'plan.json'); spec = base.read(specpath)
    for name, digest in plan['source_sha256'].items():
        if base.sha(ROOT / 'scripts' / name) != digest: raise ValueError('Frozen operational source changed')
    if previous_stage(plan, spec['condition'], spec['stage']) is not None: raise ValueError('Old stage must not spawn a new HTTP request')
    cls = httpx.Client
    def client(*args, **kwargs):
        kwargs['timeout'] = httpx.Timeout(connect=20, write=300, read=300, pool=20)
        return cls(*args, **kwargs)
    with patch.object(base, 'payload', lambda prompt, images, model: converted_payload(plan, prompt, images, model)), \
            patch.object(base.httpx, 'Client', client):
        response = ORIGINAL_CALL(root, spec['condition'], spec['stage'], spec['prompt'], spec['images'], spec['model'])
    base.save(specpath.parent / 'child-return.json', response)


def bounded_call(plan, root, condition, stage, prompt, images, model):
    previous = previous_stage(plan, condition, stage)
    if previous is not None:
        base.save(root / 'reused-v14' / stage_id(condition, stage) / 'source.json', plan['prior_stage_ledger'][stage_id(condition, stage)])
        return previous
    folder = root / 'calls' / stage_id(condition, stage)
    if (folder / 'response.json').exists(): return base.read(folder / 'response.json')
    if (folder / 'launch-started.json').exists() or (folder / 'started.json').exists():
        return {'status': 'unknown_prior_start', 'content': '', 'usage': None}
    if (root / 'STOP').exists(): return {'status': 'not_started_stop', 'content': ''}
    if time.time() + REQUEST_WALL_SECONDS > base.ABSOLUTE_DEADLINE:
        return {'status': 'not_started_deadline', 'content': ''}
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / 'launch-started.json').open('x') as stream:
        json.dump({'at': time.time(), 'logical_stage': stage_id(condition, stage), 'previous_started': False,
                   'max_http_attempts': 1, 'hard_wall_seconds': REQUEST_WALL_SECONDS}, stream)
    specpath = folder / 'request-spec.json'
    base.save(specpath, {'condition': {'case': condition['case'], 'method': condition['method']},
        'stage': stage, 'prompt': prompt, 'images': images, 'model': model})
    command = [sys.executable, str(ROOT / 'scripts/network_entry_v13.py'), '--target', str(Path(__file__).resolve()),
        '--root', str(root), '--http-child', str(specpath)]
    with (folder / 'transport.log').open('a') as log:
        process = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        try: process.wait(timeout=REQUEST_WALL_SECONDS)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGTERM)
            try: process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL); process.wait()
            if not (folder / 'response.json').exists():
                base.save(folder / 'response.json', {'status': 'request_wall_timeout', 'content': '', 'usage': None,
                    'provider_api_seconds': None, 'request_acceptance_unknown': True, 'automatic_retry': False})
    if (folder / 'response.json').exists(): return base.read(folder / 'response.json')
    if (folder / 'child-return.json').exists(): return base.read(folder / 'child-return.json')
    return {'status': 'child_failed_or_unknown', 'content': '', 'usage': None, 'exit_code': process.returncode}


def main():
    p = argparse.ArgumentParser(); p.add_argument('--root', type=Path, default=DEFAULT)
    p.add_argument('--prepare', action='store_true'); p.add_argument('--live', action='store_true')
    p.add_argument('--concurrency', type=int, default=4); p.add_argument('--http-child', type=Path)
    args = p.parse_args(); root = args.root.resolve()
    if args.http_child: child(root, args.http_child); return
    plan = prepare(root) if args.prepare else base.read(root / 'plan.json')
    if not args.live:
        print(json.dumps({'live': False, 'remaining_new_calls_cap': plan['maximum_new_calls'],
                         'old_stages_never_retried': len(plan['prior_stage_ledger']), 'encoded_images': len(plan['wire_images'])})); return
    sys.argv = [base.__file__, '--root', str(root), '--concurrency', str(args.concurrency), '--live']
    with patch.object(base, 'call_once', lambda *a, **kw: bounded_call(plan, *a, **kw)):
        base.main()


if __name__ == '__main__': main()
