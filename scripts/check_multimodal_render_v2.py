#!/usr/bin/env python3
"""Run real crop/zoom/search result formatting and VisualEngine, with zero APIs.

Only the image-search HTTP response is stubbed with deterministic local results.
Crop and zoom run their actual handlers; super-resolution is explicitly off.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def save(path, data):
    path.write_text(json.dumps(data, indent=2) + '\n')


def worker(out):
    from PIL import Image, ImageDraw
    import fitz
    sys.path.insert(0, str(ROOT / 'hermes-agent'))
    from plugins.context_engine.visual import VisualEngine
    from plugins.context_engine.visual import render
    from tools.image_crop_tool import image_crop_tool
    from tools.image_zoom_in_tool import image_zoom_in_tool
    from tools import image_search_tool as search
    out.mkdir(parents=True, exist_ok=False)
    os.environ['HERMES_IMAGE_ROOT'] = str(out)
    os.environ['HERMES_IMAGE_CACHE'] = str(out / 'tool-cache')
    source = out / 'native-parent.png'
    image = Image.new('RGB', (400, 240), 'white'); draw = ImageDraw.Draw(image)
    draw.rectangle((10, 30, 120, 180), fill='red')
    draw.ellipse((145, 30, 270, 180), fill='blue')
    draw.polygon([(285, 180), (390, 180), (335, 30)], fill='green')
    image.save(source)
    crop = image_crop_tool(image_path=str(source), bbox=[140, 20, 275, 190],
                           coord_format='absolute', padding=0, use_smart_resize=False)
    zoom = image_zoom_in_tool(image_path=str(source), bbox_2d=[280, 20, 395, 190],
                             use_super_resolution=False, use_smart_resize=False, label='triangle')
    assert isinstance(crop, dict) and crop.get('_multimodal'), crop
    assert isinstance(zoom, dict) and zoom.get('_multimodal'), zoom
    thumbnails = []
    for i, color in enumerate(['purple', 'orange', 'cyan', 'black']):
        path = out / f'search-result-{i}.png'
        im = Image.new('RGB', (100, 70), color); ImageDraw.Draw(im).text((10, 10), str(i), fill='white'); im.save(path)
        thumbnails.append({'title': f'Fixture result {i}', 'thumbnail_url': str(path),
                           'link': f'https://example.org/source/{i}', 'source': 'Offline fixture'})
    with patch.object(search, '_serper_api_key', return_value='fixture-only'), \
         patch.object(search, 'is_safe_url', return_value=True), \
         patch.object(search, '_call_serper_lens', return_value=thumbnails):
        searched = search.image_search_tool(image_url='https://example.org/query.png', top_k=4)
    save(out / 'actual-tool-results.json', {'crop': crop, 'zoom': zoom, 'search': json.loads(searched)})
    def call(ident, name, args):
        return {'role': 'assistant', 'content': f'Inspect {name} evidence.', 'tool_calls': [
            {'id': ident, 'type': 'function', 'function': {'name': name, 'arguments': json.dumps(args)}}]}
    def result(ident, content):
        return {'role': 'tool', 'tool_call_id': ident, 'content': content}
    source_url = 'data:image/png;base64,' + base64.b64encode(source.read_bytes()).decode()
    table = '\n'.join(['| item | count |', '|---|---|'] + [f'| row{i} | value{i} |' for i in range(18)])
    messages = [
        {'role': 'user', 'content': 'Inspect all visual evidence without losing returned crops.'},
        call('head', 'fixture_header', {}), result('head', 'Protected prefix.'),
        call('native', 'fixture_native', {}), result('native', [
            {'type': 'text', 'text': 'Original native image follows. This description wraps beside the picture.'},
            {'type': 'image_url', 'image_url': {'url': source_url}, 'source_occurrence': 'native-inline'},
            {'type': 'image_url', 'image_url': {'url': str(source)}, 'source_occurrence': 'native-local-duplicate'}]),
        call('crop', 'image_crop', {'image_path': str(source), 'bbox': [140, 20, 275, 190]}), result('crop', crop),
        call('zoom', 'image_zoom_in', {'image_path': str(source), 'bbox_2d': [280, 20, 395, 190]}), result('zoom', zoom['content']),
        call('search', 'image_search', {'image_url': 'https://example.org/query.png'}), result('search', searched),
        call('table', 'terminal', {'command': 'cat evidence.csv'}), result('table', table),
        {'role': 'assistant', 'content': 'All eighteen data rows remain present. The final row must not be truncated.'},
        call('tail', 'fixture_tail', {}), result('tail', 'Uncompressed tail.')]
    save(out / 'messages.json', messages)
    canvas_dir = out / 'canvas'; canvas_dir.mkdir()
    engine = VisualEngine()
    engine.configure({'strategy_config': {'font_size': 16, 'history_scale': 1,
                      'keep_rounds': 1, 'recent_rounds': 5, 'save_dir': str(canvas_dir)}})
    final = engine.compress(messages, current_tokens=40000)
    assert engine.compression_count == 1
    save(out / 'compressed-messages.json', final)
    stats = engine._compression_stats['per_compression'][0]
    assert stats['renderer_version'] == 'multimodal-wrap-v2'
    assert stats['source_image_occurrences'] == 8, stats
    assert stats['rendered_source_images'] == 7, stats
    assert stats['source_image_coverage_verified']
    with fitz.open(canvas_dir / 'compact_1.pdf') as pdf:
        image_instances = sum(len(page.get_image_info()) for page in pdf)
        text = '\n'.join(page.get_text() for page in pdf)
    assert image_instances == 7, image_instances
    assert 'row17' in text and 'value17' in text
    crops = [item for item in stats['source_images'] if item['label'] in ('image_crop', 'image_zoom_in')]
    assert [item['dimensions'] for item in crops] == [[135, 170], [115, 170]]
    assert all(item['dimensions'] != [400, 240] for item in crops)
    report = {'passed': True, 'paid_calls': 0, 'network_calls': 0,
              'search_transport': 'stubbed local structured results; actual image_search handler and formatting',
              'crop_zoom': 'actual handlers, local PNG, smart resize and super-resolution disabled',
              'renderer_version': stats['renderer_version'], 'source_occurrences': 8,
              'unique_images_in_pdf': image_instances, 'table_last_row_present': True,
              'actual_returned_crop_dimensions': [item['dimensions'] for item in crops],
              'stats': stats, 'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
              'implementation_sha256': {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in [
                  'hermes-agent/plugins/context_engine/visual/render.py', 'hermes-agent/plugins/context_engine/visual/__init__.py']}}
    save(out / 'result.json', report)
    print(json.dumps({'passed': True, 'paid_calls': 0, 'artifact': str(out / 'result.json'),
                      'source_occurrences': 8, 'unique_images_in_pdf': image_instances}))


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--out', type=Path, required=True); parser.add_argument('--worker', action='store_true')
    args = parser.parse_args()
    if args.worker:
        worker(args.out.resolve())
    else:
        from lab import environment, python_for
        env, _ = environment(ROOT, 'hermes')
        env['HERMES_HOME'] = str(args.out.resolve().parent / '.multimodal-v2-home')
        env.pop('HERMES_VISUAL_LAYOUT', None)
        subprocess.run([python_for(ROOT), str(Path(__file__).resolve()), '--worker', '--out', str(args.out.resolve())], env=env, cwd=ROOT, check=True)


if __name__ == '__main__':
    main()
