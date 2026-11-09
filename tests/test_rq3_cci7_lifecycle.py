import importlib.util,json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import monitor_rq3_cci7_lifecycle as m

def write(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v));return p
class LifecycleTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)/'campaign';self.marker=Path(self.tmp.name)/'marker.json';self.area=Path(self.tmp.name)/'lifecycle';self.area.mkdir()
  self.host='app-'+m.UID+'-replica-pod';self.owner={'hostname':self.host,'boot_id':'boot1','pid_namespace':'pid:[77]','controller_id':'controller1','pid':49,'start_identity':'1234','scale':'scale_0700'}
  self.b=self.root/'runtime/nodes'/(self.host+'-boot1')/'scale_0700/bootstrap.json'
  write(self.b,{'version':'rq3-scale0700-bootstrap-ops5','campaign_root':str(self.root),'scale_label':'scale_0700','hostname':self.host,'boot_id':'boot1','pid_namespace':'pid:[77]','controller_pid':49,'started_at_unix':10})
  self.e=self.b.parent/'exit.json';write(self.e,{'hostname':self.host,'boot_id':'boot1','scale':'scale_0700','finished_at_unix':30,'controller_exit_code':0,'bootstrap_exit_code':0,'native_processes_signaled':False})
  self.run=self.root/'cloud-scale-ops5/controllers/scale_0700/controller1';write(self.run/'maintenance.json',self.owner);write(self.run/'exit.json',{**self.owner,'at':29,'drained':True,'launched':1})
  self.job=self.root/'jobs/hermes/scale_0700/q_001_r01';write(self.job/'claim/owner.json',{**self.owner,'job_id':'hermes/scale_0700/q_001_r01'});self.result=self.job/'attempts/attempt_001/result.json';write(self.result,{'job_id':'hermes/scale_0700/q_001_r01','status':'completed','slot_released':True,'unconfirmed_child_termination':[]})
  write(self.marker,{'released':True})
 def assess(self):return m.assess_local(self.root,m.UID,self.marker)
 def test_exact_drain_and_claim_termination_pass(self):
  self.assertTrue(self.assess()['eligible']);self.assertEqual(self.assess()['owned_claims'],1)
 def test_marker_absence_is_observe_only(self):
  self.marker.unlink();self.assertFalse(self.assess()['eligible'])
 def test_mismatched_controller_identity_rejected(self):
  d=m.read(self.run/'exit.json');d['start_identity']='reusedpid';write(self.run/'exit.json',d)
  with self.assertRaisesRegex(ValueError,'identity'):self.assess()
 def test_undrained_or_unconfirmed_child_rejected(self):
  d=m.read(self.run/'exit.json');d['drained']=False;write(self.run/'exit.json',d)
  with self.assertRaisesRegex(ValueError,'not drained'):self.assess()
  d['drained']=True;write(self.run/'exit.json',d);r=m.read(self.result);r['unconfirmed_child_termination']=[99];write(self.result,r)
  with self.assertRaisesRegex(ValueError,'unconfirmed'):self.assess()
 def test_precontroller_failure_requires_no_claims(self):
  b=m.read(self.b);b.pop('controller_pid');write(self.b,b);e=m.read(self.e);e.update(controller_exit_code=None,bootstrap_exit_code=1);write(self.e,e)
  with self.assertRaisesRegex(ValueError,'Controller/claim'):self.assess()
  import shutil;shutil.rmtree(self.run);shutil.rmtree(self.job)
  self.assertEqual(self.assess()['reason'],'bootstrap_failed_before_controller_no_native_claims')
 def test_stop_attempt_is_once_even_if_unknown_response(self):
  calls=[]
  def invoke(argv):
   calls.append(argv)
   if 'describe'in argv:return {'returncode':0,'stdout':json.dumps({'name':m.NAME,'uid':m.UID,'state':'RUNNING'}),'stderr':''}
   return {'returncode':None,'error_type':'TimeoutExpired'}
  first=m.cycle(self.area,self.root,self.marker,True,invoke);self.assertEqual(first['state'],'stop_unknown_or_rejected_no_retry')
  second=m.cycle(self.area,self.root,self.marker,True,invoke);self.assertEqual(second['state'],'stop_already_attempted_never_repeat')
  self.assertEqual(sum('stop'in x for x in calls),1)
 def test_platform_wrong_uid_zero_mutations(self):
  def invoke(argv):return {'returncode':0,'stdout':json.dumps({'name':m.NAME,'uid':'other','state':'RUNNING'})}
  with self.assertRaisesRegex(ValueError,'UID'):m.cycle(self.area,self.root,self.marker,True,invoke)
  self.assertFalse((self.area/'stop-request.json').exists())
if __name__=='__main__':unittest.main()
