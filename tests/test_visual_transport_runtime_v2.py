import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import httpx
from openai import OpenAI
from visual_transport_runtime_v2 import install,DEFAULT_POLICY,TerminalTransportFailure
from bounded_visual_request_guard_v1 import BoundedVisualRequestError

class TransportRuntimeTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.cleanup=None
    def tearDown(self):
        if self.cleanup:self.cleanup()
        self.tmp.cleanup()
    def activate(self,url):
        r=install(DEFAULT_POLICY,self.tmp.name,approved_base_url=url);self.cleanup=r['uninstall']
    def rows(self):return [json.loads(x)for x in (Path(self.tmp.name)/'transport-phases-v2.jsonl').read_text().splitlines()]
    def test_real_socket_openai_sse_trace_usage_and_success_repeat(self):
        calls=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                calls.append(self.rfile.read(int(self.headers['Content-Length'])))
                chunks=[{'id':'test','object':'chat.completion.chunk','created':0,'model':'test','choices':[{'index':0,'delta':{'content':'ok'},'finish_reason':None}]}, {'id':'test','object':'chat.completion.chunk','created':0,'model':'test','choices':[],'usage':{'prompt_tokens':2,'completion_tokens':1,'total_tokens':3,'prompt_tokens_details':{'cached_tokens':1}}}]
                data=(''.join('data: '+json.dumps(c)+'\n\n'for c in chunks)+'data: [DONE]\n\n').encode()
                self.send_response(200);self.send_header('Content-Type','text/event-stream');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();url=f'http://127.0.0.1:{server.server_port}/v1';self.activate(url)
        try:
            with OpenAI(base_url=url,api_key='fixture-not-a-secret',max_retries=9,http_client=httpx.Client(trust_env=False))as client:
                for _ in range(3):
                    chunks=list(client.chat.completions.create(model='test',messages=[{'role':'user','content':'fixture'}],stream=True))
                    self.assertEqual(chunks[-1].usage.total_tokens,3)
                    self.assertEqual(chunks[0].choices[0].delta.content,'ok')
            self.assertEqual(len(calls),3);rows=self.rows();self.assertEqual(sum(x['event']=='stream_complete'for x in rows),3)
            phases=[x.get('phase')for x in rows];self.assertIn('http11.send_request_body.complete',phases);self.assertIn('http11.receive_response_headers.complete',phases)
            self.assertNotIn('fixture-not-a-secret',json.dumps(rows));self.assertNotIn('fixture',json.dumps(rows))
        finally:server.shutdown();server.server_close();thread.join()
    def test_no_sdk_retry_and_budget_blocks_third(self):
        sent=[]
        def bad(request):sent.append(1);raise httpx.ReadTimeout('private text',request=request)
        self.activate('http://test/v1')
        with OpenAI(base_url='http://test/v1',api_key='x',max_retries=9,http_client=httpx.Client(transport=httpx.MockTransport(bad)))as client:
            for _ in range(2):
                with self.assertRaises(Exception):client.chat.completions.create(model='test',messages=[])
            with self.assertRaises(TerminalTransportFailure):client.chat.completions.create(model='test',messages=[])
        self.assertEqual(len(sent),2);self.assertNotIn('private text',json.dumps(self.rows()))
    def test_deterministic_guard_does_not_retry(self):
        old=httpx.Client._send_single_request;sent=[]
        def reject(client,request):sent.append(1);raise BoundedVisualRequestError({'violations':['body_too_large']})
        httpx.Client._send_single_request=reject
        try:
            self.activate('http://test/v1')
            with OpenAI(base_url='http://test/v1',api_key='x',max_retries=9,http_client=httpx.Client(trust_env=False))as client:
                with self.assertRaises(TerminalTransportFailure):client.chat.completions.create(model='test',messages=[])
            self.assertEqual(len(sent),1)
        finally:
            self.cleanup();self.cleanup=None;httpx.Client._send_single_request=old
    def test_partial_stream_failure_is_counted(self):
        sends=[]
        class Broken(httpx.SyncByteStream):
            def __iter__(self):
                yield b'data: {"id":"x","object":"chat.completion.chunk","created":0,"model":"test","choices":[]}\n\n'
                raise httpx.ReadError('stream cut')
        def bad(r):sends.append(1);return httpx.Response(200,headers={'content-type':'text/event-stream'},stream=Broken())
        self.activate('http://test/v1')
        with OpenAI(base_url='http://test/v1',api_key='x',http_client=httpx.Client(transport=httpx.MockTransport(bad)))as client:
            for _ in range(2):
                with self.assertRaises(httpx.ReadError):list(client.chat.completions.create(model='test',messages=[],stream=True))
            with self.assertRaises(TerminalTransportFailure):client.chat.completions.create(model='test',messages=[],stream=True)
        self.assertEqual(len(sends),2)
        self.assertEqual(sum(x['event']=='stream_error'for x in self.rows()),2)
    def test_worker_wires_retention_registry_and_runtime(self):
        import base64,io,os
        from PIL import Image
        from unittest.mock import patch
        import hermes_mmbc_transport_worker_v2 as worker
        import recent_ten_images_transport_v1 as retention
        spec=Path(self.tmp.name)/'spec.json';cfg=Path(self.tmp.name)/'config.json';out=Path(self.tmp.name)/'out';out.mkdir()
        cfg.write_text(json.dumps({'transport_runtime_version':'visual-transport-runtime-v2','transport_runtime_policy':DEFAULT_POLICY}))
        spec.write_text(json.dumps({'transport_runtime_version':'visual-transport-runtime-v2','config_path':str(cfg)}))
        b=io.BytesIO();Image.new('RGB',(4,4),'white').save(b,format='PNG');url='data:image/png;base64,'+base64.b64encode(b.getvalue()).decode()
        parts=[{'type':'text','text':'preserve'}]+[{'type':'image_url','image_url':{'url':url}} for _ in range(12)]
        received=[]
        def upstream(r):
            received.append(json.loads(r.content));return httpx.Response(200,json={'id':'x','object':'chat.completion','created':0,'model':'test','choices':[{'index':0,'message':{'role':'assistant','content':'ok'},'finish_reason':'stop'}],'usage':{'prompt_tokens':2,'completion_tokens':1,'total_tokens':3}})
        def inner():
            retention.install(out/'metrics/recent-ten-images-wire.jsonl',rendered_registry=lambda:set())
            with OpenAI(base_url='http://test/v1',api_key='x',http_client=httpx.Client(transport=httpx.MockTransport(upstream)))as c:
                result=c.chat.completions.create(model='test',messages=[{'role':'user','content':parts}]);self.assertEqual(result.usage.total_tokens,3)
        old=httpx.Client._send_single_request
        try:
            with patch.object(worker.parent,'main',inner),patch.object(sys,'argv',['worker','--spec',str(spec),'--out',str(out)]),patch.dict(os.environ,{'TOKENHUB_BASE_URL':'http://test/v1'}):worker.main()
        finally:httpx.Client._send_single_request=old
        self.assertEqual(len(received[0]['messages'][0]['content']),11)
        self.assertEqual(received[0]['messages'][0]['content'][0],parts[0])
        ledger=json.loads((out/'metrics/recent-ten-images-wire.jsonl').read_text().splitlines()[0]);self.assertEqual(ledger['removed_image_count'],2)
        self.assertTrue((out/'metrics/transport-phases-v2.jsonl').exists());self.assertTrue((out/'metrics/registry-cache-v2.jsonl').exists())
    def test_other_origin_and_web_untouched(self):
        seen=[]
        def ok(r):seen.append(dict(r.extensions));return httpx.Response(200,json={'ok':1})
        self.activate('http://test/v1')
        with httpx.Client(transport=httpx.MockTransport(ok))as c:
            c.post('http://elsewhere/v1/chat/completions',json={});c.get('http://test/search')
        self.assertTrue(all('trace'not in x for x in seen));self.assertFalse((Path(self.tmp.name)/'transport-phases-v2.jsonl').exists())

if __name__=='__main__':unittest.main()
