#!/usr/bin/env python3
"""Render a DSH-selected history span using the customized Hermes renderer."""
import json
import logging
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'hermes-agent'))
from plugins.context_engine.visual.render import render_visual_compression
from plugins.context_engine.visual import render as renderer_module


def reject_fallback(*args, **kwargs):
    raise RuntimeError('PDF renderer failed; PIL fallback is invalid for this experiment')


class RenderFailures(logging.Handler):
    def __init__(self):
        super().__init__(logging.WARNING)
        self.errors = []

    def emit(self, record):
        text = record.getMessage()
        if 'failed' in text.lower() or 'pil fallback' in text.lower():
            self.errors.append(text)


def render(payload):
    messages = []
    tool_names = {}
    for message in payload['messages']:
        content, calls = [], []
        for block in message['content']:
            if block['type'] in ('text', 'reasoning'):
                content.append({'type': 'text', 'text': block['text']})
            elif block['type'] == 'tool-call':
                tool_names[block['id']] = block['name']
                calls.append({'id': block['id'], 'type': 'function', 'function': {
                    'name': block['name'], 'arguments': block['arguments']}})
            elif block['type'] == 'image_url':
                content.append(block)
            elif block['type'] == 'image':
                raise ValueError('Native DSH image must be resolved to inline bytes before rendering')
        item = {'role': message['role'], 'content': content}
        if calls:
            item['tool_calls'] = calls
        if message.get('toolCallId'):
            item['tool_call_id'] = message['toolCallId']
            if message['toolCallId'] in tool_names:
                item['name'] = tool_names[message['toolCallId']]
        messages.append(item)
    stats = {}
    start = time.monotonic()
    failures = RenderFailures()
    renderer_module.logger.addHandler(failures)
    try:
        with tempfile.TemporaryDirectory(prefix='acl-render-') as directory, patch.object(
                renderer_module, '_text_to_images_fallback', reject_fallback):
            result = render_visual_compression(
                messages, head_end=0, keep_rounds=0, save_dir=directory,
                history_scale=payload['history_scale'], stats=stats,
                font_size=payload.get('font_size', 8),
            )
        if failures.errors:
            raise RuntimeError('Invalid visual render: ' + '; '.join(failures.errors))
    finally:
        renderer_module.logger.removeHandler(failures)
    images = [part['image_url']['url'] for message in result
              for part in (message.get('content') or [])
              if isinstance(part, dict) and part.get('type') == 'image_url']
    if result is messages or not images:
        raise ValueError('History was not rendered; refusing a silent text fallback')
    expected = [block for message in messages for block in message['content']
                if block.get('type') == 'image_url']
    if expected:
        ledger = stats.get('source_images', [])
        if (stats.get('renderer_version') != 'multimodal-wrap-v2'
                or stats.get('source_image_occurrences') != len(ledger)
                or not stats.get('source_image_coverage_verified')):
            raise ValueError('Shared renderer did not verify complete inline visual evidence coverage')
        expected_sources = [(b.get('source_attachment_id'), b.get('source_occurrence')) for b in expected]
        actual_sources = [(b.get('source_attachment_id'), b.get('source_occurrence')) for b in ledger
                          if b.get('source_occurrence') is not None or b.get('source_attachment_id') is not None]
        if expected_sources != actual_sources:
            raise ValueError('Rendered evidence provenance changed order or omitted an occurrence')
    return {'images': images, 'render_seconds': time.monotonic() - start, 'stats': stats,
            'renderer': 'Hermes PDF/Poppler; inline evidence v2; fallback forbidden',
            'presentation_version': 'hermes-inline-evidence-v2'}


if __name__ == '__main__':
    print(json.dumps(render(json.load(sys.stdin))))
