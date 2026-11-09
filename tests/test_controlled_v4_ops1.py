import json,os,sys,tempfile,time,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from run_controlled_native_v4_ops1 import (target_concurrency,unpublished_trials,publication_checkpoint,
    verify_old,FROZEN_ENTRY,pidfd_open,pidfd_signal)

class ControlledOpsTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform=='linux','Linux pidfd smoke test')
    def test_native_pidfd_identity_probe_does_not_terminate(self):
        descriptor=pidfd_open(os.getpid())
        try:pidfd_signal(descriptor,0)
        finally:os.close(descriptor)
    def test_target_only_changes_after_strict_gate(self):
        for gate in ({},{'passed':False},{'passed':None},{'passed':1}):self.assertEqual(target_concurrency(gate),4)
        self.assertEqual(target_concurrency({'passed':True}),16)
    def test_publication_barrier_detects_unrecorded_or_wrong_child(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);out=root/'jobs/a';out.mkdir(parents=True)
            snap={123:{'identity':'start-a','argv':['python',str(FROZEN_ENTRY),'--trial','method','--root',str(out)]}}
            self.assertEqual(len(unpublished_trials(root,snap)),1)
            (out/'dispatch.json').write_text(json.dumps({'pid':123,'identity':'wrong'}))
            self.assertEqual(len(unpublished_trials(root,snap)),1)
            (out/'dispatch.json').write_text(json.dumps({'pid':123,'identity':'start-a'}))
            self.assertEqual(unpublished_trials(root,snap),[])
    def test_fresh_coordinator_checkpoint_required_even_if_child_exited(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);p=root/'status.json';p.write_text(json.dumps({'running_slots':0}))
            barrier=time.time_ns()+1_000_000
            self.assertFalse(publication_checkpoint(root,barrier))
            os.utime(p,ns=(barrier+1,barrier+1))
            self.assertTrue(publication_checkpoint(root,barrier))
    def test_wrong_identity_or_trial_can_never_be_signalled(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'coordinator.json').write_text(json.dumps({'pid':123,'identity':'original'}))
            record={'identity':'original','argv':['python',str(FROZEN_ENTRY),'--root',str(root),'--live']}
            self.assertEqual(verify_old(root,123,'original',{123:record})['pid'],123)
            with self.assertRaises(ValueError):verify_old(root,123,'wrong',{123:record})
            record['argv']+=['--trial','method']
            with self.assertRaises(ValueError):verify_old(root,123,'original',{123:record})

if __name__=='__main__':unittest.main()
