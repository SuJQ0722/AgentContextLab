import sys
from pathlib import Path
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import judge_rq3_final_six_ops1 as module

class ScopeTests(unittest.TestCase):
    def test_exact_six_and_new_scale_separate(self):
        for label in module.LABELS:self.assertTrue(module.included('hermes/'+label+'/q_001_r01'))
        self.assertFalse(module.included('hermes/scale_0125/q_001_r01'))
        for job in ('hermes/scale_0750/q_001_r01','dsh/scale_0500/q_001_r01','../scale_0500/q'):
            with self.assertRaises(ValueError):module.included(job)
    def test_filter_before_dispatch_and_same_grade_delegate(self):
        candidates=[{'binding':{'job_id':'hermes/'+label+'/q_001_r01'}} for label in ('scale_0125','scale_0500')]
        record={'sources_sha256':{},'campaign_root':str(module.CAMPAIGN.resolve())}
        with patch.object(module.base,'source_inventory',return_value=(candidates,{'ready_completed':2})), patch.object(module.base,'grade',return_value='unchanged') as grade:
            module.install(record)
            rows,info=module.base.source_inventory(module.CAMPAIGN,module.OUTPUT,'cohort')
            self.assertEqual(rows,[candidates[1]]);self.assertEqual(info['excluded_ready_completed'],1)
            self.assertEqual(module.base.grade(rows[0],{},{}),'unchanged');grade.assert_called_once_with(rows[0],{},{})
            with self.assertRaises(ValueError):module.base.grade(candidates[0],{},{})
            self.assertEqual(grade.call_count,1)
    def test_modified_scope_halts_before_inventory(self):
        with patch.object(module.base,'source_inventory') as inventory,patch.object(module.base,'grade'),patch.object(module.base,'sha',return_value='changed'):
            module.install({'sources_sha256':{'file':'expected'},'campaign_root':str(module.CAMPAIGN)})
            with self.assertRaises(ValueError):module.base.source_inventory(module.CAMPAIGN,module.OUTPUT,'c')
            inventory.assert_not_called()

if __name__=='__main__':unittest.main()
