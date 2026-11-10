#!/usr/bin/env python3
"""New MMBC protocol: bounded pages and final request guard; old workers unchanged."""
import argparse
import hashlib
import json
import io
from pathlib import Path

from lab import ROOT

PROTOCOL = 'bounded-multimodal-pages-v1'


def validate(spec, config, out):
    if spec.get('bounded_visual_protocol') != PROTOCOL or config.get('bounded_visual_protocol') != PROTOCOL:
        raise ValueError('A separately frozen bounded protocol is required')
    old_roots = [(ROOT / 'outputs/campaigns' / name).resolve() for name in (
        'mmbc100-hermes-deepseek-v1', 'mmbc100-hermes-vanilla-v1')]
    paths = [Path(out).resolve()]
    paths += [Path(spec[key]).resolve() for key in ('campaign_root', 'config_path') if spec.get(key)]
    if any(path.is_relative_to(old) for path in paths for old in old_roots):
        raise ValueError('Old scientific namespaces/configurations must remain immutable')
    if config.get('bounded_transport_encoding', 'png') not in ('png', 'bounded-canvas-lossless-webp-v1'):
        raise ValueError('Unknown explicit bounded transport encoding')
    if spec.get('strategy') not in ('none', 'discard', 'summarize', 'sliding_window', 'visual'):
        raise ValueError('Unknown bounded MMBC strategy')
    if spec.get('harness', 'hermes') != 'hermes':
        raise ValueError('Hermes worker cannot execute a different harness')
    if config.get('bounded_transport_encoding', 'png') not in ('png', 'bounded-canvas-lossless-webp-v1'):
        raise ValueError('Unknown bounded image encoding')
    if spec.get('config_sha256') is not None:
        if not spec.get('config_path') or hashlib.sha256(Path(spec['config_path']).read_bytes()).hexdigest() != spec['config_sha256']:
            raise ValueError('Frozen bounded configuration SHA mismatch')
    if any((out / name).exists() for name in ('attempt-started.json', 'native-result.json',
            'conversation.json', 'bounded-protocol.json', 'metrics/call-starts.jsonl')):
        raise ValueError('Existing bounded attempt cannot be overwritten or retried')
    if list((out / 'context_images').glob('compact_*_bounded_manifest.json')):
        raise ValueError('Existing rendered attempt cannot be reused')
    if spec.get('strategy') == 'visual':
        settings = config.get('shared_policy', {}).get('strategy_configs', {}).get('visual', {})
        required = {'font_size': 16, 'history_scale': .75, 'image_width': 1024,
                    'max_image_height': 2048, 'history_max_image_height': 2048}
        if any(settings.get(key) != value for key, value in required.items()):
            raise ValueError('Explicit bounded visual geometry differs from frozen protocol')
        if config.get('visual_renderer', {}).get('history_scale') != .75:
            raise ValueError('Ambiguous visual scale configuration')
    return True


def _verified_artifact(directory, value, sha):
    path = Path(value).resolve()
    if not path.is_relative_to(directory):
        raise ValueError('Canvas/source outside attempt directory')
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != sha:
        raise ValueError('Rendered/source artifact SHA mismatch')
    return raw


def _verified_png(directory, value, metadata):
    from PIL import Image
    raw = _verified_artifact(directory, value, metadata['sha256'])
    with Image.open(io.BytesIO(raw)) as image:
        if image.format != 'PNG' or list(image.size) != metadata['dimensions']:
            raise ValueError('Canvas/source PNG dimensions differ from manifest')
        image.verify()
    if metadata['bytes'] != len(raw):
        raise ValueError('Canvas/source byte count differs from manifest')
    return metadata['sha256']


