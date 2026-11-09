import json,os,sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from test_rq3_scale_cloud_ops2 import CloudScaleTests
import run_rq3_scale_cloud_ops2 as old
import run_rq3_scale0700_resume_ops5 as ops
import bootstrap_rq3_scale0700_resume_ops5 as bootstrap
from types import SimpleNamespace

class ResumeTests(unittest.TestCase):
    def setUp(self):
        fixture=CloudScaleTests();fixture.setUp();self.addCleanup(fixture.doCleanups);self.root=fixture.root;self.plan=fixture.plan
        self.owner={**fixture.owner,'hostname':ops.OLD_HOST,'controller_id':'predecessor'}
        for name in ('area','VERSION','jobs_for_scale','verify_cutover','publish_claim'):
            p=patch.object(old,name,getattr(old,name));p.start();self.addCleanup(p.stop)
        self.jobs=old.jobs_for_scale(self.plan,.7)
        lease=self.root/'cloud-scale-ops2/leases/scale_0700';lease.mkdir(parents=True)
        run=self.root/'cloud-scale-ops2/controllers/scale_0700/predecessor';run.mkdir(parents=True)
        self.write(lease/'owner.json',self.owner);self.write(lease/'runtime.json',{'directory':str(run)})
        self.write(run/'status.json',{**self.owner,'stop_dispatch':True});self.write(run/'maintenance.json',{})
        for i,j in enumerate(self.jobs[:81]):
            d=self.root/'jobs'/j['job_id'];a=d/'attempts/attempt_001';a.mkdir(parents=True)
            if i<66:self.write(a/'result.json',{'status':'completed','slot_released':True,'unconfirmed_child_termination':[]});continue
            slot=self.root/f'cloud-scale-ops2/slots/scale_0700/{i-66:02}';slot.mkdir(parents=True)
            claim={**self.owner,'job_id':j['job_id'],'slot':str(slot)};self.write(slot/'owner.json',claim);self.write(d/'claim/owner.json',claim)
            self.write(d/'claim/spec.json',j);self.write(d/'spec.json',j);self.write(a/'worker-started.json',{});self.write(a/'heartbeat.json',{})
            self.write(a/'native/metrics/call-starts.jsonl',{'call_id':'paid'})
        self.describe=self.root/'describe.json';self.workers=self.root/'workers.json'
        self.write(self.describe,{'at':'2026-11-09T08:40:00Z','returncode':0,'stdout':json.dumps({'name':ops.OLD_NAME,'uid':ops.OLD_UID,'state':'SUSPENDED','workspace_name':'rl'})})
        self.write(self.workers,{'at':'2026-11-09T08:40:01Z','returncode':0,'stdout':'| WORKER_NAME | RESOURCE | HOST_IP | POD_IP | PHASE |\n| '+ops.OLD_HOST+' | CPU | oldhost | oldpod | Deleted |\n| | continuation | | | |'})
    def write(self,p,d):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(d))
    def prepared(self):return ops.prepare(self.root,self.describe,self.workers)
    def test_exact219_only_preserves15_paid_and_old_lease(self):
        a=self.prepared();self.assertEqual(len(a['pending_job_ids']),219);self.assertEqual(len(a['excluded_paid_interrupted_job_ids']),15)
        self.assertEqual(ops.verify_authorization(self.root),a)
        for record in a['predecessor_files']:self.assertEqual(Path(record['original']).read_bytes(),Path(record['archive']).read_bytes())
        self.assertEqual(old.scientific.read(self.root/'cloud-scale-ops2/leases/scale_0700/owner.json'),self.owner)
    def test_running_or_other_worker_never_qualifies(self):
        d=ops.read(self.workers);d['stdout']=d['stdout'].replace('Deleted','Running');self.write(self.workers,d)
        with self.assertRaisesRegex(ValueError,'Deleted'):self.prepared()
        d['stdout']=d['stdout'].replace('Running','Deleted')+'\n| other-worker | CPU | | | Deleted |';self.write(self.workers,d)
        with self.assertRaises(ValueError):self.prepared()
    def test_new16slots_ignore_terminated_old15_and_release_compatible(self):
        a=self.prepared();ops.install(self.root,ops.authorization_path(self.root));owner={**self.owner,'controller_id':'new'}
        selected=old.jobs_for_scale(self.plan,.7);self.assertEqual(len(selected),219)
        claims=[old.publish_claim(self.root,j,owner,.7) for j in selected[:16]]
        self.assertTrue(all(claims));self.assertIsNone(old.publish_claim(self.root,selected[16],owner,.7))
        self.assertEqual(len(list((self.root/'cloud-scale-ops2/slots/scale_0700').glob('*/owner.json'))),15)
        directory,slot,attempt,spec=claims[0];self.assertIn('cloud-scale-ops5',str(slot));old.verify_published(spec,directory);old.scientific.validate_trial(spec,attempt)
        self.assertEqual(spec['strategy'],'visual');old.release_slot(slot);self.assertFalse(slot.exists())
        self.assertIsNone(old.publish_claim(self.root,selected[0],owner,.7))
        with self.assertRaises(ValueError):old.publish_claim(self.root,self.jobs[66],owner,.7)
        with self.assertRaises(ValueError):old.jobs_for_scale(self.plan,.8)
    def test_changed_predecessor_proof_fails_closed(self):
        self.prepared();d=ops.read(self.workers);d['at']='later';self.write(self.workers,d)
        with self.assertRaisesRegex(ValueError,'evidence changed'):ops.verify_authorization(self.root)
    def test_stop_after_one_spawn_drains_and_never_retries(self):
        self.prepared();ops.install(self.root,ops.authorization_path(self.root));created=[]
        class Child:
            pid=os.getpid();polls=0
            def poll(self):self.polls+=1;return 0 if self.polls>=3 else None
        def spawn(*a,**kw):
            c=Child();created.append(c);(self.root/'STOP').write_text('fixture');return c
        with patch('preflight_bc_v3_web.preflight',return_value={'passed':True}),patch.object(old.time,'sleep',return_value=None):old.controller(self.root,.7,popen=spawn)
        self.assertEqual(len(created),1);self.assertGreaterEqual(created[0].polls,3)
        exits=list(ops.area(self.root).glob('controllers/*/*/exit.json'));self.assertTrue(ops.read(exits[0])['drained'])
    def test_bootstrap_commands_use_reviewed_entry_and_fixed_scope(self):
        args=SimpleNamespace(root=self.root,authorization=ops.authorization_path(self.root),scale='scale_0700',reader_python='/python')
        commands=bootstrap.commands(args);c=commands['controller'];self.assertIn(str(ops.ROOT/'scripts/run_rq3_scale0700_resume_ops5.py'),c)
        self.assertEqual(c[c.index('--authorization')+1],str(args.authorization));self.assertIn('--resume',c)
        self.assertNotIn('--scale',c);self.assertIn('run_rq3_scale0700_resume_ops5.py',bootstrap.ROLE_SCRIPTS)

if __name__=='__main__':unittest.main()
