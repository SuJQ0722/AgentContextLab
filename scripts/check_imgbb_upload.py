#!/usr/bin/env python3
"""Upload a synthetic crop through Hermes' real imgBB/Lens handler; no model calls.

This explicitly performs real image-hosting and Serper requests. It uploads only
the synthetic fixture created below, never benchmark files or private images.
"""
import hashlib
import json
import os
from pathlib import Path
import time
from lab import ROOT, environment
from local_web import configure_web
from hermes_tool_bridge import initialize, execute


def main():
    out = ROOT / 'outputs/preflight' / f'imgbb-local-crop-{time.time_ns()}'
    out.mkdir(parents=True)
    configs = []
    for harness in ('hermes', 'dsh'):
        env, _ = environment(ROOT, harness, ROOT / 'configs/experiment.v3.review.json')
        configure_web(ROOT, env, ROOT / 'configs/experiment.v3.review.json')
        configs.append(env)
    key = configs[0].get('IMAGE_UPLOAD_API_KEY')
    if not key or key != configs[1].get('IMAGE_UPLOAD_API_KEY'):
        raise RuntimeError('Both harnesses must resolve the same nonempty upload key')
    env = configs[1]
    env['HERMES_IMAGE_ROOT'] = str(out)
    os.environ.update(env)
    settings = initialize(out)
    from PIL import Image, ImageDraw
    import tools.image_search_tool as image_tool

    parent = Image.new('RGB', (640, 360), 'white')
    draw = ImageDraw.Draw(parent)
    for x in range(0, 640, 20):
        for y in range(0, 360, 20):
            draw.rectangle((x, y, x + 19, y + 19), fill=(x % 256, y % 256, (x + y) % 256))
    parent_path = out / 'synthetic-parent.png'; parent.save(parent_path)
    crop_result = execute({'tool': 'image_crop', 'call_id': 'synthetic-crop', 'arguments': {
        'image_path': str(parent_path), 'bbox': [160, 80, 480, 280],
        'coord_format': 'absolute', 'padding': 0, 'use_smart_resize': False}}, out, settings)
    crop = next(p for p in crop_result['content'] if p['type'] == 'image')
    source = Path(crop['path'])
    observed = {'paid_model_calls': 0, 'synthetic_image_only': True,
                'both_harnesses_resolve_same_upload_key': True,
                'source_kind': 'actual_image_crop_return', 'source_sha256': crop['sha256'],
                'parent_sha256': hashlib.sha256(parent_path.read_bytes()).hexdigest(),
                'upload_attempts': 0, 'upload_succeeded': False}
    original = image_tool._upload_imgbb

    def upload(path):
        observed['upload_attempts'] += 1
        observed['uploaded_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        result = original(path)
        observed['upload_succeeded'] = bool(result)
        return result

    image_tool._upload_imgbb = upload
    start = time.monotonic()
    result = execute({'tool': 'image_search', 'call_id': 'synthetic-crop-lens',
                      'arguments': {'image_path': str(source), 'top_k': 3}}, out, settings)
    payload = json.loads(result['content'][0]['text'])
    observed['handler_success'] = payload.get('success') is True
    observed['result_count'] = payload.get('num_results')
    observed['client_seconds'] = time.monotonic() - start
    observed['uploaded_actual_crop'] = observed.get('uploaded_sha256') == crop['sha256'] != observed['parent_sha256']
    observed['artifact'] = str(out)
    observed['passed'] = all(observed[k] for k in ('upload_succeeded', 'handler_success', 'uploaded_actual_crop'))
    (out / 'result.json').write_text(json.dumps(observed, indent=2) + '\n')
    print(json.dumps(observed))
    if not observed['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
