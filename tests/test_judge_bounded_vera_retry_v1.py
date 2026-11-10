import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
import judge_bounded_vera_retry_v1 as m
class RetryJudgeTests(unittest.TestCase):
 def fixture(self,tmp,status='completed',clean=True):
  root=Path(tmp)/'prediction';out=Path(tmp)/'grading';jid='hermes/visual/q_r01'
  job={'job_id':jid,'harness':'hermes','strategy':'visual','question_id':'q','repeat':1,'model':m.base.MODEL,'question':'Question'}
  p=root/'jobs'/jid/'attempts/attempt_001/result.json';p.parent.mkdir(parents=True)
  p.write_text(json.dumps({**job,'status':status,'slot_released':clean,'unconfirmed_child_termination':[] if clean else ['child'],'final':{'text':'answer'}}))
  binding={'root':str(root),'plan_sha256':'plan','private_source_sha256':'gold','cohort_sha256':'cohort'}
  return root,out,{'jobs':[job]},{'q':'gold'},binding
 def test_candidate_bound_and_unknown_grade_not_zero(self):
  with tempfile.TemporaryDirectory() as tmp:
   args=self.fixture(tmp);cs,rows,info=m.inventory(*args);self.assertEqual(len(cs),1);self.assertIsNone(rows[0]['score']);self.assertTrue(info['all_terminal'])
   c=cs[0];m.atomic(c['directory']/'grade.json',{**c['binding'],'status':'judge_error','score':None})
   cs,rows,_=m.inventory(*args);self.assertEqual(cs,[]);self.assertIsNone(rows[0]['score'])
 def test_grade_tamper_rejected(self):
  with tempfile.TemporaryDirectory() as tmp:
   args=self.fixture(tmp);c=m.inventory(*args)[0][0];m.atomic(c['directory']/'grade.json',{**c['binding'],'result_sha256':'wrong','status':'scored','score':1})
   with self.assertRaises(ValueError):m.inventory(*args)
 def test_unresolved_request_never_reissued(self):
  with tempfile.TemporaryDirectory() as tmp:
   args=self.fixture(tmp);c=m.inventory(*args)[0][0];m.atomic(c['directory']/'request-started.json',{})
   cs,rows,_=m.inventory(*args);self.assertEqual(cs,[]);self.assertEqual(rows[0]['score_reason'],'unresolved_judge_request');self.assertIsNone(rows[0]['score'])
 def test_failed_only_zero_with_cleanup(self):
  for clean in (True,False):
   with tempfile.TemporaryDirectory() as tmp:
    args=self.fixture(tmp,'timeout',clean);cs,rows,info=m.inventory(*args);self.assertEqual(cs,[]);self.assertEqual(rows[0]['score'],0 if clean else None);self.assertEqual(info['all_terminal'],clean)
 def test_three_layers_no_oracle_accuracy_mislabeled(self):
  selection={'records':[{'score':1},{'score':0},{'score':0}]};v=m.three_layers(selection,[{'score':1},{'score':None}])
  self.assertEqual(v['original_first_pass_300']['correct'],1);self.assertEqual(v['selected_new_attempts_conditional']['accuracy_bounds'],[.5,1.])
  self.assertIsNone(v['retained_correct_plus_new_oracle_union']['accuracy']);self.assertFalse(v['union_is_single_attempt_avg3']);self.assertFalse(v['paired_significance_valid'])
 def test_cost_rows_keep_old_failures_and_all_attempts(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp);r=p/'old/jobs/x/attempts/attempt_001';r.mkdir(parents=True);(r.parent/'attempt_002').mkdir();new=p/'new';(new/'jobs/x/attempts/attempt_001').mkdir(parents=True)
   groups=m.cost_rows({'records':[{'job_id':'x','result_path':str(r/'result.json'),'score':0}]},new)
   self.assertEqual(len(groups['original_all300']),2);self.assertEqual(len(groups['new_selected']),1)
 def test_missing_usage_survives_sum(self):
  a=m.base.aggregate([{'raw_provider_usage':None}]);b=m.base.aggregate([{'raw_provider_usage':{'prompt_tokens':10,'completion_tokens':2,'total_tokens':12,'prompt_tokens_details':{'cached_tokens':3}}}]);merged=m.merge_tokens([a,b]);self.assertEqual(merged['observations'],2)
  self.assertEqual(merged['fields']['total']['known_subtotal'],12);self.assertEqual(merged['fields']['total']['missing_count'],1);self.assertIsNone(merged['fields']['total']['complete_total'])
if __name__=='__main__':unittest.main()
