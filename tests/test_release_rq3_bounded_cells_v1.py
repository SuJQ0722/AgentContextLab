import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import release_rq3_bounded_cells_v1 as m

def write(p,x):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x));return p
class ReleaseTests(unittest.TestCase):
 def fixture(self,d):
  root=Path(d)/'rq3';old=Path(d)/'mmbc';receipts=Path(d)/'receipts'
  jobs=[{'job_id':'hermes/'+s+'/q_r01','scale_key':s} for s in m.SCALE_KEYS]
  plan={'jobs':jobs};write(root/'plan.json',plan)
  old_jobs=[{'job_id':'hermes/visual/q'+str(i)} for i in range(60)]
  write(old/'plan.json',{'definition':{'planned_runs':60,'per_cell_concurrency_cap':48},'jobs':old_jobs});write(old/'campaign-manifest.json',{'plan_sha256':m.sha(old/'plan.json')})
  for s in m.SCALE_KEYS:
   directory=receipts/m.app_name(s);cp=write(directory/'config.json',{'scale':s})
   row={'root':str(root.resolve()),'scale_key':s,'name':m.app_name(s),'plan_sha256':m.sha(root/'plan.json'),'config_path':str(cp),'config_sha256':m.sha(cp),'launch_marker':str(m.launch_marker(s,receipts))}
   write(directory/'prepared.json',row);write(directory/'request.json',row);write(directory/'response.json',{'state':'submitted'})
  return root,old,receipts,plan,old_jobs
 def finish(self,root,job,clean=True):write(root/'jobs'/job['job_id']/'attempts/attempt_001/result.json',{'job_id':job['job_id'],'status':'timeout','slot_released':clean,'unconfirmed_child_termination':[] if clean else [{'pid':1}]})
 def test_capacity_unknown_refused(self):
  self.assertEqual(m.capacity(100,4),116);self.assertEqual(m.capacity(44,5),128)
  for v in [None,-1,True]:
   with self.assertRaises(ValueError):m.capacity(v,4)
 def test_dry_no_markers_then_release_by_remaining_not_active(self):
  with tempfile.TemporaryDirectory() as d:
   root,old,receipts,plan,jobs=self.fixture(d)
   with patch.object(m,'load_validate',return_value=(plan,{})):
    dry=m.cycle(False,root,receipts,old);self.assertEqual(sum(r['state']=='would_release' for r in dry['rows']),4);self.assertFalse((receipts/'markers').exists())
    a=m.cycle(True,root,receipts,old);self.assertEqual(sum(r['state']=='released' for r in a['rows']),4)
    for j in jobs[:16]:self.finish(old,j)
    b=m.cycle(True,root,receipts,old);self.assertEqual(b['mmbc_remaining'],44);self.assertEqual(sum(r['state']=='released' for r in b['rows']),1)
    for j in jobs[16:32]:self.finish(old,j)
    c=m.cycle(True,root,receipts,old);self.assertEqual(sum(r['state']=='released' for r in c['rows']),1)
    for j in jobs[32:48]:self.finish(old,j)
    e=m.cycle(True,root,receipts,old);self.assertEqual(sum(r['state']=='released' for r in e['rows']),1)
    self.assertEqual(len(list((receipts/'markers').glob('*.json'))),7)
    self.assertTrue(all(m.read(p)['combined_inference_upper']<=128 for p in (receipts/'markers').glob('*.json')))
 def test_unclean_terminal_does_not_free_capacity(self):
  with tempfile.TemporaryDirectory() as d:
   root,old,receipts,plan,jobs=self.fixture(d)
   for j in jobs:self.finish(old,j,False)
   self.assertEqual(m.remaining_count(old,jobs),60)
 def test_wrong_binding_no_release(self):
  with tempfile.TemporaryDirectory() as d:
   root,old,receipts,plan,jobs=self.fixture(d)
   p=receipts/m.app_name(m.SCALE_KEYS[0])/'response.json';write(p,{'state':'unknown'})
   with patch.object(m,'load_validate',return_value=(plan,{})):
    with self.assertRaises(ValueError):m.cycle(True,root,receipts,old)
   self.assertFalse((receipts/'markers').exists())
if __name__=='__main__':unittest.main()
