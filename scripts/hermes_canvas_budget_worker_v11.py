"""Independent recovery: verified canvas budget, native evidence preserved."""
import argparse
import json
from pathlib import Path
from unittest.mock import patch
import inline_visual_transport_v1 as transport
import hermes_visual_inline_retry_worker_v4 as worker

VERSION = 'seven-page-canvas-budget-recovery-v11'
REQUEST_LIMIT = 32 * 1024 * 1024
_ORIGINAL_TRANSFORM = transport.transform


def transform(body, **kwargs):
    # The versioned entry restores only the previously authorized total 32MiB guard.
    wire, audit = _ORIGINAL_TRANSFORM(body, **{**kwargs, 'max_body_bytes': REQUEST_LIMIT})
    images = audit['selection']['final_guard']['images']
    canvas = [image for image in images if image.get('rendered_canvas') is True]
    if any(type(image.get('bytes')) is not int or image['bytes'] < 0 for image in canvas):
        raise ValueError('Verified canvas byte length required')
    encoded_bytes = sum(4 * ((image['bytes'] + 2) // 3) for image in canvas)
    audit['canvas_budget_recovery'] = {
        'version': VERSION, 'verified_canvas_count': len(canvas),
        'canvas_base64_bytes': encoded_bytes, 'canvas_base64_limit': None,
        'native_base64_bytes': sum(4 * ((image['bytes'] + 2) // 3) for image in images if image.get('rendered_canvas') is not True),
        'native_images_excluded_from_canvas_budget': len(images) - len(canvas),
        'total_request_limit': REQUEST_LIMIT, 'native_evidence_modified': False,
        'pages_merged': False, 'pixels_reencoded': False,
        'budget_applies_after_explicit_page_selection': True}
    return wire, audit


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--spec', type=Path, required=True)
    args, _ = parser.parse_known_args()
    spec = json.loads(args.spec.read_text())
    config = json.loads(Path(spec['config_path']).read_text())
    if spec.get('runtime_recovery_version') != VERSION or config.get('runtime_recovery_version') != VERSION:
        raise ValueError('Explicit independent canvas-budget recovery required')
    if config.get('visual_image_retention', {}).get('max_request_bytes') != REQUEST_LIMIT:
        raise ValueError('Explicit 32MiB total request guard required; no separate canvas byte cap')
    with patch.object(transport, 'transform', transform):
        worker.main()


if __name__ == '__main__': main()
