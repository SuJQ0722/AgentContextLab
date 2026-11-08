from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import replace_sco_bc_v3_after_reader_ops as m


class ReplacementTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.receipts=self.root/'receipts';self.old=self.root/'old'
        self.job={'name':'acl-bc-v3-hermes-summarize','harness':'hermes','strategy':'summarize'}
        self.submission={**self.job,'argv':['sco','acp','jobs','create','--workspace-name','rl','--worker-nodes','1',
            '--worker-spec','N4lS.Iu.I80.8c32g','--job-name',self.job['name'],'--name',self.job['name'],
            '--container-image-url','original-image','--storage-mount','original-afs','--command','original-bootstrap']}
        self.response={'state':'rejected','returncode':1,'stderr':r'{\"reason\":\"tjUpdateNotSupportStart\"}'}
        m.resume.atomic(self.old/self.job['name']/'response.json',self.response)
        m.resume.atomic(self.old/self.job['name']/'request.json',{'job':self.job,'evidence':{'acp_state':'SUCCEEDED'}})
    def query(self,sco,op,name):
        if name.endswith('-ops2'):return {'returncode':1,'stderr':'{"reason":"trainingJobNotFound"}'}
        return {'returncode':0,'stdout':json.dumps({'state':'SUCCEEDED','name':name})}
    def assess(self,query=None):
        with patch.object(m.resume,'assess',return_value={'eligible':True,'pending':2}):
            return m.assess_replacement(self.root,{},self.job,self.root,self.old,'sco',query or self.query)
    def test_requires_exact_rejection_and_confirmed_absence(self):
        self.assertTrue(self.assess()['eligible'])
        m.resume.atomic(self.old/self.job['name']/'response.json',{**self.response,'stderr':'tjUpdateNotSupportStart mentioned, not structured'})
        self.assertFalse(self.assess()['eligible'])
        m.resume.atomic(self.old/self.job['name']/'response.json',self.response)
        def unknown(sco,op,name):
            return {'returncode':None} if name.endswith('-ops2') else self.query(sco,op,name)
        self.assertFalse(self.assess(unknown)['eligible'])
    def test_existing_replacement_and_running_original_refused(self):
        self.assertFalse(self.assess(lambda *_:{'returncode':0,'stdout':'{"state":"RUNNING"}'})['eligible'])
        def exists(sco,op,name):
            return {'returncode':0,'stdout':'{}'} if name.endswith('-ops2') else self.query(sco,op,name)
        self.assertFalse(self.assess(exists)['eligible'])
    def test_argv_only_changes_names(self):
        argv=m.create_argv(self.submission,self.job['name']+'-ops2')
        changed=[i for i,(a,b) in enumerate(zip(argv,self.submission['argv'])) if a!=b]
        self.assertEqual(changed,[self.submission['argv'].index('--job-name')+1,self.submission['argv'].index('--name')+1])
    def test_concurrent_create_once_and_unknown_never_retries(self):
        calls=[]
        def invoke(argv):
            self.assertTrue((self.receipts/(self.job['name']+'-ops2')/'request.json').exists())
            calls.append(argv);return {'returncode':None,'error_type':'TimeoutExpired'}
        def run(_):return m.replacement_once(self.receipts,self.job,self.submission,{}, {'active_workers_per_cloud_instance':8},invoke=invoke)
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(run,range(2)))
        self.assertEqual(len(calls),1)
        self.assertEqual({r['state'] for r in results},{'unknown','existing_request_never_repeated'})
        run(2);self.assertEqual(len(calls),1)
    def test_visual_hold_even_live_and_eligible(self):
        m.resume.atomic(self.root/'plan.json',{'jobs':[]})
        job=dict(self.job,name='acl-bc-v3-hermes-visual',strategy='visual')
        args=SimpleNamespace(root=self.root,submissions=self.root,resume_receipts=self.old,receipts=self.receipts,
             sco='sco',harness=['hermes'],strategy=['visual'],release_visual=False,live=True)
        with patch.object(m.resume,'original_jobs',return_value=[job]),patch.object(m,'assess_replacement',return_value={'eligible':True}),patch.object(m,'replacement_once') as create:
            result=m.cycle(args)
            self.assertFalse(result['jobs'][0]['eligible']);create.assert_not_called()

if __name__=='__main__':unittest.main()
