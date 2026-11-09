import json,os,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import report_info_loss_phase3 as report

class DescriptiveReportTests(unittest.TestCase):
    def test_missing_qa_and_semantic_are_not_zero_filled(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'facts').mkdir()
            (root/'facts/q_001.json').write_text(json.dumps([{'id':'f1','type':'number','position':0,'distance_rounds':20},{'id':'f2','type':'url','position':2,'distance_rounds':0}]))
            (root/'results.json').write_text(json.dumps({'status':'running','updated_at':'now','paired_complete_cases':[],
                'records':[{'case':'q_001','method':'canvas_1','qa_by_fact':{'f1':1,'f2':0},'semantic_judge':None},
                  {'case':'q_001','method':'canvas_0.5','qa_by_fact':None,'semantic_judge':{'f1':{'supported':False},'f2':{'supported':True}}}]}))
            data=report.aggregate(root)
            full=next(g for g in data['groups'] if g['method']=='canvas_1' and g['distance_bucket']=='all')
            half=next(g for g in data['groups'] if g['method']=='canvas_0.5' and g['distance_bucket']=='all')
            self.assertEqual(full['qa_exact']['accuracy'],.5)
            self.assertIsNone(full['semantic_supported']['accuracy'])
            self.assertIsNone(half['qa_exact']['accuracy'])
            self.assertEqual(half['semantic_supported']['accuracy'],.5)
            self.assertEqual(data['paired_question_ids'],[])
            self.assertEqual(full['source_questions'],1)
    def test_live_status_counts_inflight_separately_from_missing_returned_usage(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for name in ['a','b']:
                out=root/'calls'/name;out.mkdir(parents=True);(out/'started.json').write_text('{}')
            (root/'calls/a/response.json').write_text(json.dumps({'usage':{'prompt_tokens':10,'completion_tokens':2,'total_tokens':12}}))
            (root/'running.json').write_text(json.dumps({'pid':os.getpid(),'concurrency':1}))
            (root/'results.json').write_text(json.dumps({'status':'running','updated_at':'old_condition_report','records':[]}))
            value=report.live_status(root)
            self.assertEqual((value['calls_started'],value['calls_returned'],value['in_flight_or_unknown']),(2,1,1))
            self.assertEqual(value['usage']['cached_missing_returned_calls'],1)
            self.assertEqual(value['usage']['usage_in_flight_unknown'],1)
            self.assertIsNone(value['usage']['full_cached_input_tokens'])
            self.assertTrue(value['worker_alive'])
            (root/'quality-hold.json').write_text('{"status":"quality_hold"}')
            held=report.live_status(root)
            self.assertEqual(held['study_status'],'quality_hold')
            self.assertEqual(held['in_flight_or_unknown'],1)
    def test_age_boundaries(self):
        self.assertEqual([report.agebin(x) for x in [0,1,5,6,15,16]],['0','1-5','1-5','6-15','6-15','16+'])

if __name__=='__main__':unittest.main()
