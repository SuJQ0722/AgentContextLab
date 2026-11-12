"""Offline regression: five-image final wire shared by Hermes and DSH."""
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import inline_visual_transport_v1 as inline


class FiveImageRetentionTests(unittest.TestCase):
    def fixture(self):
        parts = [{'type': 'text', 'text': 'Keep exact facts and tools'}]
        raw_images = []
        for i in range(8):
            buf = io.BytesIO()
            Image.new('RGB', (16, 16), (i * 20, 0, 0)).save(buf, format='PNG')
            raw_images.append(buf.getvalue())
            parts.append({'type': 'image_url', 'image_url': {
                'url': 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode(), 'detail': 'high'}})
        body = json.dumps({'messages': [{'role': 'user', 'content': parts}],
                           'tools': [{'type': 'function', 'function': {'name': 'web_search'}}]}).encode()
        return body, raw_images

    def test_visual_five_keeps_last_exact_bytes_and_audits_native_canvas(self):
        body, images = self.fixture()
        registry = {hashlib.sha256(raw).hexdigest() for raw in images[::2]}
        wire, row = inline.transform(body, rendered_registry=registry, max_images=5)
        before, after = json.loads(body), json.loads(wire)
        self.assertEqual(after['messages'][0]['content'], before['messages'][0]['content'][:1] + before['messages'][0]['content'][-5:])
        self.assertEqual(after['tools'], before['tools'])
        self.assertEqual(row['image_count'], 5)
        self.assertEqual(row['version'], 'inline-recent-5-chunked-v2')
        self.assertEqual(row['selection']['retention_policy'], 'last_5_in_message_order')
        self.assertEqual([x['origin'] for x in row['selection']['removed']], ['canvas', 'native', 'canvas'])
        self.assertEqual(row['hosting_calls'], 0)
        self.assertFalse(row['pages_merged'])

    def test_baseline_default_and_explicit_historical_limit_unchanged(self):
        body, _ = self.fixture()
        wire, row = inline.transform(body, rendered_registry=set())
        self.assertEqual(wire, body)
        self.assertEqual(row['image_count'], 8)
        self.assertEqual(inline.visual_max_images({'visual_image_retention': {'max_images_per_request': 10}}), 10)
        self.assertEqual(inline.visual_max_images({}), 5)
        for value in (True, 0, 11, 5.0):
            with self.assertRaises(ValueError):
                inline.transform(body, rendered_registry=set(), max_images=value)

    def test_dsh_bridge_matches_hermes_five_image_wire_without_network(self):
        body, _ = self.fixture()
        expected, _ = inline.transform(body, rendered_registry=set(), max_images=5)
        with tempfile.TemporaryDirectory() as directory:
            env = dict(os.environ, ACL_INLINE_DSH_RETAIN_IMAGES='5')
            run = subprocess.run([sys.executable, str(ROOT / 'scripts/dsh_inline_transport_bridge_v1.py'),
                                  '--canvas-root', directory],
                                 input=json.dumps({'id': 'offline-fixture', 'body': body.decode()}) + '\n',
                                 text=True, capture_output=True, env=env, timeout=30)
            self.assertEqual(run.returncode, 0, run.stderr)
            row = json.loads(run.stdout)
            self.assertTrue(row['ok'], row)
            self.assertEqual(row['wire'].encode(), expected)
            self.assertEqual(row['ledger']['image_count'], 5)


if __name__ == '__main__':
    unittest.main()
