import sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import httpx
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import info_loss_phase4_url_ops as ops
class OpsTests(unittest.TestCase):
 def test_get_transient_retries_but_model_post_never_retries(self):
  class Client:
   def __init__(self):self.gets=0;self.posts=0
   def get(self,*a,**k):
    self.gets+=1
    if self.gets<3:raise httpx.ConnectError('fixture')
    return type('Response',(),{'status_code':200})()
   def post(self,*a,**k):self.posts+=1;raise httpx.WriteTimeout('fixture')
  source=Client();client=ops.DownloadClient(source)
  with patch.object(ops.time,'sleep'):
   self.assertEqual(client.get('url').status_code,200)
   with self.assertRaises(httpx.WriteTimeout):client.post('model')
  self.assertEqual(source.gets,3);self.assertEqual(source.posts,1)
 def test_upload_receipt_survives_failed_later_download_without_reupload(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);image=root/'image.png';image.write_bytes(b'fixture');calls=[]
   def original(p):calls.append(p);return 'https://i.ibb.co/fixture/image.png'
   upload=ops.upload_factory(original,root/'ops');self.assertEqual(upload(image),upload(image));self.assertEqual(len(calls),1)
if __name__=='__main__':unittest.main()
