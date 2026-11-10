import json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import bc_priority_capacity_ops_v1 as m

def write(p,x):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x))
class PriorityTests(unittest.TestCase):
 def test_only_two_predeclared_restore_names(self):
  self.assertNotEqual(m.restore_name('scale_0800'),m.restore_name('scale_1000'))
  with self.assertRaises(ValueError):m.restore_name('scale_0000')
 def test_stop_marker_alone_does_not_release_capacity(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);key='scale_0800';job={'job_id':'hermes/'+key+'/q','scale_key':key};plan={'jobs':[job]}
   write(root/'stops'/key,{})
   self.assertEqual(m.scale_bound(root,plan,key),16)
   c=root/'controllers'/key/'owner';write(c/'maintenance.json',{})
   write(c/'exit.json',{'drained':False});self.assertEqual(m.scale_bound(root,plan,key),16)
   write(c/'exit.json',{'drained':True});self.assertEqual(m.scale_bound(root,plan,key),0)
   write(root/'cells/hermes'/key/'slots/00/owner.json',{});self.assertEqual(m.scale_bound(root,plan,key),16)
 def test_completed_scale_requires_confirmed_cleanup(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);key='scale_1000';job={'job_id':'hermes/'+key+'/q','scale_key':key};plan={'jobs':[job]}
   p=root/'jobs'/job['job_id']/'attempts/attempt_001/result.json'
   write(p,{'job_id':job['job_id'],'status':'completed','slot_released':False,'unconfirmed_child_termination':[1]})
   self.assertEqual(m.scale_bound(root,plan,key),16)
   write(p,{'job_id':job['job_id'],'status':'completed','slot_released':True,'unconfirmed_child_termination':[]})
   self.assertEqual(m.scale_bound(root,plan,key),0)
 def test_unknown_create_cannot_release(self):
  with tempfile.TemporaryDirectory() as d:
   directory=Path(d);write(directory/'response.json',{'state':'unknown'});write(directory/'prepared.json',{});write(directory/'request.json',{})
   with self.assertRaisesRegex(ValueError,'Creation unknown'):m.marker_binding(directory,directory,'hermes')
if __name__=='__main__':unittest.main()
