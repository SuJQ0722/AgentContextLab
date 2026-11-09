from pathlib import Path
import json,sys,tempfile,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import report_bc_v3_scored as stats
from judge_bc_v3_completed import namespace,sha

class ScoredStatsTests(unittest.TestCase):
    def rows(self):
        return [{'harness':h,'method':m,'question_id':f'q_{q:03}','repeat':r,'score':1. if m=='visual' else 0.,
                 'score_reason':'judged_completed','prediction_status':'completed','actual_route':'same-route'}
                for h in ['hermes','dsh'] for m in stats.METHODS for q in range(100) for r in [1,2,3]]
    def test_question_clusters_avg3_sample_std_and_paired_direction(self):
        result=stats.analyze(self.rows(),draws=500)
        vera=next(x for x in result['summary'] if x['harness']=='hermes' and x['method']=='visual')
        self.assertEqual((vera['mean_accuracy'],vera['std_across_three_repeats'],vera['bootstrap95_low']),(1.,0.,1.))
        paired=result['paired_tests'][0];self.assertEqual(paired['question_clusters'],100);self.assertEqual(paired['paired_trajectories'],300)
        self.assertEqual(paired['mean_delta_visual_minus_baseline'],1.);self.assertLess(paired['holm_p_all_eight_comparisons'],.05)
    def test_missing_is_not_zero_and_no_p_value_until_complete(self):
        rows=self.rows();row=next(r for r in rows if r['harness']=='hermes' and r['method']=='visual');row['score']=None;row['score_reason']='judge_error'
        result=stats.analyze(rows,draws=100);vera=next(x for x in result['summary'] if x['harness']=='hermes' and x['method']=='visual')
        self.assertFalse(vera['avg3_ready']);self.assertIsNone(vera['mean_accuracy']);self.assertEqual(vera['missing_outcomes'],1)
        self.assertAlmostEqual(vera['accuracy_lower_bound'],299/300);self.assertEqual(vera['accuracy_upper_bound'],1)
        self.assertTrue(all(not r['ready'] for r in result['paired_tests'] if r['harness']=='hermes'))
        self.assertFalse(any('holm_p_all_eight_comparisons' in r for r in result['paired_tests']))
    def test_duplicate_cannot_become_an_extra_seed(self):
        rows=self.rows();rows.append(rows[0].copy())
        with self.assertRaisesRegex(ValueError,'Duplicate'):stats.analyze(rows,draws=10)
    def test_grade_namespace_and_source_hash_are_bound(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'campaign';grading=Path(directory)/'grading';job={'job_id':'hermes/visual/q001_r01','harness':'hermes','strategy':'visual','question_id':'q001','question':'Q','repeat':1}
            attempt=root/'jobs'/job['job_id']/'attempts/attempt_001';attempt.mkdir(parents=True)
            result=attempt/'result.json';result.write_text(json.dumps({'status':'completed','model':'route'}))
            grade=grading/'sources'/namespace(root)/'jobs'/job['job_id']/'grade.json';grade.parent.mkdir(parents=True)
            grade.write_text(json.dumps({'status':'scored','score':1,'result_sha256':sha(result),'attempt_path':str(attempt)}))
            self.assertEqual(stats.observation(job,attempt,grading)['score'],1)
            result.write_text(json.dumps({'status':'completed','model':'changed'}))
            self.assertEqual(stats.observation(job,attempt,grading)['score_reason'],'grade_source_mismatch')

if __name__=='__main__':unittest.main()
