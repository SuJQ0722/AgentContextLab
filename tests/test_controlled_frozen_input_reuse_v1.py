import base64
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from controlled_frozen_input_reuse_v1 import resolve_inputs, stage
import capture_multimodal_prefix_v5 as capture


class InputReuseTests(unittest.TestCase):
    def fixture(self, root):
        directory = root / 'collector/input-images'; directory.mkdir(parents=True)
        buf = io.BytesIO(); Image.new('RGB', (3, 2), 'blue').save(buf, format='PNG'); raw = buf.getvalue()
        path = directory / '00.png'; path.write_bytes(raw)
        ledger = [{'source': 'https://example.test/first.png', 'path': str(path),
                   'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw), 'dimensions': [3, 2]}]
        (directory.parent / 'input-images.json').write_text(json.dumps(ledger))
        prefix = root / 'prefix.json'; prefix.write_text(json.dumps({'messages': [{'content': [
            {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,' + base64.b64encode(raw).decode()}}]}]}))
        return {'image': [ledger[0]['source']], 'native_asset_roots': [str(directory)], 'prefix_path': str(prefix)}, raw, path

    def test_exact_bytes_reused_without_network(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); row, raw, _ = self.fixture(root); out = root / 'out'; out.mkdir()
            with patch.object(capture, 'urlopen', side_effect=AssertionError('No downloads')):
                images, ledger = stage(row, out, capture.load_images)
            self.assertEqual(base64.b64decode(images[0]['image_url']['url'].split(',', 1)[1]), raw)
            self.assertEqual(ledger[0]['source'], row['image'][0])
            self.assertTrue(json.loads((out / 'input-reuse.json').read_text())['bytes_unchanged'])

    def test_source_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            row, _, _ = self.fixture(Path(d)); row['image'] = ['https://example.test/other.png']
            with self.assertRaises(ValueError): resolve_inputs(row)

    def test_missing_file_and_changed_bytes_are_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            row, _, path = self.fixture(Path(d)); path.unlink()
            with self.assertRaises(FileNotFoundError): resolve_inputs(row)
            path.write_bytes(b'changed')
            with self.assertRaises(ValueError): resolve_inputs(row)


if __name__ == '__main__': unittest.main()
