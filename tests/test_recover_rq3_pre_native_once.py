import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import recover_rq3_pre_native_once as recovery
from report_rq3_parity_v3 import recovery_selection

class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.parent=Path(self.tmp.name)/'parent';self.parent.mkdir();self.root=Path(self.tmp.name)/'overlay';self.root.mkdir()
        self.directory=self.parent/'jobs'/recovery.JOB;self.attempt=self.directory/'attempts/attempt_001';self.attempt.mkdir(parents=True)
        (self.directory/'claim').mkdir();(self.parent/'plan.json').write_text('{}');(self.parent/'cohort.jsonl').write_text('cohort')
        self.owner={'controller_id':'old','slot':str(self.parent/'slots/00'),'pid':42}
        (self.directory/'claim/owner.json').write_text(json.dumps(self.owner));(self.directory/'spec.json').write_text('{}')
        (self.parent/'status.json').write_text(json.dumps({'controller_id':'old','stop_dispatch':True}))
        self.entry={'job_id':recovery.JOB,'parent_attempt':str(self.attempt),'retry_attempt':str(self.root/'jobs'/recovery.JOB/'attempts/attempt_001'),
            'parent_spec_sha256':recovery.scientific.sha(self.directory/'spec.json'),'parent_claim_sha256':recovery.scientific.sha(self.directory/'claim/owner.json'),'original_controller':self.owner}
        self.auth={'version':recovery.VERSION,'parent_root':str(self.parent),'recovery_root':str(self.root),'grading_root':str(self.root/'grading'),
            'parent_plan_sha256':recovery.scientific.sha(self.parent/'plan.json'),'entries':[self.entry], 'max_recovery_native_launches':1,'selection':'fixed'}
    def terminate(self):
        (self.parent/'controller-exit.json').write_text(json.dumps({'controller_id':'old','drained':True,'stopped':True}))
        (self.attempt/'result.json').write_text(json.dumps({'job_id':recovery.JOB,'status':'not_started','api_calls':0,'slot_released':True,
            'unconfirmed_child_termination':[],'failure_category':'controller_stopped_before_native_launch'}))
    def test_waits_for_exact_exit_and_explicit_no_api_result(self):
        with patch.object(recovery,'owner_alive',return_value=True):self.assertIsNone(recovery.proof(self.auth)[0])
        with patch.object(recovery,'owner_alive',return_value=False):
            self.assertIsNone(recovery.proof(self.auth)[0]);self.terminate()
            evidence,state=recovery.proof(self.auth);self.assertEqual(state,'ready');self.assertTrue(evidence['original_native_never_started'])
    def test_any_native_evidence_or_paid_status_blocks(self):
        self.terminate();(self.attempt/'worker-started.json').write_text('{}')
        with patch.object(recovery,'owner_alive',return_value=False):
            with self.assertRaisesRegex(ValueError,'native/worker'):recovery.proof(self.auth)
            (self.attempt/'worker-started.json').unlink();data=json.loads((self.attempt/'result.json').read_text());data['status']='completed';(self.attempt/'result.json').write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError,'never-started'):recovery.proof(self.auth)
    def test_overlay_uses_same_shared_16_slots_and_never_reclaims(self):
        slots=self.parent/'cells/hermes/visual/slots';slots.mkdir(parents=True)
        for n in range(16):(slots/f'{n:02}').mkdir()
        self.assertIsNone(recovery.claim(self.root,self.parent,{},dict(controller_id='new')))
        (slots/'15').rmdir();directory,slot=recovery.claim(self.root,self.parent,{},dict(controller_id='new'))
        self.assertEqual(slot,slots/'15');self.assertTrue((directory/'claim').exists())
        with self.assertRaisesRegex(ValueError,'already claimed'):recovery.claim(self.root,self.parent,{},dict(controller_id='new'))
    def test_fixed_selection_does_not_require_better_or_even_completed_result(self):
        (self.root/'plan.json').write_text('{}');(self.root/'cohort.jsonl').write_text('cohort')
        self.auth['recovery_plan_sha256']=recovery.scientific.sha(self.root/'plan.json')
        (self.root/'recovery-authorization.json').write_text(json.dumps(self.auth))
        selected,meta=recovery_selection(self.parent,self.root)
        self.assertEqual(selected[recovery.JOB][0],Path(self.entry['retry_attempt']));self.assertFalse(meta['native_never_started_proof_available'])

if __name__=='__main__':unittest.main()
