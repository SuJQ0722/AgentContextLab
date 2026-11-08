import importlib.util
from concurrent.futures import ThreadPoolExecutor
import json
import hashlib
from pathlib import Path
import tempfile
import unittest

SPEC=importlib.util.spec_from_file_location('reader_resume',Path(__file__).resolve().parents[1]/'scripts/resume_sco_bc_v3_after_reader_ops.py')
m=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(m)


class ResumeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.uid='a'*32;self.host='pt-'+self.uid+'-worker-0'
        self.job={'name':'acl-bc-v3-hermes-visual','harness':'hermes','strategy':'visual'}
        self.desc={'name':self.job['name'],'workspace_name':'rl','uid':self.uid,'state':'SUCCEEDED'}
        self.plan={'jobs':[dict(self.job,job_id='hermes/visual/q_001_r01')]}
        self.node=self.root/'runtime/nodes'/(self.host+'-boot')
        self.boot=self.node/'hermes-visual/bootstrap.json'
        self.exit=self.boot.parent/'exit.json'
        self.deploy=self.node/'reader-ops/1/deployment.json'
        m.atomic(self.boot,{'cell':'hermes/visual','started_at_unix':1})
        m.atomic(self.exit,{'controller_exit_code':0,'stopped':True,'finished_at_unix':100})
        self.deployment={'state':'verified','live':True,'new_slots':32,'hostname':self.host,'boot_id':'boot',
                         'cold_fetch':{'success':True},'egress_proxy':{'https_proxy':{'hostname':'proxy'}},
                         'maintenance_started_at':'1970-01-01T00:00:10+00:00'}
        m.atomic(self.deploy,self.deployment)
        m.atomic(self.node/'telemetry.json',{'hostname':self.host,'boot_id':'boot','pid_namespace':'pid:[1]','timestamp':'1970-01-01T00:00:20+00:00'})
    def test_strict_gates_and_unknown_not_pending(self):
        self.assertTrue(m.assess(self.root,self.plan,self.job,self.desc)['eligible'])
        for state in ['RUNNING','FAILED','CANCELLED']:
            self.assertFalse(m.assess(self.root,self.plan,self.job,dict(self.desc,state=state))['eligible'])
        (self.root/'jobs/hermes/visual/q_001_r01/claim').mkdir(parents=True)
        self.assertEqual(m.assess(self.root,self.plan,self.job,self.desc)['pending'],0)
    def test_wrong_host_failed_deploy_and_non_drained_refused(self):
        for patch in [{'state':'failed'},{'new_slots':4},{'hostname':'another'}, {'egress_proxy':{}}, {'cold_fetch':{'success':False}}]:
            m.atomic(self.deploy,{**self.deployment,**patch})
            self.assertFalse(m.assess(self.root,self.plan,self.job,self.desc)['eligible'])
        m.atomic(self.deploy,self.deployment)
        m.atomic(self.exit,{'controller_exit_code':1,'stopped':True,'finished_at_unix':100})
        self.assertFalse(m.assess(self.root,self.plan,self.job,self.desc)['eligible'])
    def test_atomic_request_precedes_start_and_no_repeat_on_unknown(self):
        calls=[];receipts=self.root/'receipts'
        def invoke(sco,op,name):
            self.assertTrue((receipts/name/'request.json').exists());calls.append(name)
            return {'returncode':None,'error_type':'TimeoutExpired'}
        self.assertEqual(m.start_once(receipts,self.job,{},'sco',invoke)['state'],'unknown')
        self.assertEqual(m.start_once(receipts,self.job,{},'sco',invoke)['state'],'existing_request_never_repeated')
        self.assertEqual(len(calls),1)
    def test_rejected_succeeded_start_is_never_replaced_or_retried(self):
        calls=[]
        def invoke(*args):calls.append(args);return {'returncode':1,'stderr':'state not supported'}
        receipts=self.root/'receipts'
        self.assertEqual(m.start_once(receipts,self.job,{},'sco',invoke)['state'],'rejected')
        m.start_once(receipts,self.job,{},'sco',invoke)
        self.assertEqual(len(calls),1);self.assertEqual(calls[0][1],'start')
    def test_empty_crashed_receipt_and_stop_do_not_dispatch(self):
        receipts=self.root/'receipts';(receipts/self.job['name']).mkdir(parents=True)
        def forbidden(*_):self.fail('Must not dispatch')
        self.assertEqual(m.start_once(receipts,self.job,{},'sco',forbidden)['state'],'existing_request_never_repeated')
        self.assertEqual(m.start_once(self.root/'other',self.job,{},'sco',forbidden,lambda:True)['state'],'stopping_no_start')
    def test_retirement_records_only_old_namespace(self):
        evidence=m.assess(self.root,self.plan,self.job,self.desc)
        def invoke(*_):
            retired=m.read(self.node/'retired.json')
            self.assertEqual(retired['pid_namespace'],'pid:[1]')
            self.assertEqual(retired['job_name'],self.job['name'])
            return {'returncode':0}
        m.start_once(self.root/'receipts',self.job,evidence,'sco',invoke)
    def test_two_watchers_issue_one_start(self):
        receipts=self.root/'receipts';calls=[]
        def invoke(*args):calls.append(args);return {'returncode':0}
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:m.start_once(receipts,self.job,{},'sco',invoke),range(2)))
        self.assertEqual(len(calls),1)
        self.assertEqual({x['state'] for x in results},{'accepted','existing_request_never_repeated'})
    def test_poststart_requires_new_bootstrap_and_real_new_claims(self):
        request={'requested_at_unix':50}
        self.assertEqual(m.post_start(self.root,self.job,request,self.desc)['state'],'awaiting_new_bootstrap')
        m.atomic(self.boot,{'started_at_unix':60,'commands':{'controller':['python','run_bc_campaign_v3_capacity1.py'],
                 'reader':['python','reader-text-v1-workers32.json']},'reader_egress_proxy':{'https_proxy':{'hostname':'proxy'}}})
        m.atomic(self.root/'experiment.json',{})
        m.atomic(self.root/'web-readiness'/(self.node.name+'.json'),{'passed':True,'hostname':self.host,'boot_id':'boot',
            'checked_at_unix':55,'config_sha256':hashlib.sha256((self.root/'experiment.json').read_bytes()).hexdigest()})
        self.assertEqual(m.post_start(self.root,self.job,request,self.desc)['state'],'bootstrap_configuration_verified')
        m.atomic(self.root/'jobs/hermes/visual/q_001_r01/claim/owner.json',{'hostname':self.host,'boot_id':'boot','claimed_at':70})
        self.assertEqual(m.post_start(self.root,self.job,request,self.desc)['state'],'resumed_claiming_pending')

if __name__=='__main__':unittest.main()
