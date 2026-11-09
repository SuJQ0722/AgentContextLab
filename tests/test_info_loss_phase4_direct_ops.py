import sys,tempfile,unittest,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import info_loss_phase4_direct_ops as ops
class DirectTests(unittest.TestCase):
 def test_proxy_removed_bytes_unchanged_and_response_evidence(self):
  capture={}
  class Client:
   def __init__(self,*a,**k):capture['options']=k
   def __enter__(self):return self
   def __exit__(self,*a):pass
   def post(self,url,**kw):capture['body']=kw['content'];return type('Response',(),{'status_code':200})()
  with tempfile.TemporaryDirectory() as d:
   root=Path(d)
   with ops.factory(Client,root)(proxy='secretproxy',trust_env=True,timeout=180) as c:c.post('http://fixture',content=b'original payload')
   self.assertNotIn('proxy',capture['options']);self.assertFalse(capture['options']['trust_env']);self.assertEqual(capture['options']['timeout'],180);self.assertEqual(capture['body'],b'original payload')
   self.assertEqual(json.loads(next(root.glob('http/*/terminal.json')).read_text())['http_status'],200)
 def test_previous_failed_response_cannot_be_changed(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);p=root/'calls/x/response.json';p.parent.mkdir(parents=True);p.write_text('{"status":"transport_error"}');before=ops.snapshot(root);p.write_text('{"status":"completed"}')
   with self.assertRaises(ValueError):ops.verify_prior(root,before)
if __name__=='__main__':unittest.main()
