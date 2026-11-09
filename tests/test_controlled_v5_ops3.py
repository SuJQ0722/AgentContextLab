import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch,MagicMock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import controlled_attempts_v5 as selected
import run_controlled_native_v5_trial as trial
import run_controlled_native_v5_ops3 as queue
class Ops3Tests(unittest.TestCase):
 def test_exact_third_selected_and_changed_spec_rejected(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);original=root/'jobs'/selected.AUTHORIZED_JOB;prior=original/'attempt_002';chosen=original/'attempt_003';chosen.mkdir(parents=True);prior.mkdir()
   prefix=root/'prefix.json';prefix.write_text('{}')
   spec={'prefix_path':str(prefix)}
   for p,v in [(root/'plan.json',{}),(root/'experiment.json',{}),(root/'attempt-selection-ops2.json',{}),(original/'spec.json',spec),(prior/'spec.json',spec),(chosen/'spec.json',spec),(original/'result.json',{'status':'failed'}),(prior/'result.json',{'status':'failed'})]:p.write_text(json.dumps(v))
   entry={'original_out':str(original),'selected_out':str(chosen),'prefix_sha256':selected.sha(prefix)}
   for k,p in [('original_result_sha256',original/'result.json'),('original_spec_sha256',original/'spec.json'),('selected_spec_sha256',chosen/'spec.json'),('previous_result_sha256',prior/'result.json'),('previous_spec_sha256',prior/'spec.json'),('old_selection_sha256',root/'attempt-selection-ops2.json')]:entry[k]=selected.sha(p)
   ledger={'version':selected.VERSION,'plan_sha256':selected.sha(root/'plan.json'),'config_sha256':selected.sha(root/'experiment.json'),'entries':{selected.AUTHORIZED_JOB:entry}}
   (root/selected.LEDGER).write_text(json.dumps(ledger));self.assertEqual(selected.selected_out(root,selected.AUTHORIZED_JOB),chosen)
   entry['selected_out']=str(original/'attempt_004');(root/selected.LEDGER).write_text(json.dumps(ledger))
   with self.assertRaises(ValueError):selected.selection(root)
 def test_trial_uses_v5_live_and_never_reexecutes(self):
  with tempfile.TemporaryDirectory() as tmp:
   out=Path(tmp)/'out';spec=Path(tmp)/'spec.json';spec.write_text(json.dumps({'config_path':str(Path(tmp)/'config')}))
   child=MagicMock();child.returncode=0
   with patch.object(trial,'environment',return_value=({},None)),patch.object(trial,'python_for',return_value=sys.executable),patch.object(trial.subprocess,'Popen',return_value=child) as popen,patch.object(trial.signal,'signal'):
    trial.trial(spec,out,'method');argv=popen.call_args.args[0]
    self.assertIn('controlled_native_worker_v5.py',argv[1]);self.assertIn('--live',argv)
    with self.assertRaises(ValueError):trial.trial(spec,out,'method')
    self.assertEqual(popen.call_count,1)
 def test_gate_target_and_explicit_dispatch(self):
  self.assertEqual(queue.target_concurrency({'passed':False}),4)
  self.assertEqual(queue.target_concurrency({'passed':True}),16)
  self.assertEqual(queue.FROZEN_ENTRY.name,'run_controlled_native_v5_trial.py')
if __name__=='__main__':unittest.main()
