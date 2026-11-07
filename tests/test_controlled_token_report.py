import importlib.util,json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from report_controlled_native_v2 import report
class ControlledTokenReportTests(unittest.TestCase):
 def test_inflight_only_and_auxiliary_are_separate(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);m=root/'jobs/mm/q_1/visual/metrics';m.mkdir(parents=True)
   (m/'call-starts.jsonl').write_text(json.dumps({'call_id':'pending','purpose':'agent'})+'\n'+json.dumps({'call_id':'probe','purpose':'budget_calibration'})+'\n')
   r=report(root);self.assertEqual(len(r['rows']),2)
   self.assertTrue(all(x['usage']['usage_in_flight_unknown']==1 for x in r['rows']))
   (m/'calls.jsonl').write_text(json.dumps({'call_id':'probe','purpose':'budget_calibration','raw_provider_usage':{'prompt_tokens':100,'completion_tokens':2,'total_tokens':102,'prompt_tokens_details':{'cached_tokens':60}}})+'\n')
   r=report(root);u=next(x['usage'] for x in r['rows'] if x['purpose']=='budget_calibration')
   self.assertEqual(u['known_noncache_input_tokens'],40);self.assertEqual(u['cached_input_tokens_known'],60)
   self.assertEqual(u['total_tokens_reported_known'],102)
   self.assertEqual(next(x['usage'] for x in r['rows'] if x['purpose']=='agent')['usage_in_flight_unknown'],1)
