import base64,hashlib,io,json,os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import httpx
from PIL import Image
import hermes_mmbc_hosted_worker_v3 as worker
import hermes_bc_worker_v3 as native
import recent_ten_images_transport_v1 as retention
from visual_transport_runtime_v2 import DEFAULT_POLICY

class HostedWorkerTests(unittest.TestCase):
    def test_composition_metadata_and_restore(self):
        with tempfile.TemporaryDirectory()as d:
            root=Path(d);out=root/'out';out.mkdir();cfg=root/'config.json';spec=root/'spec.json'
            settings={'transport_runtime_version':'visual-transport-runtime-v2','image_transport':'verified-imgbb-url-v1','transport_runtime_policy':DEFAULT_POLICY}
            cfg.write_text(json.dumps(settings));spec.write_text(json.dumps({**settings,'config_path':str(cfg)}))
            b=io.BytesIO();Image.new('RGB',(4,4),'white').save(b,format='PNG');raw=b.getvalue();key=hashlib.sha256(raw).hexdigest();url='data:image/png;base64,'+base64.b64encode(raw).decode()
            body=json.dumps({'messages':[{'role':'user','content':[{'type':'image_url','image_url':{'url':url,'detail':'high'}}for _ in range(11)]}]}).encode();received=[]
            class Host:
                def __init__(self,*args):pass
                def __call__(self,raw):return {'url':'https://i.ibb.co/test/image.png','source_sha256':key,'download_sha256':key,'byte_identical':True,'pixel_identical':True,'pixel_sha256':'fixture','dimensions':[4,4]}
            def configure(*args,**kwargs):
                retention.install(out/'metrics/recent-ten-images-wire.jsonl',rendered_registry=lambda:set())
                (out/'bounded-protocol.json').write_text(json.dumps({'sdk_and_request_archive_stage':'old recent-ten-images-wire.jsonl'}))
            def execute():
                native.configure_engine(None,None,None)
                protocol=json.loads((out/'bounded-protocol.json').read_text());self.assertEqual(protocol['actual_wire_ledger'],'hosted-images-wire-v3.jsonl')
                recorder=worker.parent.RetentionVisionRecorder(out/'metrics');recorder.write('vision-wire.jsonl',{'event':'old'})
                def send(req):received.append(req.content);return httpx.Response(200,json={'ok':True})
                with httpx.Client(transport=httpx.MockTransport(send))as c:c.post('http://test/v1/chat/completions',content=body)
            def parent_main():native.main()
            original_send=httpx.Client._send_single_request;original_install=retention.install;original_recorder=worker.parent.RetentionVisionRecorder
            with patch.object(native,'main',execute),patch.object(native,'configure_engine',configure),patch.object(worker.parent,'main',parent_main),patch.object(worker,'VerifiedImageHost',Host),patch.object(sys,'argv',['worker','--spec',str(spec),'--out',str(out)]),patch.dict(os.environ,{'TOKENHUB_BASE_URL':'http://test/v1'}):
                worker.main();self.assertIs(native.main,execute);self.assertIs(native.configure_engine,configure)
            self.assertIs(httpx.Client._send_single_request,original_send);self.assertIs(retention.install,original_install);self.assertIs(worker.parent.RetentionVisionRecorder,original_recorder)
            row=json.loads((out/'metrics/vision-pre-retention.jsonl').read_text());self.assertEqual(row['actual_wire_ledger'],'hosted-images-wire-v3.jsonl')
            hosted=json.loads((out/'metrics/hosted-images-wire-v3.jsonl').read_text());self.assertEqual(hosted['image_count'],10)
            trace=[json.loads(x)for x in (out/'metrics/transport-phases-v2.jsonl').read_text().splitlines()];started=next(x for x in trace if x['event']=='request_started')
            self.assertEqual(started['body_sha256'],hashlib.sha256(received[0]).hexdigest());self.assertNotIn(b'base64',received[0]);self.assertTrue((out/'metrics/registry-cache-v2.jsonl').exists())
            self.assertIn('implementation_sha256',json.loads((out/'transport-runtime.json').read_text()))
    def test_opt_in_required_before_parent_runs(self):
        with tempfile.TemporaryDirectory()as d:
            root=Path(d);cfg=root/'config.json';spec=root/'spec.json';cfg.write_text(json.dumps({'transport_runtime_version':'visual-transport-runtime-v2'}));spec.write_text(json.dumps({'transport_runtime_version':'visual-transport-runtime-v2','config_path':str(cfg)}))
            with patch.object(sys,'argv',['worker','--spec',str(spec),'--out',str(root/'out')]),patch.object(worker.parent,'main')as run:
                with self.assertRaises(ValueError):worker.main()
                run.assert_not_called()

if __name__=='__main__':unittest.main()
