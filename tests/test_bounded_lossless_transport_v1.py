import base64
import copy
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest

from PIL import Image
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import bounded_lossless_transport_v1 as transport


def image_bytes(mode='RGB', size=(16, 12)):
    image = Image.new(mode, size)
    if size[0] * size[1] < 10000:
        values = []
        for y in range(size[1]):
            for x in range(size[0]):
                color = ((x * 37 + y) % 256, (x + y * 61) % 256, (x * 79 + y * 13) % 256)
                values.append(color + ((0 if x % 3 == 0 else 127 if x % 3 == 1 else 255),) if mode == 'RGBA' else color)
        image.putdata(values)
    buffer = io.BytesIO(); image.save(buffer, format='PNG'); return buffer.getvalue()


def part(raw, detail='high'):
    return {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,' + base64.b64encode(raw).decode(), 'detail': detail}}


def rgba(raw):
    with Image.open(io.BytesIO(raw)) as image: return image.size, image.convert('RGBA').tobytes()


class LosslessBoundedTransportTests(unittest.TestCase):
    def test_rgb_and_transparent_hidden_rgb_are_pixel_exact(self):
        for mode in ('RGB', 'RGBA'):
            raw = image_bytes(mode); encoded, record = transport.encode(raw)
            self.assertEqual(rgba(raw), rgba(encoded))
            self.assertEqual(record['source_sha256'], hashlib.sha256(raw).hexdigest())
            self.assertEqual(record['output_sha256'], hashlib.sha256(encoded).hexdigest())
            self.assertTrue(record['rgba_pixel_identical']); self.assertFalse(record['resolution_changed'])
            self.assertEqual(record['encoder_parameters'], {'format': 'WEBP', 'lossless': True, 'quality': 80, 'method': 4, 'exact': True})
            if mode == 'RGBA':
                pixels = rgba(raw)[1]; self.assertTrue(any(pixels[i + 3] == 0 and any(pixels[i:i + 3]) for i in range(0, len(pixels), 4)))

    def test_oversized_canvas_cannot_be_hidden_by_encoding(self):
        for size in ((2049, 5), (1025, 2048)):
            with self.assertRaisesRegex(ValueError, 'oversized'): transport.encode(image_bytes(size=size))

    def test_reject_non_png_disguised_as_png_and_remote_url(self):
        buffer = io.BytesIO(); Image.new('RGB', (4, 4)).save(buffer, format='JPEG')
        with self.assertRaisesRegex(ValueError, 'PNG'): transport.encode_part(part(buffer.getvalue()))
        with self.assertRaisesRegex(ValueError, 'inline PNG'):
            transport.encode_part({'type': 'image_url', 'image_url': {'url': 'https://example.test/img.png'}})

    def fixture(self, directory):
        raw = image_bytes('RGBA'); source = directory / 'compact_1_recent_001.png'; source.write_bytes(raw)
        bound = directory / 'compact_1_bounded_manifest.json'; bound.write_text('{"version":"fixture"}')
        page = {'path': str(source), 'output': {'sha256': hashlib.sha256(raw).hexdigest()},
                'segment': 'recent', 'page_index': 1, 'detail': 'high'}
        head = {'role': 'user', 'content': [{'type': 'text', 'text': 'native head'}, part(raw, 'auto')]}
        tail = {'role': 'tool', 'content': [part(raw, 'auto')]}
        compression = {'role': 'user', 'content': [{'type': 'text', 'text': 'COMPRESSED'}, part(raw)]}
        original_result = [head, compression, tail]
        def render(*args, **kwargs):
            kwargs['stats'].update(bounded_pages=[page], bounded_page_manifest=str(bound))
            return original_result
        module = types.SimpleNamespace(_bounded_multimodal_renderer_v1={'version': 'fixture'},
                    render_visual_compression=render, VISUAL_CONTEXT_PROMPT='COMPRESSED')
        return module, original_result, page, source, bound

    def test_only_compressed_pages_encoded_native_objects_preserved_manifest_bound(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp); module, original, page, source, bound = self.fixture(directory)
            snapshot = copy.deepcopy(original); stats = {}; transport.install(module)
            result = module.render_visual_compression([], 1, stats=stats)
            self.assertIs(result[0], original[0]); self.assertIs(result[2], original[2])
            self.assertEqual(original, snapshot)
            self.assertTrue(result[1]['content'][1]['image_url']['url'].startswith('data:image/webp;base64,'))
            self.assertEqual(result[1]['content'][1]['image_url']['detail'], 'high')
            self.assertTrue(result[0]['content'][1]['image_url']['url'].startswith('data:image/png;base64,'))
            manifest = json.loads(Path(stats['transport_manifest']).read_text())
            self.assertEqual(manifest['native_images_encoded'], 0)
            self.assertEqual(manifest['source_bounded_manifest_sha256'], hashlib.sha256(bound.read_bytes()).hexdigest())
            self.assertEqual(len(manifest['pages']), 1)
            encoded_path = Path(manifest['pages'][0]['path'])
            self.assertEqual(rgba(source.read_bytes()), rgba(encoded_path.read_bytes()))
            self.assertEqual(manifest['pages'][0]['output_sha256'], hashlib.sha256(encoded_path.read_bytes()).hexdigest())

    def test_disk_source_and_inline_source_mismatch_refused(self):
        for target in ('disk', 'inline'):
            with tempfile.TemporaryDirectory() as tmp:
                directory = Path(tmp); module, original, page, source, bound = self.fixture(directory)
                if target == 'disk': source.write_bytes(image_bytes('RGB'))
                else: original[1]['content'][1] = part(image_bytes('RGB'))
                transport.install(module)
                with self.assertRaisesRegex(ValueError, 'source file|page bytes'):
                    module.render_visual_compression([], 1, stats={})
                self.assertFalse(list(directory.glob('*.webp')))
                self.assertFalse(list(directory.glob('*_transport_manifest.json')))

    def test_no_render_pages_and_wrong_install_order(self):
        original = [{'role': 'user', 'content': 'unchanged'}]
        module = types.SimpleNamespace(render_visual_compression=lambda *a, **k: original)
        with self.assertRaisesRegex(ValueError, 'pagination'): transport.install(module)
        module._bounded_multimodal_renderer_v1 = True; transport.install(module)
        self.assertIs(module.render_visual_compression([], 0, stats={}), original)
        with self.assertRaisesRegex(ValueError, 'already installed'): transport.install(module)

    def test_existing_different_transport_artifact_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp); module, original, page, source, bound = self.fixture(directory)
            encoded = source.with_suffix('.webp'); encoded.write_bytes(b'old artifact'); transport.install(module)
            with self.assertRaisesRegex(ValueError, 'already differs'):
                module.render_visual_compression([], 1, stats={})
            self.assertEqual(encoded.read_bytes(), b'old artifact')


if __name__ == '__main__': unittest.main()
