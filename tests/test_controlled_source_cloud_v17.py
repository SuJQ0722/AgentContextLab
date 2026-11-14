import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from judge_controlled_source_v20 import valid_control
from report_mmbc_timeout_overlay_v18 import cost_scope
from provision_controlled_source_v21 import template_value

class Eligibility(unittest.TestCase):
    def setUp(self):
        self.target={'source_first_post_prompt_tokens':20000,'prefix_sha256':'p','baseline_native_hashes':['img1']}
        self.control={'passed':True,'native_identity_verified':True,'final_wire_native_identity_preserved':True,
            'image_token_parity_claimed':False,'prefix_sha256':'p','native_hashes':['img1'],'first_actual_prompt_tokens':20000}
    def test_real_target_above_old_16k_cap(self):self.assertTrue(valid_control(self.control,self.target))
    def test_total_budget_boundary(self):
        for n,expected in [(19600,True),(20400,True),(19599,False),(20401,False),(None,False)]:
            with self.subTest(n=n):self.assertEqual(valid_control({**self.control,'first_actual_prompt_tokens':n},self.target),expected)
    def test_native_mismatch_never_grade(self):
        self.assertFalse(valid_control({**self.control,'native_hashes':['other']},self.target))
        self.assertFalse(valid_control({**self.control,'final_wire_native_identity_preserved':False},self.target))
    def test_missing_and_false_gate(self):
        self.assertFalse(valid_control({},self.target));self.assertFalse(valid_control({**self.control,'passed':False},self.target))
    def test_no_image_token_parity_claim(self):self.assertFalse(valid_control({**self.control,'image_token_parity_claimed':True},self.target))

class CostPartition(unittest.TestCase):
    def classify(self,job,definition):
        with tempfile.TemporaryDirectory()as td:
            root=Path(td);job={'job_id':'hermes/visual/q_r01','harness':'hermes','strategy':'visual',**job}
            (root/'plan.json').write_text(json.dumps({'jobs':[job],'definition':definition}))
            result=root/'jobs'/job['job_id']/'attempts/attempt_001/result.json';result.parent.mkdir(parents=True)
            return cost_scope({'attempt_path':str(result.parent),'result_path':str(result)})
    def test_controlled_wins_over_core_looking_path(self):
        scope,proof=self.classify({'experiment_kind':'controlled','benchmark':'mmbc100'},{'cell':'mmbc_vera'})
        self.assertEqual(scope,'controlled');self.assertEqual(proof['experiment_kind'],'controlled')
    def test_original_core_execution_version(self):
        self.assertEqual(self.classify({},{'execution_version':'mmbc100-hermes-deepseek-v1'})[0],'core_vera')
    def test_unclassified_not_charged_to_core(self):self.assertEqual(self.classify({},{})[0],'other_or_unclassified')

class Resources(unittest.TestCase):
    def test_exact_8cpu32g_private_image_mount(self):
        v=template_value();c=v['template']['containers'][0]
        self.assertEqual(c['resource_request'],{'cpu':'8','memory':'32GiB'})
        self.assertEqual(c['volume_mounts'][0]['mount_path'],'/mnt/afs_agents')
        self.assertEqual(c['env'],[])

if __name__=='__main__':unittest.main()
