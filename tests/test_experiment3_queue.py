import base64,hashlib,io,json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from controlled_native_preflight import prepare_captures
from run_rebuttal_queue import capture_gate,fresh_stage
from lab import ROOT

class FreshPrefixQueueTests(unittest.TestCase):
    def fixture(self,root):
        from PIL import Image
        buf=io.BytesIO();Image.new('RGB',(3,4),'blue').save(buf,format='PNG')
        cfg=json.loads((ROOT/'configs/experiment.json').read_text())
        for ds in ['browsecomp_v3','mmbrowsecomp']:
            p=root/ds;p.mkdir(parents=True)
            request={'model':cfg['model'],'messages':[{'role':'user','content':[{'type':'text','text':'Exact number 42'},
                 {'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(buf.getvalue()).decode()}}]}]}
            raw=json.dumps(request).encode();(p/'prefix.json').write_bytes(raw)
            (p/'prefix-manifest.json').write_text(json.dumps({'status':'captured','sha256':hashlib.sha256(raw).hexdigest(),'native_image_parts':1}))
            (p/'result.json').write_text('{"status":"captured"}')
            (p/'spec.json').write_text(json.dumps({'question_id':ds+'-fixture','question':'Look at the image','model':cfg['model']}))
    def test_two_local_captures_prepare_without_api_or_base64_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'capture';self.fixture(root);out=Path(tmp)/'fresh';out.mkdir()
            self.assertEqual(capture_gate(root)[0],'ready')
            manifest=prepare_captures(out,root)
            self.assertEqual(len(manifest['samples']),2)
            for sample in manifest['samples']:
                self.assertNotIn('base64',json.dumps(sample['prefix']))
                self.assertIn('Exact number 42',json.dumps(sample['prefix']))
                self.assertEqual(len(sample['input_images']),1)
                self.assertTrue(sample['complete_native_evidence'])
            self.assertFalse((out/'calls').exists())
            self.assertEqual(manifest['request_cap'],12)
    def test_hash_failure_and_uncertain_started_stage_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'prefix-capture';self.fixture(root)
            (root/'mmbrowsecomp/prefix.json').write_text('tampered')
            self.assertEqual(capture_gate(root)[0],'blocked')
            self.assertEqual(fresh_stage(root,True,{}),'blocked')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'prefix-capture';root.mkdir()
            fresh=root.parent/'native-budget-preflight-fresh';fresh.mkdir()
            (fresh/'stage-started.json').write_text('{"pid":123,"start_identity":"old"}')
            self.assertEqual(fresh_stage(root,True,{}),'blocked')
            self.assertFalse((fresh/'calls').exists())
