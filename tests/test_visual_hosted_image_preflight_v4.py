import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import preflight_visual_hosted_transport_v4 as p
class ImageReadinessTests(unittest.TestCase):
 def test_receipt_only_cache_and_upload_block(self):
  import requests
  with tempfile.TemporaryDirectory()as d:
   def ensure(host,raw):
    key=p.sha(raw)
    self.assertTrue((host.root/'hosted'/(key+'.upload.json')).exists())
    self.assertFalse((host.root/'hosted'/(key+'.json')).exists())
    with self.assertRaisesRegex(RuntimeError,'Upload prohibited'):requests.Session().request('POST','https://unused')
    return {'byte_identical':True,'pixel_identical':True,'verification_attempts':1,'verification_route':'proxy'}
   with patch.object(p.VerifiedImageHost,'ensure',ensure):result=p.check(Path(d))
   self.assertTrue(result['passed']);self.assertEqual(result['model_calls'],0);self.assertEqual(result['upload_calls'],0)
 def test_missing_receipt_rejects_without_host(self):
  with tempfile.TemporaryDirectory()as d:
   fixture=Path(d);(fixture/'manifest.json').write_text('{}')
   with patch.object(p.VerifiedImageHost,'ensure')as host:
    with self.assertRaisesRegex(ValueError,'manifest binding'):p.check(fixture,fixture)
    host.assert_not_called()
if __name__=='__main__':unittest.main()
