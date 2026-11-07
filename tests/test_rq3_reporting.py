import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from report_rq3_campaign import complete_cohort,SCALES

def rows():
    return [dict(scale=s,question_id=f'q{i}',question_hash=f'hash{i}',repeat=r,model='deepseek-v4.1-flash-1017/huoshan/huoshan',score=float(i%2),state='terminal') for s in SCALES for i in range(100) for r in [1,2,3]]
class RQ3ReadinessTests(unittest.TestCase):
    def test_all_seven_matched_100x3_required(self):
        records=rows();self.assertTrue(complete_cohort(records)[0]);self.assertFalse(complete_cohort(records[:-1])[0])
    def test_unknown_grade_and_wrong_content_block_headline(self):
        records=rows();records[0]['score']=None;self.assertFalse(complete_cohort(records)[0])
        records=rows();records[0]['question_hash']='different';self.assertFalse(complete_cohort(records)[0])
    def test_duplicate_repeat_and_mixed_models_rejected(self):
        records=rows();records[0]['repeat']=2;self.assertFalse(complete_cohort(records)[0])
        records=rows();records[0]['model']='gemini';self.assertFalse(complete_cohort(records)[0])
if __name__=='__main__':unittest.main()
