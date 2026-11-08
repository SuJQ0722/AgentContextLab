#!/usr/bin/env python3
"""Zero-API paired renderer audit with synthetic text, native geometry and table.

Uses actual VisualEngine.compress and DSH separateImages -> render bridge. Only
temporary artifact cleanup is disabled; renderer behavior is not replaced.
"""
import argparse
import base64
from contextlib import nullcontext
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def save(path, data):
    path.write_text(json.dumps(data, indent=2) + '\n')


def image_parts(messages):
    return [b for m in messages if isinstance(m.get('content'), list)
            for b in m['content'] if b.get('type') == 'image_url']


def worker(out):
    from PIL import Image, ImageDraw
    sys.path.insert(0, str(ROOT / 'hermes-agent'))
    from plugins.context_engine.visual import VisualEngine
    from plugins.context_engine.visual import render as renderer
    import render_dsh_history as bridge
    out.mkdir(parents=True, exist_ok=False)
    native = out / 'native-evidence.png'
    image = Image.new('RGB', (360, 220), 'white')
    draw = ImageDraw.Draw(image)
    draw.rectangle((12, 30, 110, 140), fill=(230, 20, 20))
    draw.ellipse((135, 30, 245, 140), fill=(20, 50, 230))
    draw.polygon([(255, 140), (345, 140), (300, 30)], fill=(20, 180, 50))
    draw.text((12, 175), 'RED BOX   BLUE CIRCLE   GREEN TRIANGLE', fill='black')
    image.save(native)
    native_bytes = native.read_bytes()
    native_url = 'data:image/png;base64,' + base64.b64encode(native_bytes).decode()
    description = ('Fixture evidence: the red rectangle is on the left, the blue circle is in the middle, '
                   'and the green triangle is on the right. This sentence belongs beside the image. ')
    caption = ('Following caption: archive sample CEDAR has three colored geometric objects. '
               'Keep this caption after the evidence image in reading order. ') * 3
    table = '| Object | Count |\n|---|---|\n| Rectangle | 1 |\n| Circle | 1 |\n| Triangle | 1 |'
    call = lambda ident, name: {'id': ident, 'type': 'function', 'function': {'name': name,
                              'arguments': '{"command":"cat evidence.csv"}' if name == 'terminal' else '{}'}}
    prefix = [{'role': 'user', 'content': 'Compare the fixture evidence.'},
              {'role': 'assistant', 'content': '', 'tool_calls': [call('head', 'fixture_header')]},
              {'role': 'tool', 'tool_call_id': 'head', 'content': 'Protected task header.'}]
    history = [{'role': 'assistant', 'content': 'Inspect native evidence.', 'tool_calls': [call('img', 'fixture_read')]},
               {'role': 'tool', 'tool_call_id': 'img', 'content': [{'type': 'text', 'text': description * 3},
                   {'type': 'image_url', 'image_url': {'url': str(native), 'detail': 'high'}}]},
               {'role': 'assistant', 'content': caption},
               {'role': 'assistant', 'content': 'Read the table.', 'tool_calls': [call('tab', 'terminal')]},
               {'role': 'tool', 'tool_call_id': 'tab', 'content': table},
               {'role': 'assistant', 'content': 'Table commentary: the CSV lists one of each object. '
                'This text follows the original table and should remain associated with its three data rows. ' * 2}]
    tail = [{'role': 'assistant', 'content': 'Preserved recent round.', 'tool_calls': [call('tail', 'fixture_tail')]},
            {'role': 'tool', 'tool_call_id': 'tail', 'content': 'Tail remains text.'}]
    save(out / 'semantic-source.json', {'description': description * 3, 'caption': caption, 'table': table,
                                      'native_sha256': sha(native_bytes), 'native_dimensions': [360, 220]})
    results = {}
    for name, image_ref in [('hermes-local-path', str(native)), ('hermes-inline-data', native_url)]:
        directory = out / name
        directory.mkdir()
        messages = copy.deepcopy(prefix + history + tail)
        messages[4]['content'][1]['image_url']['url'] = image_ref
        save(directory / 'input.json', messages)
        engine = VisualEngine()
        engine.configure({'strategy_config': {'font_size': 16, 'history_scale': 1,
                          'keep_rounds': 1, 'recent_rounds': 5, 'save_dir': str(directory)}})
        with patch.object(renderer, '_text_to_images_fallback', bridge.reject_fallback):
            compressed = engine.compress(messages, current_tokens=40000)
        assert engine.compression_count == 1
        save(directory / 'output.json', compressed)
        save(directory / 'selected-source.json', engine._full_history)
        blocks = [renderer._format_message_block(m, tool_name_map=renderer._build_tool_name_map(engine._full_history), msg_index=i)
                  for i, m in enumerate(engine._full_history)]
        save(directory / 'formatted-blocks.json', blocks)
        results[name] = {'path': str(directory), 'selected_messages': len(engine._full_history),
                         'renderer_inline_image_count': sum(len(b['images']) for b in blocks),
                         'renderer_table_count': sum(bool(b.get('table_data')) for b in blocks),
                         'canvas_count': len(image_parts(compressed)),
                         'original_native_image_retained_separately': any(b['image_url']['url'] in (str(native), native_url) for b in image_parts(compressed)),
                         'stats': engine._compression_stats}
    attachment = {'attachmentId': 'sha256:' + sha(native_bytes), 'mediaType': 'image/png',
                  'width': 360, 'height': 220, 'bytes': len(native_bytes)}
    dsh_messages = []
    for m in history:
        contents = [{'type': 'text', 'text': m['content']}] if isinstance(m['content'], str) else [
            {'type': 'image', 'attachment': attachment} if b['type'] == 'image_url' else b for b in m['content']]
        contents += [{'type': 'tool-call', 'id': c['id'], 'name': c['function']['name'],
                      'arguments': c['function']['arguments']} for c in m.get('tool_calls', [])]
        item = {'role': m['role'], 'content': contents}
        if m.get('tool_call_id'):
            item['toolCallId'] = m['tool_call_id']
        dsh_messages.append(item)
    directory = out / 'dsh-separated-native'
    directory.mkdir()
    save(directory / 'input.json', dsh_messages)
    js = "import {separateImages} from './plugins/dsh-context/content.mjs'; let s='';for await(const c of process.stdin)s+=c;process.stdout.write(JSON.stringify(separateImages(JSON.parse(s))));"
    separated = json.loads(subprocess.run(['node', '--input-type=module', '-e', js], input=json.dumps(dsh_messages),
                          text=True, capture_output=True, check=True, cwd=ROOT).stdout)
    save(directory / 'separated.json', separated)
    payload = {'messages': separated['text'], 'font_size': 16, 'history_scale': 1}
    save(directory / 'renderer-payload.json', payload)
    normalized = []
    actual_renderer = bridge.render_visual_compression

    def observed_render(messages, *args, **kwargs):
        normalized.extend(copy.deepcopy(messages))
        return actual_renderer(messages, *args, **kwargs)

    # Preserve exactly the files that the actual bridge normally deletes.
    with patch.object(bridge.tempfile, 'TemporaryDirectory', lambda **kw: nullcontext(str(directory))), \
         patch.object(bridge, 'render_visual_compression', observed_render):
        rendered = bridge.render(payload)
    save(directory / 'renderer-output.json', rendered)
    save(directory / 'normalized-render-input.json', normalized)
    blocks = [renderer._format_message_block(m, tool_name_map=renderer._build_tool_name_map(normalized), msg_index=i)
              for i, m in enumerate(normalized)]
    save(directory / 'formatted-blocks.json', blocks)
    native_copy = directory / 'separately-retained-native.png'
    native_copy.write_bytes(native_bytes)
    assert separated['images'] == [{'type': 'image', 'attachment': attachment}]
    assert not any(b['type'] == 'image' for m in separated['text'] for b in m['content'])
    results['dsh-separated-native'] = {'path': str(directory), 'selected_messages': len(normalized),
        'renderer_inline_image_count': sum(len(b['images']) for b in blocks),
        'renderer_table_count': sum(bool(b.get('table_data')) for b in blocks),
        'canvas_count': len(rendered['images']), 'separate_native_count': len(separated['images']),
        'native_reference_unchanged': separated['images'][0]['attachment'] == attachment,
        'separate_native_file_sha256': sha(native_copy.read_bytes()), 'stats': rendered['stats'],
        'scope': 'Actual separateImages and render bridge; summary attachment assembly verified from plugin source, not a full native loop.'}
    hashes = {str(p.relative_to(out)): sha(p.read_bytes()) for p in out.rglob('*') if p.is_file()}
    report = {'paid_calls': 0, 'synthetic_fixture': True, 'font_size': 16, 'history_scale': 1,
              'hermes_keep_rounds': 1, 'hermes_recent_rounds': 5, 'results': results, 'artifact_sha256': hashes,
              'implementation_sha256': {p: sha((ROOT / p).read_bytes()) for p in [
                  'hermes-agent/plugins/context_engine/visual/__init__.py', 'hermes-agent/plugins/context_engine/visual/render.py',
                  'plugins/dsh-context/content.mjs', 'plugins/dsh-context/index.mjs', 'scripts/render_dsh_history.py']}}
    save(out / 'report.json', report)
    print(json.dumps({'report': str(out / 'report.json'), 'results': results}, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--worker', action='store_true')
    args = parser.parse_args()
    if args.worker:
        worker(args.out.resolve())
    else:
        from lab import environment, python_for
        env, _ = environment(ROOT, 'hermes')
        env['HERMES_HOME'] = str(args.out.resolve().parent / '.parity-hermes-home')
        env.pop('HERMES_VISUAL_LAYOUT', None)
        subprocess.run([python_for(ROOT), str(Path(__file__).resolve()), '--worker', '--out', str(args.out.resolve())],
                       env=env, cwd=ROOT, check=True)


if __name__ == '__main__':
    main()
