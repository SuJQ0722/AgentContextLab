import base64
import contextvars
import json
import sys
import tempfile
import threading
import types
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import controlled_native_engine_v17 as engine


class EngineTests(unittest.TestCase):
    def test_sdk_dynamic_target_over_16k_overshoot_trim_preserves_native(self):
        import httpx
        from openai import OpenAI
        from openai.resources.chat.completions import Completions
        import capture_multimodal_prefix_v5 as capture
        native = {'type': 'image_url', 'image_url': {
            'url': 'data:image/png;base64,' + base64.b64encode(b'fixture-native').decode(), 'detail': 'high'}}
        summary = 'Supported archived fact. ' * 1200
        sent = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                sent.append(payload)
                generation = payload.get('max_tokens') == 8192
                if generation:
                    self.server.testcase.assertEqual(payload.get('thinking'), {'type': 'disabled'})
                    content = json.dumps({'summary': summary})
                    prompt = 2000
                else:
                    parts = payload['messages'][0]['content']
                    self.server.testcase.assertEqual(parts[1], native)
                    text = parts[2]['text'] if len(parts) > 2 else ''
                    self.server.testcase.assertTrue(summary.startswith(text))
                    prompt = 1000 + len(text)
                    content = 'final answer'
                raw = json.dumps({'id': 'local-fixture', 'object': 'chat.completion', 'created': 1,
                    'model': 'fixture', 'choices': [{'index': 0, 'finish_reason': 'stop',
                    'message': {'role': 'assistant', 'content': content}}],
                    'usage': {'prompt_tokens': prompt, 'completion_tokens': 1,
                              'total_tokens': prompt + 1, 'prompt_tokens_details': {'cached_tokens': 0}}}).encode()
                self.send_response(200); self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(raw))); self.end_headers(); self.wfile.write(raw)
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler); server.testcase = self
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder); prefix = out / 'prefix.json'; target = out / 'target.json'
            prefix.write_text(json.dumps({'model': 'fixture', 'messages': [
                {'role': 'user', 'content': [{'type': 'text', 'text': 'archived'}, native]}]}))
            target.write_text(json.dumps({'version': 'source-vera-total-prompt-reference-v17', 'source_usage_verified': True, 'image_token_parity_claimed': False,
                'prefix_sha256': engine.hashlib.sha256(prefix.read_bytes()).hexdigest(),
                'baseline_native_hashes': engine.image_ids([native]), 'source_first_post_prompt_tokens': 20000}))
            spec = {'model': 'fixture', 'method': 'summary', 'prefix_path': str(prefix),
                    'target_reference_path': str(target), 'question': 'task', 'question_id': 'local',
                    'source_target_upper': 20400, 'source_native_root': str(engine.ROOT/'outputs/preflight/fixture')}
            metrics = out / 'metrics'; metrics.mkdir()
            class Recorder:
                def __init__(self):
                    self.out = metrics; self.purpose = contextvars.ContextVar('purpose', default='agent')
                def write(self, name, value):
                    with (metrics / name).open('a') as stream: stream.write(json.dumps(value) + '\n')
                def archive(self, value): pass
            recorder = Recorder(); sdk = Completions.create
            def measured(obj, *args, **kwargs):
                result = sdk(obj, *args, **kwargs)
                recorder.write('calls.jsonl', {'call_id': str(len(sent)), 'purpose': recorder.purpose.get(),
                    'raw_provider_usage': result.usage.model_dump()})
                return result
            def fake_capture_worker(spec, path):
                capture.install_capture(recorder)
                client = OpenAI(base_url=f'http://127.0.0.1:{server.server_port}/v1', api_key='fixture-only', max_retries=0,
                                http_client=httpx.Client(trust_env=False))
                result = client.chat.completions.create(model='fixture', messages=[{'role': 'user', 'content': 'task'}], max_tokens=100, stream=False)
                (out / 'conversation.json').write_text(json.dumps({'final_response': result.choices[0].message.content}))
            with patch.object(Completions, 'create', measured), patch.object(capture, 'worker', fake_capture_worker), \
                    patch.object(capture, 'install_capture', None), patch.object(capture, 'write', capture.write):
                engine.run(spec, out)
            result = json.loads((out / 'result.json').read_text())
            self.assertEqual(result['status'], 'completed', result)
            self.assertTrue(result['control_gate']['passed'])
            self.assertGreater(result['control_gate']['first_actual_prompt_tokens'], 16384)
            self.assertFalse(result['control_gate']['image_token_parity_claimed'])
            self.assertEqual(result['control_gate']['native_hashes'], engine.image_ids([native]))
            self.assertEqual(sum(p.get('max_tokens') == 8192 for p in sent), 1)
            self.assertLessEqual(len(sent), 14)
            self.assertTrue(summary.startswith(json.loads((out / 'representation.json').read_text())[0]['text']))
            self.assertTrue((metrics / 'summary-prefix-fit.jsonl').exists())


if __name__ == '__main__': unittest.main()
