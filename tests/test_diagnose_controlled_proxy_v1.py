import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import diagnose_controlled_proxy_v1 as diag

class ProxyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);root=Path(self.tmp.name)
        self.source=root/'source';self.source.mkdir();self.out=root/'out';self.attempt=root/'attempt';self.attempt.mkdir()
        self.raw=json.dumps({'model':diag.MODEL,'messages':[{'role':'user','content':'exact original content'}],'max_tokens':1,'stream':False,'tools':[]},separators=(',',':')).encode()
        (self.source/'original-body.json').write_bytes(self.raw);expected=diag.sha(self.source/'original-body.json')
        (self.source/'plan.json').write_text(json.dumps({'original_body_sha256':expected}));(self.attempt/'spec.json').write_text('{"config_path":"fixture.json"}')
        for name,value in [('SOURCE',self.source),('OUT',self.out),('ATTEMPT',self.attempt),('EXPECTED',expected)]:
            p=patch.object(diag,name,value);p.start();self.addCleanup(p.stop)
    def test_prepare_byte_identical_and_no_payload_changes(self):
        plan=diag.prepare();self.assertEqual((self.out/'request-body.json').read_bytes(),self.raw)
        self.assertEqual(plan['payload_changes'],{});self.assertEqual(plan['maximum_post_operations'],1)
    def test_modified_parameter_body_rejected(self):
        obj=json.loads(self.raw);obj['max_tokens']=64;(self.source/'original-body.json').write_text(json.dumps(obj))
        with self.assertRaises(ValueError):diag.prepare()
    def test_proxy_single_post_and_raw_response_retained(self):
        class Response:
            status_code=200;is_success=True;headers={};content=b'{"usage":{"prompt_tokens":42,"completion_tokens":1,"total_tokens":43}}'
            def json(self):return json.loads(self.content)
        class Client:
            kwargs=None;calls=[]
            def __init__(self,**kwargs):Client.kwargs=kwargs
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def post(self,url,**kw):Client.calls.append(kw['content']);return Response()
        with patch('httpx.Client',Client),patch.object(diag,'environment',return_value=({'TOKENHUB_BASE_URL':'https://tokenhub.sensetime.com/v1','TOKENHUB_API_KEY':'fixture'},{})):
            result=diag.live()
            with self.assertRaises(ValueError):diag.live()
        self.assertEqual(Client.calls,[self.raw]);self.assertEqual(Client.kwargs['proxy'],diag.PROXY)
        self.assertFalse(Client.kwargs['trust_env']);self.assertFalse(Client.kwargs['follow_redirects'])
        self.assertEqual(Client.kwargs['timeout'].read,120);self.assertEqual(Client.kwargs['timeout'].write,120)
        self.assertEqual(result['raw_provider_usage']['total_tokens'],43);self.assertIsNone(result['provider_latency_seconds'])
        self.assertEqual((self.out/'response-body.bin').read_bytes(),Response.content)
    def test_wall_cap_does_not_resend(self):
        class Client:
            calls=0
            def __init__(self,**kwargs):pass
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def post(self,*args,**kw):Client.calls+=1;raise diag.WallCap()
        with patch('httpx.Client',Client),patch.object(diag,'environment',return_value=({'TOKENHUB_BASE_URL':'https://tokenhub.sensetime.com/v1','TOKENHUB_API_KEY':'fixture'},{})):
            result=diag.live()
            with self.assertRaises(ValueError):diag.live()
        self.assertEqual(Client.calls,1);self.assertEqual(result['status'],'total_wall_timeout');self.assertIsNone(result['raw_provider_usage'])

if __name__=='__main__':unittest.main()
