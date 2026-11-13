"""Preserve page labels across DSH's verified native image-handle text only."""
import base64,copy,hashlib,io,json,re
from PIL import Image


def verified_handle(text, part, registry):
    if part.get('type') != 'image_url': return False
    value=part.get('image_url');url=value.get('url') if isinstance(value,dict) else value
    if not isinstance(url,str) or not url.startswith('data:image/'): return False
    try:
        raw=base64.b64decode(url.split(',',1)[1],validate=True)
        sha=hashlib.sha256(raw).hexdigest()
        if sha not in registry: return False
        with Image.open(io.BytesIO(raw)) as image: width,height=image.size
    except Exception: return False
    identity=r'(?:"(?:[^"\\]|\\.)*" \()?sha256:'+sha+r'\)?'
    prefix='Image '+identity+f'; request preview {width}x{height}px\.'
    fallback=r' It may be resized or re-encoded; source dimensions, format, and byte size may differ\.'
    access=r' Normalized copy \(read-only; may be resized or re-encoded\): "(?:[^"\\]|\\.)*" \(\d+x\d+px, image/(?:png|jpeg|webp|gif)\)\. Source dimensions, format, and byte size may differ\. Copy to a writable path ending in \.(?:png|jpg|webp|gif) before editing\.'
    return re.fullmatch(prefix+'(?:'+fallback+'|'+access+')',text) is not None

def select_canvas_pages(body, registry, budget):
    """Bound labeled, verified canvas pages; preserve native images and exact bytes."""
    if set(budget) != {'history', 'recent'} or any(type(v) is not int or v < 1 for v in budget.values()):
        raise ValueError('Positive history/recent page budgets required')
    payload = json.loads(body)
    pages = []
    handles = {}
    native_count = 0
    for mi, message in enumerate(payload['messages']):
        content = message.get('content')
        if not isinstance(content, list): continue
        label = None
        for pi, part in enumerate(content):
            if part.get('type') == 'text':
                match = re.search(r'\[(History|Recent) page (\d+)/(\d+) — linear scale [^,]+, high detail\]\s*$', part.get('text', ''))
                if match:
                    label = (match.group(1).lower(), pi, part.get('text', '')[:match.start()])
                elif label is not None and pi + 1 < len(content) and verified_handle(part.get('text', ''), content[pi + 1], registry):
                    handles[(mi, pi + 1)] = pi
                else:
                    label = None
            elif part.get('type') == 'image_url':
                value = part['image_url']; url = value.get('url') if isinstance(value, dict) else value
                if not url.startswith('data:image/'): raise ValueError('Inline images required')
                raw = base64.b64decode(url.split(',', 1)[1], validate=True)
                digest = hashlib.sha256(raw).hexdigest()
                if digest in registry:
                    if label is None: raise ValueError('Canvas lacks a verified segment label')
                    pages.append({'segment': label[0], 'message_index': mi, 'label_index': label[1], 'label_prefix': label[2], 'part_index': pi, 'sha256': digest})
                else:
                    native_count += 1
                label = None
    if native_count > 10:
        raise ValueError('Native images exceed 10; refusing native evidence deletion')
    available = 10 - native_count
    effective = {'recent': min(budget['recent'], available, sum(p['segment'] == 'recent' for p in pages))}
    effective['history'] = min(budget['history'], available - effective['recent'])
    removed = []
    for segment, limit in effective.items():
        selected = [p for p in pages if p['segment'] == segment]
        removed.extend(selected[:-limit] if limit else selected)
    positions = {(p['message_index'], i) for p in removed for i in (p['part_index'], p['label_index'])}
    positions.update((p['message_index'], handles[(p['message_index'], p['part_index'])]) for p in removed if (p['message_index'], p['part_index']) in handles)
    result = copy.deepcopy(payload)
    for page in removed:
        if page['label_prefix']:
            result['messages'][page['message_index']]['content'][page['label_index']]['text'] = page['label_prefix']
            positions.discard((page['message_index'], page['label_index']))
    for mi, message in enumerate(result['messages']):
        if isinstance(message.get('content'), list):
            message['content'] = [part for pi, part in enumerate(message['content']) if (mi, pi) not in positions]
    count = sum(part.get('type') == 'image_url' for message in result['messages'] if isinstance(message.get('content'), list) for part in message['content'])
    if count > 10:
        raise ValueError('Canvas budget plus native images exceeds 10; refusing native evidence deletion')
    audit = {'version': 'dsh-canvas-handle-segments-v13', 'verified_native_handle_count': len(handles), 'budget': dict(budget), 'effective_budget': effective, 'native_count': native_count,
             'generated_counts': {k: sum(p['segment'] == k for p in pages) for k in budget},
             'retained_counts': {k: min(effective[k], sum(p['segment'] == k for p in pages)) for k in budget},
             'removed': [{k: v for k, v in p.items() if k != 'label_prefix'} for p in removed], 'native_images_preserved': True,
             'policy': 'last_pages_per_segment_no_merge_no_rescale', 'evidence_complete': not removed}
    return (json.dumps(result, ensure_ascii=False, separators=(',', ':')).encode() if removed else body), audit
