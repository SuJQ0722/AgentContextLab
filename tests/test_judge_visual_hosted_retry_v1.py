import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import judge_visual_hosted_retry_v1 as worker

class HostedJudgeTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)/'prediction';self.root.mkdir();self.out=Path(self.temp.name)/'grade'
  self.job={'job_id':'hermes/visual/q_001_r01','harness':'hermes','strategy':'visual','question_id':'q_001','repeat':1,'model':worker.base.MODEL,'question':'fixture question'}
  for name in ('plan.json','experiment.json'):(self.root/name).write_text('{}')
  self.data={'root':self.root,'plan':{'jobs':[self.job]},'answers':{self.job['job_id']:'private gold'},'binding':{'plan_sha256':worker.sha(self.root/'plan.json'),'config_sha256':worker.sha(self.root/'experiment.json'),'gold_sources_sha256':{}}}
  self.attempt=self.root/'jobs'/self.job['job_id']/'attempts/attempt_001';self.attempt.mkdir(parents=True)
 def tearDown(self):self.temp.cleanup()
 def result(self,status='completed',clean=True):
  r={k:v for k,v in self.job.items()if k!='question'};r.update(status=status,slot_released=clean,unconfirmed_child_termination=[],final={'text':'answer'})
  (self.attempt/'result.json').write_text(json.dumps(r));return r
 def inspect(self):return worker.inventory_cell('bc_hermes',self.data,self.out)
 def test_failure_zero_but_unconfirmed_and_missing_stay_unknown(self):
  for state in ('failed','timeout'):
   self.result(state);c,r=self.inspect();self.assertEqual(c,[]);self.assertEqual(r[0]['score'],0)
  self.result('timeout',False);c,r=self.inspect();self.assertIsNone(r[0]['score']);self.assertEqual(r[0]['score_reason'],'cleanup_unconfirmed')
  (self.attempt/'result.json').unlink();c,r=self.inspect();self.assertIsNone(r[0]['score'])
 def test_completed_queued_once_and_grade_binding_checked(self):
  self.result();c,r=self.inspect();self.assertEqual(len(c),1);self.assertIsNone(r[0]['score']);self.assertEqual(c[0]['answer'],'private gold')
  dest=c[0]['directory'];dest.mkdir(parents=True);(dest/'request-started.json').write_text('{}')
  c2,r=self.inspect();self.assertEqual(c2,[]);self.assertEqual(r[0]['score_reason'],'unresolved_judge_request')
  (dest/'grade.json').write_text(json.dumps({**c[0]['binding'],'status':'scored','score':1}))
  c2,r=self.inspect();self.assertEqual(r[0]['score'],1)
  (dest/'grade.json').write_text(json.dumps({**c[0]['binding'],'result_sha256':'changed','status':'scored','score':1}))
  with self.assertRaisesRegex(ValueError,'binding'):self.inspect()
 def test_prediction_identity_and_source_change_block_before_grading(self):
  r=self.result();r['repeat']=2;(self.attempt/'result.json').write_text(json.dumps(r))
  with self.assertRaisesRegex(ValueError,'identity'):self.inspect()
  self.result();c,_=self.inspect();(self.attempt/'result.json').write_text('{}')
  with patch.object(worker.base,'judge_one',side_effect=AssertionError('must not send')):
   with self.assertRaisesRegex(ValueError,'changed'):worker.grade_bound(c[0],{}, {})
 def test_cost_collects_failed_and_additional_attempts(self):
  self.result('failed');(self.attempt.parent/'attempt_002').mkdir()
  seen=[]
  def inspect(p,h):seen.append(p);return {},[{'raw_provider_usage':None,'_incomplete':True}]
  with patch('monitor_bc_campaign_v3.inspect_attempt',inspect):
   r=worker.resources({'bc_hermes':self.data},self.out)
  self.assertEqual(len(seen),2);self.assertEqual(r['cells']['bc_hermes']['observed_attempts'],2)
 def test_source_gold_maps_are_consistent_and_external_to_prediction(self):
  gold,hashes=worker.gold_sources();self.assertEqual(len(gold['bc']),100);self.assertEqual(len(gold['mmbc']),100)
  self.assertTrue(all('/outputs/grading/'in p or '/outputs/cohorts/'in p for p in hashes))

if __name__=='__main__':unittest.main()
