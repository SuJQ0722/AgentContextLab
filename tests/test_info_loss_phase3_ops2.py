import sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from info_loss_phase3_ops2 import StopAwareClient,QualityHold,check_hold
class StopGateTests(unittest.TestCase):
 def test_hold_before_request_creates_no_started_marker(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);(root/'quality-hold.json').write_text('{}');client=StopAwareClient.__new__(StopAwareClient);client.out=root
   with self.assertRaises(QualityHold):client.call('new','never sent')
   self.assertFalse((root/'calls').exists())
 def test_stop_marker_is_independent_of_model_or_api(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);check_hold(root);(root/'STOP').touch()
   with self.assertRaises(QualityHold):check_hold(root)
if __name__=='__main__':unittest.main()
