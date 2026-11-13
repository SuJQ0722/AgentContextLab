import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

SPEC=importlib.util.spec_from_file_location('once_report',Path(__file__).parents[1]/'scripts/report_once24h_v15.py')
m=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(m)


class ReportingTests(unittest.TestCase):
    def test_earliest_completed_not_best_answer(self):
        early={'status':'completed','identity_valid':True,'cleanup_confirmed':True,'finished_unix':1,'result_path':'early','score':0}
        later={**early,'finished_unix':2,'result_path':'later','score':1}
        self.assertEqual(m.choose_completed([later,early])['result_path'],'early')
        self.assertIsNone(m.choose_completed([{**early,'cleanup_confirmed':False}]))

    def test_grade_requires_result_question_repeat_binding(self):
        grade={'status':'scored','score':0,'result_sha256':'r','question_sha256':'q','repeat':2}
        self.assertTrue(m.matching_grade(grade,'r','q',2))
        for args in [('different','q',2),('r','different',2),('r','q',3)]:
            self.assertFalse(m.matching_grade(grade,*args))
        self.assertFalse(m.matching_grade({**grade,'repeat':None},'r','q',2))

    def test_incomplete_repeat_is_not_complete_avg3(self):
        rows=[{'repeat':1,'score':1},{'repeat':1,'score':0},{'repeat':2,'score':1},{'repeat':3,'score':None}]
        s=m.repeat_statistics(rows)
        self.assertEqual([r['valid_n']for r in s['repeats']],[2,1,0])
        self.assertIsNone(s['mean']);self.assertIsNone(s['sample_std'])
        rows[-1]['score']=0
        self.assertEqual(m.repeat_statistics(rows)['mean'],.5)

    def test_replay_paths_deduplicate_same_attempt_only(self):
        self.assertFalse(m.replay_flags(['a'],['a'])['replay_detected'])
        self.assertTrue(m.replay_flags(['b'],['a'])['replay_detected'])

    def test_system_timeout_not_zero_filled(self):
        reporter=m.Reporter.__new__(m.Reporter);reporter.new={}
        slot={'slot_id':'s','benchmark':'bc','harness':'dsh','method':'visual','question_id':'q','repeat':1,
              'latest_known_result':{'path':'old','sha256':'h'}}
        reporter.result=Mock(return_value={'status':'timeout','identity_valid':True,'cleanup_confirmed':True,'failure_category':'timeout','finished_unix':1,'result_path':'old','result_sha256':'h'})
        row=reporter.observe(slot)
        self.assertEqual(row['status'],'timeout_unresolved');self.assertIsNone(row['score']);self.assertIsNone(row['task_valid_score'])
        reporter.result.return_value.update(status='failed',failure_category='output_limit')
        row=reporter.observe(slot)
        self.assertEqual(row['status'],'task_budget_failed');self.assertIsNone(row['score']);self.assertEqual(row['task_valid_score'],0)

    def test_missing_cell_cost_is_unknown_not_zero(self):
        reporter=m.Reporter.__new__(m.Reporter)
        reporter.mapping={'grading_root':'/tmp/grading'};reporter.hashes={'/tmp/grading/resources.json':'h'};reporter.bound_sources={'baseline':'ledger'}
        reporter.slots={'a':{'benchmark':'bc','harness':'dsh','method':'visual'},'b':{'benchmark':'bc','harness':'dsh','method':'visual'}}
        reporter.new={'a':{'cell':'one','slot_id':'a'},'b':{'cell':'two','slot_id':'b'}}
        reporter.read=Mock(return_value={'cells':{'one':{'unknown_usage_attempts':1,'new_prediction_all_attempts':{'fields':{
            'total':{'known_subtotal':100,'missing_count':1,'complete_total':None},
            'output':{'known_subtotal':20,'missing_count':0,'complete_total':20}}}}}})
        groups={('bc','dsh','visual'): {}}
        reporter.resources(groups);cost=groups[('bc','dsh','visual')]['new_pass_tokens']
        self.assertEqual(cost['missing_cells'],['two']);self.assertIsNone(cost['fields']['output']['complete_total'])
        self.assertEqual(cost['fields']['total']['known_subtotal'],100)

    def test_bad_single_result_quarantined_not_silently_dropped(self):
        reporter=m.Reporter.__new__(m.Reporter);reporter.errors=[];reporter.observe=Mock(side_effect=ValueError('changed'))
        slot=dict(slot_id='s',benchmark='bc',harness='dsh',method='visual',question_id='q',repeat=1)
        row=reporter.safe_observe(slot)
        self.assertEqual(row['status'],'read_quarantined');self.assertIsNone(row['score']);self.assertEqual(len(reporter.errors),1)

if __name__=='__main__':unittest.main()
