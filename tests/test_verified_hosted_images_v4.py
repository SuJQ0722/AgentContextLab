import base64, hashlib, io, json, os, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import httpx
from PIL import Image
import verified_hosted_images_v4 as hosted
from recent_ten_hosted_selection_v1 import RecentImageTransportError
from info_loss_phase4_url import pixel_sha
from visual_transport_runtime_v2 import TerminalTransportFailure

class HostedRecoveryTests(unittest.TestCase):
    def setUp(self):
        buf=io.BytesIO();Image.new('RGB',(4,4),'white').save(buf,format='PNG')
        self.raw=buf.getvalue();self.sha=hashlib.sha256(self.raw).hexdigest()
    def record(self,raw):
        sha=hashlib.sha256(raw).hexdigest();pixel,dims=pixel_sha(raw)
        return dict(url='https://images.invalid/fixture',source_sha256=sha,download_sha256=sha,
                    pixel_sha256=pixel,dimensions=dims,byte_identical=True,pixel_identical=True)
    def payload(self,raw=None,count=1,text='fixed'):
        raw=raw or self.raw;url='data:image/png;base64,'+base64.b64encode(raw).decode()
        return json.dumps({'messages':[{'role':'user','content':[{'type':'text','text':text}]+[
            {'type':'image_url','image_url':{'url':url,'detail':'high'}}for _ in range(count)]}],
            'tools':[{'type':'function','function':{'name':'search'}}]}).encode()
    def seed_receipt(self,root):
        p=Path(root)/'hosted';p.mkdir()
        (p/(self.sha+'.upload.json')).write_text(json.dumps({'source_sha256':self.sha,'url':'https://images.invalid/fixture'}))
        (p/(self.sha+'.verify-started.json')).write_text('{"legacy":true}')
        return p
    def client(self,outcomes,calls):
        class Fake:
            def __init__(self,**kwargs):self.kwargs=kwargs
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def get(self,url):
                calls.append(self.kwargs)
                outcome=outcomes.pop(0)
                if isinstance(outcome,Exception):raise outcome
                return httpx.Response(200,content=outcome,request=httpx.Request('GET',url))
        return Fake
    def test_legacy_failed_verification_recovers_without_upload(self):
        calls=[]
        with tempfile.TemporaryDirectory()as root:
            p=self.seed_receipt(root)
            with patch('httpx.Client',self.client([httpx.ConnectError('secret-url'),self.raw],calls)),patch.object(hosted.time,'sleep'),patch('local_web.configure_image_upload',side_effect=AssertionError('must not configure or upload')):
                result=hosted.VerifiedImageHost(root,{}).ensure(self.raw)
            self.assertTrue(result['byte_identical']);self.assertEqual(len(calls),2)
            self.assertEqual(json.loads((p/(self.sha+'.verify-started.json')).read_text()),{'legacy':True})
            rows=[json.loads(x)for x in (p/(self.sha+'.verify-attempts-v4.jsonl')).read_text().splitlines()]
            self.assertEqual([x['outcome']for x in rows],['started','failed','started','verified'])
            self.assertNotIn('secret-url',json.dumps(rows))
    def test_exhaustion_is_bounded_and_does_not_poison_future_sessions(self):
        calls=[]
        with tempfile.TemporaryDirectory()as root:
            self.seed_receipt(root);host=hosted.VerifiedImageHost(root,{})
            with patch('httpx.Client',self.client([httpx.ReadTimeout('x')]*3+[self.raw],calls)),patch.object(hosted.time,'sleep'):
                with self.assertRaises(httpx.ReadTimeout):host.ensure(self.raw)
                self.assertEqual(len(calls),3)
                self.assertTrue(host.ensure(self.raw)['pixel_identical'])
            self.assertEqual(len(calls),4)
    def test_proxy_retries_then_byte_verified_direct_fallback(self):
        calls=[]
        with tempfile.TemporaryDirectory()as root:
            self.seed_receipt(root)
            with patch('httpx.Client',self.client([httpx.ConnectError('x')]*3+[self.raw],calls)),patch.object(hosted.time,'sleep'):
                result=hosted.VerifiedImageHost(root,{'https_proxy':'http://proxy.invalid'}).ensure(self.raw)
            self.assertEqual([x['proxy']for x in calls],['http://proxy.invalid']*3+[None])
            self.assertEqual(result['verification_route'],'direct_fallback')
    def test_changed_bytes_fail_without_retry_or_cache(self):
        calls=[];buf=io.BytesIO();Image.new('RGB',(4,4),'black').save(buf,format='PNG')
        with tempfile.TemporaryDirectory()as root:
            p=self.seed_receipt(root)
            with patch('httpx.Client',self.client([buf.getvalue()],calls)):
                with self.assertRaisesRegex(ValueError,'bytes/pixels changed'):hosted.VerifiedImageHost(root,{}).ensure(self.raw)
            self.assertEqual(len(calls),1);self.assertFalse((p/(self.sha+'.json')).exists())
    def test_legacy_unknown_upload_recovers_in_new_bounded_session(self):
        from lab import ROOT
        sys.path.insert(0,str(ROOT/'hermes-agent'))
        from tools import image_search_tool
        calls=[];uploads=[]
        def configured(root,env):env['IMAGE_UPLOAD_API_KEY']='fixture'
        def upload(path):
            uploads.append(path)
            return None if len(uploads)==1 else 'https://images.invalid/fixture'
        with tempfile.TemporaryDirectory()as root:
            p=Path(root)/'hosted';p.mkdir();marker=p/(self.sha+'.upload-started.json');marker.write_text('{"legacy":true}')
            with patch('local_web.configure_image_upload',configured),patch.object(image_search_tool,'_upload_imgbb',upload),patch('httpx.Client',self.client([self.raw],calls)),patch.object(hosted.time,'sleep'):
                result=hosted.VerifiedImageHost(root,{}).ensure(self.raw)
                self.assertTrue(result['byte_identical'])
                self.assertTrue(hosted.VerifiedImageHost(root,{}).ensure(self.raw)['byte_identical'])
            self.assertEqual(len(uploads),2);self.assertEqual(json.loads(marker.read_text()),{'legacy':True})
            ledger=(p/(self.sha+'.verify-attempts-v4.jsonl')).read_text()
            self.assertIn('prior_upload_outcome_unknown',ledger)
    def test_upload_exceptions_are_audited_and_bounded_to_two(self):
        import requests
        def configured(root,env):env['IMAGE_UPLOAD_API_KEY']='fixture'
        with tempfile.TemporaryDirectory()as root:
            with patch('local_web.configure_image_upload',configured),patch('requests.sessions.Session.request',side_effect=requests.ConnectTimeout('sensitive-url'))as upload,patch.object(hosted.time,'sleep'):
                with self.assertRaisesRegex(ValueError,'Bounded image upload'):
                    hosted.VerifiedImageHost(root,{}).ensure(self.raw)
                self.assertEqual(upload.call_count,2)
            p=Path(root)/'hosted';ledger=(p/(self.sha+'.verify-attempts-v4.jsonl')).read_text()
            self.assertEqual(ledger.count('"error_type":"ConnectTimeout"'),2)
            self.assertNotIn('sensitive-url',ledger);self.assertFalse((p/(self.sha+'.upload.json')).exists())
    def test_valid_legacy_cache_needs_no_network(self):
        with tempfile.TemporaryDirectory()as root:
            p=Path(root)/'hosted';p.mkdir();(p/(self.sha+'.json')).write_text(json.dumps(self.record(self.raw)))
            with patch('httpx.Client',side_effect=AssertionError('network forbidden')):
                self.assertTrue(hosted.VerifiedImageHost(root,{}).ensure(self.raw)['byte_identical'])
    def test_staging_over_8mib_is_allowed_but_final_wire_small(self):
        raw=io.BytesIO();Image.frombytes('RGB',(1024,1024),os.urandom(1024*1024*3)).save(raw,format='PNG')
        image=raw.getvalue();body=self.payload(image,count=3)
        self.assertGreater(len(body),8*1024*1024)
        wire,row=hosted.transform(body,rendered_registry={hashlib.sha256(image).hexdigest()},host=self.record)
        self.assertLess(len(wire),8192);self.assertEqual(row['image_count'],3)
        self.assertFalse(row['selection']['network_send_authorized'])
        self.assertIn('body_exceeds_8_mib',row['selection']['final_guard']['deferred_to_hosted_wire'])
    def test_final_wire_over_8mib_rejected(self):
        with self.assertRaisesRegex(ValueError,'body budget'):
            hosted.transform(self.payload(text='x'*(8*1024*1024)),rendered_registry=set(),host=self.record)
    def test_canvas_geometry_still_rejected(self):
        raw=io.BytesIO();Image.new('RGB',(2050,1)).save(raw,format='PNG');image=raw.getvalue()
        with self.assertRaises(RecentImageTransportError):
            hosted.transform(self.payload(image),rendered_registry={hashlib.sha256(image).hexdigest()},host=self.record)
    def test_recent10_and_text_tools_are_preserved(self):
        original=self.payload(count=12);wire,row=hosted.transform(original,rendered_registry=set(),host=self.record)
        p=json.loads(wire);old=json.loads(original)
        self.assertEqual(row['image_count'],10);self.assertEqual(row['selection']['removed_image_count'],2)
        self.assertEqual(p['tools'],old['tools']);self.assertEqual(p['messages'][0]['content'][0],old['messages'][0]['content'][0])
        self.assertTrue(all(x['image_url']['detail']=='high'for x in p['messages'][0]['content'][1:]))
    def test_host_failure_never_sends_model_request(self):
        seen=[]
        with tempfile.TemporaryDirectory()as root:
            def fail(raw):raise httpx.ConnectError('download failure')
            hook=hosted.install(root,rendered_registry=set(),host=fail,approved_base_url='http://test/v1')
            try:
                with httpx.Client(transport=httpx.MockTransport(lambda q:seen.append(q)))as client:
                    with self.assertRaises(TerminalTransportFailure):client.post('http://test/v1/chat/completions',content=self.payload())
            finally:hook['uninstall']()
        self.assertEqual(seen,[])
if __name__=='__main__':unittest.main()
