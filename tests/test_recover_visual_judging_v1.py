import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import recover_visual_judging_v1 as m

class RecoveryTests(unittest.TestCase):
 def candidate(self,root):
  old=root/'old.json';old.write_text('{"status":"http_error","http_status":429}')
  return {'cell':'bc','job_id':'h/visual/q1','directory':root/'new','old_grade_path':str(old),'old_grade_sha256':m.base.sha(old),'binding':{'gold_sources_sha256':{}},'question':'q','answer':'a','prediction':'p'}
 def test_selection_never_uses_scores(self):
  self.assertTrue(m.eligible({'status':'http_error','http_status':429}))
  for score in [0,1]:self.assertFalse(m.eligible({'status':'scored','score':score}))
  self.assertFalse(m.eligible({'status':'invalid_judge_response'}))
 def test_rotate_preserves_zero_score_and_old_grade(self):
  with tempfile.TemporaryDirectory() as tmp:
   c=self.candidate(Path(tmp));calls=[]
   def call(candidate,cfg,env):
    calls.append(cfg['judge_model']);return {'status':'http_error','http_status':429} if len(calls)==1 else {'status':'scored','score':0}
   r=m.recover(c,{},call=call);self.assertEqual(r['score'],0);self.assertEqual(len(calls),2);self.assertNotEqual(*calls)
   self.assertEqual(m.base.sha(c['old_grade_path']),c['old_grade_sha256'])
   m.recover(c,{},call=lambda *a: self.fail('already resolved'));self.assertEqual(len(calls),2)
 def test_unresolved_request_not_replayed(self):
  with tempfile.TemporaryDirectory() as tmp:
   c=self.candidate(Path(tmp));d=c['directory']/'attempts/attempt_001';d.mkdir(parents=True);(d/'request-started.json').write_text('{}')
   with self.assertRaisesRegex(RuntimeError,'Unresolved'):m.recover(c,{},call=lambda *a:self.fail('paid replay'))
 def test_changed_old_grade_rejected(self):
  with tempfile.TemporaryDirectory() as tmp:
   c=self.candidate(Path(tmp));Path(c['old_grade_path']).write_text('{}')
   with self.assertRaisesRegex(ValueError,'Old grade changed'):m.recover(c,{},call=lambda *a:self.fail('paid replay'))
 def test_base_model_alias_revalidated_without_api(self):
  with tempfile.TemporaryDirectory() as tmp:
   c=self.candidate(Path(tmp));d=c['directory']/'attempts/attempt_001';d.mkdir(parents=True)
   (d/'grade.json').write_text(json.dumps({'status':'judge_model_identity_unverified','returned_model':'deepseek-v4.1-flash-1017','api_calls':1}))
   (d/'response.json').write_text(json.dumps({'model':'deepseek-v4.1-flash-1017','choices':[{'finish_reason':'stop','message':{'content':'{"score": 0}'}}]}))
   original=(d/'grade.json').read_bytes()
   result=m.recover(c,{},call=lambda *a:self.fail('must not regrade'))
   self.assertEqual(result['score'],0)
   self.assertEqual((d/'grade.json').read_bytes(),original)
   self.assertTrue((d/'identity-validated-grade.json').exists())
if __name__=='__main__':unittest.main()
