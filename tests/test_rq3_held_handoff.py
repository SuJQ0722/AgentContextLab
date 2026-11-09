import sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import handoff_rq3_scale0700_held_ops2 as held
import test_rq3_local_cloud_handoff as fixture

class HeldTests(unittest.TestCase):
    def setUp(self):
        f=fixture.HandoffTests();f.setUp();self.addCleanup(f.doCleanups);self.f=f
        self.status={**f.status,'at':100.,'reserved_not_started':held.JOB};f.write(f.status_path,self.status)
        self.d=f.root/'jobs'/held.JOB;self.a=self.d/'attempts/attempt_001';self.a.mkdir(parents=True)
        self.slot=Path(f.record['shared_slots'])/'12';claim={**f.owner,'job_id':held.JOB,'slot':str(self.slot)};job={'job_id':held.JOB,'question_id':'q_045','repeat':2,'scale':.7,'strategy':'visual','harness':'hermes'}
        f.write(f.root/'plan.json',{'jobs':[job]});spec={**job,'controller_id':f.owner['controller_id'],'slot_path':str(self.slot),'plan_sha256':held.base.sha(f.root/'plan.json')}
        f.write(self.d/'claim/owner.json',claim);f.write(self.d/'claim/spec.json',spec);f.write(self.d/'spec.json',spec);f.write(self.slot/'owner.json',claim);f.write(self.a/'cloud-scale-dispatch-ops2.json',{})
    def test_held_slot_stays_and_archive_allows_other_pending(self):
        before=(self.slot/'owner.json').read_bytes()
        with patch.object(held.time,'time',return_value=101.):ready,state=held.handoff(self.f.record)
        self.assertTrue(ready);self.assertEqual((self.slot/'owner.json').read_bytes(),before);self.assertTrue((self.d/'claim').exists());self.assertTrue((self.f.out/'held-ready.json').exists())
    def test_any_native_evidence_blocks_handoff(self):
        self.f.write(self.a/'worker-started.json',{})
        with self.assertRaisesRegex(ValueError,'execution evidence'):held.held_proof(self.f.record,self.status)
        self.assertTrue(self.f.lease.exists())
    def test_changed_slot_or_other_job_rejected(self):
        with self.assertRaises(ValueError):held.held_proof(self.f.record,{**self.status,'reserved_not_started':'other'})
        self.f.write(self.slot/'owner.json',{'job_id':'wrong'})
        with self.assertRaises(ValueError):held.held_proof(self.f.record,self.status)

if __name__=='__main__':unittest.main()
