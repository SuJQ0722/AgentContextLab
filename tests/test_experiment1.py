import importlib.util
from pathlib import Path
import unittest
spec=importlib.util.spec_from_file_location('experiment1',Path(__file__).parents[1]/'scripts/rebuild_experiment1.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


class ExperimentOneTests(unittest.TestCase):
    def test_revised_discard_is_not_merged_with_original_cohort(self):
        self.assertEqual(module.labels('preds_archive/bc/gemini-3.5-flash-thinking-discard'),('bc','Discard',False))
        self.assertEqual(module.labels('preds_archive/gemini35_flash_discard/browsecomp_subset_200'),('bc','Discard',True))

    def test_multimodal_ablation_is_not_full_vera(self):
        self.assertEqual(module.labels('preds_archive/to_upload/mmbrowsecomp/gemini-3.5-flash-thinking-vis-text'),('mmbrowsecomp','VERA text-only',False))

    def test_paired_matching_uses_question_content_and_repeat(self):
        def row(method,question,repeat):
            return dict(canonical=True,official_token_usd_estimate=1,score=1,benchmark='bc',method=method,
                        question_hash=question,repeat=repeat)
        # Same nominal question IDs would be unsafe: these content hashes differ.
        rows=[row('Summarize','questionA',1),row('VERA','questionB',1)]
        result,membership,duplicates=module.paired_tables(rows)
        self.assertEqual(result,[]);self.assertEqual(membership,[]);self.assertEqual(duplicates,[])
