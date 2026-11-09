import json,sys,tempfile,types,unittest
from pathlib import Path
from unittest.mock import patch,Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import run_mmbc_vanilla_campaign as controller
import provision_mmbc_vanilla_cci as launch
import bootstrap_mmbc_vanilla_cci as bootstrap
import yaml

def template():
 return {'display_name':'acl-rq3-s0700-cci7','resource_pool':{'name':'agents','available_zone':'cn-tj-01a','vpc_id':'019e25be-ec63-7831-98f8-3993ee8be3ab'},'replicas':1,'scheduling':{'priority':'NORMAL','quota_type':'RESERVED'},'template':{'resource_spec':{'name':'N4lS.Iu.I80.8c32g'},'containers':[{'name':'rq3','image_path':'registry.cn-tj-01.sensecore.cn/ccr-zuhu2026/sjq-dev-cpu:sjq-dev-20261108063401','resource_request':{'cpu':'8','memory':'32GiB'},'env':[],'volume_mounts':[{'id':'019ed8e0-f4f8-71f7-830c-f8a1e667a9ec','mount_path':'/mnt/afs_agents','subdir':'/'}],'command':['/bin/bash','-c','old']}]}}

class MMBCVanillaCloudTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
 def test_shared_cell_slots_and_complete_owner_before_spec(self):
  plan={'definition':{'cohort_sha256':'cohort'}};(self.root/'plan.json').write_text(json.dumps(plan))
  job={'job_id':'hermes/visual/q_001_r01','harness':'hermes','strategy':'visual','method_label':'vanilla_visual','question_id':'q_001','repeat':1};owner={'controller_id':'owned','pid':1}
  got=controller.publish_spec(self.root,job,owner,plan)
  jobdir,slot,attempt,spec=got
  self.assertEqual(json.loads((jobdir/'claim/owner.json').read_text())['controller_id'],'owned')
  self.assertEqual(json.loads((slot/'owner.json').read_text())['job_id'],job['job_id'])
  self.assertEqual(json.loads((jobdir/'spec.json').read_text())['slot_path'],str(slot))
  self.assertIsNone(controller.publish_spec(self.root,job,owner,plan))
  self.assertFalse((attempt/'worker-started.json').exists())
 def test_reject_parent_scope_without_vanilla_label(self):
  plan={'jobs':[{'job_id':str(i),'harness':'hermes','strategy':'visual'} for i in range(300)]}
  with self.assertRaisesRegex(ValueError,'Vanilla-only'):controller.selected_jobs(plan,'visual')
 def test_lease_never_reclaimed_after_unknown(self):
  controller.acquire_lease(self.root,'visual',{'controller_id':'first'})
  with self.assertRaises(FileExistsError):controller.acquire_lease(self.root,'visual',{'controller_id':'second'})
 def test_stop_before_dispatch_never_spawns(self):
  jobs=[{'job_id':f'hermes/visual/q_{i:03}_r{n:02}','harness':'hermes','strategy':'visual','method_label':'vanilla_visual'}for i in range(100)for n in range(1,4)]
  plan={'jobs':jobs,'definition':{'cohort_sha256':'abc'}};(self.root/'plan.json').write_text(json.dumps(plan));(self.root/'STOP').touch()
  helper=types.SimpleNamespace(load_validate=lambda r:(plan,{}),validate=lambda p,r:None)
  fake=Mock()
  with patch.dict(sys.modules,{'prepare_mmbc_vanilla':helper}),patch.object(controller,'environment',return_value=({},{})),patch('review_execution.enforce'),patch('preflight_bc_v3_web.preflight',return_value={'passed':True}),patch.object(controller.signal,'signal'):
   controller.controller(self.root,'visual',popen=fake)
  fake.assert_not_called();exitfile=next((self.root/'controllers/visual').glob('*/exit.json'));self.assertTrue(json.loads(exitfile.read_text())['drained'])
 def test_cci_resource_contract_and_explicit_argv(self):
  base=template();cfg=launch.build_config(base,'visual',self.root,self.root/'marker')
  self.assertEqual(cfg['template']['resource_spec'],base['template']['resource_spec'])
  a=cfg['template']['containers'][0];b=base['template']['containers'][0]
  for key in ['image_path','resource_request','volume_mounts','env']:self.assertEqual(a[key],b[key])
  self.assertEqual(a['command'][:2],['/bin/bash','-c']);self.assertIn('--concurrency 16',a['command'][2]);self.assertIn('exec sleep infinity',a['command'][2])
  self.assertEqual(base['display_name'],'acl-rq3-s0700-cci7')
  self.assertEqual(cfg['display_name'],'acl-mmbc100-hermes-vanilla-v1')
  with self.assertRaises(ValueError):launch.build_config(base,'none')
 def test_unknown_create_never_replayed(self):
  config=self.root/'config.yaml';config.write_text('test');record={'name':launch.app_name('visual'),'config_path':str(config),'config_sha256':controller.digest(config.read_bytes())};calls=[]
  def invoke(argv):
   calls.append(argv)
   if 'describe'in argv:return {'returncode':1,'stdout':'','stderr':'{"reason":"appNotFound"}'}
   return {'returncode':None,'error_type':'TimeoutExpired'}
  self.assertEqual(launch.submit(record,invoke)['state'],'unknown')
  self.assertEqual(launch.submit(record,invoke)['state'],'existing_request_never_repeated')
  self.assertEqual(sum('create'in x for x in calls),1)
 def test_bootstrap_real_entry_wiring(self):
  a=types.SimpleNamespace(root=self.root,scale='visual',reader_python='/opt/conda/bin/python')
  commands=bootstrap.commands(a);cmd=commands['controller']
  self.assertIn(str(controller.ROOT/'scripts/run_mmbc_vanilla_campaign.py'),cmd);self.assertEqual(cmd[cmd.index('--strategy')+1],'visual');self.assertEqual(cmd[cmd.index('--concurrency')+1],'16');self.assertIn('--resume',cmd)
  self.assertIn('--strategy',commands['telemetry'])
if __name__=='__main__':unittest.main()
