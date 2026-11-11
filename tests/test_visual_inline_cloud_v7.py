import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import monitor_visual_inline_two_hour_v7 as m
import yaml

def write(path,value):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value));return path
class BoundedRecyclingTests(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup);self.root=Path(self.t.name)/'root/cells/bc_hermes';self.receipts=Path(self.t.name)/'receipts';self.strategy='hermes';self.uid='resource-uid';self.host='app-'+self.uid+'-replica-pod';self.marker=self.receipts/'launch-ready.json';write(self.marker,{})
  write(self.root/'plan.json',{})
  self.owner={'plan_sha256':m.sha(self.root/'plan.json'),'hostname':self.host,'boot_id':'boot','pid_namespace':'pid:[123]','controller_id':'ctr','pid':12,'start_identity':'777','harness':'hermes'}
  self.b=self.root/'runtime/nodes'/(self.host+'-boot')/'hermes/bootstrap.json';write(self.b,{'plan_sha256':m.sha(self.root/'plan.json'),'version':'visual-inline-two-hour-bootstrap-v7','campaign_root':str(self.root),'strategy':'hermes','harness':'hermes','hostname':self.host,'boot_id':'boot','pid_namespace':'pid:[123]','controller_pid':12,'started_at_unix':10})
  write(self.b.parent/'exit.json',{'hostname':self.host,'boot_id':'boot','scale':'hermes','finished_at_unix':30,'controller_exit_code':0,'bootstrap_exit_code':0,'native_processes_signaled':False})
  self.c=self.root/'controllers/hermes/ctr';write(self.c/'maintenance.json',self.owner);write(self.c/'exit.json',{**self.owner,'at':29,'drained':True,'launched':1})
  j=self.root/'jobs/hermes/visual/q001_r01';write(j/'claim/owner.json',{**self.owner,'job_id':'hermes/visual/q001_r01'});self.result=j/'attempts/attempt_001/result.json';write(self.result,{'job_id':'hermes/visual/q001_r01','status':'completed','slot_released':True,'unconfirmed_child_termination':[]})
 def assess(self):return m.assess_local(self.root,self.uid,self.marker,'hermes')
 def test_exact_method_finished(self):self.assertTrue(self.assess()['eligible'])
 def test_missing_result_and_undrained_refuse(self):
  d=m.read(self.c/'exit.json');d['drained']=False;write(self.c/'exit.json',d)
  with self.assertRaisesRegex(ValueError,'not drained'):self.assess()
  d['drained']=True;write(self.c/'exit.json',d);self.result.unlink()
  with self.assertRaisesRegex(ValueError,'terminal result'):self.assess()
 def test_changed_epoch_and_retained_slot_refuse(self):
  d=m.read(self.c/'exit.json');d['start_identity']='other';write(self.c/'exit.json',d)
  with self.assertRaisesRegex(ValueError,'identity'):self.assess()
  d['start_identity']='777';write(self.c/'exit.json',d);write(self.root/'cells/hermes/visual/slots/00/owner.json',self.owner)
  with self.assertRaisesRegex(ValueError,'owns a scale slot'):self.assess()
 def test_marker_absent_does_not_stop(self):
  self.marker.unlink();self.assertEqual(self.assess()['reason'],'launch_marker_absent_observe_only')
 def test_resource_binding_and_stop_once(self):
  name=m.app_name('bc_hermes');directory=self.receipts/name;directory.mkdir(parents=True);plan=write(self.root/'plan.json',{})
  cfg={'template':{'containers':[{'command':['/bin/bash','-c','test'],'image_path':'reviewed'}]}};cp=directory/'config.yaml';cp.write_text(yaml.safe_dump(cfg))
  ready={'harness':'bc_hermes','name':name,'root':str(self.root),'plan_sha256':m.sha(plan),'config_path':str(cp),'config_sha256':m.sha(cp),'launch_marker':str(self.marker)}
  write(self.marker,{'plan_sha256':m.sha(plan)});write(directory/'prepared.json',ready);write(directory/'request.json',ready);write(directory/'response.json',{'state':'submitted','returncode':0});calls=[]
  def invoke(argv):
   calls.append(argv)
   if 'describe'in argv:return {'returncode':0,'stdout':json.dumps({'name':name,'uid':self.uid,'state':'RUNNING',**cfg})}
   return {'returncode':None,'error_type':'TimeoutExpired'}
  first=m.cycle('bc_hermes',True,invoke,self.receipts,self.root.parent.parent);second=m.cycle('bc_hermes',True,invoke,self.receipts,self.root.parent.parent)
  self.assertEqual(first['state'],'stop_unknown_or_rejected_no_retry');self.assertEqual(second['state'],'stop_attempted_never_repeated');self.assertEqual(sum('stop'in a for a in calls),1)


 def test_bootstrap_failed_before_controller_confirmed_zero_native(self):
  import shutil
  shutil.rmtree(self.c)
  shutil.rmtree(self.root/'jobs')
  b=m.read(self.b);b.pop('controller_pid');write(self.b,b)
  e=m.read(self.b.parent/'exit.json');e.update(controller_exit_code=None,bootstrap_exit_code=1);write(self.b.parent/'exit.json',e)
  self.assertEqual(self.assess()['reason'],'bootstrap_failed_before_controller_no_native_claims')
  write(self.root/'jobs/hermes/visual/x/claim/owner.json',self.owner)
  with self.assertRaisesRegex(ValueError,'claim evidence'):self.assess()
 def test_unconfirmed_child_and_other_shard_refuse(self):
  r=m.read(self.result);r['unconfirmed_child_termination']=[{'pid':123}];write(self.result,r)
  with self.assertRaisesRegex(ValueError,'termination unconfirmed'):self.assess()
  r['unconfirmed_child_termination']=[];write(self.result,r)
  o=m.read(self.c/'maintenance.json');o['harness']='dsh';write(self.c/'maintenance.json',o)
  with self.assertRaisesRegex(ValueError,'scope'):self.assess()

 def test_rq3_nonvisual_jobpath_is_accounted(self):
  import shutil
  j=self.result.parent.parent.parent
  target=self.root/'jobs/hermes/scale_0750/q001_r01'
  target.parent.mkdir(parents=True,exist_ok=True);shutil.move(str(j),str(target))
  self.assertEqual(self.assess()['owned_claims'],1)
  (target/'attempts/attempt_001/result.json').unlink()
  with self.assertRaisesRegex(ValueError,'terminal result'):self.assess()

