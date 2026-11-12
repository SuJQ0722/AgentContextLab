"""Independent DSH BC entry: direct inline last-ten images and four approved routes."""
import argparse
import json
from pathlib import Path
from unittest.mock import patch
import dsh_bounded_bc_worker_v1 as parent
from lab import ROOT
from inline_visual_transport_v1 import visual_max_images, transport_version
from inline_route_contract_v1 import validate_routes

BOUNDED_SOURCE_FILES = list(dict.fromkeys(parent.BOUNDED_SOURCE_FILES + [
    'scripts/' + name for name in ('dsh_hosted_bc_worker_v3.py', 'dsh_bounded_bc_worker_v1.py',
    'dsh_hosted_wire_v3.mjs', 'dsh_inline_transport_bridge_v1.py', 'inline_visual_transport_v1.py',
    'inline_route_contract_v1.py', 'verified_canvas_registry_cache.py', 'recent_ten_hosted_selection_v1.py',
    'recent_ten_images_transport_v1.py', 'bounded_ten_image_guard_v1.py',
    'bounded_visual_request_guard_v1.py', 'visual_transport_runtime_v3.py', 'sse_completion.py', 'sse_completion.mjs', 'dsh_pre_sdk_images.mjs')]))


def main():
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument('--config', type=Path, required=True)
    p.add_argument('--output-root', type=Path, required=True)
    a, _ = p.parse_known_args()
    cfg = json.loads(a.config.read_text()); validate_routes(cfg, cfg)
    max_images = visual_max_images(cfg)
    if cfg.get('bounded_max_images') != 10 or cfg.get('bounded_request_protocol') != 'bounded-multimodal-recent-ten-v1':
        raise ValueError('Explicit recent-ten configuration required')
    parts = a.output_root.resolve().parts
    if 'jobs' not in parts or 'attempts' not in parts:
        raise ValueError('Immutable experiment job output path required')
    worker_key = '/'.join(parts[parts.index('jobs') + 1:parts.index('attempts')])
    original = parent.native.command
    def command(root, harness, prompt, env):
        old = str(ROOT / 'scripts/dsh_bounded_wire_guard_v1.mjs')
        new = str(ROOT / 'scripts/dsh_hosted_wire_v3.mjs')
        if env.get('NODE_OPTIONS', '').count(old) != 1:
            raise ValueError('Expected one inner bounded guard')
        env['NODE_OPTIONS'] = env['NODE_OPTIONS'].replace(old, new)
        metrics = Path(env['ACL_BOUNDED_WIRE_LEDGER']).parent
        env['ACL_INLINE_DSH_LEDGER'] = str(metrics / 'inline-images-wire-dsh-v1.jsonl')
        env['ACL_INLINE_DSH_JOB_ID'] = worker_key
        env['ACL_INLINE_DSH_RETAIN_IMAGES'] = str(max_images)
        (metrics.parent.parent / 'inline-dsh-protocol.json').write_text(json.dumps({
            'version': 'dsh-inline-wire-v1', 'max_images': max_images, 'image_transport': transport_version(max_images),
            'wire_ledger': env['ACL_INLINE_DSH_LEDGER'], 'body_chunk_bytes': 65536,
            'prior_image_observer_stage': 'pre_retention', 'approved_model_routes': cfg['approved_model_routes'],
            'model_route_policy': cfg['model_route_policy'], 'worker_key': worker_key,
            'content_length_policy': 'native_fetch_streams_without_manual_content_length',
            'fetch_wall_timeout_seconds': 300, 'outer_trial_timeout_seconds': 1800,
            'provider_internal_latency_measured': False, 'image_host_uploads': 0}, indent=2))
        return original(root, harness, prompt, env)
    with patch.object(parent.native, 'command', command):
        parent.main()


if __name__ == '__main__':
    main()
