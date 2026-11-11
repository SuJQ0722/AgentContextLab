import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from analyze_bc_completed_intersection_v3 import select, paired_scope, check_grade

class BCIntersectionTests(unittest.TestCase):
    def test_wrong_completed_never_replaced(self):
        wrong={'prediction_status':'completed','score':0}
        later={'prediction_status':'completed','score':1}
        self.assertIs(select(wrong,later),wrong)
        self.assertIs(select({'prediction_status':'timeout'},later),later)

    def test_strict_three_repeats_require_every_method_and_grade(self):
        index={method:{(q,r):{'clean_completed':True,'score':int(r!=2)}
            for q in ('a','b') for r in (1,2,3)} for method in ('hermes','dsh')}
        index['dsh'][('b',3)]['score']=None
        scope=paired_scope(index)
        self.assertEqual(scope['slots'],5)
        self.assertEqual(scope['balanced_questions'],['a'])
        self.assertEqual(scope['missing_any_grade_slots'],1)
        self.assertEqual(scope['methods']['hermes']['balanced_avg3']['per_repeat_correct'],[1,0,1])
        self.assertAlmostEqual(scope['methods']['hermes']['balanced_avg3']['mean'],2/3)
        self.assertAlmostEqual(scope['methods']['hermes']['balanced_avg3']['sample_std_ddof1'],(1/3)**.5)

    def test_cross_harness_question_hash_must_match(self):
        index={'a':{('q',1):{'clean_completed':True,'score':1,'question_hash':'one'}},
               'b':{('q',1):{'clean_completed':True,'score':1,'question_hash':'two'}}}
        with self.assertRaisesRegex(ValueError,'question hash mismatch'):paired_scope(index)

    def test_missing_grade_not_counted_as_zero(self):
        row={'prediction_status':'completed','judge_path':None,'score':0}
        check_grade(None,row)
        self.assertIsNone(row['score'])

    def test_grade_sha_mismatch_rejected_even_correct_answer(self):
        class FakeSnapshot:
            def read(self,p): return {'job_id':'j','result_sha256':'wrong','question_sha256':'q','status':'scored','score':1}
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'grade.json';path.write_text('{}')
            row={'prediction_status':'completed','judge_path':str(path),'job_id':'j','result_sha256':'right','question_hash':'q'}
            with self.assertRaisesRegex(ValueError,'Grade binding mismatch'):check_grade(FakeSnapshot(),row)

if __name__=='__main__':unittest.main()
