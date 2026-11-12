import base64
import hashlib
import importlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import httpx
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from compression_inline_only import CompressionHostingRemoved
from inline_visual_transport_v1 import install


class InlineOnlyTests(unittest.TestCase):
    def image(self):
        buffer = io.BytesIO()
        Image.new('RGB', (8, 8), 'blue').save(buffer, format='PNG')
        return buffer.getvalue()

    def test_legacy_host_cache_and_credentials_cannot_enable_upload_or_url_reuse(self):
        raw = self.image()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = root / 'hosted'
            cache.mkdir()
            (cache / (hashlib.sha256(raw).hexdigest() + '.json')).write_text(
                json.dumps({'url': 'https://i.ibb.co/fixture/canvas.png', 'byte_identical': True}))
            for name in ('verified_hosted_images_v3', 'verified_hosted_images_v4'):
                with self.subTest(module=name):
                    module = importlib.import_module(name)
                    with patch('httpx.Client.send', side_effect=AssertionError('No HTTP allowed')), \
                         patch('requests.sessions.Session.request', side_effect=AssertionError('No upload allowed')):
                        host = module.VerifiedImageHost(root, {'IMAGE_UPLOAD_API_KEY': 'fixture'})
                        with self.assertRaises(CompressionHostingRemoved):
                            host.ensure(raw)
                        with self.assertRaises(CompressionHostingRemoved):
                            module.transform(b'{}', rendered_registry=set(), host=lambda _: self.fail('host called'))
                        with self.assertRaises(CompressionHostingRemoved):
                            module.install(root, rendered_registry=set(), host=host, approved_base_url='http://fixture/v1')

    def test_retired_workers_fail_before_loading_credentials_or_starting_requests(self):
        names = ('info_loss_phase4_url', 'info_loss_phase4_url_ops', 'info_loss_phase4_url_ops2',
                 'info_loss_phase4_url_ops3', 'info_loss_phase4_rate_ops4',
                 'dsh_hosted_transport_bridge_v1', 'dsh_hosted_transport_bridge_v2',
                 'visual_hosted_diagnostic_v3', 'controlled_hosted_visual_worker_v1',
                 'controlled_hosted_visual_worker_v2', 'dsh_hosted_bc_worker_v1',
                 'dsh_hosted_bc_worker_v2', 'hermes_visual_hosted_retry_worker_v1',
                 'hermes_visual_hosted_retry_worker_v2', 'hermes_mmbc_hosted_worker_v3',
                 'preflight_visual_hosted_transport_v4')
        for name in names:
            with self.subTest(module=name), patch.object(sys, 'argv', [name]), \
                 patch('httpx.Client.send', side_effect=AssertionError('No HTTP allowed')):
                with self.assertRaises(CompressionHostingRemoved):
                    importlib.import_module(name).main()

    def test_hermes_wire_retains_ten_exact_inline_images_and_text_without_hosting(self):
        raw = self.image()
        uri = 'data:image/png;base64,' + base64.b64encode(raw).decode()
        parts = [{'type': 'image_url', 'image_url': {'url': uri, 'detail': 'high'}} for _ in range(12)]
        payload = {'model': 'fixture', 'messages': [{'role': 'user', 'content': [{'type': 'text', 'text': 'fixed prompt'}] + parts}]}
        received = []
        with tempfile.TemporaryDirectory() as directory:
            hook = install(directory, rendered_registry={hashlib.sha256(raw).hexdigest()}, approved_base_url='http://fixture/v1')
            def handle(request):
                self.assertEqual(str(request.url), 'http://fixture/v1/chat/completions')
                received.append(json.loads(request.read()))
                return httpx.Response(200, json={'ok': True})
            try:
                with patch('requests.sessions.Session.request', side_effect=AssertionError('No image hosting')), \
                     httpx.Client(transport=httpx.MockTransport(handle)) as client:
                    client.post('http://fixture/v1/chat/completions', json=payload)
            finally:
                hook['uninstall']()
            content = received[0]['messages'][0]['content']
            self.assertEqual(content[0], payload['messages'][0]['content'][0])
            self.assertEqual(content[1:], parts[-10:])
            self.assertTrue(all(base64.b64decode(p['image_url']['url'].split(',')[1]) == raw for p in content[1:]))
            ledger = json.loads((Path(directory) / 'inline-images-wire-v1.jsonl').read_text())
            self.assertEqual(ledger['hosting_calls'], 0)
            self.assertEqual(ledger['selection']['removed_image_count'], 2)

    def test_dsh_bridge_delivers_inline_bytes_without_host_cache(self):
        raw = self.image()
        uri = 'data:image/png;base64,' + base64.b64encode(raw).decode()
        payload = {'messages': [{'role': 'user', 'content': [{'type': 'image_url', 'image_url': {'url': uri}} for _ in range(11)]}]}
        with tempfile.TemporaryDirectory() as directory:
            run = subprocess.run([sys.executable, str(ROOT / 'scripts/dsh_inline_transport_bridge_v1.py'),
                                  '--canvas-root', directory], input=json.dumps({'id': 1, 'body': json.dumps(payload)}) + '\n',
                                 text=True, capture_output=True, timeout=30)
            self.assertEqual(run.returncode, 0, run.stderr)
            row = json.loads(run.stdout)
            self.assertTrue(row['ok'])
            images = json.loads(row['wire'])['messages'][0]['content']
            self.assertEqual(len(images), 10)
            self.assertTrue(all(p['image_url']['url'] == uri for p in images))
            self.assertEqual(row['ledger']['hosting_calls'], 0)
            self.assertFalse(list(Path(directory).glob('**/*upload*')))

    def test_information_loss_uses_verified_inline_payload_and_never_url_hosting(self):
        import info_loss_phase4 as study
        sent = []
        raw = self.image()
        class HTTP:
            def __init__(self, **kwargs): pass
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def post(self, endpoint, **kwargs):
                sent.append(json.loads(kwargs['content']))
                return httpx.Response(200, json={'model': study.old.MODEL, 'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2},
                                                'choices': [{'message': {'content': 'ok'}, 'finish_reason': 'stop'}]})
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'canvas.png'
            path.write_bytes(raw)
            manifest = {'model': study.old.MODEL, 'max_requests': 1, 'max_output_tokens': 8192,
                        'max_request_wall_seconds': 30, 'thinking': {'type': 'disabled'}}
            env = {'TOKENHUB_BASE_URL': 'http://fixture', 'TOKENHUB_API_KEY': 'fixture', 'https_proxy': 'http://fixture'}
            # This offline transport test must not wait for the host's live
            # experiment process count to fall below the production throttle.
            original_iterdir = Path.iterdir
            def fixture_iterdir(path):
                return iter(()) if str(path) == '/proc' else original_iterdir(path)
            with patch.object(Path, 'iterdir', fixture_iterdir), \
                 patch.object(study, 'environment', return_value=(env, {})), patch.object(study.httpx, 'Client', HTTP), \
                 patch('requests.sessions.Session.request', side_effect=AssertionError('No upload')):
                client = study.Client(root, manifest)
                item = {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'media_type': 'image/png', 'detail': 'high'}
                result = client.call('one', 'fixed prompt', [item])
                self.assertEqual(result['status'], 'completed')
                self.assertEqual(client.call('one', 'fixed prompt', [item]), result)
            self.assertEqual(len(sent), 1)
            image = sent[0]['messages'][0]['content'][1]['image_url']
            self.assertEqual(image['detail'], 'high')
            self.assertEqual(base64.b64decode(image['url'].split(',')[1]), raw)


if __name__ == '__main__':
    unittest.main()