class CloudConfigTests(unittest.TestCase):
 def test_each_cell_has_separate_root_marker_and_fixed16(self):
  import provision_visual_inline_two_hour_v7 as p
  template=yaml.safe_load(p.base.TEMPLATE.read_text());names=set();commands=[]
  for cell in p.CELLS:
   config=p.build_config(template,cell);names.add(config['display_name'])
   command=config['template']['containers'][0]['command'][-1];commands.append(command)
   self.assertIn('/cells/'+cell,command);self.assertIn('--concurrency 16',command)
   self.assertIn(str(p.launch_marker(cell)),command)
   self.assertEqual(config['template']['resource_spec'],{'name':'N4lS.Iu.I80.8c32g'})
  self.assertEqual(len(names),len(p.CELLS));self.assertEqual(len(set(commands)),len(p.CELLS))
 def test_wrong_scope_rejected(self):
  import provision_visual_inline_two_hour_v7 as p
  with self.assertRaises(ValueError):p.app_name('all')

class StartupContractTests(unittest.TestCase):
 def test_wrong_trial_deadline_refused(self):
  import bootstrap_visual_inline_two_hour_v7 as b
  with patch('prepare_visual_hosted_retry_v1.load_validate',return_value=({'jobs':[{'timeout_seconds':1800}]},{})):
   with self.assertRaisesRegex(ValueError,'7200'):b.load_validate(Path('/unused'))
 def test_cloud_default_excludes_local_cells_and_no_ttl(self):
  import provision_visual_inline_two_hour_v7 as p
  self.assertEqual(len(p.CLOUD_CELLS),11)
  self.assertNotIn('bc_hermes',p.CLOUD_CELLS);self.assertNotIn('bc_dsh',p.CLOUD_CELLS)
  config=p.build_config(yaml.safe_load(p.base.TEMPLATE.read_text()),'mmbc_vera')
  self.assertFalse(any(k in json.dumps(config).lower() for k in ('activedeadline','expiration','lease_seconds','max_runtime')))
 def test_local_affinities_disjoint_and_fixed(self):
  import launch_visual_inline_two_hour_local_v7 as l
  self.assertEqual(l.CELLS,{'bc_hermes':('hermes','0-7'),'bc_dsh':('dsh','8-15')})
 def test_warmup_failure_blocks_dispatch(self):
  import warm_visual_inline_worker_v7 as w
  from types import SimpleNamespace
  with tempfile.TemporaryDirectory() as tmp,patch.object(w.subprocess,'run',return_value=SimpleNamespace(returncode=1)):
   with self.assertRaisesRegex(RuntimeError,'no native dispatch'):w.warm(Path(tmp),'hermes')

if __name__=='__main__':unittest.main()
