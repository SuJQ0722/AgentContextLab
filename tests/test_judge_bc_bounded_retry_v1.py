import copy,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import judge_bc_bounded_retry_v1 as g
import bc_bounded_retry_sources_v1 as source

def fixture():
 records=[];jobs=[]
 for h in ('hermes','dsh'):
  for rep in (1,2,3):
   for q in range(100):
    r={'job_id':f'{h}/visual/q{q}_r{rep}','question_id':f'q{q}','repeat':rep,'harness':h,'score':int(q>1),'status':'completed' if q else 'timeout','selected_for_retry':q<=1}
    records.append(r)
    if r['selected_for_retry']:jobs.append({k:r[k] for k in ('job_id','question_id','repeat','harness')})
 return {'jobs':jobs},{'records':records}

class BCGraderTests(unittest.TestCase):
 def test_answer_selection_allows_wrong_but_excludes_correct(self):
  plan,s=fixture();g.validate_selection(plan,s['records'])
  bad=copy.deepcopy(plan);bad['jobs'].append({k:s['records'][2][k] for k in ('job_id','question_id','repeat','harness')})
  with self.assertRaises(ValueError):g.validate_selection(bad,s['records'])
 def test_unknown_original_grade_is_blocked(self):
  plan,s=fixture();s['records'][0]['score']=None
  with self.assertRaises(ValueError):g.validate_selection(plan,s['records'])
 def test_union_is_answer_conditioned_and_missing_retry_not_zero(self):
  p,s=fixture();x=g.three_layers(s,[])
  self.assertTrue(x['selection_uses_answer_correctness']);self.assertFalse(x['union_is_clean_single_attempt_avg3'])
  for c in x['per_harness']:
   self.assertEqual(c['previous_selected300']['correct'],294)
   self.assertEqual(c['new_noncorrect_conditional']['missing'],6)
   self.assertEqual(c['retained_correct_plus_new_oracle_union']['missing'],6)
  new=[dict(j,score=0) for j in p['jobs']];x=g.three_layers(s,new)
  self.assertTrue(all(c['retained_correct_plus_new_oracle_union']['correct']==294 for c in x['per_harness']))
 def test_inventory_dsh_unknown_judge_is_not_reissued(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d)/'root';out=Path(d)/'out';j={'job_id':'dsh/visual/q_r01','harness':'dsh','strategy':'visual','question_id':'q','question':'Q','repeat':1,'model':g.base.MODEL}
   rp=root/'jobs'/j['job_id']/'attempts/attempt_001/result.json';rp.parent.mkdir(parents=True);rp.write_text(json.dumps({**j,'status':'completed','final':'prediction','slot_released':True,'unconfirmed_child_termination':[]}))
   gd=out/'jobs'/j['job_id'];gd.mkdir(parents=True);(gd/'request-started.json').write_text('{}')
   cs,rows,_=g.inventory(root,out,{'jobs':[j]},{'q':'gold'},{'plan_sha256':'p'})
   self.assertEqual(cs,[]);self.assertEqual(rows[0]['harness'],'dsh');self.assertIsNone(rows[0]['score'])
 def test_cost_uses_each_harness_extractor_and_missing_usage(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d)/'root';out=Path(d)/'out';records=[]
   for h in ('hermes','dsh'):
    jid=h+'/visual/q_r01';(root/'jobs'/jid/'attempts/attempt_001').mkdir(parents=True)
    records.append({'job_id':jid,'harness':h,'selected_for_retry':True})
   info={'requests':{},'web_cache':{}};raw=[{'raw_provider_usage':None,'_incomplete':True}]
   with patch('monitor_bc_campaign_v3.inspect_attempt',return_value=(info,raw)) as inspect:
    report=g.resource_report({'records':records},root,out)
   self.assertEqual({c.args[1] for c in inspect.call_args_list},{'hermes','dsh'})
   self.assertIsNone(report['combined_old_new_token_total'])
   for h in ('hermes','dsh'):
    t=report['new_attempts_raw_accounting'][h]['prediction_tokens']['fields']['total'];self.assertEqual(t['missing_count'],1);self.assertIsNone(t['complete_total'])
 def test_source_public_rows_never_carry_gold_and_cleanup_blocks(self):
  import hashlib
  with tempfile.TemporaryDirectory() as d:
   cohort=Path(d)/'cohort';inventory=Path(d)/'inventory'
   cohort.write_text(''.join(json.dumps({'id':f'q{i}','question':f'Q{i}','answer':f'G{i}'})+'\n' for i in range(100)))
   rows=[];results={}
   for h in ('hermes','dsh'):
    for rep in (1,2,3):
     for i in range(100):
      jid=f'{h}/visual/q{i}_r{rep}';path='result-'+jid
      v={'job_id':jid,'harness':h,'question_id':f'q{i}','repeat':rep,'status':'failed','slot_released':True,'unconfirmed_child_termination':[]}
      results[path]=v
      rows.append({**v,'group':f'bc/{h}/visual','prediction_status':'failed','result_path':path,'result_sha256':'safe','score':0,'grade_path':None,'grade_sha256':None,'attempt_path':'old/'+jid,'question_sha256':hashlib.sha256(f'Q{i}'.encode()).hexdigest()})
   inventory.write_text(''.join(json.dumps(r)+'\n' for r in rows))
   with patch.object(source,'sha',return_value='safe'),patch.object(source,'read',side_effect=lambda p:results[str(p)]):
    records,gold,public=source.source_records(inventory,cohort)
    self.assertEqual(len(records),600);self.assertEqual(len(gold),100)
    self.assertTrue(all(set(p)=={'id','question'} for p in public))
    results[rows[0]['result_path']]['slot_released']=False
    with self.assertRaises(ValueError):source.source_records(inventory,cohort)

if __name__=='__main__':unittest.main()
