import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import controlled_attempts_v4 as retries
class RetryTests(unittest.TestCase):
    def setup_root(self,folder):
        root=Path(folder);base=root/'jobs'/retries.AUTHORIZED_JOB;base.mkdir(parents=True)
        for name,data in [('plan.json',{'jobs':[{'job_id':retries.AUTHORIZED_JOB}]}),('experiment.json',{'model':'test'}),('prefix.json',{'messages':[]})]:
            (root/name).write_text(json.dumps(data))
        spec={'model':'deepseek-v4.1-flash-1017/zijian/sfb','prefix_path':str(root/'prefix.json')}
        for name,data in [('spec.json',spec),('result.json',{'status':'failed','error_type':'APIConnectionError'}),('supervisor.json',{'pid':888,'identity':'old'}),('worker-started.json',{'pid':889})]:
            (base/name).write_text(json.dumps(data))
        return root,base
    @patch.object(retries,'processes',return_value={})
    def test_retry_preserves_original_and_fixed_selection(self,_):
        with tempfile.TemporaryDirectory() as f:
            root,base=self.setup_root(f);original=(base/'result.json').read_bytes()
            entries=retries.prepare_retry(root);self.assertEqual((base/'result.json').read_bytes(),original)
            self.assertEqual(retries.selected_out(root,retries.AUTHORIZED_JOB),base/'attempt_002')
            (base/'attempt_002/result.json').write_text('{"status":"failed"}')
            self.assertEqual(retries.prepare_retry(root),entries)
            self.assertFalse((base/'attempt_003').exists())
    @patch.object(retries,'processes',return_value={888:{'identity':'old','argv':[]}})
    def test_live_old_supervisor_blocks_retry(self,_):
        with tempfile.TemporaryDirectory() as f:
            root,_=self.setup_root(f)
            with self.assertRaises(ValueError):retries.prepare_retry(root)
    @patch.object(retries,'processes',return_value={})
    def test_changed_native_prefix_or_spec_rejected(self,_):
        with tempfile.TemporaryDirectory() as f:
            root,base=self.setup_root(f);retries.prepare_retry(root)
            (root/'prefix.json').write_text('{"changed":true}')
            with self.assertRaises(ValueError):retries.selection(root)
    @patch.object(retries,'processes',return_value={})
    def test_no_retry_for_other_failure(self,_):
        with tempfile.TemporaryDirectory() as f:
            root,base=self.setup_root(f);(base/'result.json').write_text('{"status":"failed","error_type":"BudgetInfeasible"}')
            with self.assertRaises(ValueError):retries.prepare_retry(root)
if __name__=='__main__':unittest.main()
