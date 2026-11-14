import json
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import httpx
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import mmbc_bounded_route_runtime_v1 as runtime
import visual_transport_runtime_v4 as frozen
import hermes_mmbc_bounded_calls_worker_v1 as worker


class MMBCBoundedRequestTests(unittest.TestCase):
    def run_server(self, outcomes, calls, delay=0):
        class Proxy(BaseHTTPRequestHandler):
            def log_message(self, *args):pass
            def do_POST(self):
                payload=json.loads(self.rfile.read(int(self.headers['content-length'])))
                calls.append(payload)
                status=outcomes[min(len(calls)-1,len(outcomes)-1)]
                if delay:time.sleep(delay)
                raw=(b'data: {"usage":{"prompt_tokens":1,"completion_tokens":1,"total_tokens":2}}\n\ndata: [DONE]\n\n' if status==200 else b'{"error":{"message":"fixture"}}')
                try:
                    self.send_response(status);self.send_header('Content-Length',str(len(raw)))
                    self.send_header('Content-Type','text/event-stream'if status==200 else'application/json')
                    self.end_headers();self.wfile.write(raw)
                except (BrokenPipeError,ConnectionResetError):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Proxy)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(lambda:(server.shutdown(),server.server_close(),thread.join()))
        return 'http://127.0.0.1:'+str(server.server_port)

    def install(self, root, proxy, max_http_attempts=2, **policy):
        return runtime.install({**frozen.DEFAULT_POLICY,'max_failed_sends':max_http_attempts,**policy},root,approved_base_url='http://fixture/v1',
                               gateway_proxy=proxy,worker_key='offline',deadline_seconds=30,max_http_attempts=max_http_attempts)

    def test_three_send_candidate_preserves_third_route_success_and_caps_next_call(self):
        calls=[];proxy=self.run_server([503,503,200,503,503,503],calls)
        with tempfile.TemporaryDirectory()as root:
            h=self.install(root,proxy,max_http_attempts=3)
            try:
                with httpx.Client()as client:
                    payload={'model':frozen.ALLOWED_MODELS[0],'messages':[]}
                    self.assertEqual(client.post('http://fixture/v1/chat/completions',json=payload).status_code,200)
                    with self.assertRaises(frozen.TerminalTransportFailure):
                        client.post('http://fixture/v1/chat/completions',json=payload)
                self.assertEqual(len(calls),6)
            finally:h['uninstall']()

    def test_failed_routes_stop_after_two_real_sends(self):
        calls=[];proxy=self.run_server([503],calls)
        with tempfile.TemporaryDirectory()as root:
            before=httpx.Client._send_single_request;h=self.install(root,proxy)
            try:
                with httpx.Client()as client:
                    with self.assertRaises(frozen.TerminalTransportFailure)as e:
                        client.post('http://fixture/v1/chat/completions',json={'model':frozen.ALLOWED_MODELS[0],'messages':[]})
                self.assertEqual(e.exception.reason,'mmbc_logical_request_http_attempt_budget')
                self.assertEqual(len(calls),2)
                self.assertNotEqual(calls[0]['model'],calls[1]['model'])
                rows=[json.loads(l)for l in(Path(root)/'mmbc-request-budget-v1.jsonl').read_text().splitlines()]
                exhausted=next(r for r in rows if r['event']=='request_budget_exhausted')
                self.assertEqual(exhausted['http_sends'],2)
                self.assertFalse(exhausted['network_send_authorized'])
            finally:h['uninstall']()
            self.assertIs(httpx.Client._send_single_request,before)

    def test_retry_success_preserves_payload_and_each_new_request_resets_budget(self):
        calls=[];proxy=self.run_server([503,200,200,200],calls)
        payload={'model':frozen.ALLOWED_MODELS[0],'messages':[{'role':'user','content':[{'type':'text','text':'original evidence'},
                 {'type':'image_url','image_url':{'url':'data:image/png;base64,fixture','detail':'high'}}]}],'max_tokens':8192}
        with tempfile.TemporaryDirectory()as root:
            h=self.install(root,proxy)
            try:
                with httpx.Client()as client:
                    for _ in range(3):
                        r=client.post('http://fixture/v1/chat/completions',json=payload)
                        self.assertEqual(r.status_code,200);self.assertEqual(r.content.count(b'[DONE]'),1)
                self.assertEqual(len(calls),4)
                for sent in calls:
                    sent['model']=payload['model'];self.assertEqual(sent,payload)
            finally:h['uninstall']()

    def test_slow_headers_are_cut_by_inherited_socket_watchdog(self):
        calls=[];proxy=self.run_server([200],calls,delay=.4)
        with tempfile.TemporaryDirectory()as root:
            h=self.install(root,proxy,stream_seconds=.08);start=time.monotonic()
            try:
                with httpx.Client()as client:
                    with self.assertRaises(frozen.TerminalTransportFailure):
                        client.post('http://fixture/v1/chat/completions',json={'model':frozen.ALLOWED_MODELS[0],'messages':[]})
                self.assertEqual(len(calls),2)
                self.assertLess(time.monotonic()-start,1)
            finally:h['uninstall']()

    def test_web_endpoint_bypasses_model_budget(self):
        with tempfile.TemporaryDirectory()as root:
            h=self.install(root,'http://127.0.0.1:1')
            try:
                with httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(200,content=b'web')))as client:
                    self.assertEqual(client.get('http://local-web/fetch').text,'web')
                rows=[json.loads(l)for l in(Path(root)/'mmbc-request-budget-v1.jsonl').read_text().splitlines()]
                self.assertFalse(any(r['event']=='http_send_authorized'for r in rows))
            finally:h['uninstall']()

    def test_invalid_budget_cannot_install(self):
        for limit in (0,4,True,2.5):
            with self.assertRaises(ValueError):
                runtime.install(frozen.DEFAULT_POLICY,'unused',approved_base_url='http://fixture/v1',max_http_attempts=limit)

    def test_worker_requires_independent_mmbc_opt_in(self):
        spec={'experiment_kind':'mmbc','mmbc_request_budget_version':runtime.VERSION,'mmbc_max_http_attempts_per_request':3}
        config={**spec,'transport_runtime_policy':{'max_failed_sends':3}}
        with patch.object(worker.previous,'validate'):
            worker.validate(spec,config)
            with self.assertRaises(ValueError):worker.validate({**spec,'experiment_kind':'bc'},config)
            with self.assertRaises(ValueError):worker.validate({**spec,'mmbc_request_budget_version':None},config)


if __name__=='__main__':unittest.main()
