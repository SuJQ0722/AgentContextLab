import argparse
from concurrent.futures import ThreadPoolExecutor
import errno
import json
import os
from pathlib import Path
import sys,tempfile,threading,unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import run_rq3_scale_cloud_ops2 as cloud
import run_rq3_parity_v3 as scientific

class CloudScaleTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.base=Path(self.tmp.name)/'base';self.base.mkdir();self.root=Path(self.tmp.name)/'campaign'
        cfg=scientific.read(scientific.BASE/'experiment.json');(self.base/'experiment.json').write_text(json.dumps(cfg));(self.base/'plan.json').write_text('{}')
        (self.base/'cohort.jsonl').write_text(''.join(json.dumps({'id':f'q_{i:03}','question':f'Q{i}','answer':'PRIVATE'})+'\n' for i in range(100)))
        with patch.object(scientific,'BASE',self.base),patch.object(scientific,'sources',return_value={}):self.plan=scientific.prepare(self.root)
        self.owner={'controller_id':'test','hostname':'host','boot_id':'boot','pid_namespace':'ns','pid':42,'start_identity':'start'}
    def jobs(self,scale):return cloud.jobs_for_scale(self.plan,scale)
    def cutover(self):
        area=cloud.area(self.root);area.mkdir(parents=True,exist_ok=True);status={**self.owner,'stop_dispatch':True}
        snapshot=area/'ack.json';snapshot.write_text(json.dumps(status));current=self.root/'old-status.json';current.write_text(json.dumps(status))
        record={'version':'rq3-cloud-scale-cutover-ops2','launch_authorized':True,'campaign_root':str(self.root),
            'plan_sha256':scientific.sha(self.root/'plan.json'),'allowed_scales':list(cloud.LABEL_TO_SCALE),'max_concurrency_per_scale':16,
            'old_stop_ack':[{'path':str(snapshot),'sha256':scientific.sha(snapshot),'status_path':str(current)}]}
        (area/'cutover.json').write_text(json.dumps(record));return record
    def test_seven_independent_16_slot_namespaces(self):
        for scale in cloud.LABEL_TO_SCALE:
            for index in range(16):self.assertIsNotNone(cloud.acquire_scale_slot(self.root,scale,self.owner,f'external{index}'))
            self.assertIsNone(cloud.acquire_scale_slot(self.root,scale,self.owner,'overflow'))
        self.assertEqual(len(list(cloud.area(self.root).glob('slots/*/*/owner.json'))),112)
        self.assertFalse((self.root/'cells/hermes/visual/slots').exists())
    def test_scale_selection_is_strict_and_never_changes_strategy(self):
        self.assertEqual(cloud.normalize_scale('.125'),'scale_0125');self.assertEqual(cloud.normalize_scale('scale_1000'),'scale_1000')
        with self.assertRaises(argparse.ArgumentTypeError):cloud.normalize_scale(.333)
        job=self.jobs(0)[0]
        with self.assertRaisesRegex(ValueError,'Cross-scale'):cloud.publish_claim(self.root,job,self.owner,1)
        result=cloud.publish_claim(self.root,job,self.owner,0);directory,slot,attempt,spec=result
        self.assertEqual(spec['strategy'],'visual');self.assertEqual(spec['scale'],0)
        self.assertTrue((directory/'claim/owner.json').exists());self.assertEqual(scientific.read(directory/'claim/spec.json'),spec)
        cloud.verify_published(spec,directory);scientific.validate_trial(spec,attempt)
    def test_prior_claim_attempt_or_partial_publication_is_never_replayed(self):
        jobs=self.jobs(.5)
        first=cloud.publish_claim(self.root,jobs[0],self.owner,.5);owner_bytes=(first[0]/'claim/owner.json').read_bytes()
        self.assertIsNone(cloud.publish_claim(self.root,jobs[0],self.owner,.5));self.assertEqual((first[0]/'claim/owner.json').read_bytes(),owner_bytes)
        for job,artifact in zip(jobs[1:4],['attempts','claim','.claim-staging-orphan']):
            (self.root/'jobs'/job['job_id']/artifact).mkdir(parents=True)
            self.assertIsNone(cloud.publish_claim(self.root,job,self.owner,.5))
    def test_old_unknowns_reserve_capacity_until_confirmed_cleanup(self):
        jobs=self.jobs(.7)
        for job in jobs[:2]:
            path=self.root/'jobs'/job['job_id']/'claim';path.mkdir(parents=True);(path/'owner.json').write_text(json.dumps({**self.owner,'slot':'/legacy/slot'}))
        for i in range(14):self.assertIsNotNone(cloud.acquire_scale_slot(self.root,.7,self.owner,f'external{i}'))
        self.assertIsNone(cloud.acquire_scale_slot(self.root,.7,self.owner,'extra'))
        attempt=self.root/'jobs'/jobs[0]['job_id']/'attempts/attempt_001';attempt.mkdir(parents=True)
        (attempt/'result.json').write_text(json.dumps({'status':'not_started','slot_released':True,'unconfirmed_child_termination':[]}))
        self.assertIsNotNone(cloud.acquire_scale_slot(self.root,.7,self.owner,'released'))
    def test_unknown_result_does_not_release_reserved_capacity(self):
        job=self.jobs(.25)[0];directory=self.root/'jobs'/job['job_id'];(directory/'claim').mkdir(parents=True)
        (directory/'claim/owner.json').write_text(json.dumps({'slot':'/old'}));attempt=directory/'attempts/attempt_001';attempt.mkdir(parents=True)
        (attempt/'result.json').write_text(json.dumps({'status':'unknown','slot_released':True,'unconfirmed_child_termination':[]}))
        self.assertEqual(cloud.scale_capacity(self.root,.25)['legacy_reserved'],1)
    def test_concurrent_recovery_and_cloud_cannot_make_seventeenth_slot(self):
        jobs=self.jobs(.8)
        for job in jobs[:2]:
            path=self.root/'jobs'/job['job_id']/'claim';path.mkdir(parents=True);(path/'owner.json').write_text(json.dumps({'slot':'/old'}))
        for i in range(13):cloud.acquire_scale_slot(self.root,.8,self.owner,f'initial{i}')
        original=cloud.scale_capacity;barrier=threading.Barrier(2)
        def both_read(*args,**kwargs):
            result=original(*args,**kwargs);barrier.wait(timeout=10);return result
        with patch.object(cloud,'scale_capacity',side_effect=both_read),ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda i:cloud.acquire_scale_slot(self.root,.8,self.owner,f'concurrent{i}'),range(2)))
        self.assertEqual(sum(r is not None for r in results),1)
        self.assertEqual(original(self.root,.8)['reserved_total'],16)
    def test_stop_authorization_and_permanent_lease_cannot_be_stolen(self):
        self.cutover();cloud.verify_cutover(self.root)
        cloud.acquire_lease(self.root,0,self.owner)
        with self.assertRaisesRegex(ValueError,'permanent'):cloud.acquire_lease(self.root,0,dict(self.owner,controller_id='other'))
        current=self.root/'old-status.json';record=json.loads(current.read_text());record['stop_dispatch']=False;current.write_text(json.dumps(record))
        with self.assertRaisesRegex(ValueError,'acknowledged stopped'):cloud.verify_cutover(self.root)
    def test_stop_after_one_spawn_drains_without_signalling_or_new_dispatch(self):
        self.cutover();created=[]
        class Child:
            pid=os.getpid()
            polls=0
            def poll(self):self.polls+=1;return 0 if self.polls>=3 else None
        def spawn(*a,**k):
            child=Child();created.append(child);(self.root/'STOP').write_text('test');return child
        with patch('preflight_bc_v3_web.preflight',return_value={'passed':True}),patch.object(cloud.time,'sleep',return_value=None):
            cloud.controller(self.root,0,popen=spawn)
        self.assertEqual(len(created),1);self.assertGreaterEqual(created[0].polls,3)
        end=scientific.read(next(cloud.area(self.root).glob('controllers/*/*/exit.json')));self.assertTrue(end['drained']);self.assertTrue(end['stopped'])
    def test_post_spawn_metadata_error_still_drains_and_never_respawns(self):
        self.cutover();created=[];original=cloud.atomic
        class Child:
            pid=os.getpid()
            polls=0
            def poll(self):self.polls+=1;return 0 if self.polls>=3 else None
        def spawn(*a,**k):child=Child();created.append(child);return child
        def fail(path,value):
            if Path(path).name=='controller-dispatched.json':raise OSError(errno.EIO,'fixture')
            return original(path,value)
        with patch('preflight_bc_v3_web.preflight',return_value={'passed':True}),patch.object(cloud.time,'sleep',return_value=None),patch.object(cloud,'atomic',side_effect=fail):
            with self.assertRaisesRegex(RuntimeError,'after draining'):cloud.controller(self.root,1,popen=spawn)
        self.assertEqual(len(created),1);self.assertGreaterEqual(created[0].polls,3)
        self.assertTrue(scientific.read(next(cloud.area(self.root).glob('controllers/*/*/exit.json')))['drained'])

if __name__=='__main__':unittest.main()
