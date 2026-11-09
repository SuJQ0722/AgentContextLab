import sys,tempfile,unittest,json,time
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import info_loss_phase4_rate_ops4 as ops
class RateTests(unittest.TestCase):
 def test_prior_429_and_unknown_are_never_retried(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);folder=root/'calls/old';folder.mkdir(parents=True);(folder/'started.json').write_text('{}');(folder/'response.json').write_text('{"status":"provider_error","http_status":429}')
   class Base:
    def __init__(self):self.out=root
    def call(self,key,*a,**k):return json.loads((folder/'response.json').read_text())
   pace=ops.Pace(root,root/'ops')
   with patch.object(pace,'before',side_effect=AssertionError('no new inference')):
    self.assertEqual(ops.paced_client(Base,pace)().call('old')['http_status'],429)
 def test_future_call_wait_and_retry_after_and_cap(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);pace=ops.Pace(root,root/'ops');p=root/'calls/new/response.json';p.parent.mkdir(parents=True);p.write_text('{}');pace.retry_after='1200';pace.after('new',{'status':'provider_error','http_status':429})
   s=pace.load();self.assertEqual(s['events'][-1]['delay_seconds'],1200);self.assertEqual(s['infra_failures'],1)
   s['infra_failures']=12;ops.worker.save(pace.path,s)
   with self.assertRaises(ops.worker.study.Hold):pace.before(lambda:None)
 def test_new_third_infra_is_recorded_then_returns_without_repost(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);pace=ops.Pace(root,root/'ops')
   class Base:
    n=0
    def __init__(self):self.out=root;self.errors=2
    def boundary(self):pass
    def call(self,key,*a,**k):
     self.n+=1;folder=root/'calls'/key;folder.mkdir(parents=True);(folder/'started.json').write_text('{}');(folder/'response.json').write_text('{"status":"transport_error","error_type":"ConnectTimeout"}');raise ops.worker.study.Hold('infrastructure_or_model_identity_gate')
   c=ops.paced_client(Base,pace)();r=c.call('new');self.assertEqual(c.n,1);self.assertEqual(r['status'],'transport_error');self.assertEqual(pace.load()['infra_failures'],1)
 def test_model_identity_and_quality_hold_remain_fail_closed(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);(root/'quality-hold.json').write_text('{"reason":"two_or_more_visual_QA_invalid_in_one_case","inflight":0}')
   with self.assertRaises(ValueError):ops.release_expected_hold(root,root/'ops')
 def test_post429_returns_once_and_captures_retry_header(self):
  class C:
   n=0
   def post(self,*a,**k):self.n+=1;return type('R',(),{'headers':{'retry-after':'120'}})()
  c=C();pace=type('P',(),{})();ops.ObservedClient(c,None,pace).post('endpoint');self.assertEqual(c.n,1);self.assertEqual(pace.retry_after,'120')
if __name__=='__main__':unittest.main()
