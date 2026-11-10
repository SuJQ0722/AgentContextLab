"""Lossless encoding for bounded canvases only, with decoded-pixel proof."""
import base64
import copy
import functools
import hashlib
import io
import json
from pathlib import Path

VERSION = 'bounded-canvas-lossless-webp-v1'
ENCODER = {'format': 'WEBP', 'lossless': True, 'quality': 80, 'method': 4, 'exact': True}


def encode(raw):
    from PIL import Image
    with Image.open(io.BytesIO(raw)) as source:
        if source.format != 'PNG':
            raise ValueError('Only original PNG canvas bytes may be encoded')
        source.load(); dimensions = list(source.size); original_mode = source.mode
        if max(dimensions) > 2048 or dimensions[0] * dimensions[1] > 2097152:
            raise ValueError('Encoding cannot hide an oversized canvas')
        original = source.convert('RGBA').tobytes()
        buffer = io.BytesIO()
        source.save(buffer, **ENCODER)
    encoded = buffer.getvalue()
    with Image.open(io.BytesIO(encoded)) as restored:
        restored.load()
        if list(restored.size) != dimensions or restored.convert('RGBA').tobytes() != original:
            raise ValueError('Lossless transport changed decoded pixels')
    return encoded, {'version': VERSION, 'source_sha256': hashlib.sha256(raw).hexdigest(),
                     'output_sha256': hashlib.sha256(encoded).hexdigest(), 'source_bytes': len(raw),
                     'output_bytes': len(encoded), 'dimensions': dimensions, 'source_mode': original_mode,
                     'rgba_pixel_sha256': hashlib.sha256(json.dumps(dimensions).encode() + original).hexdigest(),
                     'rgba_pixel_identical': True, 'mime': 'image/webp', 'resolution_changed': False,
                     'encoder_parameters': dict(ENCODER)}


def encode_part(part):
    value = part.get('image_url', {})
    if not isinstance(value, dict) or not value.get('url', '').startswith('data:image/png;base64,'):
        raise ValueError('Expected an original inline PNG canvas')
    raw = base64.b64decode(value['url'].split(',', 1)[1], validate=True)
    encoded, record = encode(raw)
    result = copy.deepcopy(part)
    result['image_url']['url'] = 'data:image/webp;base64,' + base64.b64encode(encoded).decode()
    return result, encoded, record


def install(render):
    if not getattr(render, '_bounded_multimodal_renderer_v1', None):
        raise ValueError('Bounded pagination must be installed first')
    if getattr(render, '_bounded_lossless_transport_v1', False):
        raise ValueError('Encoding adapter already installed')
    original = render.render_visual_compression

    @functools.wraps(original)
    def converted(*args, **kwargs):
        stats = kwargs.get('stats')
        if stats is None:
            stats = {}; kwargs['stats'] = stats
        result = original(*args, **kwargs)
        pages = stats.get('bounded_pages')
        if not pages: return result
        head_end = kwargs.get('head_end', args[1] if len(args) > 1 else None)
        if head_end is None: raise ValueError('Missing explicit render boundary')
        target = result[head_end]
        content = target.get('content')
        if not isinstance(content, list) or content[0].get('text') != render.VISUAL_CONTEXT_PROMPT:
            raise ValueError('Cannot identify the new compressed history message')
        positions = [i for i, part in enumerate(content) if part.get('type') == 'image_url']
        if len(positions) != len(pages): raise ValueError('Page count changed before encoding')
        bounded_manifest_sha = hashlib.sha256(Path(stats['bounded_page_manifest']).read_bytes()).hexdigest()
        rewritten = copy.deepcopy(target); records = []
        for index, page in zip(positions, pages):
            if hashlib.sha256(Path(page['path']).read_bytes()).hexdigest() != page['output']['sha256']:
                raise ValueError('Original PNG source file differs from bounded manifest')
            part, raw, record = encode_part(content[index])
            if record['source_sha256'] != page['output']['sha256']:
                raise ValueError('Unexpected compressed page bytes')
            path = Path(page['path']).with_suffix('.webp')
            if path.exists() and path.read_bytes() != raw: raise ValueError('Encoded artifact already differs')
            if not path.exists():
                with path.open('xb') as stream: stream.write(raw)
            records.append({**record, 'source_path': page['path'], 'path': str(path),
                            'segment': page['segment'], 'page_index': page['page_index'], 'detail': page['detail']})
            rewritten['content'][index] = part
        manifest = {'version': VERSION, 'source_bounded_manifest': stats['bounded_page_manifest'],
                    'source_bounded_manifest_sha256': bounded_manifest_sha, 'pages': records,
                    'source_png_bytes': sum(p['source_bytes'] for p in records),
                    'wire_image_bytes': sum(p['output_bytes'] for p in records), 'native_images_encoded': 0}
        path = Path(stats['bounded_page_manifest']).with_name(Path(stats['bounded_page_manifest']).name.replace('_bounded_manifest', '_transport_manifest'))
        serialized = (json.dumps(manifest, ensure_ascii=False, indent=2) + '\n').encode()
        if path.exists() and path.read_bytes() != serialized: raise ValueError('Transport manifest differs')
        if not path.exists():
            with path.open('xb') as stream: stream.write(serialized)
        stats.update(transport_encoding=VERSION, transport_manifest=str(path),
                     transport_image_bytes=manifest['wire_image_bytes'], transport_pixel_identity_verified=True)
        return result[:head_end] + [rewritten] + result[head_end + 1:]

    render.render_visual_compression = converted
    render._bounded_lossless_transport_v1 = VERSION
    return VERSION
