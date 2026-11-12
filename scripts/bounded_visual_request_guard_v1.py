"""Exact final HTTP limits for bounded visual requests; never edits a payload."""
from __future__ import annotations

import base64
import hashlib
import io
import json
import threading
import time
import uuid
from pathlib import Path

MAX_BODY_BYTES = 8 * 1024 * 1024
MAX_IMAGES = 32
MAX_CANVAS_SIDE = 2048
MAX_CANVAS_PIXELS = 1024 * 2048
VERSION = 'bounded-visual-request-guard-v1'


class BoundedVisualRequestError(RuntimeError):
    def __init__(self, ledger):
        self.ledger = ledger
        super().__init__('Bounded visual request rejected: ' + ', '.join(ledger['violations']))


def inspect_payload(body, *, rendered_registry=None, strict_all_images=True, max_canvas_pixels=MAX_CANVAS_PIXELS):
    """Inspect exact serialized bytes. Registry identities are decoded image SHA256.

    Preflight defaults to applying canvas limits to every inline image. Workers
    must supply the current rendered registry and explicitly disable that mode.
    Returned/error ledgers contain hashes and dimensions, never image/text data.
    """
    if not isinstance(body, (bytes, bytearray, memoryview)):
        raise TypeError('Exact serialized HTTP body bytes required')
    if type(max_canvas_pixels) is not int or not 1 <= max_canvas_pixels <= 1280*2048:
        raise ValueError('Invalid explicit canvas pixel limit')
    body = bytes(body)
    row = {'version': VERSION, 'body_bytes': len(body),
           'body_sha256': hashlib.sha256(body).hexdigest(), 'image_count': 0,
           'inline_image_count': 0, 'images': [], 'violations': [],
           'strict_all_images': bool(strict_all_images), 'payload_modified': False}

    def fail(code):
        if code not in row['violations']:
            row['violations'].append(code)

    if len(body) > MAX_BODY_BYTES:
        fail('body_exceeds_8_mib')
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeError):
        fail('invalid_json')
        raise BoundedVisualRequestError(row) from None
    if not isinstance(payload, dict) or not isinstance(payload.get('messages'), list):
        fail('invalid_chat_messages')
        raise BoundedVisualRequestError(row)
    try:
        registry = rendered_registry() if callable(rendered_registry) else rendered_registry
        if registry is None and not strict_all_images:
            raise ValueError('Missing rendered registry')
        registry = set(registry or ())
        if any(not isinstance(x, str) or len(x) != 64 or
               any(c not in '0123456789abcdef' for c in x) for x in registry):
            raise ValueError('Invalid rendered SHA256 registry')
    except Exception:
        fail('rendered_registry_unavailable_or_invalid')
        raise BoundedVisualRequestError(row) from None

    from PIL import Image
    for mi, message in enumerate(payload['messages']):
        if not isinstance(message, dict):
            fail('invalid_message'); continue
        content = message.get('content')
        if not isinstance(content, list):
            continue
        for pi, part in enumerate(content):
            if not isinstance(part, dict):
                fail('invalid_content_part'); continue
            kind = part.get('type')
            if kind in ('image', 'input_image'):
                fail('unsupported_image_block'); continue
            if kind != 'image_url':
                continue
            row['image_count'] += 1
            item = {'message_index': mi, 'part_index': pi}
            row['images'].append(item)
            value = part.get('image_url')
            url = value.get('url') if isinstance(value, dict) else value
            if not isinstance(url, str) or not url.startswith('data:image/'):
                item['inline'] = False; fail('unverifiable_image_url'); continue
            row['inline_image_count'] += 1
            item['inline'] = True
            try:
                header, encoded = url.split(',', 1)
                if not header.endswith(';base64'):
                    raise ValueError('Not base64')
                data = base64.b64decode(encoded, validate=True)
                if not data:
                    raise ValueError('Empty image')
                sha = hashlib.sha256(data).hexdigest()
                with Image.open(io.BytesIO(data)) as image:
                    width, height = image.size
                    image.verify()
                if width <= 0 or height <= 0:
                    raise ValueError('Invalid dimensions')
            except Exception:
                fail('invalid_inline_image'); continue
            rendered = sha in registry
            item.update(sha256=sha, bytes=len(data), width=width, height=height,
                        pixels=width * height, rendered_canvas=rendered)
            if strict_all_images or rendered:
                if max(width, height) > MAX_CANVAS_SIDE:
                    fail('canvas_side_exceeds_2048')
                if width * height > max_canvas_pixels:
                    fail(f'canvas_area_exceeds_{max_canvas_pixels}')
    if row['image_count'] > MAX_IMAGES:
        fail('image_count_exceeds_32')
    if row['violations']:
        raise BoundedVisualRequestError(row)
    return row


def install(reportpath, *, rendered_registry):
    """Install on this process's final synchronous httpx send boundary.

    Requires a set/callable registry even when empty. The callable is evaluated
    on each request. A ledger write failure also blocks sending. No uninstaller
    is provided: use a fresh worker for a new guard policy.
    """
    import httpx
    if rendered_registry is None:
        raise ValueError('Explicit rendered image registry required')
    original = httpx.Client._send_single_request
    if getattr(original, '_bounded_visual_request_guard_v1', False):
        raise RuntimeError('Bounded visual guard already installed')
    path = Path(reportpath)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = threading.Lock()

    def guarded(client, request):
        if not request.url.path.rstrip('/').endswith('/chat/completions'):
            return original(client, request)
        if request.method != 'POST':
            row = {'version': VERSION, 'body_bytes': None, 'images': [],
                   'image_count': None, 'violations': ['unsupported_completion_method'],
                   'payload_modified': False}
            error = BoundedVisualRequestError(row)
        else:
            try:
                row = inspect_payload(request.content, rendered_registry=rendered_registry,
                                      strict_all_images=False)
                error = None
            except BoundedVisualRequestError as exc:
                row, error = exc.ledger, exc
            except Exception:
                row = {'version': VERSION, 'body_bytes': None, 'images': [],
                       'image_count': None, 'violations': ['uninspectable_request'],
                       'payload_modified': False}
                error = BoundedVisualRequestError(row)
        row = {**row, 'observed_at_unix': time.time(), 'observation_id': uuid.uuid4().hex,
               'decision': 'reject' if error else 'allow',
               'network_send_authorized': error is None,
               'note': 'Allow is pre-send validation, not proof of delivery or response.'}
        with lock:
            with path.open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(row, separators=(',', ':')) + '\n')
                stream.flush()
        if error is not None:
            raise BoundedVisualRequestError(row)
        return original(client, request)

    guarded._bounded_visual_request_guard_v1 = True
    httpx.Client._send_single_request = guarded
    return {'version': VERSION, 'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'reportpath': str(path), 'max_body_bytes': MAX_BODY_BYTES,
            'max_images': MAX_IMAGES, 'max_canvas_side': MAX_CANVAS_SIDE,
            'max_canvas_pixels': MAX_CANVAS_PIXELS,
            'registry_identity': 'sha256 of decoded image bytes', 'payload_modified': False}