def registered_pages(directory):
    """Verify complete source PDF/raw/final lineage before registering byte hashes."""
    result = set()
    verified_manifests = {}
    directory = directory.resolve()
    for path in directory.glob('compact_*_bounded_manifest.json'):
        if not path.resolve().is_relative_to(directory):
            raise ValueError('Manifest outside attempt directory')
        manifest_raw = path.read_bytes()
        manifest = json.loads(manifest_raw)
        if manifest.get('version') != PROTOCOL:
            raise ValueError('Unknown canvas lineage')
        layout = manifest['layout']
        required = {'width': 1024, 'max_page_side': 2048, 'font_size': 16, 'dpi': 72,
                    'far_scale': .75, 'recent_scale': 1., 'vertical_merge': False,
                    'far_pre_enlargement': False, 'fit_to_content_height': False}
        if any(layout.get(key) != value for key, value in required.items()):
            raise ValueError('Rendered manifest violates the declared bounded layout')
        sources = {}
        for source in manifest['source_pdfs']:
            segment = source['segment']
            if segment not in ('history', 'recent') or segment in sources:
                raise ValueError('Duplicate or unknown source segment')
            _verified_artifact(directory, source['path'], source['sha256'])
            sources[segment] = len(source['page_dimensions'])
        pages = manifest['pages']
        if not pages or len(pages) != manifest['output_image_count']:
            raise ValueError('Missing/incomplete rendered-page manifest')
        seen = {key: set() for key in sources}
        total_bytes = 0
        for item in pages:
            segment = item['segment']
            if segment not in sources or item['page_index'] in seen[segment]:
                raise ValueError('Unknown or repeated rendered page')
            seen[segment].add(item['page_index'])
            scale = .75 if segment == 'history' else 1.
            if item['scale'] != scale or item['detail'] != 'high' or item['segment_pages'] != sources[segment]:
                raise ValueError('Page scale/detail/count differs from source segment')
            _verified_png(directory, item['raw_path'], item['raw'])
            result.add(_verified_png(directory, item['path'], item['output']))
            if item['output']['dimensions'] != [max(1, int(d * scale)) for d in item['raw']['dimensions']]:
                raise ValueError('Page is not the declared one-step scale')
            total_bytes += item['output']['bytes']
        if any(seen[key] != set(range(1, count + 1)) for key, count in sources.items()):
            raise ValueError('Source PDF page missing from rendered manifest')
        if total_bytes != manifest['output_total_png_bytes']:
            raise ValueError('Rendered manifest byte total mismatch')
        verified_manifests[path.resolve()] = hashlib.sha256(manifest_raw).hexdigest()
    for path in directory.glob('compact_*_transport_manifest.json'):
        from PIL import Image
        if not path.resolve().is_relative_to(directory):
            raise ValueError('Transport manifest outside attempt directory')
        manifest = json.loads(path.read_text())
        verified_source_sha = verified_manifests.get(Path(manifest.get('source_bounded_manifest', '')).resolve())
        if verified_source_sha is None or verified_source_sha != manifest.get('source_bounded_manifest_sha256'):
            raise ValueError('Transport source is not a fully verified bounded manifest')
        if manifest.get('version') != 'bounded-canvas-lossless-webp-v1' or manifest.get('native_images_encoded') != 0:
            raise ValueError('Unknown or native-modifying transport encoding')
        bounded_raw = _verified_artifact(directory, manifest['source_bounded_manifest'], manifest['source_bounded_manifest_sha256'])
        bounded_pages = json.loads(bounded_raw)['pages']
        if len(manifest['pages']) != len(bounded_pages):
            raise ValueError('Transport encoding omitted a page')
        for item, source_page in zip(manifest['pages'], bounded_pages):
            if item['source_sha256'] not in result or item['source_sha256'] != source_page['output']['sha256']:
                raise ValueError('Encoded canvas has no ordered verified PNG source')
            source = _verified_artifact(directory, item['source_path'], item['source_sha256'])
            encoded = _verified_artifact(directory, item['path'], item['output_sha256'])
            with Image.open(io.BytesIO(source)) as a, Image.open(io.BytesIO(encoded)) as b:
                if b.format != 'WEBP' or a.size != b.size or list(b.size) != item['dimensions'] or a.convert('RGBA').tobytes() != b.convert('RGBA').tobytes():
                    raise ValueError('Encoded canvas pixel identity mismatch')
            result.add(item['output_sha256'])
    return result


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--spec', type=Path, required=True); parser.add_argument('--out', type=Path, required=True)
    args, _ = parser.parse_known_args()
    spec = json.loads(args.spec.read_text()); config = json.loads(Path(spec['config_path']).read_text())
    out = args.out.resolve(); validate(spec, config, out)
    import hermes_bc_worker_v3 as native
    from mmbc_input_images import stage_images
    from bounded_visual_request_guard_v1 import install as install_guard
    original = native.configure_engine

    def configure(engine, strategy, policy):
        original(engine, strategy, policy)
        if strategy == 'visual':
            from plugins.context_engine.visual import render
            from bounded_multimodal_renderer_v1 import install
            install(render)
            if getattr(engine, '_text_only', False):
                from mmbc_vanilla_renderer import install as vanilla_install
                vanilla_install(render)
            if config.get('bounded_transport_encoding') == 'bounded-canvas-lossless-webp-v1':
                from bounded_lossless_transport_v1 import install as encoding_install
                encoding_install(render)
            if getattr(engine, '_history_scale', None) != .75:
                raise ValueError('Live engine differs from declared far-history scale')
        install_guard(out / 'metrics/bounded-request-guard.jsonl',
                      rendered_registry=lambda: registered_pages(out / 'context_images'))
        out.mkdir(parents=True, exist_ok=True)
        (out / 'bounded-protocol.json').write_text(json.dumps({
            'version': PROTOCOL, 'far_scale': .75, 'recent_scale': 1., 'max_canvas_size': [1024, 2048],
            'detail': 'high', 'vertical_merge': False, 'guard_max_request_bytes': 8 * 1024 * 1024,
            'guard_max_images': 32, 'native_pixels_unchanged': True, 'variant_not_original_protocol': True,
            'transport_encoding': config.get('bounded_transport_encoding', 'png'),
            'implementation_sha256': {name: hashlib.sha256((ROOT / 'scripts' / name).read_bytes()).hexdigest()
                for name in ('hermes_bounded_mmbc_worker_v1.py', 'bounded_multimodal_renderer_v1.py', 'bounded_visual_request_guard_v1.py', 'bounded_lossless_transport_v1.py')}
        }, indent=2))

    original_stage = native.stage_images
    native.stage_images, native.configure_engine = stage_images, configure
    try:
        native.main()
    finally:
        native.stage_images, native.configure_engine = original_stage, original


if __name__ == '__main__': main()
