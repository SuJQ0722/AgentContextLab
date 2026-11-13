import io
import base64
import json
import sys
import tempfile
import unittest
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from PIL import Image
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import info_loss_lossless_ops_v15 as v


class LosslessOpsTests(unittest.TestCase):
    def test_real_http_child_uses_webp_same_pixels_and_300_second_write(self):
        import httpx
        calls = []; testcase = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                calls.append(body)
                item = body['messages'][0]['content'][1]['image_url']
                testcase.assertEqual(item['detail'], 'high')
                raw = base64.b64decode(item['url'].split(',', 1)[1])
                with Image.open(io.BytesIO(raw)) as opened:
                    testcase.assertEqual(opened.format, 'WEBP'); testcase.assertEqual(opened.size, (11, 17))
                    testcase.assertEqual(opened.getpixel((0, 0)), (10, 20, 30))
                response = json.dumps({'model': 'fixture', 'choices': [{'finish_reason': 'stop', 'message': {'content': '{"f1":"42"}'}}],
                    'usage': {'prompt_tokens': 100, 'completion_tokens': 2, 'total_tokens': 102}}).encode()
                self.send_response(200); self.send_header('Content-Length', str(len(response))); self.end_headers(); self.wfile.write(response)
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); image = root / 'source.png'; Image.new('RGB', (11, 17), (10, 20, 30)).save(image)
            raw, proof = v.encode(image.read_bytes()); wire = root / 'wire.webp'; wire.write_bytes(raw)
            original = {'path': str(image), 'sha256': v.base.sha(image), 'width': 11, 'height': 17, 'media_type': 'image/png', 'detail': 'high'}
            v.base.save(root / 'plan.json', {'source_sha256': {}, 'prior_stage_ledger': {}, 'wire_images': {
                original['sha256']: {**original, 'path': str(wire), 'sha256': v.base.sha(wire), 'media_type': 'image/webp'}}})
            spec = root / 'request-spec.json'; v.base.save(spec, {'condition': {'case': 'q', 'method': 'canvas_1'},
                'stage': 'qa', 'prompt': 'question only', 'images': [original], 'model': 'fixture'})
            env = {'HTTPS_PROXY': f'http://127.0.0.1:{server.server_port}', 'TOKENHUB_BASE_URL': 'http://fixture.test/v1', 'TOKENHUB_API_KEY': 'fixture-only'}
            original_init = httpx.Client.__init__; timeouts = []
            def capture_init(client, *args, **kwargs):
                timeouts.append(kwargs['timeout'].write)
                return original_init(client, *args, **kwargs)
            with patch.object(v.base, 'environment', return_value=(env, {})), patch.object(httpx.Client, '__init__', capture_init):
                v.child(root, spec)
                v.child(root, spec)  # Exact completed stage reused, no second send.
            self.assertEqual(len(calls), 1)
            self.assertEqual(timeouts, [300])
            response = v.base.read(root / 'calls/q/canvas_1/qa/response.json')
            self.assertEqual(response['status'], 'completed'); self.assertEqual(response['usage']['total_tokens'], 102)

    def test_old_failure_blocks_before_encoding_new_fingerprint(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); old = root / 'old.json'
            old.write_text(json.dumps({'status': 'transport_error', 'error_type': 'WriteTimeout', 'content': '', 'usage': None}))
            condition = {'case': 'q', 'method': 'canvas_0.75'}
            plan = {'prior_stage_ledger': {'q/canvas_0.75/qa': {'started': {'path': 'old-start'}, 'response': v.base.binding(old)}}}
            with patch.object(v, 'converted_payload', side_effect=AssertionError('Must check old stage first')), \
                    patch.object(v.subprocess, 'Popen', side_effect=AssertionError('No duplicate request')):
                result = v.bounded_call(plan, root, condition, 'qa', 'same prompt', [], 'same model')
            self.assertEqual(result['error_type'], 'WriteTimeout')
            self.assertFalse((root / 'calls').exists())

    def test_old_unknown_also_consumes_stage(self):
        plan = {'prior_stage_ledger': {'q/canvas_1/reconstruction': {'started': {'path': 'old'}, 'response': None}}}
        result = v.previous_stage(plan, {'case': 'q', 'method': 'canvas_1'}, 'reconstruction')
        self.assertEqual(result['status'], 'unknown_prior_start')
        self.assertFalse(result['new_api_call'])

    def test_lossless_encoded_pixels_detail_and_order(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); source = root / 'source.png'
            image = Image.new('RGBA', (23, 41), (10, 20, 30, 255)); image.putpixel((4, 7), (255, 0, 1, 128)); image.save(source)
            encoded, proof = v.encode(source.read_bytes()); target = root / 'wire.webp'; target.write_bytes(encoded)
            original = {'path': str(source), 'sha256': v.base.sha(source), 'width': 23, 'height': 41, 'media_type': 'image/png', 'detail': 'high'}
            plan = {'wire_images': {original['sha256']: {**original, 'path': str(target), 'sha256': v.base.sha(target), 'media_type': 'image/webp'}}}
            result = v.converted_payload(plan, 'same', [original, original], 'model')
            content = result['messages'][0]['content']
            self.assertEqual(len(content), 3); self.assertEqual(content[1], content[2])
            self.assertEqual(content[1]['image_url']['detail'], 'high')
            self.assertTrue(proof['rgba_pixel_identical'])
            with Image.open(io.BytesIO(encoded)) as restored: self.assertEqual(restored.convert('RGBA').tobytes(), image.tobytes())


if __name__ == '__main__': unittest.main()
