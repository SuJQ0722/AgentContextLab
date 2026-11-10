import sys,unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import bootstrap_visual_hosted_ops2 as boot
import run_visual_hosted_retry_ops2 as run
import provision_visual_hosted_ops2 as provision

class ReadinessTests(unittest.TestCase):
 def test_controller_retries_only_failed_preflight(self):
  with TemporaryDirectory()as d:
   results=[{'passed':False},{'passed':True}]
   with patch.object(run.readiness,'preflight',side_effect=results)as probe,patch.object(run.time,'sleep'),patch.object(run.controller,'main',side_effect=lambda:run.readiness.preflight(d,{})):
    run.main();self.assertEqual(probe.call_count,2)
 def test_bootstrap_retries_only_web_readiness(self):
  original=boot.bootstrap.base.checked
  def main():
   boot.bootstrap.base.checked(['python','preflight_bc_v3_web.py'])
  with patch.object(boot.bootstrap.base,'checked',side_effect=[RuntimeError(),0])as probe,patch.object(boot.bootstrap,'main',side_effect=main),patch.object(boot.time,'sleep'):
   boot.main();self.assertEqual(probe.call_count,2)
  self.assertIs(boot.bootstrap.base.checked,original)
 def test_bootstrap_does_not_retry_prediction(self):
  def main():boot.bootstrap.base.checked(['python','paid_worker.py'])
  with patch.object(boot.bootstrap.base,'checked',side_effect=RuntimeError())as probe,patch.object(boot.bootstrap,'main',side_effect=main),patch.object(boot.time,'sleep'):
   with self.assertRaises(RuntimeError):boot.main()
   self.assertEqual(probe.call_count,1)
 def test_no_controlled_cells_in_ops2(self):
  self.assertEqual(len(provision.CELLS),5)
  self.assertFalse(any(x.startswith('controlled')for x in provision.CELLS))
if __name__=='__main__':unittest.main()
