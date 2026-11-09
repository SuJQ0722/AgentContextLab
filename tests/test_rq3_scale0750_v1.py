import copy,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import run_rq3_parity_v3 as old
import prepare_rq3_scale0750_v1 as scope
import run_rq3_scale0750_trial as trial
import rq3_scale0750_worker as worker
import rq3_hermes_parity_worker as old_worker
from run_bc_campaign_v3 import acquire_claim,identity,atomic
class ScopeTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.base=Path(self.tmp.name)/'base';self.base.mkdir();self.parent=Path(self.tmp.name)/'old';self.root=Path(self.tmp.name)/'new'
  (self.base/'experiment.json').write_bytes((old.BASE/'experiment.json').read_bytes());(self.base/'plan.json').write_text('{}')
  (self.base/'cohort.jsonl').write_text(''.join(json.dumps({'id':f'q_{n:03}','question':f'Q{n}','answer':'PRIVATE'})+'\n' for n in range(100)))
  with patch.object(old,'BASE',self.base),patch.object(old,'sources',return_value={}):self.parent_plan=old.prepare(self.parent)
  self.parent_sha=old.sha(self.parent/'plan.json');self.manifest=scope.prepare(self.parent,self.root)
 def test_exact_new_scope_same_questions_and_parent_unchanged(self):
  plan,m=scope.validate_scope(self.root);self.assertEqual(len(plan['jobs']),2100);self.assertEqual(len(m['authorized_job_ids']),300)
  self.assertEqual(plan['definition']['scales'],[0.,.25,.5,.7,.75,.8,1.]);self.assertEqual(old.sha(self.parent/'plan.json'),self.parent_sha)
  self.assertEqual(old.sha(self.root/'cohort.jsonl'),old.sha(self.parent/'cohort.jsonl'));self.assertEqual(scope.prepare(self.parent,self.root),m)
  a=old.read(self.root/'configs/scale_0750.json');b=old.read(self.parent/'configs/scale_1000.json')
  for cfg in (a,b):cfg.pop('rq3');cfg['visual_renderer'].pop('history_scale')
  self.assertEqual(a,b);self.assertNotIn(.75,old.SCALES)
 def spec(self,scale=.75):
  plan=old.read(self.root/'plan.json');job=next(j for j in plan['jobs'] if j['scale']==scale);owner={**identity(),'controller_id':'fixture'}
  directory,slot=acquire_claim(self.root,job,owner,cap=16);out=directory/'attempts/attempt_001';out.mkdir(parents=True)
  spec={**job,'campaign_root':str(self.root),'plan_sha256':old.sha(self.root/'plan.json'),'cohort_sha256':plan['definition']['cohort_sha256'],'slot_path':str(slot),'controller_id':'fixture'}
  atomic(directory/'spec.json',spec);return spec,out
 def test_frozen_validation_and_new_trial_accept_authorized0750(self):
  spec,out=self.spec();self.assertEqual(old.validate_trial(spec,out),self.root);self.assertEqual(trial.validate_spec(spec,out),self.root)
  self.assertIs(worker.RQ3VisionRecorder,old_worker.RQ3VisionRecorder)
  import run_bc_trial_v3
  self.assertIs(trial.trial,run_bc_trial_v3)
 def test_placeholder_rejected_and_changed_config_fails_closed(self):
  spec,out=self.spec(1.);old.validate_trial(spec,out)
  with self.assertRaisesRegex(ValueError,'Only the new'):trial.validate_spec(spec,out)
  spec,out=self.spec(.75);p=Path(spec['config_path']);cfg=old.read(p);cfg['visual_renderer']['history_scale']=.8;p.write_text(json.dumps(cfg))
  with self.assertRaisesRegex(ValueError,'input changed'):trial.validate_spec(spec,out)
 def test_supervisor_command_changes_only_native_entry(self):
  captured={};original=trial.trial.native_command
  def fake_main():
   command,result,timeout=trial.trial.native_command({},Path('/tmp/out'));captured['command']=command
  command=['python',str(old.ROOT/'scripts/hermes_bc_worker_v3.py'),'--spec','fixed','--live']
  with patch.object(trial.trial,'main',fake_main),patch.object(trial.trial,'native_command',return_value=(command,Path('/tmp/result'),10)):
   trial.main()
  self.assertEqual(captured['command'],['python',str(old.ROOT/'scripts/rq3_scale0750_worker.py'),'--spec','fixed','--live'])
if __name__=='__main__':unittest.main()
