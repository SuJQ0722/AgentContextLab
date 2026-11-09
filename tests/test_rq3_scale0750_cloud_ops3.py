import argparse,errno,json,os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import run_rq3_scale0750_cloud_ops3 as cloud
import run_rq3_parity_v3 as scientific
import prepare_rq3_scale0750_v1 as scope
class NewScopeCloudTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);base=Path(self.tmp.name)/'base';base.mkdir();self.parent=Path(self.tmp.name)/'parent';self.root=Path(self.tmp.name)/'new'
  (base/'experiment.json').write_text(json.dumps(scientific.read(scientific.BASE/'experiment.json')));(base/'plan.json').write_text('{}');(base/'cohort.jsonl').write_text(''.join(json.dumps({'id':f'q_{i:03}','question':f'Q{i}','answer':'PRIVATE'})+'\n' for i in range(100)))
  with patch.object(scientific,'BASE',base),patch.object(scientific,'sources',return_value={}):scientific.prepare(self.parent)
  self.manifest=scope.prepare(self.parent,self.root);self.plan=scientific.read(self.root/'plan.json');self.jobs=cloud.jobs_for_scale(self.plan,.75);self.owner={'controller_id':'test','hostname':'host','boot_id':'boot','pid_namespace':'ns','pid':42,'start_identity':'start'}
 def launch(self):
  a=cloud.area(self.root);a.mkdir(parents=True,exist_ok=True);x={'version':'rq3-scale0750-cloud-launch-ops3','launch_authorized':True,'campaign_root':str(self.root),'plan_sha256':scientific.sha(self.root/'plan.json'),'scope_sha256':scientific.sha(self.root/scope.MANIFEST),'authorized_job_ids_sha256':self.manifest['authorized_job_ids_sha256'],'allowed_scale':'scale_0750','max_concurrency':16};(a/'launch.json').write_text(json.dumps(x));return x
 def test_only_0750_and_300_ids_never_execute_placeholders(self):
  self.assertEqual(cloud.normalize_scale('.75'),'scale_0750');self.assertEqual(len(self.jobs),300)
  for s in [0,.125,.25,.5,.7,.8,1]:
   with self.assertRaises(argparse.ArgumentTypeError):cloud.normalize_scale(s)
  wrong=next(j for j in self.plan['jobs'] if j['scale']==.25)
  with self.assertRaises(ValueError):cloud.publish_claim(self.root,wrong,self.owner,.75)
  fake={**self.jobs[0],'job_id':'hermes/scale_0750/q_999_r01'}
  with self.assertRaises(ValueError):cloud.publish_claim(self.root,fake,self.owner,.75)
  self.assertFalse((self.root/'jobs').exists())
 def test_frozen_scientific_parameters_preserved(self):
  a=scientific.read(self.root/'configs/scale_0750.json');b=scientific.read(self.parent/'configs/scale_0700.json')
  self.assertEqual(a['model'],b['model']);self.assertEqual(a['web'],b['web']);self.assertEqual(a['bc100_campaign'],b['bc100_campaign']);self.assertEqual(a['shared_policy'],b['shared_policy'])
  self.assertEqual({k:v for k,v in a['visual_renderer'].items() if k!='history_scale'},{k:v for k,v in b['visual_renderer'].items() if k!='history_scale'})
 def test_launch_requires_exact_scope_plan_and_new_entries(self):
  self.launch();cloud.verify_launch(self.root)
  p=cloud.area(self.root)/'launch.json';x=json.loads(p.read_text());x['scope_sha256']='wrong';p.write_text(json.dumps(x))
  with self.assertRaises(ValueError):cloud.verify_launch(self.root)
 def test_atomic_claim_never_replays_existing_attempt_and_uses_new_trial(self):
  job=self.jobs[0];first=cloud.publish_claim(self.root,job,self.owner,.75);directory,slot,attempt,spec=first
  original=(directory/'claim/owner.json').read_bytes();cloud.verify_published(spec,directory);scope.validate_authorized_spec(spec)
  self.assertIsNone(cloud.publish_claim(self.root,job,self.owner,.75));self.assertEqual(original,(directory/'claim/owner.json').read_bytes())
  other=self.root/'jobs'/self.jobs[1]['job_id']/'attempts';other.mkdir(parents=True)
  self.assertIsNone(cloud.publish_claim(self.root,self.jobs[1],self.owner,.75))
 def test_exact16slots_and_permanent_lease(self):
  for j in self.jobs[:16]:self.assertIsNotNone(cloud.acquire_scale_slot(self.root,.75,self.owner,j['job_id']))
  self.assertIsNone(cloud.acquire_scale_slot(self.root,.75,self.owner,self.jobs[16]['job_id']))
  cloud.acquire_lease(self.root,.75,self.owner)
  with self.assertRaises(ValueError):cloud.acquire_lease(self.root,.75,self.owner)
 def test_stop_after_one_new_trial_drains_without_paid_retry(self):
  self.launch();created=[]
  class Child:
   pid=os.getpid();polls=0
   def poll(self):self.polls+=1;return 0 if self.polls>=3 else None
  def spawn(cmd,**kwargs):
   self.assertEqual(Path(cmd[1]).name,'run_rq3_scale0750_trial.py');created.append(Child());(self.root/'STOP').touch();return created[-1]
  with patch('preflight_bc_v3_web.preflight',return_value={'passed':True}),patch.object(cloud.time,'sleep',return_value=None):cloud.controller(self.root,.75,popen=spawn)
  self.assertEqual(len(created),1);self.assertGreaterEqual(created[0].polls,3)
  m=scientific.read(next(cloud.area(self.root).glob('controllers/*/*/maintenance.json')));self.assertEqual(m['native_entry'],'scripts/rq3_scale0750_worker.py');self.assertEqual(m['scope_version'],scope.VERSION)
 def test_error_after_spawn_still_drains(self):
  self.launch();created=[];original=cloud.atomic
  class Child:
   pid=os.getpid();polls=0
   def poll(self):self.polls+=1;return 0 if self.polls>=3 else None
  def spawn(*a,**k):created.append(Child());return created[-1]
  def atomic(path,value):
   if Path(path).name=='controller-dispatched.json':raise OSError(errno.EIO,'fixture')
   original(path,value)
  with patch('preflight_bc_v3_web.preflight',return_value={'passed':True}),patch.object(cloud.time,'sleep',return_value=None),patch.object(cloud,'atomic',side_effect=atomic):
   with self.assertRaises(RuntimeError):cloud.controller(self.root,.75,popen=spawn)
  self.assertEqual(len(created),1);self.assertGreaterEqual(created[0].polls,3)
if __name__=='__main__':unittest.main()
