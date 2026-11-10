import base64,hashlib,io,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from PIL import Image
import httpx
from verified_hosted_images_v3 import transform,install,VerifiedImageHost
from visual_transport_runtime_v2 import install as runtime,DEFAULT_POLICY,TerminalTransportFailure

class HostedTests(unittest.TestCase):
    def payload(self):
        raw=io.BytesIO();Image.new('RGB',(4,4),'white').save(raw,format='PNG');self.raw=raw.getvalue();url='data:image/png;base64,'+base64.b64encode(self.raw).decode()
        return json.dumps({'messages':[{'role':'user','content':[{'type':'text','text':'fixed'}]+[{'type':'image_url','image_url':{'url':url,'detail':'high'}}for _ in range(12)]}],'tools':[{'type':'function','function':{'name':'search'}}]}).encode()
    def host(self,raw):
        h=hashlib.sha256(raw).hexdigest();return {'url':'https://i.ibb.co/example/image.png','source_sha256':h,'download_sha256':h,'byte_identical':True,'pixel_identical':True,'pixel_sha256':'fixture','dimensions':[4,4],'checked_at':1}
    def test_selection_precedes_hosting_preserves_nonimage_semantics(self):
        body=self.payload();calls=[]
        def host(raw):calls.append(raw);return self.host(raw)
        wire,row=transform(body,rendered_registry=set(),host=host);p=json.loads(wire)
        self.assertEqual(len(calls),10);self.assertEqual(row['selection']['removed_image_count'],2)
        self.assertEqual(p['tools'],json.loads(body)['tools']);self.assertEqual(p['messages'][0]['content'][0],{'type':'text','text':'fixed'})
        self.assertTrue(all(x['image_url']['detail']=='high'for x in p['messages'][0]['content'][1:]));self.assertNotIn(b'base64',wire)
    def test_identity_failure_closed(self):
        body=self.payload()
        def bad(raw):r=self.host(raw);r['download_sha256']='wrong';return r
        with self.assertRaises(ValueError):transform(body,rendered_registry=set(),host=bad)
    def test_runtime_sees_final_hosted_body(self):
        body=self.payload();seen=[]
        with tempfile.TemporaryDirectory()as d:
            r=runtime(DEFAULT_POLICY,d,approved_base_url='http://test/v1');h=install(d,rendered_registry=set(),host=self.host,approved_base_url='http://test/v1')
            try:
                def send(q):seen.append(q.content);return httpx.Response(200,json={'ok':True})
                with httpx.Client(transport=httpx.MockTransport(send))as c:c.post('http://test/v1/chat/completions',content=body)
            finally:h['uninstall']();r['uninstall']()
            events=[json.loads(x)for x in (Path(d)/'transport-phases-v2.jsonl').read_text().splitlines()]
            started=next(x for x in events if x['event']=='request_started');self.assertEqual(started['body_sha256'],hashlib.sha256(seen[0]).hexdigest())
            self.assertNotIn(b'base64',seen[0]);self.assertLess(len(seen[0]),len(body))
    def test_host_failure_never_reaches_model(self):
        body=self.payload();seen=[]
        with tempfile.TemporaryDirectory()as d:
            def bad(raw):raise ValueError('host unavailable')
            h=install(d,rendered_registry=set(),host=bad,approved_base_url='http://test/v1')
            try:
                with httpx.Client(transport=httpx.MockTransport(lambda q:seen.append(q)))as c:
                    with self.assertRaises(TerminalTransportFailure):c.post('http://test/v1/chat/completions',content=body)
            finally:h['uninstall']()
            self.assertEqual(seen,[])
    def test_download_failure_preserves_upload_receipt_and_never_reuploads(self):
        self.payload();key=hashlib.sha256(self.raw).hexdigest();uploads=[]
        from lab import ROOT
        sys.path.insert(0,str(ROOT/'hermes-agent'))
        from tools import image_search_tool
        def configured(root,env):env['IMAGE_UPLOAD_API_KEY']='fixture'
        def uploaded(path):uploads.append(path);return 'https://i.ibb.co/example/image.png'
        class Download:
            def __init__(self,**kwargs):pass
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def get(self,url):raise httpx.ReadTimeout('fixture download failed')
        with tempfile.TemporaryDirectory()as d:
            host=VerifiedImageHost(d,{})
            with patch('local_web.configure_image_upload',configured),patch.object(image_search_tool,'_upload_imgbb',uploaded),patch('httpx.Client',Download):
                with self.assertRaises(httpx.ReadTimeout):host.ensure(self.raw)
                receipt=json.loads((Path(d)/'hosted'/(key+'.upload.json')).read_text());self.assertEqual(receipt['source_sha256'],key)
                with self.assertRaisesRegex(ValueError,'Prior verification'):host.ensure(self.raw)
            self.assertEqual(len(uploads),1)
    def test_verified_cache_reuses_without_network(self):
        self.payload();key=hashlib.sha256(self.raw).hexdigest()
        with tempfile.TemporaryDirectory()as d:
            p=Path(d)/'hosted';p.mkdir();(p/(key+'.json')).write_text(json.dumps(self.host(self.raw)))
            with patch('requests.sessions.Session.request',side_effect=AssertionError('network forbidden')):
                record=VerifiedImageHost(d,{}).ensure(self.raw)
            self.assertEqual(record['source_sha256'],key)

if __name__=='__main__':unittest.main()
