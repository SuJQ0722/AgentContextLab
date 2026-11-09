import sys,tempfile,unittest,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import info_loss_phase3_ops as ops

class OperationsTests(unittest.TestCase):
 def test_explicit_proxy_preserves_request_bytes_and_existing_response_skips_network(self):
  calls=[];construct=[]
  class Fake:
   def __init__(self,*a,**k):construct.append(k)
   def __enter__(self):return self
   def __exit__(self,*a):pass
   def post(self,url,**k):calls.append((url,k));return type('Response',(),{'status_code':200})()
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory);create=ops.factory(Fake,'http://proxy.test:8080',root)
   with create(trust_env=True,timeout=90) as c:c.post('https://model.test',content=b'unchanged full image payload',headers={'Authorization':'secret'})
   self.assertEqual(calls[0][1]['content'],b'unchanged full image payload');self.assertEqual(construct,[{'trust_env':False,'timeout':90,'proxy':'http://proxy.test:8080'}])
   self.assertNotIn('secret',''.join(p.read_text() for p in root.glob('http/*/*.json')))
   from info_loss_phase3 import Client
   prior=root/'calls/old';prior.mkdir(parents=True);(prior/'response.json').write_text('{"status":"transport_error","usage":null}')
   client=Client.__new__(Client);client.out=root
   self.assertEqual(client.call('old','same frozen prompt')['status'],'transport_error')
   self.assertEqual(len(calls),1)
 def test_previous_call_response_evidence_cannot_change(self):
  with tempfile.TemporaryDirectory() as directory:
   r=Path(directory);p=r/'calls/one';p.mkdir(parents=True);(p/'response.json').write_text('{"usage":null}')
   snap=ops.snapshot_calls(r);ops.verify_prior(r,snap);(p/'response.json').write_text('{}')
   with self.assertRaises(ValueError):ops.verify_prior(r,snap)
if __name__=='__main__':unittest.main()
