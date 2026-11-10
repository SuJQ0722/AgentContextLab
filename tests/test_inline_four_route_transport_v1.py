import base64,hashlib,io,json,os,sys,tempfile,threading,unittest
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import httpx
from PIL import Image
import inline_visual_transport_v1 as inline
import visual_transport_runtime_v3 as runtime

class InlineRouteTests(unittest.TestCase):
    def payload(self,count=12,noise=False):
        buf=io.BytesIO()
        image=Image.frombytes('RGB',(128,128),os.urandom(128*128*3))if noise else Image.new('RGB',(4,4),'white')
        image.save(buf,format='PNG');self.raw=buf.getvalue();self.registry={hashlib.sha256(self.raw).hexdigest()}
        return json.dumps({'model':runtime.ALLOWED_MODELS[0],'messages':[{'role':'user','content':[{'type':'text','text':'fixed'}]+[
            {'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(self.raw).decode(),'detail':'high'}}for _ in range(count)]}],
            'stream':True,'tools':[{'type':'function','function':{'name':'web_search'}}]}).encode()
    def hooks(self,root,base='http://fixture/v1',deadline=1800):
        rt=runtime.install(runtime.DEFAULT_POLICY,root,approved_base_url=base,route_policy=runtime.ROUTE_POLICY,worker_key='fixture-worker',deadline_seconds=deadline)
        ih=inline.install(root,rendered_registry=self.registry,approved_base_url=base)
        return rt,ih
    def cleanup(self,handles):
        for h in reversed(handles):h['uninstall']()
    def test_real_local_http_inline_then_route_rebuild_preserves_chunks_and_pixels(self):
        body=self.payload(noise=True);expected=json.loads(inline.transform(body,rendered_registry=self.registry)[0]);seen=[];chunks=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                raw=self.rfile.read(int(self.headers['content-length']));seen.append((raw,self.headers.get('transfer-encoding')))
                code=403 if len(seen)==1 else 200
                data=json.dumps({'error':{'code':'RouteUnavailable'}}).encode()if code==403 else b'data: {"usage":{"prompt_tokens":2,"completion_tokens":1,"total_tokens":3}}\n\ndata: [DONE]\n\n'
                self.send_response(code);self.send_header('content-type','text/event-stream');self.send_header('content-length',str(len(data)));self.end_headers();self.wfile.write(data)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);t=threading.Thread(target=server.serve_forever,daemon=True);t.start()
        original_iter=inline.ChunkedBytes.__iter__
        def measured(stream):
            for part in original_iter(stream):chunks.append(len(part));yield part
        try:
            with tempfile.TemporaryDirectory()as root:
                base=f'http://127.0.0.1:{server.server_port}/v1';handles=self.hooks(root,base)
                try:
                    with patch.object(inline.ChunkedBytes,'__iter__',measured),patch('requests.sessions.Session.request',side_effect=AssertionError('image hosting prohibited')),httpx.Client(trust_env=False)as client:
                        result=client.post(base+'/chat/completions',content=body)
                    self.assertEqual(result.status_code,200);self.assertEqual(len(seen),2);self.assertGreater(len(chunks),2);self.assertLessEqual(max(chunks),65536)
                    models=[]
                    for raw,transfer in seen:
                        data=json.loads(raw);models.append(data['model']);data['model']=expected['model'];self.assertEqual(data,expected);self.assertIsNone(transfer)
                    self.assertNotEqual(models[0],models[1]);self.assertEqual(len(expected['messages'][0]['content'])-1,10)
                    ledger=[json.loads(x)for x in (Path(root)/'transport-phases-v3.jsonl').read_text().splitlines()]
                    starts=[x for x in ledger if x['event']=='request_started'];self.assertEqual([x['route']for x in starts],models)
                    self.assertEqual([x['body_sha256']for x in starts],[hashlib.sha256(x[0]).hexdigest()for x in seen])
                    self.assertTrue(any(x.get('phase')=='http11.send_request_body.complete'for x in ledger))
                    image_ledger=(Path(root)/'inline-images-wire-v1.jsonl').read_text();self.assertNotIn('final_hosted_body',image_ledger)
                finally:self.cleanup(handles)
        finally:server.shutdown();server.server_close();t.join()
    def test_four_failures_rotate_before_wait_then_cycle(self):
        body=self.payload();seen=[];wait=[]
        def handler(req):
            seen.append(json.loads(req.content)['model'])
            code=[429,503,404,403,200][len(seen)-1]
            return httpx.Response(code,headers={'retry-after':'130'},json={'error':{'code':'ModelAccountRpmRateLimitExceeded'}}if code!=200 else {'ok':True})
        with tempfile.TemporaryDirectory()as root:
            handles=self.hooks(root)
            try:
                with patch.object(runtime.time,'sleep',side_effect=lambda seconds:wait.append((seconds,len(seen)))),patch.object(runtime.random,'uniform',return_value=.1),httpx.Client(transport=httpx.MockTransport(handler))as client:
                    self.assertEqual(client.post('http://fixture/v1/chat/completions',content=body).status_code,200)
                self.assertEqual(len(set(seen[:4])),4);self.assertEqual(seen[0],seen[4]);self.assertEqual(wait,[(130.1,4)])
            finally:self.cleanup(handles)
    def test_partial_stream_timeout_does_not_concatenate_failed_answer(self):
        body=self.payload();calls=[]
        class Broken(httpx.SyncByteStream):
            def __iter__(self):yield b'data: {"answer":"BAD"}\n\n';raise httpx.ReadTimeout('partial')
        def handler(req):
            calls.append(req)
            return httpx.Response(200,stream=Broken())if len(calls)==1 else httpx.Response(200,content=b'data: {"answer":"GOOD"}\n\ndata: [DONE]\n\n')
        with tempfile.TemporaryDirectory()as root:
            handles=self.hooks(root)
            try:
                with httpx.Client(transport=httpx.MockTransport(handler))as client:r=client.post('http://fixture/v1/chat/completions',content=body)
                self.assertEqual(len(calls),2);self.assertNotIn(b'BAD',r.content);self.assertIn(b'GOOD',r.content)
                rows=[json.loads(x)for x in (Path(root)/'transport-phases-v3.jsonl').read_text().splitlines()];failure=next(x for x in rows if x['event']=='route_failed');self.assertFalse(failure['usage_known'])
            finally:self.cleanup(handles)
    def test_401_stops_globally(self):
        body=self.payload();seen=[]
        def handler(req):seen.append(req);return httpx.Response(401,json={'error':{'code':'InvalidKey'}})
        with tempfile.TemporaryDirectory()as root:
            handles=self.hooks(root)
            try:
                with httpx.Client(transport=httpx.MockTransport(handler))as client:
                    with self.assertRaises(runtime.TerminalTransportFailure):client.post('http://fixture/v1/chat/completions',content=body)
                self.assertEqual(len(seen),1)
            finally:self.cleanup(handles)
    def test_unsupported_image400_rotates_but_malformed400_does_not(self):
        for unsupported in (True,False):
            body=self.payload();seen=[]
            def handler(req):
                seen.append(req)
                return httpx.Response(400,json={'error':{'message':'image not supported'if unsupported else'malformed JSON'}})if len(seen)==1 else httpx.Response(200,json={'ok':True})
            with tempfile.TemporaryDirectory()as root:
                handles=self.hooks(root)
                try:
                    with httpx.Client(transport=httpx.MockTransport(handler))as client:r=client.post('http://fixture/v1/chat/completions',content=body)
                    self.assertEqual(len(seen),2 if unsupported else 1);self.assertEqual(r.status_code,200 if unsupported else 400)
                finally:self.cleanup(handles)
    def test_deadline_bounds_retry_without_route_cycle_cap(self):
        body=self.payload();seen=[]
        def handler(req):seen.append(req);return httpx.Response(429,headers={'retry-after':'300'},json={'error':{}})
        with tempfile.TemporaryDirectory()as root:
            handles=self.hooks(root,deadline=5)
            try:
                with patch.object(runtime.time,'sleep')as sleep,httpx.Client(transport=httpx.MockTransport(handler))as client:
                    with self.assertRaises(runtime.TerminalTransportFailure):client.post('http://fixture/v1/chat/completions',content=body)
                self.assertEqual(len(seen),4);sleep.assert_not_called()
            finally:self.cleanup(handles)
    def test_unapproved_model_rejected_before_network(self):
        body=json.loads(self.payload());body['model']='other-model';seen=[]
        with tempfile.TemporaryDirectory()as root:
            handles=self.hooks(root)
            try:
                with httpx.Client(transport=httpx.MockTransport(lambda q:seen.append(q)))as client:
                    with self.assertRaises(ValueError):client.post('http://fixture/v1/chat/completions',json=body)
                self.assertEqual(seen,[])
            finally:self.cleanup(handles)
    def test_sdk_sse_compatibility_and_success_route_affinity(self):
        from openai import OpenAI
        body=json.loads(self.payload());seen=[]
        def handler(req):
            seen.append(json.loads(req.content)['model'])
            if len(seen)==1:return httpx.Response(403,json={'error':{'code':'RouteUnavailable'}})
            event={'id':'fixture','object':'chat.completion.chunk','created':0,'model':seen[-1],
                   'choices':[{'index':0,'delta':{'content':'ok'},'finish_reason':'stop'}],
                   'usage':{'prompt_tokens':3,'completion_tokens':1,'total_tokens':4}}
            return httpx.Response(200,headers={'content-type':'text/event-stream'},content=('data: '+json.dumps(event)+'\n\ndata: [DONE]\n\n').encode())
        with tempfile.TemporaryDirectory()as root:
            handles=self.hooks(root)
            try:
                with OpenAI(api_key='fixture',base_url='http://fixture/v1',http_client=httpx.Client(transport=httpx.MockTransport(handler)))as client:
                    for _ in range(2):
                        with client.chat.completions.create(**body)as stream:
                            chunks=list(stream);self.assertEqual(chunks[0].choices[0].delta.content,'ok');self.assertEqual(chunks[0].usage.total_tokens,4)
                self.assertEqual(len(seen),3);self.assertNotEqual(seen[0],seen[1]);self.assertEqual(seen[1],seen[2])
            finally:self.cleanup(handles)
    def test_inline32mib_and_native_canvas_identity_rules(self):
        wire,row=inline.transform(self.payload(),rendered_registry=self.registry)
        self.assertEqual(row['image_count'],10);self.assertEqual(row['max_body_bytes'],32*1024*1024);self.assertEqual(row['hosting_calls'],0)
        self.assertNotIn('hosted',json.dumps(row))
        data=json.loads(wire);data['messages'][0]['content'][0]['text']='x'*(32*1024*1024)
        with self.assertRaisesRegex(ValueError,'32MiB'):inline.transform(json.dumps(data).encode(),rendered_registry=self.registry)
if __name__=='__main__':unittest.main()
