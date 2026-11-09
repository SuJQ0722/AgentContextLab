import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch,Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import judge_rq3_scale0750_v1 as judge
class ScopeGradingTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)/'campaign';self.root.mkdir()
  (self.root/'plan.json').write_text('{}');(self.root/judge.MANIFEST).write_text('{}');self.jid='hermes/scale_0750/q_001_r01'
  with patch.object(judge,'validate_scope',return_value=({'jobs':[{'job_id':self.jid}]},{'authorized_job_ids':[self.jid]})):self.guard=judge.ScopeGuard(self.root)
  out=self.root/'jobs'/self.jid/'attempts/attempt_001';self.candidate={'binding':{'job_id':self.jid,'root':str(self.root),'attempt_path':str(out),'result_path':str(out/'result.json')}}
 def test_per_candidate_gate_precedes_any_grade_operation(self):
  original=Mock(return_value={'status':'scored'});self.guard.grade(original,self.candidate,{},{});self.assertEqual(original.call_count,1)
  wrong={'binding':dict(self.candidate['binding'],job_id='hermes/scale_1000/q_001_r01')}
  with self.assertRaisesRegex(ValueError,'outside authorized'):self.guard.grade(original,wrong,{},{})
  self.assertEqual(original.call_count,1)
 def test_changed_plan_blocks_inventory_and_queued_grade(self):
  (self.root/'plan.json').write_text('{"changed":true}');original=Mock()
  with self.assertRaisesRegex(ValueError,'scope changed'):self.guard.inventory(original,self.root,Path('/tmp/private'),'cohort')
  with self.assertRaisesRegex(ValueError,'scope changed'):self.guard.grade(original,self.candidate,{},{})
  original.assert_not_called()
 def test_inventory_only_authorized_counts_and_invalid_attempt_rejected(self):
  original=Mock(return_value=([self.candidate],{'planned':2100,'prediction_states':{'no_terminal_result':2100}}))
  rows,info=self.guard.inventory(original,self.root,Path('/tmp/private'),'cohort');self.assertEqual(info['planned'],1);self.assertEqual(info['prediction_states'],{'no_terminal_result':1})
  wrong={'binding':dict(self.candidate['binding'],attempt_path='/other')}
  with self.assertRaisesRegex(ValueError,'attempt differs'):self.guard.candidate(wrong)
if __name__=='__main__':unittest.main()
