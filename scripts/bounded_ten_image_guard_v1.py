"""Independent MMBC final HTTP guard: ten images total, with no payload edits."""
import hashlib
import json
from pathlib import Path
import threading
import time
import uuid
import bounded_visual_request_guard_v1 as original_guard

VERSION = 'bounded-ten-image-request-guard-v1'
MAX_IMAGES = 10
MAX_BODY_BYTES = original_guard.MAX_BODY_BYTES
MAX_CANVAS_SIDE = original_guard.MAX_CANVAS_SIDE
MAX_CANVAS_PIXELS = original_guard.MAX_CANVAS_PIXELS

class TenImageRequestError(original_guard.BoundedVisualRequestError):
    pass

def inspect_payload(body, *, rendered_registry=None, strict_all_images=True):
    """Reuse immutable decoding/geometry/registry checks, enforce our own count."""
    try:
        row = original_guard.inspect_payload(body, rendered_registry=rendered_registry,
                                             strict_all_images=strict_all_images)
    except original_guard.BoundedVisualRequestError as error:
        row = dict(error.ledger)
    except Exception:
        row = {'body_bytes': None, 'image_count': None, 'inline_image_count': None,
               'images': [], 'violations': ['uninspectable_request'], 'payload_modified': False}
    row.update(version=VERSION, max_images=MAX_IMAGES, image_limit_scope='all image_url occurrences: native plus canvas')
    # The original inspector also checks its own 32-image policy. This independent
    # ledger states only the applicable ten-image count violation.
    row['violations'] = [v for v in row['violations'] if v != 'image_count_exceeds_32']
    count = row.get('image_count')
    if isinstance(count, int) and count > MAX_IMAGES:
        row['violations'].append('image_count_exceeds_10')
    images = row.get('images', [])
    row['verified_canvas_images'] = sum(i.get('rendered_canvas') is True for i in images)
    row['verified_native_images'] = sum(i.get('rendered_canvas') is False for i in images)
    row['unclassified_images'] = sum('rendered_canvas' not in i for i in images)
    row['remaining_canvas_slots_after_native'] = max(0, MAX_IMAGES-row['verified_native_images'])
    if row['violations']:
        raise TenImageRequestError(row)
    return row

def install(reportpath, *, rendered_registry):
    """Observe exact serialized synchronous httpx requests immediately before send."""
    import httpx
    if rendered_registry is None:
        raise ValueError('Explicit verified rendered-image registry required')
    original = httpx.Client._send_single_request
    if (getattr(original, '_bounded_visual_request_guard_v1', False)
            or getattr(original, '_bounded_ten_image_guard_v1', False)):
        raise RuntimeError('Image guard already installed; use a fresh worker')
    path = Path(reportpath); path.parent.mkdir(parents=True, exist_ok=True)
    lock = threading.Lock()
    def guarded(client, request):
        if not request.url.path.rstrip('/').endswith('/chat/completions'):
            return original(client, request)
        error = None
        try:
            if request.method != 'POST':
                raise TenImageRequestError({'version': VERSION, 'max_images': MAX_IMAGES,
                    'body_bytes': None, 'images': [], 'image_count': None,
                    'violations': ['unsupported_completion_method'], 'payload_modified': False})
            row = inspect_payload(request.content, rendered_registry=rendered_registry,
                                  strict_all_images=False)
        except TenImageRequestError as exc:
            row, error = exc.ledger, exc
        except Exception:
            row = {'version': VERSION, 'max_images': MAX_IMAGES, 'body_bytes': None,
                   'images': [], 'image_count': None, 'violations': ['uninspectable_request'],
                   'payload_modified': False}
            error = TenImageRequestError(row)
        row = {**row, 'observed_at_unix': time.time(), 'observation_id': uuid.uuid4().hex,
               'decision': 'reject' if error else 'allow', 'network_send_authorized': error is None,
               'note': 'Allow is pre-send validation, not proof of delivery or response.'}
        with lock:
            with path.open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(row, separators=(',', ':'))+'\n'); stream.flush()
        if error is not None:
            raise TenImageRequestError(row)
        return original(client, request)
    guarded._bounded_ten_image_guard_v1 = True
    # Prevent subsequent installation of the older policy on top of this guard.
    guarded._bounded_visual_request_guard_v1 = True
    httpx.Client._send_single_request = guarded
    return {'version': VERSION, 'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'reportpath': str(path), 'max_images': MAX_IMAGES, 'max_body_bytes': MAX_BODY_BYTES,
            'max_canvas_side': MAX_CANVAS_SIDE, 'max_canvas_pixels': MAX_CANVAS_PIXELS,
            'payload_modified': False, 'native_and_canvas_counted_together': True}
