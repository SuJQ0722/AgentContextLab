import importlib.util
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location('once_stats',Path(__file__).parents[1]/'scripts/once24h_statistics_v15.py')
s=importlib.util.module_from_spec(spec);spec.loader.exec_module(s)
PRICE={'cached_input_per_million':.15,'non_cache_input_per_million':1.5,'output_per_million':9}


def fixture():
    rows=[];metrics={}
    for method in ('none','visual','summarize'):
        for q in ('q1','q2'):
            for rep in (1,2,3):
                slot=f'{method}:{q}:{rep}'
                rows.append({'slot_id':slot,'benchmark':'bc100','harness':'hermes','method':method,
                             'question_sha256':q,'repeat':rep,'status':'completed_scored','score':int(method=='visual')})
                metrics[slot]={'tokens_complete':True,'complete_tokens':{'cached_input':10,'noncache_input':20,'output':5,'total':35}}
    return rows,metrics


class StatisticsTests(unittest.TestCase):
    def test_primary_cohort_requires_all_methods_and_all_three_repeats(self):
        rows,metrics=fixture();next(r for r in rows if r['slot_id']=='summarize:q2:3')['score']=None
        out=s.analyze(rows,metrics,PRICE,draws=100)
        self.assertEqual({x['all_methods_complete_three_repeats']['questions']for x in out['strict_three_repeat_summaries']},{1})
        pair=next(x for x in out['paired_tests'] if x['baseline']=='none')
        self.assertEqual(pair['question_clusters'],2)
        pair=next(x for x in out['paired_tests'] if x['baseline']=='summarize')
        self.assertEqual(pair['question_clusters'],1)

    def test_cost_both_axes_have_identical_all_method_slots(self):
        rows,metrics=fixture();metrics['summarize:q2:3']['tokens_complete']=False
        out=s.analyze(rows,metrics,PRICE,draws=100);group=out['paired_cost_groups'][0]
        self.assertEqual(group['common_n'],5)
        self.assertEqual({p['n']for p in group['points']},{5})
        self.assertEqual(len(group['common_question_repeat_pairs']),5)
        self.assertEqual({tuple(sorted(p['repeat_denominators'].items()))for p in group['points']},{((1,2),(2,2),(3,1))})

    def test_price_is_three_separate_categories_and_bad_total_rejected(self):
        self.assertAlmostEqual(s.reference_cost({'cached_input':10,'noncache_input':20,'output':5,'total':35},PRICE),.0000765)
        self.assertIsNone(s.reference_cost({'cached_input':10,'noncache_input':20,'output':5,'total':36},PRICE))
        self.assertIsNone(s.reference_cost({'cached_input':None,'noncache_input':20,'output':5,'total':35},PRICE))

    def test_missing_cost_intersection_is_unavailable(self):
        rows,metrics=fixture()
        for k,m in metrics.items():
            if k.startswith('none:'):m['tokens_complete']=False
        group=s.analyze(rows,metrics,PRICE,draws=100)['paired_cost_groups'][0]
        self.assertFalse(group['available']);self.assertEqual(group['points'],[])

    def test_holm_does_not_treat_missing_pairs_as_pzero(self):
        self.assertEqual(s.holm([.01,None,.04,.03]),[.03,None,.06,.06])

    def test_cluster_ci_and_std_keep_three_repeats(self):
        rows,metrics=fixture();out=s.analyze(rows,metrics,PRICE,draws=100)
        item=next(x for x in out['strict_three_repeat_summaries']if x['method']=='visual')['all_methods_complete_three_repeats']
        self.assertEqual(item['repeat_means'],[1,1,1]);self.assertEqual(item['sample_std'],0);self.assertEqual(item['bootstrap95'],[1.,1.])
        self.assertFalse(item['full_100x3'])

    def test_partial_latency_coverage_never_claims_complete_mean(self):
        m=s.observed_metric([{'client_http_seconds':5},{'client_http_seconds':None}],'client_http_seconds')
        self.assertEqual(m['observed_trajectories'],1);self.assertEqual(m['mean_observed'],5);self.assertIsNone(m['complete_cohort_mean'])

if __name__=='__main__':unittest.main()
