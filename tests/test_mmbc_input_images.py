import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from PIL import Image
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import mmbc_input_images as assets
from run_bc_campaign_v3 import digest


class InputImageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.url = 'https://raw.githubusercontent.com/test/images/main/a.png'
        (self.root/'cohort.jsonl').write_text(json.dumps({'question_id':'q1','question':'test','image':[self.url]})+'\n')
        buffer = io.BytesIO(); Image.new('RGB', (8, 8), 'red').save(buffer, format='PNG')
        self.raw = buffer.getvalue(); self.requests = 0
    def opener(self, url, timeout):
        self.assertEqual(url, self.url); self.requests += 1
        return io.BytesIO(self.raw)
    def freeze(self):
        result = assets.prepare(self.root, opener=self.opener)
        (self.root/'plan.json').write_text(json.dumps({'definition': {'input_images_sha256':digest((self.root/'image-assets/manifest.json').read_bytes())}}))
        return result
    def test_resume_and_repeat_preserve_exact_bytes_without_network(self):
        self.freeze(); assets.prepare(self.root, opener=self.opener)
        self.assertEqual(self.requests, 1)
        for i in range(3):
            workspace = self.root/str(i); workspace.mkdir()
            result = assets.stage_images({'campaign_root': str(self.root), 'image':[self.url]}, workspace)
            self.assertEqual(Path(result[0]['path']).read_bytes(), self.raw)
    def test_changed_pixels_or_manifest_are_rejected(self):
        result = self.freeze(); path = self.root/result['images'][self.url]['relative_path']
        path.write_bytes(b'changed')
        with self.assertRaises(ValueError):
            assets.stage_images({'campaign_root':str(self.root),'image':[self.url]}, self.root)
    def test_missing_asset_not_silently_replaced(self):
        result = self.freeze(); (self.root/result['images'][self.url]['relative_path']).unlink()
        with self.assertRaises(ValueError): assets.prepare(self.root, opener=self.opener)
        self.assertEqual(self.requests, 1)
    def test_manifest_traversal_rejected(self):
        result = self.freeze(); result['images'][self.url]['relative_path'] = '../outside.png'
        (self.root/'image-assets/manifest.json').write_text(json.dumps(result))
        with self.assertRaises(ValueError): assets.validate_assets(self.root)
    def test_empty_image_question_has_no_inserted_image(self):
        self.freeze()
        self.assertEqual(assets.stage_images({'campaign_root':str(self.root),'image':[]}, self.root), [])


if __name__ == '__main__': unittest.main()
