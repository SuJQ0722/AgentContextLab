import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import monitor_bounded_vera_cci_v1 as m
import yaml

def write(path,value):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value));return path
class BoundedRecyclingTests(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup);self.root=Path(self.t.name)/'root';self.receipts=Path(self.t.name)/'receipts';self.strategy='shard-0';self.uid='resource-uid';self.host='app-'+self.uid+'-replica-pod';self.marker=self.receipts/'launch-ready.json';write(self.marker,{})
  write(self.root/'plan.json',{})
  self.owner={'plan_sha256':m.sha(self.root/'plan.json'),'hostname':self.host,'boot_id':'boot','pid_namespace':'pid:[123]','controller_id':'ctr','pid':12,'start_identity':'777','shard':0}
  self.b=self.root/'runtime/nodes'/(self.host+'-boot')/'shard-0/bootstrap.json';write(self.b,{'plan_sha256':m.sha(self.root/'plan.json'),'version':'bounded-vera-retry-bootstrap-v1','campaign_root':str(self.root),'strategy':'shard-0','shard':0,'hostname':self.host,'boot_id':'boot','pid_namespace':'pid:[123]','controller_pid':12,'started_at_unix':10})
  write(self.b.parent/'exit.json',{'hostname':self.host,'boot_id':'boot','scale':'shard-0','finished_at_unix':30,'controller_exit_code':0,'bootstrap_exit_code':0,'native_processes_signaled':False})
  self.c=self.root/'controllers/0/ctr';write(self.c/'maintenance.json',self.owner);write(self.c/'exit.json',{**self.owner,'at':29,'drained':True,'launched':1})
  j=self.root/'jobs/hermes/visual/q001_r01';write(j/'claim/owner.json',{**self.owner,'job_id':'hermes/visual/q001_r01'});self.result=j/'attempts/attempt_001/result.json';write(self.result,{'job_id':'hermes/visual/q001_r01','status':'completed','slot_released':True,'unconfirmed_child_termination':[]})
 def assess(self):return m.assess_local(self.root,self.uid,self.marker,0)
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
  name=m.app_name(0);directory=self.receipts/name;directory.mkdir(parents=True);plan=write(self.root/'plan.json',{})
  cfg={'template':{'containers':[{'command':['/bin/bash','-c','test'],'image_path':'reviewed'}]}};cp=directory/'config.yaml';cp.write_text(yaml.safe_dump(cfg))
  ready={'shard':0,'name':name,'root':str(self.root),'plan_sha256':m.sha(plan),'config_path':str(cp),'config_sha256':m.sha(cp),'launch_marker':str(self.marker)}
  write(self.marker,{'plan_sha256':m.sha(plan)});write(directory/'prepared.json',ready);write(directory/'request.json',ready);write(directory/'response.json',{'state':'submitted','returncode':0});calls=[]
  def invoke(argv):
   calls.append(argv)
   if 'describe'in argv:return {'returncode':0,'stdout':json.dumps({'name':name,'uid':self.uid,'state':'RUNNING',**cfg})}
   return {'returncode':None,'error_type':'TimeoutExpired'}
  first=m.cycle(0,True,invoke,self.receipts,self.root);second=m.cycle(0,True,invoke,self.receipts,self.root)
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
  o=m.read(self.c/'maintenance.json');o['shard']=1;write(self.c/'maintenance.json',o)
  with self.assertRaisesRegex(ValueError,'scope'):self.assess()
 def test_platform_caching_and_marker_binding(self):
  name=m.app_name(0);directory=self.receipts/name;directory.mkdir(parents=True)
  plan=write(self.root/'plan.json',{});cfg={'template':{'containers':[{'command':['reviewed'],'image_path':'reviewed'}]}}
  cp=directory/'config.yaml';cp.write_text(yaml.safe_dump(cfg))
  ready={'shard':0,'name':name,'root':str(self.root),'plan_sha256':m.sha(plan),'config_path':str(cp),'config_sha256':m.sha(cp),'launch_marker':str(self.marker)}
  write(directory/'prepared.json',ready);write(directory/'request.json',ready);write(directory/'response.json',{'state':'submitted'})
  calls=[]
  def invoke(argv):
   calls.append(argv)
   return {'returncode':0,'stdout':json.dumps({'name':name,'uid':self.uid,'state':'RUNNING',**cfg})}
  with self.assertRaisesRegex(ValueError,'marker plan'):m.cycle(0,False,invoke,self.receipts,self.root)
  self.assertFalse(calls)
  write(self.marker,{'plan_sha256':m.sha(plan)})
  cache={}
  for now in [100,130,190,220]:m.cycle(0,False,invoke,self.receipts,self.root,cache=cache,clock=lambda:now)
  self.assertEqual(len(calls),2)
  self.assertTrue(all('describe' in x and 'stop' not in x for x in calls))
  cache[name]['platform']['uid']='replacement'
  with self.assertRaisesRegex(ValueError,'UID/plan/config'):m.cycle(0,True,invoke,self.receipts,self.root,cache=cache,clock=lambda:221)
  cache[name]['platform']['uid']=self.uid
  cache[name]['platform']['template']['containers'][0]['command']=['other']
  with self.assertRaisesRegex(ValueError,'command/image'):m.cycle(0,True,invoke,self.receipts,self.root,cache=cache,clock=lambda:221)
  self.assertFalse(any('stop' in x for x in calls))

if __name__=='__main__':unittest.main()
