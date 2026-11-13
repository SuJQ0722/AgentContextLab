import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import controlled_visual_same_target_v13 as v
class SameTargetTests(unittest.TestCase):
 def target(self):return {'passed':True,'method':'visual','native_identity_verified':True,'final_wire_native_identity_preserved':True,'final_wire_observed':True,'bounded_native_protocol':v.bounded.PROTOCOL,'first_actual_prompt_tokens':10000,'native_hashes':['native'],'prefix_sha256':'prefix'}
 def test_calibration_gate_stops_before_continuation(self):
  gate=v.TargetGate(self.target())
  for count in (None,9799,10201):
   with self.assertRaises(v.bounded.v5.BudgetInfeasible):gate.budget({'method':'visual','canvas_scale':1,'prompt_tokens':count})
  for count in (9800,10000,10200):gate.budget({'method':'visual','canvas_scale':1,'prompt_tokens':count})
 def test_cannot_refit_reference_scale(self):
  with self.assertRaises(v.bounded.v5.BudgetInfeasible):v.TargetGate(self.target()).budget({'method':'visual','canvas_scale':.75,'prompt_tokens':10000})
 def test_actual_violation_marks_sticky_invalid(self):
  gate=v.TargetGate(self.target());state={'passed':True,'first_actual_prompt_tokens':11000}
  with self.assertRaises(v.bounded.v5.BudgetInfeasible):gate.annotate(state)
  self.assertFalse(state['passed']);self.assertEqual(state['fatal_error'],'BudgetInfeasible');gate.annotate(state);self.assertFalse(state['passed'])
 def test_unmeasured_target_refused(self):
  t=self.target();t['first_actual_prompt_tokens']=None
  with self.assertRaises(ValueError):v.TargetGate(t)
if __name__=='__main__':unittest.main()
