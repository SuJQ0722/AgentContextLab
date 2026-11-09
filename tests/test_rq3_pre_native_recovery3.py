import json,os,sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import test_rq3_scale_cloud_ops2 as fixture
import recover_rq3_pre_native_third_once as recovery
import run_rq3_pre_native3_trial as trial
import report_rq3_final_seven_v3 as report

class Recovery3Tests(unittest.TestCase):
    def setUp(self):
        f=fixture.CloudScaleTests();f.setUp();self.addCleanup(f.doCleanups);self.f=f;self.parent=f.root;self.root=f.root.parent/'recovery3';self.grade=f.root.parent/'grading3'
        self.job=next(j for j in f.plan['jobs'] if j['job_id']==recovery.JOB);self.owner={**f.owner,'controller_id':'stopped-local'};self.directory=self.parent/'jobs'/recovery.JOB;self.attempt=self.directory/'attempts/attempt_001';self.attempt.mkdir(parents=True)
        self.slot=recovery.pending.area(self.parent)/'slots/scale_0700/12';self.run=recovery.pending.area(self.parent)/'controllers/scale_0700/stopped-local';self.run.mkdir(parents=True)
        claim={**self.owner,'job_id':recovery.JOB,'slot':str(self.slot)};spec={**self.job,'campaign_root':str(self.parent),'plan_sha256':recovery.sha(self.parent/'plan.json'),'cohort_sha256':f.plan['definition']['cohort_sha256'],'controller_id':self.owner['controller_id'],'slot_path':str(self.slot)}
        for p,d in [(self.directory/'claim/owner.json',claim),(self.directory/'spec.json',spec),(self.directory/'claim/spec.json',spec),(self.slot/'owner.json',claim),(self.attempt/'cloud-scale-dispatch-ops2.json',{})]:self.write(p,d)
        h=recovery.pending.area(self.parent)/'handoffs/local-to-cloud1';self.write(h/'held-reservation.json',{'job_id':recovery.JOB,'native_never_started_at_checkpoint':True,'original_controller':self.owner,'slot_path':str(self.slot)})
        self.write(h/'held-ready.json',{'held_reservation_sha256':recovery.sha(h/'held-reservation.json')});self.write(h/'request.json',{'old_run':str(self.run)});self.write(h/'stop-ack.json',{**self.owner,'stop_dispatch':True})
        allowed=[j['job_id'] for j in f.plan['jobs'] if j['scale']==.7]
        patcher=patch.object(recovery.pending,'verify_authorization',return_value={'pending_job_ids':allowed});patcher.start();self.addCleanup(patcher.stop)
        for name in ('area','VERSION','jobs_for_scale','verify_cutover','publish_claim','acquire_scale_slot'):
            patcher=patch.object(recovery.base,name,getattr(recovery.base,name));patcher.start();self.addCleanup(patcher.stop)
        self.auth=recovery.prepare(self.parent,self.root,self.grade)
    def write(self,p,d):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(d))
    def finish_old(self,api_calls=0):
        self.write(self.run/'exit.json',{**self.owner,'drained':True,'stopped':True})
        self.write(self.attempt/'result.json',{'job_id':recovery.JOB,'status':'not_started','api_calls':api_calls,'slot_released':True,'unconfirmed_child_termination':[],'failure_category':'cloud_controller_stopped_before_native_launch'})
        recovery.base.release_slot(self.slot)
    def test_wait_for_exact_owner_exit_and_explicit_zero_api(self):
        with patch.object(recovery,'owner_alive',return_value=True):self.assertIsNone(recovery.exit_proof(self.auth)[0])
        with patch.object(recovery,'owner_alive',return_value=False):
            self.assertIsNone(recovery.exit_proof(self.auth)[0]);self.finish_old();self.assertTrue(recovery.exit_proof(self.auth)[0]['native_never_started'])
    def test_paid_or_native_evidence_rejected(self):
        self.finish_old(api_calls=1)
        with patch.object(recovery,'owner_alive',return_value=False):
            with self.assertRaises(ValueError):recovery.exit_proof(self.auth)
        (self.attempt/'native').mkdir()
        with self.assertRaises(ValueError):recovery.validate_scope(self.root)
    def test_actual_frozen_trial_guard_and_repeat_claim_skip(self):
        self.finish_old()
        with patch.object(recovery,'owner_alive',return_value=False):
            recovery.install(self.root);jobs=recovery.base.jobs_for_scale(recovery.read(self.root/'plan.json'),.7);self.assertEqual(len(jobs),1)
            claim=recovery.base.publish_claim(self.root,jobs[0],{**self.owner,'controller_id':'recovery'},.7,1);self.assertIsNotNone(claim)
            d,s,a,spec=claim;trial.guard(spec,a);self.assertEqual(s.parent,Path(self.auth['shared_slot_root']))
            self.assertIsNone(recovery.base.publish_claim(self.root,jobs[0],{**self.owner,'controller_id':'recovery'},.7,1))
    def test_full_parent16blocks_first_launch(self):
        self.finish_old()
        for i in range(16):self.write(Path(self.auth['shared_slot_root'])/f'{i:02}'/'owner.json',{'job_id':'external'+str(i)})
        with patch.object(recovery,'owner_alive',return_value=False):
            recovery.install(self.root);job=recovery.base.jobs_for_scale(recovery.read(self.root/'plan.json'),.7)[0]
            self.assertIsNone(recovery.base.publish_claim(self.root,job,self.owner,.7,1))
    def test_report_only_replaces_one_keeps2100_and_paid15(self):
        old=self.parent.parent/'v2';out=self.parent.parent/'v3';entries=[]
        for j in self.f.plan['jobs']:
            scale=.75 if j['scale']==.125 else j['scale'];jid=j['job_id'].replace('scale_0125','scale_0750');attempt=str(self.parent/'jobs'/jid/'attempts/attempt_001')
            entries.append({'job_id':jid,'scale':scale,'original_attempt':attempt,'selected_attempt':attempt,'grading_root':'old'})
        self.write(old/'comparison-plan.json',{'scales':list(report.previous.original.SCALES),'entries':entries,'source_files_sha256':{},'selection_policy':'fixed paid15','paid_retry_root':'preserved-paid-root'})
        c=report.prepare_comparison(old,self.root,out);self.assertEqual(len(c['entries']),2100);self.assertEqual(sum(r['original_attempt']!=r['selected_attempt'] for r in c['entries']),1);self.assertEqual(c['paid_retry_root'],'preserved-paid-root')

if __name__=='__main__':unittest.main()
