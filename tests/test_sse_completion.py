"""Offline regression tests for terminal events, truncated answers and accounting."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import httpx
from sse_completion import SSECompletion
import visual_transport_runtime_v3 as runtime
from lab import runtime_path

ROOT = Path(__file__).resolve().parents[1]
USAGE = b'data: {"usage":{"prompt_tokens":7,"completion_tokens":3,"total_tokens":10}}\n\n'
DONE = b'data: [DONE]\n\n'

class SSETests(unittest.TestCase):
    def test_all_chunk_boundaries_and_no_substring_match(self):
        for newline in (b'\n', b'\r\n', b'\r'):
            prefix = b'data: {"text":"data: [DONE]"}' + newline * 2
            terminal = b'data: [DONE]' + newline * 2
            data = prefix + terminal + b'garbage' * 100
            for split in range(len(data) + 1):
                parser = SSECompletion()
                parser.feed(data[:split]);parser.feed(data[split:])
                self.assertTrue(parser.done)
                self.assertIn(parser.done_offset, (len(prefix + terminal), len(prefix + terminal)-1) if newline==b"\r\n" else (len(prefix + terminal),))
            parser = SSECompletion();parser.feed(prefix)
            self.assertFalse(parser.done)
        parser = SSECompletion();parser.feed(b'data: [DONE]\ndata: extra\n\n')
        self.assertFalse(parser.done)

    def install(self, root, base):
        return runtime.install_four_routes(runtime.DEFAULT_POLICY, root, approved_base_url=base,
                                           worker_key='offline-sse', deadline_seconds=30)

    def test_real_http_done_does_not_wait_for_connection_eof(self):
        release = threading.Event()
        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'
            def log_message(self, *args):pass
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                self.send_response(200);self.send_header('Content-Type', 'text/event-stream')
                self.send_header('Transfer-Encoding', 'chunked');self.end_headers()
                data = USAGE + DONE
                self.wfile.write(f'{len(data):x}\r\n'.encode() + data + b'\r\n');self.wfile.flush()
                release.wait(4)  # Deliberately no final HTTP chunk after SSE termination.
                self.close_connection = True
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True);thread.start()
        try:
            with tempfile.TemporaryDirectory() as root:
                base = f'http://127.0.0.1:{server.server_port}/v1';hook = self.install(root, base)
                try:
                    started = time.monotonic()
                    with httpx.Client(trust_env=False) as client:
                        result = client.post(base + '/chat/completions', json={'model':runtime.ALLOWED_MODELS[0], 'stream':True})
                    self.assertLess(time.monotonic() - started, 2)
                    self.assertEqual(result.content, USAGE + DONE)
                    rows = [json.loads(x) for x in (Path(root)/'transport-phases-v3.jsonl').read_text().splitlines()]
                    completed = [x for x in rows if x['event']=='stream_complete']
                    self.assertEqual(len(completed), 1)
                    self.assertEqual(completed[0]['completion_evidence'], 'sse_done')
                    self.assertEqual(completed[0]['raw_provider_usage']['total_tokens'], 10)
                finally:hook['uninstall']()
        finally:release.set();server.shutdown();server.server_close();thread.join()

    def test_clean_truncated_eof_retries_without_concatenating_or_losing_usage(self):
        seen = []
        def handler(request):
            seen.append(request)
            data = USAGE + b'data: {"text":"BAD"}\n\n' if len(seen)==1 else b'data: {"text":"GOOD"}\n\n' + DONE
            return httpx.Response(200, headers={'content-type':'text/event-stream'}, content=data)
        with tempfile.TemporaryDirectory() as root:
            hook = self.install(root, 'http://fixture/v1')
            try:
                with httpx.Client(transport=httpx.MockTransport(handler)) as client:
                    result = client.post('http://fixture/v1/chat/completions', json={'model':runtime.ALLOWED_MODELS[0], 'stream':True})
                self.assertEqual(len(seen), 2);self.assertNotIn(b'BAD', result.content)
                rows = [json.loads(x) for x in (Path(root)/'transport-phases-v3.jsonl').read_text().splitlines()]
                failure = next(x for x in rows if x['event']=='route_failed')
                self.assertEqual(failure['raw_provider_usage']['total_tokens'],10)
                self.assertEqual(failure['error_type'],'RemoteProtocolError')
            finally:hook['uninstall']()

    def test_javascript_stream_framing_and_route_integration(self):
        result = subprocess.run(['node','--test','tests/sse-completion.test.mjs','tests/image-data-url-cache.test.mjs','tests/dsh-pre-sdk-images.test.mjs'],cwd=ROOT,env={**os.environ,'PATH':runtime_path(ROOT)},capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
