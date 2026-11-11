import json,os,sys,tempfile,threading,unittest,time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import httpx
from types import SimpleNamespace
import visual_transport_runtime_v4 as runtime
import inline_visual_transport_v1 as inline

class ProxyRuntimeTests(unittest.TestCase):
    def test_explicit_proxy_overrides_no_proxy_and_preserves_inline_route_stream(self):
        seen=[];sizes=[]
        class Proxy(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                raw=self.rfile.read(int(self.headers['content-length']));seen.append((self.path,raw))
                response=b'data: {"usage":{"prompt_tokens":1,"completion_tokens":1,"total_tokens":2}}\n\ndata: [DONE]\n\n'
                self.send_response(200);self.send_header('content-length',str(len(response)));self.send_header('content-type','text/event-stream');self.end_headers();self.wfile.write(response)
        server=ThreadingHTTPServer(('127.0.0.1',0),Proxy);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        def forbid(req):raise AssertionError('Incoming client direct transport must not be used')
        old_iter=inline.ChunkedBytes.__iter__
        def chunks(self):
            for data in old_iter(self):sizes.append(len(data));yield data
        try:
            with tempfile.TemporaryDirectory()as root,patch.dict(os.environ,{'NO_PROXY':'*','no_proxy':'*','HTTPS_PROXY':'http://unreachable.invalid:1'}):
                proxy='http://127.0.0.1:'+str(server.server_port)
                rt=runtime.install(runtime.DEFAULT_POLICY,root,approved_base_url='http://gateway.invalid/v1',gateway_proxy=proxy,worker_key='fixture')
                ih=inline.install(root,rendered_registry=set(),approved_base_url='http://gateway.invalid/v1')
                try:
                    payload={'model':runtime.ALLOWED_MODELS[0],'messages':[{'role':'user','content':'x'*200000}]}
                    with patch.object(inline.ChunkedBytes,'__iter__',chunks),httpx.Client(transport=httpx.MockTransport(forbid))as client:
                        response=client.post('http://gateway.invalid/v1/chat/completions',json=payload)
                    self.assertEqual(response.status_code,200);self.assertEqual(len(seen),1)
                    got=json.loads(seen[0][1]);got['model']=payload['model'];self.assertEqual(got,payload)
                    self.assertEqual(seen[0][0],'http://gateway.invalid/v1/chat/completions');self.assertGreater(len(sizes),1);self.assertLessEqual(max(sizes),65536)
                    log=(Path(root)/'gateway-proxy-v4.jsonl').read_text();self.assertIn('ChunkedBytes',log);self.assertNotIn(proxy,log)
                finally:ih['uninstall']();rt['uninstall']()
        finally:server.shutdown();server.server_close();thread.join()
    def test_header_and_body_deadlines_and_successful_timer_cancellation(self):
        for mode in ('slow_headers','slow_body','success'):
            class Proxy(BaseHTTPRequestHandler):
                def log_message(self,*args):pass
                def do_POST(self):
                    self.rfile.read(int(self.headers['content-length']))
                    if mode=='slow_headers':time.sleep(.7)
                    try:
                        self.send_response(200);self.send_header('content-length','2');self.end_headers()
                        if mode=='slow_body':time.sleep(.7)
                        if mode=='success':time.sleep(.05)
                        self.wfile.write(b'OK')
                    except (BrokenPipeError,ConnectionResetError):pass
            server=ThreadingHTTPServer(('127.0.0.1',0),Proxy);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                with tempfile.TemporaryDirectory()as root:
                    policy={**runtime.DEFAULT_POLICY,'read_seconds':.01,'stream_seconds':.2}
                    rt=runtime.install(policy,root,approved_base_url='http://fixture/v1',gateway_proxy='http://127.0.0.1:'+str(server.server_port),worker_key='test',deadline_seconds=.45)
                    began=time.monotonic()
                    try:
                        with httpx.Client(trust_env=False)as client:
                            if mode=='success':self.assertEqual(client.post('http://fixture/v1/chat/completions',json={'model':runtime.ALLOWED_MODELS[0],'messages':[]}).status_code,200)
                            else:
                                with self.assertRaises(runtime.TerminalTransportFailure):client.post('http://fixture/v1/chat/completions',json={'model':runtime.ALLOWED_MODELS[0],'messages':[]})
                        elapsed=time.monotonic()-began
                        self.assertLess(elapsed,.8)
                        time.sleep(.23)
                        rows=[json.loads(x)for x in (Path(root)/'gateway-proxy-v4.jsonl').read_text().splitlines()]
                        deadlines=[x for x in rows if x['event']=='http_wall_deadline']
                        if mode=='success':self.assertEqual(deadlines,[])
                        else:self.assertTrue(deadlines);self.assertTrue(all(x['socket_shutdown_attempted']for x in deadlines))
                    finally:rt['uninstall']()
            finally:server.shutdown();server.server_close();thread.join()
    def test_connect_tunnel_phases_are_not_model_uploads(self):
        def core(client,request):
            trace=request.extensions['trace']
            for method in (b'CONNECT',b'POST'):
                for phase in ('send_request_headers','send_request_body'):
                    trace('http11.'+phase+'.started',{'request':SimpleNamespace(method=method)})
                    trace('http11.'+phase+'.complete',{})
            return httpx.Response(200,content=b'OK',request=request)
        with tempfile.TemporaryDirectory()as root,patch.object(httpx.Client,'_send_single_request',core):
            rt=runtime.install(runtime.DEFAULT_POLICY,root,approved_base_url='http://fixture/v1',gateway_proxy='http://127.0.0.1:1',worker_key='test')
            try:
                with httpx.Client(trust_env=False)as client:client.post('http://fixture/v1/chat/completions',json={'model':runtime.ALLOWED_MODELS[0],'messages':[]})
                rows=[json.loads(x)for x in (Path(root)/'transport-phases-v3.jsonl').read_text().splitlines()]
                self.assertEqual(sum(r.get('phase')=='http11.send_request_body.complete'for r in rows),1)
                other=[json.loads(x)for x in (Path(root)/'gateway-proxy-v4.jsonl').read_text().splitlines()]
                self.assertEqual(sum(r.get('event')=='proxy_tunnel_phase'for r in other),4)
            finally:rt['uninstall']()
    def test_send_failure_cancels_each_watchdog(self):
        def core(client,request):raise httpx.ConnectError('fixture')
        with tempfile.TemporaryDirectory()as root,patch.object(httpx.Client,'_send_single_request',core):
            policy={**runtime.DEFAULT_POLICY,'stream_seconds':.1}
            rt=runtime.install(policy,root,approved_base_url='http://fixture/v1',gateway_proxy='http://127.0.0.1:1',worker_key='test',deadline_seconds=2)
            try:
                with httpx.Client(trust_env=False)as client:
                    with self.assertRaises(runtime.TerminalTransportFailure):client.post('http://fixture/v1/chat/completions',json={'model':runtime.ALLOWED_MODELS[0],'messages':[]})
                time.sleep(.15)
                rows=[json.loads(x)for x in (Path(root)/'gateway-proxy-v4.jsonl').read_text().splitlines()]
                self.assertFalse(any(r['event']=='http_wall_deadline'for r in rows))
            finally:rt['uninstall']()
    def test_expired_empty_eof_is_not_success(self):
        class EmptyAfterDeadline(httpx.SyncByteStream):
            def __iter__(self):
                time.sleep(.12)
                return
                yield b''
        def core(client,request):return httpx.Response(200,stream=EmptyAfterDeadline(),request=request)
        with tempfile.TemporaryDirectory()as root,patch.object(httpx.Client,'_send_single_request',core):
            rt=runtime.install({**runtime.DEFAULT_POLICY,'stream_seconds':.08},root,approved_base_url='http://fixture/v1',gateway_proxy='http://127.0.0.1:1',worker_key='test',deadline_seconds=.3)
            try:
                with httpx.Client(trust_env=False)as client:
                    with self.assertRaises(runtime.TerminalTransportFailure):client.post('http://fixture/v1/chat/completions',json={'model':runtime.ALLOWED_MODELS[0],'messages':[]})
                rows=[json.loads(x)for x in (Path(root)/'transport-phases-v3.jsonl').read_text().splitlines()]
                self.assertFalse(any(x['event']=='route_returned'for x in rows))
            finally:rt['uninstall']()
    def test_socket_arriving_after_deadline_is_shutdown(self):
        shutdown=[]
        class Sock:
            def shutdown(self,mode):shutdown.append(mode)
        def core(client,request):
            time.sleep(.12)
            request.extensions['trace']('connection.connect_tcp.complete',{'return_value':SimpleNamespace(get_extra_info=lambda _:Sock())})
            raise AssertionError('expired socket must not reach request send')
        with tempfile.TemporaryDirectory()as root,patch.object(httpx.Client,'_send_single_request',core):
            rt=runtime.install({**runtime.DEFAULT_POLICY,'stream_seconds':.08},root,approved_base_url='http://fixture/v1',gateway_proxy='http://127.0.0.1:1',worker_key='test',deadline_seconds=.3)
            try:
                with httpx.Client(trust_env=False)as client:
                    with self.assertRaises(runtime.TerminalTransportFailure):client.post('http://fixture/v1/chat/completions',json={'model':runtime.ALLOWED_MODELS[0],'messages':[]})
                self.assertTrue(shutdown)
            finally:rt['uninstall']()
    def test_invalid_proxy_is_rejected(self):
        with tempfile.TemporaryDirectory()as root:
            for proxy in [None,'','ftp://host','http://host?secret=value']:
                with self.assertRaises(ValueError):runtime.install(runtime.DEFAULT_POLICY,root,approved_base_url='http://fixture/v1',gateway_proxy=proxy,worker_key='fixture')
    def test_other_endpoints_keep_original_client_transport(self):
        seen=[]
        with tempfile.TemporaryDirectory()as root:
            rt=runtime.install(runtime.DEFAULT_POLICY,root,approved_base_url='http://fixture/v1',gateway_proxy='http://127.0.0.1:1',worker_key='fixture')
            try:
                with httpx.Client(transport=httpx.MockTransport(lambda r:(seen.append(str(r.url))or httpx.Response(200))))as client:
                    self.assertEqual(client.get('http://webtool.invalid/fetch').status_code,200)
                self.assertEqual(seen,['http://webtool.invalid/fetch'])
            finally:rt['uninstall']()
if __name__=='__main__':unittest.main()
