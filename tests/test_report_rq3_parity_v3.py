from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from report_rq3_parity_v3 import analyze,SCALES

class RQ3ReportTests(unittest.TestCase):
    def rows(self):
        return [{'scale':s,'question_id':f'q{i:03}','repeat':r,'score':float(i<(70 if s==1 else 50)),
                 'prediction_status':'completed','score_reason':'judged_completed','compression_count':int(i%2==0)}
                for s in SCALES for i in range(100) for r in [1,2,3]]
    def test_paired_clusters_and_holm(self):
        result=analyze(self.rows(),draws=100)
        self.assertTrue(all(x['avg3_ready'] for x in result['summary']))
        self.assertEqual(result['summary'][-1]['mean_accuracy'],.7)
        for p in result['paired_tests']:
            self.assertAlmostEqual(p['mean_delta_scale_minus_1x'],-.2)
            self.assertEqual(p['question_clusters'],100);self.assertIn('holm_p_six_comparisons',p)
    def test_missing_does_not_become_wrong_or_publish_p(self):
        rows=self.rows();rows[0]['score']=None
        result=analyze(rows,draws=100)
        self.assertFalse(result['summary'][0]['avg3_ready']);self.assertFalse(result['paired_tests'][0]['ready'])
        self.assertTrue(all('holm_p_six_comparisons' not in p for p in result['paired_tests']))
    def test_duplicate_fails(self):
        rows=self.rows()
        with self.assertRaisesRegex(ValueError,'Duplicate'):analyze(rows+[rows[0]],draws=10)

if __name__=='__main__':unittest.main()
