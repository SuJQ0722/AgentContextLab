import json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import report_info_loss_phase4 as report
class HoldoutTests(unittest.TestCase):
 def test_gate_case_excluded_cost_retained_missing_bounds(self):
  with tempfile.TemporaryDirectory() as d:
   r=Path(d)
   report.save(r/'manifest.json',{'cases':[{'id':'q004'},{'id':'q009'}]})
   facts=[{'id':'f1','type':'number','distance_rounds':3}]
   for q in ['q004','q009']:report.save(r/'facts'/f'{q}.json',facts)
   rows=[{'case':q,'method':m,'fact_count':1,'qa_exact_correct':1,'qa_by_fact':{'f1':1}} for q in ['q004','q009'] for m in report.METHODS]
   rows[-1]['qa_exact_correct']=None;rows[-1]['qa_by_fact']=None
   report.save(r/'results.json',{'status':'running','records':rows})
   report.save(r/'calls/gate/started.json',{});report.save(r/'calls/gate/response.json',{'usage':{'prompt_tokens':10,'completion_tokens':2,'total_tokens':12}})
   result=report.aggregate(r);self.assertEqual(result['primary_cohort'],['q009']);self.assertEqual(len(result['points']),5);self.assertEqual(result['paired_complete_question_ids'],[])
   self.assertEqual(result['table'][-1]['missing_bounds'],[0,1]);self.assertEqual(result['all_new_usage_including_failed_gates']['calls_started'],1)
if __name__=='__main__':unittest.main()
