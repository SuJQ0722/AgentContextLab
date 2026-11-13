import hashlib,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import info_loss_quota_recovery_v13 as info
import run_controlled_dependency_recovery_v13 as control
class RecoveryTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);self.manifest={'model':'fixture','thinking':{'type':'disabled'}}
 def fingerprint(self):
  payload={'model':'fixture','messages':[{'role':'user','content':[{'type':'text','text':'same'}]}],'max_tokens':8192,'temperature':0,'stream':False,'thinking':self.manifest['thinking']}
  return hashlib.sha256(json.dumps(payload,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
 def client(self,index):
  with patch.object(info,'environment',return_value=({},{})):return info.Client(self.root,self.manifest,index,True)
 def test_three_physical_starts_block_network(self):
  c=self.client({self.fingerprint():{'physical_starts':3,'evidence':[]}})
  with patch.object(info,'PARENT',self.root/'old'),patch.object(info.httpx,'Client',side_effect=AssertionError('No network')):
   self.assertEqual(c.call('k','same')['status'],'cumulative_three_request_cap');self.assertEqual(c.sent,0)
 def test_unknown_acceptance_is_not_retried(self):
  c=self.client({self.fingerprint():{'physical_starts':1,'evidence':[{'response':None,'status':'unknown'}]}})
  with patch.object(info,'PARENT',self.root/'old'),patch.object(info.httpx,'Client',side_effect=AssertionError('No network')):
   self.assertEqual(c.call('k','same')['status'],'unknown_acceptance')
 def test_successful_length_response_is_reused_not_improved(self):
  p=self.root/'old/completed-calls'/self.fingerprint();p.parent.mkdir(parents=True);p.write_text(json.dumps({'status':'completed','finish_reason':'length','content':'truncated'}))
  c=self.client({})
  with patch.object(info,'PARENT',self.root/'old'),patch.object(info.httpx,'Client',side_effect=AssertionError('No network')):
   self.assertEqual(c.call('k','same')['finish_reason'],'length');self.assertEqual(c.sent,0)
 def test_control_guard_precedes_explicit_round_override(self):
  root=self.root/'campaign';root.mkdir();out=root/'jobs/test';out.mkdir(parents=True);job={'campaign_root':str(root)};spec=root/'job.json';spec.write_text(json.dumps(job));(root/'plan.json').write_text(json.dumps({'jobs':[job],'implementation_sha256':{}}));called=[]
  def original(j,d):called.append(j);return {'max_rounds':60,'native':'unchanged'},{'foo':1}
  def fake_main():
   spec,cfg=control.frozen.validate(job,out);self.assertEqual(spec,{'max_rounds':500,'native':'unchanged'});self.assertEqual(cfg,{'foo':1})
  with patch.object(control.frozen,'validate',original),patch.object(control.frozen,'main',fake_main):control.worker(spec,out)
  self.assertEqual(len(called),1);self.assertEqual(json.loads((out/'v13-operational-budget.json').read_text())['actual_max_iterations'],500)
if __name__=='__main__':unittest.main()
