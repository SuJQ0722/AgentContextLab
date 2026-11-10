import copy,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import judge_rq3_bounded_retry_v1 as g


def fixture():
 rows=[];records=[];jobs=[]
 for scale in g.campaign.SCALES:
  for rep in (1,2,3):
   for q in range(100):
    jid=f'hermes/{g.campaign.key(scale)}/q{q}_r{rep}'
    status='timeout' if q==0 else 'completed';score=0 if q in (0,1) else None if q==2 else 1
    rows.append({'job_id':jid,'question_id':f'q{q}','repeat':rep,'scale':scale,'prediction_status':status,'score':score})
    records.append({'job_id':jid,'question_id':f'q{q}','repeat':rep,'scale':scale,'status':status,'selected_for_retry':status=='timeout'})
    if status=='timeout':jobs.append({'job_id':jid,'question_id':f'q{q}','repeat':rep,'scale':scale})
 return {'jobs':jobs},{'records':records,'original_rows':rows}


class RQ3JudgeTests(unittest.TestCase):
 def test_status_selection_keeps_completed_wrong_and_missing(self):
  plan,s=fixture();g.validate_selection(plan,s['records'],s['original_rows'])
  bad=copy.deepcopy(plan);bad['jobs'].append(dict(bad['jobs'][0],job_id=s['records'][1]['job_id'],question_id='q1'))
  with self.assertRaises(ValueError):g.validate_selection(bad,s['records'],s['original_rows'])
 def test_selection_flag_cannot_change_with_score(self):
  plan,s=fixture();s['records'][1]['selected_for_retry']=True
  with self.assertRaises(ValueError):g.validate_selection(plan,s['records'],s['original_rows'])
 def test_overlay_replaces_only_failure_slots_never_unknown_zero(self):
  plan,s=fixture();new=[dict(j,score=1) for j in plan['jobs']]
  layers=g.three_layers(s,new)
  for scale in layers['per_scale']:
   old=scale['original_selected300'];overlay=scale['fixed_execution_status_overlay']
   self.assertEqual(old['missing'],3);self.assertEqual(overlay['missing'],3)
   self.assertEqual(overlay['correct']-old['correct'],3)
   self.assertIsNone(overlay['std_across_three_repeat_accuracies'])
  self.assertFalse(layers['selection_uses_answer_correctness']);self.assertFalse(layers['overlay_is_clean_new_protocol_avg3'])
 def test_unfinished_retry_stays_unknown_and_no_best_score_choice(self):
  plan,s=fixture();a=g.three_layers(s,[])
  for x in a['per_scale']:
   self.assertEqual(x['new_execution_failure_conditional']['missing'],3)
   self.assertEqual(x['fixed_execution_status_overlay']['missing'],6)
  with self.assertRaises(ValueError):g.three_layers(s,[dict(s['original_rows'][1],score=1)])
 def test_completed_std_only_when_all300_known(self):
  rows=[{'repeat':rep,'score':int(q<80+rep)} for rep in (1,2,3) for q in range(100)]
  result=g.repeated_summary(rows,300)
  self.assertAlmostEqual(result['mean_accuracy'],.82);self.assertAlmostEqual(result['std_across_three_repeat_accuracies'],.01)
 def test_inventory_missing_judge_claim_not_replayed(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d)/'root';out=Path(d)/'grades';job={'job_id':'hermes/scale_0000/q0_r1','harness':'hermes','strategy':'visual','question_id':'q0','question':'question','repeat':1,'model':g.base.MODEL,'scale':0.}
   rp=root/'jobs'/job['job_id']/'attempts/attempt_001/result.json';rp.parent.mkdir(parents=True)
   rp.write_text(json.dumps({**job,'status':'completed','final':'prediction','slot_released':True,'unconfirmed_child_termination':[]}))
   gd=out/'jobs'/job['job_id'];gd.mkdir(parents=True);(gd/'request-started.json').write_text('{}')
   cs,rows,info=g.inventory(root,out,{'jobs':[job]},{'q0':'gold'},{'plan_sha256':'p','private_source_sha256':'s'})
   self.assertEqual(cs,[]);self.assertIsNone(rows[0]['score']);self.assertEqual(rows[0]['score_reason'],'unresolved_judge_request')
 def test_cost_original_is_explicit_reference_not_false_cumulative_total(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d)/'root';out=Path(d)/'out';old=Path(d)/'old';old.mkdir()
   (old/'paid-interruption-cumulative-cost.json').write_text('{"old_retry_cost":42}')
   with patch.object(g.campaign,'SOURCE_REPORT',old),patch.object(g.base,'accounting',return_value={'new':True}):
    report=g.resource_report({'records':[]},root,out)
   self.assertFalse(report['original_costs_reaggregated']);self.assertIsNone(report['combined_old_new_token_total'])
   self.assertTrue(any(r['name']=='paid-interruption-cumulative-cost.json' and r['available'] for r in report['original_cost_reference_snapshots']))

if __name__=='__main__':unittest.main()
