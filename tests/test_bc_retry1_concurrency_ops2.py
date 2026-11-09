import json,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import set_bc_retry1_concurrency_ops2 as ops
import run_bc_campaign_v3_routes1 as policy
class ConcurrencyTests(unittest.TestCase):
 def test_policy_enforces_total16_even_when_both_routes_allow16(self):
  desired=json.loads(ops.DESIRED.read_text());ops.validate_policy(desired)
  with patch.object(policy,'ROUTE_PLAN',None):d=policy.DispatchPolicy(ops.DESIRED,'cloud').refresh()
  self.assertTrue(policy.can_dispatch(d,15));self.assertFalse(policy.can_dispatch(d,16))
  self.assertTrue(policy.can_route_dispatch(d,{'deepseek-v4.1-flash-1017/huoshan/huoshan':15},'deepseek-v4.1-flash-1017/huoshan/huoshan'))
  desired['local_target_workers']=2
  with self.assertRaises(ValueError):ops.validate_policy(desired)
 def test_ack_requires_same_identity_and_exact_policy_hash(self):
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/'status.json';owner={k:str(i) for i,k in enumerate(ops.IDENTITY)};item={'status_path':str(path),'owner':owner,'role':'cloud','cell':'hermes/visual'}
   s={**owner,'heartbeat_unix':time.time(),'active_local':1,'dispatch_policy':{'valid':True,'config_sha256':'new','target':0}}
   path.write_text(json.dumps(s));self.assertIsNone(ops.acknowledged(item,'other',0));self.assertEqual(ops.acknowledged(item,'new',0)['active_local'],1)
   s['start_identity']='changed';path.write_text(json.dumps(s))
   with self.assertRaisesRegex(ValueError,'identity changed'):ops.acknowledged(item,'new',0)
 def test_atomic_policy_publication_and_no_process_actions(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp)/'config.json';p.write_bytes(b'old');ops.atomic_bytes(p,b'{"target":16}\n');self.assertEqual(p.read_bytes(),b'{"target":16}\n')
   self.assertEqual(len(list(Path(tmp).iterdir())),1)
if __name__=='__main__':unittest.main()
