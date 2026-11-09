import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import monitor_mmbc_vanilla_lifecycle as m
import yaml

def write(path,value):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value));return path
class MMBCVanillaRecyclingTests(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup);self.root=Path(self.t.name)/'root';self.receipts=Path(self.t.name)/'receipts';self.strategy='visual';self.uid='resource-uid';self.host='app-'+self.uid+'-replica-pod';self.marker=self.receipts/'launch-ready.json';write(self.marker,{})
  self.owner={'hostname':self.host,'boot_id':'boot','pid_namespace':'pid:[123]','controller_id':'ctr','pid':12,'start_identity':'777','strategy':self.strategy}
  self.b=self.root/'runtime/nodes'/(self.host+'-boot')/'visual/bootstrap.json';write(self.b,{'version':'mmbc100-hermes-vanilla-cci-bootstrap-v1','campaign_root':str(self.root),'strategy':'visual','hostname':self.host,'boot_id':'boot','pid_namespace':'pid:[123]','controller_pid':12,'started_at_unix':10})
  write(self.b.parent/'exit.json',{'hostname':self.host,'boot_id':'boot','scale':'visual','finished_at_unix':30,'controller_exit_code':0,'bootstrap_exit_code':0,'native_processes_signaled':False})
  self.c=self.root/'controllers/visual/ctr';write(self.c/'maintenance.json',self.owner);write(self.c/'exit.json',{**self.owner,'at':29,'drained':True,'launched':1})
  j=self.root/'jobs/hermes/visual/q001_r01';write(j/'claim/owner.json',{**self.owner,'job_id':'hermes/visual/q001_r01'});self.result=j/'attempts/attempt_001/result.json';write(self.result,{'job_id':'hermes/visual/q001_r01','status':'completed','slot_released':True,'unconfirmed_child_termination':[]})
 def assess(self):return m.assess_local(self.root,self.uid,self.marker,'visual')
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
  name=m.app_name('visual');directory=self.receipts/name;directory.mkdir(parents=True);plan=write(self.root/'plan.json',{})
  cfg={'template':{'containers':[{'command':['/bin/bash','-c','test'],'image_path':'reviewed'}]}};cp=directory/'config.yaml';cp.write_text(yaml.safe_dump(cfg))
  ready={'name':name,'root':str(self.root),'plan_sha256':m.sha(plan),'config_path':str(cp),'config_sha256':m.sha(cp),'launch_marker':str(self.marker)}
  write(directory/'prepared.json',ready);write(directory/'request.json',ready);write(directory/'response.json',{'state':'submitted','returncode':0});calls=[]
  def invoke(argv):
   calls.append(argv)
   if 'describe'in argv:return {'returncode':0,'stdout':json.dumps({'name':name,'uid':self.uid,'state':'RUNNING',**cfg})}
   return {'returncode':None,'error_type':'TimeoutExpired'}
  with patch.object(m,'DEFAULT_ROOT',self.root):
   first=m.cycle('visual',True,invoke,self.receipts);second=m.cycle('visual',True,invoke,self.receipts)
  self.assertEqual(first['state'],'stop_unknown_or_rejected_no_retry');self.assertEqual(second['state'],'stop_already_attempted_never_repeat');self.assertEqual(sum('stop'in a for a in calls),1)
if __name__=='__main__':unittest.main()
