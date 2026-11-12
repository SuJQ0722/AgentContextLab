"""Persistent local inline-image bridge: no hosting, upload, or model calls."""
import argparse
import contextlib
import json
import os
from pathlib import Path
import sys
from hermes_bounded_rq3_worker_v1 import registered_pages
from verified_canvas_registry_cache import VerifiedCanvasRegistryCache
from inline_visual_transport_v1 import transform


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--canvas-root', type=Path, required=True)
    a = p.parse_args(); output = sys.stdout
    max_images = int(os.environ.get('ACL_INLINE_DSH_RETAIN_IMAGES', '10'))
    if not 1 <= max_images <= 10:
        raise ValueError('DSH image limit must be from 1 to 10')
    page_budget = json.loads(os.environ.get('ACL_INLINE_DSH_PAGE_BUDGET', 'null'))
    window = json.loads(os.environ.get('ACL_PAGE_WINDOW_RENDERER', 'null'))
    limits = json.loads(os.environ.get('ACL_INLINE_VISUAL_LIMITS', '{}'))
    if window:
        from page_window_renderer_v1 import registered_pages as window_registry
        validator = window_registry
    else:
        validator = lambda root: registered_pages(root, .75)
    registry = VerifiedCanvasRegistryCache(a.canvas_root, validator)
    for line in sys.stdin:
        try:
            request = json.loads(line)
            with contextlib.redirect_stdout(sys.stderr):
                wire, ledger = transform(request['body'].encode(), rendered_registry=registry, max_images=max_images, page_budget=page_budget, max_canvas_pixels=limits.get('canvas_max_pixels',2097152), max_body_bytes=limits.get('max_request_bytes',33554432))
            result = {'id': request['id'], 'ok': True, 'wire': wire.decode(), 'ledger': ledger}
        except Exception as error:
            result = {'id': locals().get('request', {}).get('id'), 'ok': False, 'error_type': type(error).__name__}
        output.write(json.dumps(result, separators=(',', ':')) + '\n'); output.flush()


if __name__ == '__main__':
    main()
