import json,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import handoff_rq3_scale0700_local_cloud_ops1 as h

class HandoffTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup);self.root=Path(t.name);self.out=h.directory(self.root);self.out.mkdir(parents=True)
        self.owner={'hostname':'local','boot_id':'boot','pid_namespace':'ns','pid':42,'start_identity':'start','controller_id':'localid'}
        self.lease=h.pending.area(self.root)/'leases/scale_0700';self.lease.mkdir(parents=True)
        self.status_path=self.root/'status.json';self.write(self.lease/'owner.json',self.owner);self.write(self.lease/'runtime.json',{'directory':'same-old'})
        self.status={**self.owner,'at':100.,'active_local':16,'stop_dispatch':True,'reserved_not_started':None};self.write(self.status_path,self.status)
        self.record={'root':str(self.root),'owner':self.owner,'requested_at_unix':99.,'old_status_path':str(self.status_path),'lease_path':str(self.lease),
            'lease_owner_sha256':h.sha(self.lease/'owner.json'),'lease_runtime_sha256':h.sha(self.lease/'runtime.json'),'shared_slots':str(h.pending.area(self.root)/'slots/scale_0700')}
        self.write(self.out/'request.json',self.record)
        for i in range(16):self.write(Path(self.record['shared_slots'])/f'{i:02}'/'owner.json',{'job_id':str(i)})
        patcher=patch.object(h,'verify_request');patcher.start();self.addCleanup(patcher.stop)
    def write(self,p,d):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(d))
    def test_live_children_handoff_preserves16slots_and_archives_whole_lease(self):
        before={str(p):p.read_bytes() for p in Path(self.record['shared_slots']).glob('*/owner.json')};ready,state=h.archive_lease(self.record,now=101.)
        self.assertEqual(state,'ready');self.assertEqual(ready['old_active_at_ack'],16);self.assertFalse(self.lease.exists());self.assertTrue((self.out/'archived-lease/runtime.json').exists())
        self.assertEqual(before,{str(p):p.read_bytes() for p in Path(self.record['shared_slots']).glob('*/owner.json')})
        self.assertFalse(ready['native_interrupted']);self.assertFalse(ready['retry15_touched'])
    def test_reserved_spec_or_missing_ack_or_stale_never_releases_lease(self):
        for changes in [{'reserved_not_started':'some-job'},{'stop_dispatch':False},{'at':0.}]:
            self.write(self.status_path,{**self.status,**changes});ready,_=h.archive_lease(self.record,now=101.)
            self.assertIsNone(ready);self.assertTrue(self.lease.exists())
    def test_changed_identity_rejected(self):
        self.write(self.status_path,{**self.status,'pid':43})
        with self.assertRaises(ValueError):h.archive_lease(self.record,now=101.)
        self.assertTrue(self.lease.exists())
    def test_completed_handoff_never_steals_successor_lease(self):
        h.archive_lease(self.record,now=101.);self.write(self.lease/'owner.json',{'controller_id':'cloud'})
        _,state=h.archive_lease(self.record,now=102.);self.assertEqual(state,'already_ready_no_second_handoff');self.assertEqual(h.read(self.lease/'owner.json'),{'controller_id':'cloud'})
    def test_only_exact_controller_signalled_once(self):
        calls=[];verified=[]
        h.signal_dispatcher(self.record,kill=lambda pid,s:calls.append((pid,s)),verifier=lambda r,o:verified.append(o))
        h.signal_dispatcher(self.record,kill=lambda pid,s:calls.append((pid,s)),verifier=lambda r,o:verified.append(o))
        self.assertEqual(len(calls),1);self.assertEqual(calls[0][0],42);self.assertEqual(len(verified),1)

if __name__=='__main__':unittest.main()
