import json
from pathlib import Path
import sys
import tempfile
import unittest

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from tile_rendered_canvases import intervals, tile_images, verify_manifest


class CanvasTilingTests(unittest.TestCase):
    def test_boundaries_and_complete_exact_reconstruction(self):
        for height in (1, 32, 1504, 1536, 1537, 3040, 6045, 8854):
            with self.subTest(height=height), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                image = Image.new('RGBA', (7, height))
                image.putdata([(x * 31, y % 256, (y // 256) % 256, (x + y) % 256)
                               for y in range(height) for x in range(7)])
                source = root / 'source.png'
                image.save(source)
                path = tile_images({'images': [{'id': 'canvas', 'kind': 'rendered_canvas', 'path': str(source)}]}, root / 'out')
                manifest = json.loads(path.read_text())
                self.assertEqual((root / 'out' / manifest['images'][0]['original_file']).read_bytes(), source.read_bytes())
                self.assertTrue(verify_manifest(path)[0]['reconstruction_pixel_identical'])
                self.assertTrue(all(t['box'][3] - t['box'][1] <= 1536 for t in manifest['images'][0]['tiles']))

    def test_native_evidence_never_tiled_and_order_kept(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            canvas = root / 'canvas.png'
            native = root / 'original.jpg'
            Image.new('RGB', (9, 1600), 'red').save(canvas)
            Image.new('RGB', (9, 6000), 'blue').save(native)
            path = tile_images({'images': [{'id': 'first', 'kind': 'rendered_canvas', 'path': str(canvas)},
                                          {'id': 'second', 'kind': 'native_evidence', 'path': str(native)}]}, root / 'out')
            manifest = json.loads(path.read_text())
            self.assertEqual([r['id'] for r in manifest['images']], ['first', 'second'])
            evidence = manifest['images'][1]
            self.assertEqual(evidence['tiles'], [])
            self.assertEqual((path.parent / evidence['original_file']).read_bytes(), native.read_bytes())
            self.assertTrue(verify_manifest(path)[1]['native_bytes_preserved'])

    def test_tampered_gap_and_pixels_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); source = root / 'source.png'
            Image.new('RGB', (9, 1700), 'red').save(source)
            path = tile_images({'images': [{'id': 'a', 'kind': 'rendered_canvas', 'path': str(source)}]}, root / 'out')
            manifest = json.loads(path.read_text()); original = path.read_text()
            manifest['images'][0]['tiles'][1]['box'][1] += 1
            path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, 'coordinate'):
                verify_manifest(path)
            path.write_text(original)
            tile = path.parent / manifest['images'][0]['tiles'][0]['file']
            Image.new('RGB', (9, 1536), 'blue').save(tile)
            with self.assertRaisesRegex(ValueError, 'hash'):
                verify_manifest(path)

    def test_invalid_inputs_and_no_overwrite(self):
        for cap, overlap in ((1537, 32), (32, 32), (0, 0), (10, -1)):
            with self.assertRaises(ValueError):
                list(intervals(100, cap, overlap))
        self.assertEqual(list(intervals(4, 2, 0)), [(0, 2), (2, 4)])
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); source = root / 'source.png'
            Image.new('RGB', (3, 3)).save(source)
            spec = {'images': [{'id': 'a', 'kind': 'rendered_canvas', 'path': str(source)}]}
            tile_images(spec, root / 'out')
            with self.assertRaises(FileExistsError):
                tile_images(spec, root / 'out')
            spec['images'][0]['kind'] = 'unclassified'
            with self.assertRaises(ValueError):
                tile_images(spec, root / 'other')


if __name__ == '__main__':
    unittest.main()
