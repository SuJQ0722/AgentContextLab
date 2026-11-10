#!/usr/bin/env python3
"""BC Hermes wrapper: identical fixed-page .75 renderer used by the DSH adapter."""
import argparse, hashlib, json
from pathlib import Path
from lab import ROOT
from hermes_bounded_rq3_worker_v1 import registered_pages, validate as validate_rq3

def validate_bc(spec, config, out):
    if spec.get('bounded_bc_protocol') != 'bc-bounded-pages-v1' or config.get('bounded_bc_protocol') != 'bc-bounded-pages-v1':
        raise ValueError('Independent BC bounded protocol required')
    if spec.get('scale') != .75 or spec.get('scale_key') != 'scale_0750':
        raise ValueError('BC requires fixed .75 far scale')
    # Reuse validation without altering files or the frozen configuration SHA.
    validate_rq3(dict(spec, bounded_rq3_protocol='rq3-bounded-pages-v1'),
                 dict(config, bounded_rq3_protocol='rq3-bounded-pages-v1'), out)

def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--spec', type=Path, required=True); parser.add_argument('--out', type=Path, required=True)
    args, _ = parser.parse_known_args()
    spec = json.loads(args.spec.read_text()); config = json.loads(Path(spec['config_path']).read_text())
    out = args.out.resolve(); validate_bc(spec, config, out)
    import hermes_bc_worker_v3 as native
    from bounded_visual_request_guard_v1 import install as install_guard
    original = native.configure_engine

    def configure(engine, strategy, policy):
        original(engine, strategy, policy)
        if strategy == 'visual':
            from plugins.context_engine.visual import render
            from rq3_bounded_renderer_v2 import install
            install(render)
            if config.get('bounded_transport_encoding') == 'bounded-canvas-lossless-webp-v1':
                from bounded_lossless_transport_v1 import install as encoding_install
                encoding_install(render)
            if getattr(engine, '_history_scale', None) != spec['scale']:
                raise ValueError('Live engine differs from declared far-history scale')
        install_guard(out / 'metrics/bounded-request-guard.jsonl',
                      rendered_registry=lambda: registered_pages(out / 'context_images', spec['scale']))
        out.mkdir(parents=True, exist_ok=True)
        (out / 'bounded-protocol.json').write_text(json.dumps({
            'version': 'bc-bounded-pages-v1', 'far_scale': spec['scale'], 'recent_scale': 1., 'max_canvas_size': [1024, 2048],
            'detail': 'high', 'vertical_merge': False, 'guard_max_request_bytes': 8 * 1024 * 1024,
            'guard_max_images': 32, 'native_pixels_unchanged': True, 'variant_not_original_protocol': True,
            'transport_encoding': config.get('bounded_transport_encoding', 'png'),
            'implementation_sha256': {name: hashlib.sha256((ROOT / 'scripts' / name).read_bytes()).hexdigest()
                for name in ('hermes_bounded_bc_worker_v1.py', 'rq3_bounded_renderer_v2.py', 'bounded_visual_request_guard_v1.py', 'bounded_lossless_transport_v1.py')}
        }, indent=2))

    native.configure_engine = configure
    try:
        native.main()
    finally:
        native.configure_engine = original


if __name__ == '__main__': main()
