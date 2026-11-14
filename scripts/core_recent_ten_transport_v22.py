"""Explicit core last-ten transport; frozen V1 transports are not modified.

Core selects at most five history/two recent canvas pages, then sends the last
ten image occurrences of any origin. Controlled callers must explicitly select
strict_native: native evidence is never silently removed. No API calls occur
until an explicitly installed HTTP transport receives a request.
"""
import base64
import copy
import hashlib
import json
import re
import time
from pathlib import Path

import httpx
import inline_visual_transport_v1 as frozen
from dsh_canvas_segments_v13 import verified_handle
from visual_transport_runtime_v2 import TerminalTransportFailure

VERSION = 'core-page-caps-then-recent-ten-v22'
POLICIES = {'core_recent10', 'strict_native'}
# Capture before a fresh wrapper temporarily binds the legacy worker's adapter.
_FROZEN_TRANSFORM = frozen.transform


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def scan(payload, registry, harness):
    """Bind canvas labels/DSH handles to payload hashes, never filename guesses."""
    if harness not in ('hermes', 'dsh'):
        raise ValueError('Explicit supported harness required')
    images = []
    for mi, message in enumerate(payload['messages']):
        content = message.get('content')
        if not isinstance(content, list):
            continue
        label = None
        handle_index = None
        for pi, part in enumerate(content):
            if part.get('type') == 'text':
                match = re.search(r'\[(History|Recent) page (\d+)/(\d+) — linear scale [^,]+, high detail\]\s*$', part.get('text', ''))
                if match:
                    label = {'segment': match.group(1).lower(), 'label_index': pi,
                             'label_prefix': part['text'][:match.start()]}
                    handle_index = None
                elif (harness == 'dsh' and label is not None and pi + 1 < len(content)
                      and verified_handle(part.get('text', ''), content[pi + 1], registry)):
                    handle_index = pi
                else:
                    label = None
                    handle_index = None
            elif part.get('type') == 'image_url':
                value = part['image_url']
                url = value.get('url') if isinstance(value, dict) else value
                if not isinstance(url, str) or not url.startswith('data:image/'):
                    raise ValueError('Inline image bytes required')
                header, encoded = url.split(',', 1)
                if not header.endswith(';base64'):
                    raise ValueError('Base64 inline image required')
                raw = base64.b64decode(encoded, validate=True)
                identity = digest(raw)
                canvas = identity in registry
                if canvas and label is None:
                    raise ValueError('Canvas lacks a verified segment label')
                row = {'original_image_ordinal': len(images), 'message_index': mi,
                       'original_part_index': pi, 'sha256': identity, 'bytes': len(raw),
                       'detail': value.get('detail', 'auto') if isinstance(value, dict) else 'auto',
                       'origin': 'canvas' if canvas else 'native'}
                if canvas:
                    row.update(label)
                    row['handle_index'] = handle_index
                images.append(row)
                label = None
                handle_index = None
    return images


def _public(row):
    return {k: v for k, v in row.items() if k != 'label_prefix'}


def select_core_canvas_pages(body, registry, budget, *, harness='hermes'):
    """Only apply per-segment caps; native count does not shrink or reject pages."""
    if (set(budget) != {'history', 'recent'} or
            any(type(v) is not int or v < 1 for v in budget.values()) or
            budget['history'] > 5 or budget['recent'] > 2):
        raise ValueError('Core canvas caps require history<=5 and recent<=2, both positive')
    payload = json.loads(body)
    images = scan(payload, registry, harness)
    removed = []
    for segment, limit in budget.items():
        pages = [r for r in images if r.get('segment') == segment]
        removed.extend(pages[:-limit])
    positions = set()
    result = copy.deepcopy(payload)
    for row in removed:
        mi = row['message_index']
        positions.add((mi, row['original_part_index']))
        if row['label_prefix']:
            result['messages'][mi]['content'][row['label_index']]['text'] = row['label_prefix']
        else:
            positions.add((mi, row['label_index']))
        if row.get('handle_index') is not None:
            positions.add((mi, row['handle_index']))
    for mi, message in enumerate(result['messages']):
        if isinstance(message.get('content'), list):
            message['content'] = [part for pi, part in enumerate(message['content']) if (mi, pi) not in positions]
    wire = json.dumps(result, ensure_ascii=False, separators=(',', ':')).encode() if removed else body
    removed_ordinals = {r['original_image_ordinal'] for r in removed}
    survivors = [r for r in images if r['original_image_ordinal'] not in removed_ordinals]
    audit = {'version': VERSION, 'policy': 'independent_segment_caps_before_global_last10',
             'harness': harness, 'budget': dict(budget), 'native_count': sum(r['origin'] == 'native' for r in images),
             'generated_counts': {k: sum(r.get('segment') == k for r in images) for k in budget},
             'retained_counts': {k: sum(r.get('segment') == k for r in survivors) for k in budget},
             'removed': [_public(r) for r in removed], 'input_body_sha256': digest(body),
             'output_body_sha256': digest(wire), 'native_images_preserved_at_this_stage': True}
    return wire, audit, images, survivors


