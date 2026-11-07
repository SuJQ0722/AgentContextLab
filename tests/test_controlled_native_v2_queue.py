import sys,tempfile,json,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from run_controlled_native_v2 import pilot_gate,active,freeze_inputs,verify_inputs,DATASETS,METHODS

def good():
 return [{'dataset':d,'method':m,'status':'completed','control_gate':{'first_actual_prompt_tokens':16000,'prefix_sha256':d,'native_hashes':['image'],'passed':True,'native_identity_verified':True}} for d in DATASETS for m in METHODS]
class QueueTests(unittest.TestCase):
 def test_all_six_three_way_realized_budget_gate(self):
  rows=good();self.assertTrue(pilot_gate(rows)['passed']);self.assertFalse(pilot_gate(rows[:-1])['passed'])
  rows[0]['control_gate']['first_actual_prompt_tokens']=8000;self.assertFalse(pilot_gate(rows)['passed'])
 def test_unknown_usage_native_and_prefix_change_block(self):
  for key,value in [('first_actual_prompt_tokens',None),('native_hashes',['different']),('prefix_sha256','different')]:
   rows=good();rows[0]['control_gate'][key]=value;self.assertFalse(pilot_gate(rows)['passed'])
 def test_dispatch_identity_covers_before_supervisor_created(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t);(p/'dispatch.json').write_text(json.dumps({'pid':123,'identity':'start'}))
   with patch('run_controlled_native_v2.process_identity',return_value='start'):self.assertTrue(active(p))
   with patch('run_controlled_native_v2.process_identity',return_value=None):self.assertFalse(active(p))
 def test_changed_input_blocks_resume(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t);(p/'plan.json').write_text('{}');(p/'experiment.json').write_text('{}');freeze_inputs(p);verify_inputs(p)
   (p/'plan.json').write_text('{"changed":true}')
   with self.assertRaises(ValueError):verify_inputs(p)
if __name__=='__main__':unittest.main()
