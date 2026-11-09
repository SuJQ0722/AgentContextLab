import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import recover_rq3_pre_native_ops2 as recovery
from report_rq3_parity_v3 import recovery_selection


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.parent=Path(self.tmp.name)/'parent';self.parent.mkdir();self.root=Path(self.tmp.name)/'overlay';self.root.mkdir()
        self.directory=self.parent/'jobs'/recovery.JOB;self.attempt=self.directory/'attempts/attempt_001';self.attempt.mkdir(parents=True)
        (self.directory/'claim').mkdir();(self.parent/'plan.json').write_text('{}');(self.parent/'cohort.jsonl').write_text('cohort')
        self.owner={'controller_id':'old','slot':str(self.parent/'slots/00'),'pid':42,'hostname':'local','boot_id':'boot','pid_namespace':'ns','start_identity':'123'}
        (self.directory/'claim/owner.json').write_text(json.dumps(self.owner));(self.directory/'spec.json').write_text('{}')
        (self.parent/'status-ops1.json').write_text(json.dumps({**self.owner,'stop_dispatch':True,'active_local':0}))
        dispatch={'version':'rq3-parity-v3-dispatch-ops1','scientific_sources_unchanged':True,'model_or_strategy_changed':False,'plan_sha256':recovery.scientific.sha(self.parent/'plan.json')}
        (self.attempt/'dispatch-ops1.json').write_text(json.dumps(dispatch));self.ack=self.parent/'ack.json';self.ack.write_text(json.dumps({**self.owner,'reserved_not_started':recovery.JOB,'stop_dispatch':True}))
        self.entry={'job_id':recovery.JOB,'parent_attempt':str(self.attempt),'retry_attempt':str(self.root/'jobs'/recovery.JOB/'attempts/attempt_001'),
            'parent_spec_sha256':recovery.scientific.sha(self.directory/'spec.json'),'parent_claim_sha256':recovery.scientific.sha(self.directory/'claim/owner.json'),'original_controller':self.owner,'dispatch_declaration_sha256':recovery.scientific.sha(self.attempt/'dispatch-ops1.json'),'stop_ack_path':str(self.ack),'stop_ack_sha256':recovery.scientific.sha(self.ack)}
        self.auth={'version':recovery.VERSION,'parent_root':str(self.parent),'recovery_root':str(self.root),'grading_root':str(self.root/'grading'),
            'parent_plan_sha256':recovery.scientific.sha(self.parent/'plan.json'),'entries':[self.entry], 'max_recovery_native_launches':1,'selection':'fixed'}
    def terminate(self):
        (self.parent/'controller-exit-ops1.json').write_text(json.dumps({**self.owner,'drained':True,'stopped':True}))
        (self.attempt/'result.json').write_text(json.dumps({'job_id':recovery.JOB,'status':'not_started','api_calls':0,'slot_released':True,
            'unconfirmed_child_termination':[],'failure_category':'ops_controller_stopped_before_native_launch'}))
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
    def test_overlay_uses_shared_cloud_slots_and_never_reclaims(self):
        slot=self.parent/'cloud-scale-ops2/slots/scale_0000/15'
        with patch.object(recovery,'acquire_scale_slot',return_value=None):self.assertIsNone(recovery.claim(self.root,self.parent,{},dict(controller_id='new')))
        with patch.object(recovery,'acquire_scale_slot',return_value=slot) as acquire:
            directory,chosen=recovery.claim(self.root,self.parent,{},dict(controller_id='new'))
            self.assertEqual(chosen,slot);self.assertTrue((directory/'claim').exists())
            with self.assertRaisesRegex(ValueError,'already claimed'):recovery.claim(self.root,self.parent,{},dict(controller_id='new'))
            self.assertEqual(acquire.call_count,1)
    def test_fixed_overlay_selected_without_score_choice_and_bound(self):
        (self.root/'plan.json').write_text('{}');(self.root/'cohort.jsonl').write_text('cohort')
        self.auth['recovery_plan_sha256']=recovery.scientific.sha(self.root/'plan.json')
        (self.root/'recovery-authorization.json').write_text(json.dumps(self.auth))
        selected,meta=recovery_selection(self.parent,self.root)
        self.assertEqual(selected[recovery.JOB][0],Path(self.entry['retry_attempt']))
        self.assertFalse(meta['native_never_started_proof_available'])
        (self.directory/'spec.json').write_text('{"changed":true}')
        with self.assertRaisesRegex(ValueError,'evidence changed'):recovery_selection(self.parent,self.root)
    def test_unknown_identity_or_unfinished_drain_does_not_pass(self):
        self.terminate()
        with patch.object(recovery,'owner_alive',return_value=None):self.assertIsNone(recovery.proof(self.auth)[0])
        path=self.parent/'controller-exit-ops1.json';data=json.loads(path.read_text());data['pid_namespace']='different';path.write_text(json.dumps(data))
        with patch.object(recovery,'owner_alive',return_value=False):
            with self.assertRaisesRegex(ValueError,'clean termination'):recovery.proof(self.auth)
    def test_cutover_and_dispatch_sha_are_bound(self):
        self.terminate();self.ack.write_text('{}')
        with patch.object(recovery,'owner_alive',return_value=False):
            with self.assertRaisesRegex(ValueError,'evidence changed'):recovery.proof(self.auth)

if __name__=='__main__':unittest.main()
