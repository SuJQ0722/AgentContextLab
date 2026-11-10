import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import bc_priority_capacity_ops_v2 as m

def write(p,x):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x))
class DrainBoundTests(unittest.TestCase):
 def fixture(self,root):
  key='scale_0800';run=root/'controllers'/key/'controller';owner={'hostname':'host','boot_id':'boot','pid_namespace':'ns','pid':1,'start_identity':'start','controller_id':'controller','shard':key,'scale_key':key,'version':'rq3-bounded-retry-controller-v1','run_directory':str(run)}
  jobs=[{'scale_key':key,'job_id':'hermes/'+key+'/q'+str(i)}for i in range(4)];plan={'definition':{'implementation_sha256':{m.CONTROLLER:m.base.sha(m.base.ROOT/m.CONTROLLER)}},'jobs':jobs};write(root/'plan.json',plan)
  write(root/'stops'/key,{'at':10});write(root/'leases'/key/'owner.json',owner);write(root/'leases'/key/'runtime.json',{'directory':str(run)})
  write(run/'maintenance.json',{**owner,'cell_cap':16,'target_concurrency':16,'plan_sha256':m.base.sha(root/'plan.json'),'source_sha256':plan['definition']['implementation_sha256'][m.CONTROLLER]})
  write(run/'status.json',{**owner,'at':20,'active_local':2,'launched':3,'reserved_not_started':None,'stop_dispatch':True})
  for i,j in enumerate(jobs[:3]):
   slot=root/'cells/hermes'/key/'slots'/str(i);o={**owner,'job_id':j['job_id'],'slot':str(slot)};write(root/'jobs'/j['job_id']/'claim/owner.json',o)
   if i==0:write(root/'jobs'/j['job_id']/'attempts/attempt_001/result.json',{'job_id':j['job_id'],'status':'completed','slot_released':True,'unconfirmed_child_termination':[]})
   else:write(slot/'owner.json',o)
  return key,plan,run,owner
 def test_acknowledged_stop_uses_max_status_and_all_unconfirmed_claims(self):
  with tempfile.TemporaryDirectory()as d:
   root=Path(d);key,plan,run,_=self.fixture(root);self.assertEqual(m.scale_bound(root,plan,key),2)
   s=m.base.read(run/'status.json');s['active_local']=1;write(run/'status.json',s);self.assertEqual(m.scale_bound(root,plan,key),2)
   s['active_local']=5;write(run/'status.json',s);self.assertEqual(m.scale_bound(root,plan,key),5)
 def test_unknown_stop_status_source_lease_claim_and_slot_fail_closed(self):
  for mutation in ('no_stop','not_ack','old_ack','source','lease','claim','slot','coverage'):
   with self.subTest(mutation=mutation),tempfile.TemporaryDirectory()as d:
    root=Path(d);key,plan,run,owner=self.fixture(root)
    if mutation=='no_stop':(root/'stops'/key).unlink()
    elif mutation in ('not_ack','old_ack','coverage'):
     s=m.base.read(run/'status.json');s.update({'stop_dispatch':False}if mutation=='not_ack' else {'at':9}if mutation=='old_ack' else {'launched':9});write(run/'status.json',s)
    elif mutation=='source':s=m.base.read(run/'maintenance.json');s['source_sha256']='changed';write(run/'maintenance.json',s)
    elif mutation=='lease':write(root/'leases'/key/'owner.json',{**owner,'pid':99})
    elif mutation=='claim':p=root/'jobs'/plan['jobs'][1]['job_id']/'claim/owner.json';s=m.base.read(p);s['pid']=99;write(p,s)
    elif mutation=='slot':write(root/'cells/hermes'/key/'slots/unknown/owner.json',{**owner,'job_id':'unknown'})
    self.assertEqual(m.scale_bound(root,plan,key),16)
 def test_reservation_counted_and_exit_requires_all_native_cleanup(self):
  with tempfile.TemporaryDirectory()as d:
   root=Path(d);key,plan,run,owner=self.fixture(root);s=m.base.read(run/'status.json');s.update(active_local=2,launched=2,reserved_not_started=plan['jobs'][2]['job_id']);write(run/'status.json',s);self.assertEqual(m.scale_bound(root,plan,key),3)
   write(run/'exit.json',{**owner,'at':21,'drained':True});self.assertEqual(m.scale_bound(root,plan,key),16)
 def test_prior_unexited_controller_is_not_hidden(self):
  with tempfile.TemporaryDirectory()as d:
   root=Path(d);key,plan,run,owner=self.fixture(root);other=run.parent/'other';s=m.base.read(run/'maintenance.json');s.update(controller_id='other',run_directory=str(other));write(other/'maintenance.json',s);write(other/'status.json',{**s,'at':20,'active_local':0,'launched':0,'stop_dispatch':True});self.assertEqual(m.scale_bound(root,plan,key),16)
 def test_existing_restore_receipt_keeps_original_v1_provenance(self):
  with tempfile.TemporaryDirectory()as d:
   restore=Path(d);key='scale_0800';path=restore/m.base.restore_name(key)/'prepared.json'
   write(path,{'source_sha256':m.base.sha(m._original_file)})
   seen=[]
   with patch.object(m.base,'RESTORE',restore),patch.object(m,'_original_prepare',side_effect=lambda key:seen.append(m.base.__file__)),patch.object(m.base,'__file__',m.__file__):m.prepare_restore(key)
   self.assertEqual(seen,[m._original_file])
 def test_new_entry_retains_v1_lock_and_receipts_but_records_v2_source(self):
  old_area=m.base.AREA;old_restore=m.base.RESTORE
  def main():
   self.assertEqual(m.base.AREA,old_area);self.assertEqual(m.base.RESTORE,old_restore)
   self.assertIs(m.base.scale_bound,m.scale_bound);self.assertEqual(m.base.__file__,m.__file__)
  with patch.object(m.base,'main',main):m.main()
  self.assertEqual(m.base.__file__,m._original_file)
if __name__=='__main__':unittest.main()
