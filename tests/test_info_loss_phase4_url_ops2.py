import sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
import httpx
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import info_loss_phase4_url_ops2 as ops
class DurableTests(unittest.TestCase):
 def test_retry_after_never_shortened_by_normal120cap(self):self.assertEqual(ops.retry_delay('240',0),240);self.assertEqual(ops.retry_delay(None,4),120)
 def test_attempt_limit_is_durable_across_new_state_objects(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d)
   with patch.object(ops.time,'sleep'):
    for n in range(12):
     state=ops.State(root);row=state.reserve('x','upload');state.finish('x',row,error='ConnectError')
    with self.assertRaises(ops.HostingExhausted):ops.State(root).reserve('x','upload')
 def test_model_post_is_not_wrapped_in_zero_model_retry(self):
  class Client:
   n=0
   def post(self,*a,**k):self.n+=1;raise httpx.WriteTimeout('fixture')
  c=Client();wrapper=ops.DirectClient(c,None)
  with self.assertRaises(httpx.WriteTimeout):wrapper.post('model')
  self.assertEqual(c.n,1)
if __name__=='__main__':unittest.main()
