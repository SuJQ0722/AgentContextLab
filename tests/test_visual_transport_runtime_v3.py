import json,sys,tempfile,threading,unittest
from datetime import datetime,timezone
from email.utils import format_datetime
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import httpx
from openai import OpenAI,RateLimitError,InternalServerError,APIConnectionError
import visual_transport_runtime_v3 as runtime

SUCCESS={'id':'fixture','object':'chat.completion','created':0,'model':'fixture','choices':[{'index':0,'message':{'role':'assistant','content':'ok'},'finish_reason':'stop'}],'usage':{'prompt_tokens':1,'completion_tokens':1,'total_tokens':2}}
REFUSED={'error':{'message':'secret-not-for-audit','code':'ModelAccountTpmRateLimitExceeded','type':'TooManyRequests'}}

class RuntimeQuotaTests(unittest.TestCase):
    def setup_client(self,root,handler):
        hook=runtime.install(runtime.DEFAULT_POLICY,root,approved_base_url='http://fixture/v1')
        client=OpenAI(api_key='fixture',base_url='http://fixture/v1',http_client=httpx.Client(transport=httpx.MockTransport(handler)))
        return hook,client
    def call(self,client):return client.chat.completions.create(model='fixture',messages=[{'role':'user','content':'fixed'}])
    def test_actual_local_http_429_then_200(self):
        seen=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                seen.append(self.rfile.read(int(self.headers['content-length'])))
                code=429 if len(seen)==1 else 200;raw=json.dumps(REFUSED if code==429 else SUCCESS).encode()
                self.send_response(code);self.send_header('content-type','application/json');self.send_header('content-length',str(len(raw)));self.send_header('retry-after','0');self.end_headers();self.wfile.write(raw)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with tempfile.TemporaryDirectory()as root:
                base=f'http://127.0.0.1:{server.server_port}/v1';hook=runtime.install(runtime.DEFAULT_POLICY,root,approved_base_url=base)
                try:
                    with patch.object(runtime.time,'sleep')as sleep,patch.object(runtime.random,'uniform',return_value=.1),OpenAI(api_key='fixture',base_url=base,http_client=httpx.Client(trust_env=False))as client:
                        self.assertEqual(self.call(client).choices[0].message.content,'ok')
                    self.assertEqual(len(seen),2);self.assertEqual(seen[0],seen[1]);sleep.assert_called_once_with(.1)
                    ledger=(Path(root)/'transport-phases-v3.jsonl').read_text()
                    self.assertIn('ModelAccountTpmRateLimitExceeded',ledger);self.assertNotIn('secret-not-for-audit',ledger)
                finally:hook['uninstall']()
        finally:server.shutdown();server.server_close();thread.join()
    def test_attempt_budget_returns_real_rate_limit_and_does_not_poison_next_call(self):
        seen=[]
        def send(req):
            seen.append(req)
            return httpx.Response(429 if len(seen)<=5 else 200,headers={'retry-after':'0'},json=REFUSED if len(seen)<=5 else SUCCESS)
        with tempfile.TemporaryDirectory()as root:
            hook,client=self.setup_client(root,send)
            try:
                with patch.object(runtime.time,'sleep')as sleep,patch.object(runtime.random,'uniform',return_value=.1):
                    with self.assertRaises(RateLimitError):self.call(client)
                    self.assertEqual(len(seen),5);self.assertEqual(sleep.call_count,4)
                    self.assertEqual(self.call(client).choices[0].message.content,'ok')
                ledger=(Path(root)/'transport-phases-v3.jsonl').read_text();self.assertNotIn('failed_send_budget',ledger)
            finally:client.close();hook['uninstall']()
    def test_wait_budget_no_header_uses_60_120_and_stops_before_300(self):
        seen=[]
        def send(req):seen.append(req);return httpx.Response(429,json=REFUSED)
        with tempfile.TemporaryDirectory()as root:
            hook,client=self.setup_client(root,send)
            try:
                with patch.object(runtime.time,'sleep')as sleep,patch.object(runtime.random,'uniform',return_value=.1):
                    with self.assertRaises(RateLimitError):self.call(client)
                self.assertEqual([c.args[0]for c in sleep.call_args_list],[60.1,120.1]);self.assertEqual(len(seen),3)
            finally:client.close();hook['uninstall']()
    def test_retry_after_longer_than_budget_is_not_shortened(self):
        seen=[]
        def send(req):seen.append(req);return httpx.Response(429,headers={'retry-after':'301'},json=REFUSED)
        with tempfile.TemporaryDirectory()as root:
            hook,client=self.setup_client(root,send)
            try:
                with patch.object(runtime.time,'sleep')as sleep:
                    with self.assertRaises(RateLimitError):self.call(client)
                sleep.assert_not_called();self.assertEqual(len(seen),1)
            finally:client.close();hook['uninstall']()
    def test_other_http_failure_is_not_retried(self):
        seen=[]
        def send(req):seen.append(req);return httpx.Response(503,json={'error':{'message':'unavailable'}})
        with tempfile.TemporaryDirectory()as root:
            hook,client=self.setup_client(root,send)
            try:
                with patch.object(runtime.time,'sleep')as sleep:
                    with self.assertRaises(InternalServerError):self.call(client)
                self.assertEqual(len(seen),1);sleep.assert_not_called()
            finally:client.close();hook['uninstall']()
    def test_unknown_connection_failure_is_not_retried(self):
        seen=[]
        def send(req):seen.append(req);raise httpx.ReadTimeout('unknown acceptance')
        with tempfile.TemporaryDirectory()as root:
            hook,client=self.setup_client(root,send)
            try:
                with patch.object(runtime.time,'sleep')as sleep:
                    with self.assertRaises(APIConnectionError):self.call(client)
                self.assertEqual(len(seen),1);sleep.assert_not_called()
            finally:client.close();hook['uninstall']()
    def test_retry_after_formats_and_invalid_values(self):
        self.assertEqual(runtime.retry_after_seconds(httpx.Headers({'retry-after-ms':'2500'})),(2.5,'retry-after-ms'))
        self.assertEqual(runtime.retry_after_seconds(httpx.Headers({'retry-after':'12'})),(12.,'retry-after'))
        date=format_datetime(datetime.fromtimestamp(1120,timezone.utc),usegmt=True)
        self.assertEqual(runtime.retry_after_seconds(httpx.Headers({'retry-after':date}),now=1000),(120.,'retry-after-date'))
        self.assertEqual(runtime.retry_after_seconds(httpx.Headers({'retry-after':'secret invalid'})),(None,None))
        self.assertEqual(runtime.retry_after_seconds(httpx.Headers({'retry-after':'nan'})),(None,None))
if __name__=='__main__':unittest.main()