def transform(body, *, rendered_registry, policy, harness='hermes', max_images=10,
              page_budget=None, max_canvas_pixels=2097152, max_body_bytes=frozen.MAX_BODY_BYTES):
    if policy not in POLICIES:
        raise ValueError('Explicit core_recent10 or strict_native policy required')
    if max_images != 10:
        raise ValueError('V22 requires the authorized ten-image envelope')
    registry = set(rendered_registry() if callable(rendered_registry) else rendered_registry)
    if policy == 'strict_native':
        images = scan(json.loads(body), registry, harness)
        native_count = sum(r['origin'] == 'native' for r in images)
        if native_count > 10:
            raise ValueError('Strict native evidence exceeds ten-image limit; no image may be discarded')
        if page_budget is None and len(images) > 10:
            raise ValueError('Strict native total exceeds ten; an explicit canvas allocation is required')
        # The legacy selector preserves every native image, allocating only the
        # remaining slots to canvas. No shared module is monkeypatched here.
        if page_budget is not None:
            if harness == 'dsh':
                from dsh_canvas_segments_v13 import select_canvas_pages
            else:
                select_canvas_pages = frozen.select_canvas_pages
            selected_body, segment = select_canvas_pages(body, registry, page_budget)
        else:
            selected_body, segment = body, None
        wire, audit = _FROZEN_TRANSFORM(selected_body, rendered_registry=registry, max_images=10,
                                       max_canvas_pixels=max_canvas_pixels, max_body_bytes=max_body_bytes)
        final_native = [r['sha256'] for r in audit['selection']['retained'] if r['origin'] == 'native']
        if final_native != [r['sha256'] for r in images if r['origin'] == 'native']:
            raise ValueError('Strict native identity/order changed')
        audit.update(version=VERSION, scientific_policy=policy, harness=harness,
                     canvas_page_selection=segment, native_evidence_preserved=True)
        return wire, audit

    if page_budget is None:
        raise ValueError('Core V22 requires explicit history/recent caps')
    staged, segment, original_images, survivors = select_core_canvas_pages(body, registry, page_budget, harness=harness)
    wire, audit = _FROZEN_TRANSFORM(staged, rendered_registry=registry, max_images=10,
                                   max_canvas_pixels=max_canvas_pixels, max_body_bytes=max_body_bytes)
    selection = audit['selection']
    # The frozen last-ten selector indexes the intermediate body. Preserve its
    # ledger and additionally map every occurrence back to original SDK offsets.
    def original_binding(row):
        original = survivors[row['original_image_ordinal']]
        if (original['sha256'], original['origin'], original['detail']) != (row['sha256'], row['origin'], row['detail']):
            raise ValueError('Two-stage image provenance mismatch')
        return _public(original) | {'stage_message_index': row['message_index'],
                                    'stage_part_index': row['original_part_index']}
    removed_global = [original_binding(r) for r in selection['removed']]
    retained = [original_binding(r) for r in selection['retained']]
    removed = [dict(r, reason='canvas_segment_cap') for r in segment['removed']]
    removed.extend(dict(r, reason='global_last10') for r in removed_global)
    removed.sort(key=lambda r: r['original_image_ordinal'])
    native_removed = sum(r['origin'] == 'native' for r in removed)
    audit.update(version=VERSION, scientific_policy=policy, harness=harness,
                 original_body_sha256=digest(body), original_image_count=len(original_images),
                 canvas_page_selection=segment, removed_original_images=removed,
                 retained_original_images=retained, native_images_removed=native_removed,
                 native_evidence_preserved=native_removed == 0,
                 final_canvas_counts={k: sum(r.get('segment') == k for r in retained) for k in page_budget},
                 protocol_changed_from_frozen_v1=True)
    selection['retention_policy'] = 'canvas_history5_recent2_then_last10_all_origins'
    return wire, audit


def install(out, *, rendered_registry, approved_base_url, policy, harness='hermes',
            max_images=10, page_budget=None, max_canvas_pixels=2097152,
            max_body_bytes=frozen.MAX_BODY_BYTES):
    """Fresh-worker-only HTTP adapter, with explicit experiment policy selection."""
    if policy not in POLICIES:
        raise ValueError('Explicit scientific policy required')
    endpoint = httpx.URL(approved_base_url.rstrip('/') + '/chat/completions')
    original = httpx.Client._send_single_request
    if getattr(original, '_inline_recent_ten_v1', False) or getattr(original, '_core_recent_ten_v22', False):
        raise RuntimeError('Fresh worker required; do not layer V22 over an installed old adapter')
    path = Path(out) / 'inline-images-wire-v22.jsonl'
    path.parent.mkdir(parents=True, exist_ok=True)

    def send(client, request):
        if request.url != endpoint:
            return original(client, request)
        began = time.monotonic()
        try:
            wire, row = transform(request.content, rendered_registry=rendered_registry, policy=policy,
                                  harness=harness, max_images=max_images, page_budget=page_budget,
                                  max_canvas_pixels=max_canvas_pixels, max_body_bytes=max_body_bytes)
            outgoing = frozen.chunk_request(request, wire)
        except Exception as exc:
            row = {'version': VERSION, 'scientific_policy': policy, 'decision': 'reject',
                   'network_send_authorized': False, 'at_unix': time.time(),
                   'error_type': type(exc).__name__, 'local_policy_failure': True}
            with path.open('a') as stream:
                stream.write(json.dumps(row) + '\n')
            raise TerminalTransportFailure('core_v22_local_image_policy_rejected') from None
        row.update(decision='allow', at_unix=time.time(), network_send_authorized=True,
                   client_image_preparation_seconds=time.monotonic() - began,
                   wire_stage='after_canvas_caps_then_last10_before_route_rotation')
        with path.open('a') as stream:
            stream.write(json.dumps(row, separators=(',', ':')) + '\n')
        return original(client, outgoing)

    send._core_recent_ten_v22 = True
    httpx.Client._send_single_request = send
    return {'version': VERSION, 'policy': policy, 'ledger': str(path),
            'uninstall': lambda: setattr(httpx.Client, '_send_single_request', original)}
