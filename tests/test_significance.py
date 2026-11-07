import importlib.util
from pathlib import Path
import unittest
import numpy as np
spec=importlib.util.spec_from_file_location('significance',Path(__file__).resolve().parents[1]/'scripts/analyze_significance.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class SignificanceTests(unittest.TestCase):
    def test_identical_pairs_are_not_significant(self):
        self.assertEqual(m.paired_test([0,0,0],np.random.default_rng(1),100),1)
        self.assertEqual(m.interval([.5]*4,np.random.default_rng(1),100),[.5,.5])
    def test_holm_monotonic_and_bounded(self):
        self.assertEqual(m.holm([.03,.01,.8]),[.06,.03,.8])
    def test_missing_scores_do_not_become_failures_and_models_separate(self):
        rows=[]
        for model in ['gemini','deepseek']:
            for method in ['VERA','Discard']:
                for q in ['a','b']:
                    for rep in ['1','2']:
                        rows.append(dict(model=model,method=method,benchmark='bc',canonical=True,
                            question_hash=q,question_id=q,repeat=rep,score=1,source_path='x'))
        rows[0]['score']=None
        out=m.analyze(rows,draws=100)
        self.assertEqual(len(out['summary']),4)
        gem=[r for r in out['summary'] if r['model']=='gemini']
        self.assertTrue(all(r['balanced_questions']==1 and r['mean_score']==1 for r in gem))
        self.assertEqual(sum(r['action']=='grade_existing_or_inspect' for r in out['avg3_gaps']),1)
    def test_duplicate_export_excluded(self):
        row=dict(method='VERA',question_hash='a',repeat='1')
        ix,dups=m.index_rows([row,row])
        self.assertEqual(ix,{})
        self.assertEqual(len(dups),1)

    def test_same_model_harnesses_are_not_pooled(self):
        rows=[]
        for harness in ['dsh','hermes']:
            for method in ['VERA','Discard']:
                rows.append(dict(model='deepseek',harness=harness,method=method,benchmark='bc',canonical=True,
                    question_hash='q',question_id='q',repeat='1',score=1 if harness=='dsh' else 0,source_path='x'))
        out=m.analyze(rows,draws=100)
        self.assertEqual(len(out['summary']),4)
        self.assertEqual({r['mean_score'] for r in out['summary'] if r['harness']=='dsh'},{1})
        self.assertEqual({r['mean_score'] for r in out['summary'] if r['harness']=='hermes'},{0})
