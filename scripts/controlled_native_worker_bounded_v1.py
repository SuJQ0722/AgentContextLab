#!/usr/bin/env python3
"""Opt-in bounded-page control; v5 budget calibration and native loop unchanged.

No paid call by default. This is a new protocol, never a repair of old results.
"""
import argparse
import base64
import copy
import fcntl
import hashlib
import io
import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch

from lab import ROOT
import controlled_native_worker_v5 as v5

VERSION = 'controlled-native-bounded-v1'
OUTPUT_ROOT = ROOT / 'outputs/experiment3/controlled-native-bounded-v1'
PROTOCOL = {
    'version': VERSION, 'base_page_width': 1024, 'base_page_height': 1536,
    'font_size': 16, 'dpi': 72, 'base_history_scale': .75,
    'keep_rounds': 0, 'recent_rounds': 0, 'detail': 'high',
    'page_merge': False, 'native_payload_policy': 'preserve bytes and detail',
    'budget_fit_scales': [1., .75, .5, .25], 'ceiling': 16384,
    'actual_text_arm_match_fraction': .02,
    'table_policy': 'preserve structured table content',
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def raw(part):
    return base64.b64decode(part['image_url']['url'].split(',', 1)[1], validate=True)


def fit_part(part, scale):
    """Exactly v5's PNG fit transform; originals are never passed here."""
    from PIL import Image
    result = copy.deepcopy(part)
    if scale != 1:
        with Image.open(io.BytesIO(raw(part))) as image:
            image = image.resize((max(1, round(image.width * scale)), max(1, round(image.height * scale))), Image.Resampling.LANCZOS)
            buf = io.BytesIO(); image.save(buf, format='PNG')
        result['image_url']['url'] = 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode()
    return result


def validate_spec(spec, out):
    if spec.get('bounded_native_protocol') != PROTOCOL:
        raise ValueError('Explicit bounded native protocol required')
    if spec.get('bounded_transport_encoding') not in (None, 'bounded-canvas-lossless-webp-v1'):
        raise ValueError('Unknown canvas transport encoding')
    if not out.resolve().is_relative_to(OUTPUT_ROOT.resolve()) or out.resolve() == OUTPUT_ROOT.resolve():
        raise ValueError('New bounded output namespace required')
    plan_path = Path(spec['source_parent_plan_path'])
    if sha(plan_path.read_bytes()) != spec['source_parent_plan_sha256']:
        raise ValueError('Parent plan SHA mismatch')
    plan = json.loads(plan_path.read_text())
    jobs = [j for j in plan['jobs'] if j['job_id'] == spec['source_parent_job_id']]
    if len(jobs) != 1 or jobs[0]['method'] != spec['method']:
        raise ValueError('Original cohort job mismatch')
    source = next(p['spec'] for p in plan['prefixes'] if p['key'] == jobs[0]['prefix_key'])
    for field in ('question', 'question_id', 'dataset', 'image', 'repeat', 'threshold', 'max_rounds'):
        if source.get(field) != spec.get(field):
            raise ValueError('Original cohort field mismatch: ' + field)
    old_prefix = Path(source['prefix_path'])
    if not old_prefix.is_file() or sha(old_prefix.read_bytes()) != sha(Path(spec['prefix_path']).read_bytes()):
        raise ValueError('Original eligible prefix unavailable or changed')
    if spec['method'] != 'visual':
        refpath = Path(spec['target_reference_path']).resolve()
        if not refpath.is_relative_to(OUTPUT_ROOT.resolve()):
            raise ValueError('Old protocol target prohibited')
        reference = json.loads(refpath.read_text())
        if reference.get('bounded_native_protocol') != PROTOCOL:
            raise ValueError('Target must use the same new bounded protocol')
        if reference.get('bounded_transport_encoding') != spec.get('bounded_transport_encoding'):
            raise ValueError('Target transport encoding differs')
    return source


class BoundedAdapter:
    def __init__(self, spec, out):
        self.spec, self.out = spec, out
        self.registry = set()
        self.variants = {}
        self.render_stats = {}
        self.encoding_cache = {}
        self.encoding_seconds = 0.0
        self.native = v5.native_parts(json.loads(Path(spec['prefix_path']).read_text())['messages'])
        self.native_ids = v5.image_ids(self.native)
        self.original_compose, self.original_write = v5.compose, v5.write

    def set_pages(self, pages):
        if not pages:
            raise ValueError('Bounded rendering produced no pages')
        self.variants = {scale: [sha(raw(fit_part(p, scale))) for p in pages]
                         for scale in PROTOCOL['budget_fit_scales']}

    def render_prefix(self, messages, font_size):
        from bounded_multimodal_renderer_v1 import render_visual_compression
        sys.path.insert(0, str(ROOT / 'hermes-agent'))
        from plugins.context_engine.visual import render
        import rq3_pdf_renderer
        rq3_pdf_renderer.install(render)
        if font_size != 16:
            raise ValueError('Unexpected font size')
        started = time.monotonic()
        # Native evidence is retained separately in all three arms. Prevent
        # tool-reference extraction from duplicating those pictures in text pages.
        with patch.object(render, '_image_candidates', return_value=[]):
            result = render_visual_compression(
                render, messages, head_end=0, image_width=1024, font_size=16,
                max_image_height=1536, history_max_image_height=1536, dpi=72,
                history_scale=.75, keep_rounds=0, recent_rounds=0,
                save_dir=str(self.out / 'bounded-render'), compact_count=1,
                stats=self.render_stats, max_page_side=2048,
                far_detail='high', recent_detail='high')
        pages = [copy.deepcopy(p) for m in result for p in m.get('content', [])
                 if isinstance(m.get('content'), list) and isinstance(p, dict) and p.get('type') == 'image_url']
        self.set_pages(pages)
        self.original_write(self.out / 'bounded-render-stats.json', self.render_stats)
        return pages, time.monotonic() - started

    def compose(self, current, question, native, representation):
        if v5.image_ids(native) != self.native_ids:
            raise ValueError('Original native pixels/detail changed')
        images = [p for p in representation if p.get('type') == 'image_url']
        if images:
            ids = [sha(raw(p)) for p in images]
            matching = [scale for scale, expected in self.variants.items() if ids == expected]
            if not matching or any(p['image_url'].get('detail') != 'high' for p in images):
                raise ValueError('Unknown, reordered, missing or altered canvas pages')
            # Register the actual post-fit bytes, not merely the base .75 pages.
            wire_ids = ids
            encoding_records = []
            if self.spec.get('bounded_transport_encoding'):
                from bounded_lossless_transport_v1 import encode_part
                converted = []
                for part, identity in zip(images, ids):
                    if identity not in self.encoding_cache:
                        started = time.monotonic()
                        encoded_part, encoded_raw, proof = encode_part(part)
                        elapsed = time.monotonic() - started
                        self.encoding_seconds += elapsed
                        self.encoding_cache[identity] = (encoded_part, {**proof, 'encoding_seconds': elapsed})
                        directory = self.out / 'bounded-transport'; directory.mkdir(parents=True, exist_ok=True)
                        (directory / (proof['output_sha256'] + '.webp')).write_bytes(encoded_raw)
                    encoded_part, proof = self.encoding_cache[identity]
                    converted.append(copy.deepcopy(encoded_part)); encoding_records.append(proof)
                iterator = iter(converted)
                representation = [next(iterator) if p.get('type') == 'image_url' else copy.deepcopy(p) for p in representation]
                wire_ids = [sha(raw(p)) for p in converted]
            self.registry.update(wire_ids)
            self.out.mkdir(parents=True, exist_ok=True)
            with (self.out / 'bounded-fit-registrations.jsonl').open('a') as stream:
                stream.write(json.dumps({'base_scale': .75, 'matching_fit_scales': matching,
                    'effective_linear_scales': [.75 * s for s in matching],
                    'source_png_sha256': ids, 'canvas_sha256': wire_ids,
                    'transport_encoding': self.spec.get('bounded_transport_encoding'),
                    'encoding_proofs': encoding_records, 'cumulative_encoding_seconds': self.encoding_seconds,
                    'native_identity_verified': True}) + '\n')
        return self.original_compose(current, question, native, representation)

    def annotate(self, value):
        value = copy.deepcopy(value)
        value['bounded_native_protocol'] = PROTOCOL
        value['runtime_maintenance'] = VERSION
        value['bounded_transport_encoding'] = self.spec.get('bounded_transport_encoding')
        value['canvas_encoding_seconds'] = self.encoding_seconds
        scale = value.get('canvas_scale')
        value['bounded_base_scale'] = .75
        value['budget_fit_scale'] = scale
        value['effective_canvas_linear_scale'] = .75 * scale if isinstance(scale, (float, int)) else None
        return value

    def write(self, path, value):
        if Path(path).name == 'compression-control.json':
            value = self.annotate(value)
        elif Path(path).name == 'result.json' and 'control_gate' in value:
            value = copy.deepcopy(value); value['control_gate'] = self.annotate(value['control_gate'])
            value['protocol'] = VERSION
        return self.original_write(path, value)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--spec', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--live', action='store_true')
    args = ap.parse_args(); spec = json.loads(args.spec.read_text()); out = args.out.resolve()
    validate_spec(spec, out)
    if not args.live:
        print(json.dumps({'live': False, 'protocol': PROTOCOL, 'source_validated': True})); return
    out.mkdir(parents=True, exist_ok=True)
    lease = (out / 'worker.lock').open('a'); fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
    if (out / 'worker-started.json').exists() or (out / 'result.json').exists():
        raise SystemExit('Prior attempt retained; no automatic paid retry')
    adapter = BoundedAdapter(spec, out)
    from bounded_visual_request_guard_v1 import install
    install(out / 'bounded-wire-guard.jsonl', rendered_registry=lambda: adapter.registry)
    sources = ['controlled_native_worker_bounded_v1.py', 'bounded_multimodal_renderer_v1.py',
        'bounded_visual_request_guard_v1.py', 'bounded_lossless_transport_v1.py', 'rq3_pdf_renderer.py', 'controlled_native_worker_v5.py',
        'capture_multimodal_prefix_v5.py', 'controlled_transport_v5.py', 'controlled_native_guard_v4.py',
        'controlled_native_preflight.py']
    v5.write(out / 'bounded-protocol.json', {'protocol': PROTOCOL, 'spec_sha256': sha(args.spec.read_bytes()),
        'config_sha256': sha(Path(spec['config_path']).read_bytes()),
        'prefix_sha256': sha(Path(spec['prefix_path']).read_bytes()),
        'sources_sha256': {name: sha((ROOT / 'scripts' / name).read_bytes()) for name in sources},
        'calibration_and_native_retry_policy': 'unchanged from frozen v5', 'new_paid_retry_loop': False})
    with (out / 'worker-started.json').open('x') as stream:
        json.dump({'pid': os.getpid(), 'started_at': time.time(), 'protocol': VERSION}, stream)
    with patch.object(v5, 'render_prefix', adapter.render_prefix), patch.object(v5, 'compose', adapter.compose), patch.object(v5, 'write', adapter.write):
        v5.run(spec, out)


if __name__ == '__main__':
    main()
