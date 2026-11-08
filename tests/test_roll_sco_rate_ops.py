import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import roll_sco_bc_v3_rate_ops as roll


class RollTests(unittest.TestCase):
    def setup_case(self,td):
        root=Path(td);uid='a'*32;host='pt-'+uid+'-worker-0';node=root/'runtime/nodes'/f'{host}-boot'
        directory=node/'dsh-discard';directory.mkdir(parents=True)
        boot={'hostname':host,'boot_id':'boot','pid_namespace':'pid:[99]','cell':'dsh/discard',
              'started_at_unix':200,'controller_pid':53}
        (directory/'bootstrap.json').write_text(json.dumps(boot))
        (directory/'exit.json').write_text(json.dumps({'controller_exit_code':0,'stopped':True,'finished_at_unix':300}))
        (node/'telemetry.json').write_text(json.dumps(boot))
        name='acl-bc-v3-dsh-discard-ops2'
        submission={'name':name,'requested_at_unix':100,'argv':['sco','acp','jobs','create',
            '--workspace-name','rl','--job-name',name,'--name',name,'--worker-nodes','1',
            '--worker-spec','N4lS.Iu.I80.8c32g','--container-image-url','unchanged:tag',
            '--storage-mount','afs-id:/same','--command','same bootstrap command']}
        job={'name':name,'new_name':name[:-1]+'3','original_name':name.removesuffix('-ops2'),
             'harness':'dsh','strategy':'discard','submission':submission,
             'parent_request':'parent-request','parent_response':'parent-response',
             'parent_request_sha256':'1'*64,'parent_response_sha256':'2'*64}
        plan={'jobs':[{'harness':'dsh','strategy':'discard','job_id':'dsh/discard/q_099_r01'}]}
        description={'name':name,'uid':uid,'workspace_name':'rl','state':'SUCCEEDED'}
        return root,node,job,plan,description

    def test_terminal_namespace_and_drain_required(self):
        with tempfile.TemporaryDirectory() as td:
            root,node,job,plan,description=self.setup_case(td)
            self.assertTrue(roll.assess(root,plan,job,description)['eligible'])
            for state in ['RUNNING','FAILED','STOPPED']:
                self.assertFalse(roll.assess(root,plan,job,{**description,'state':state})['eligible'])
            path=node/'telemetry.json';data=json.loads(path.read_text());data['pid_namespace']='pid:[100]';path.write_text(json.dumps(data))
            self.assertFalse(roll.assess(root,plan,job,description)['eligible'])

    def test_controller_only_stop_requires_bound_durable_drain(self):
        with tempfile.TemporaryDirectory() as td:
            root,node,job,plan,description=self.setup_case(td)
            exitpath=node/'dsh-discard/exit.json';data=json.loads(exitpath.read_text());data['stopped']=False;exitpath.write_text(json.dumps(data))
            self.assertFalse(roll.assess(root,plan,job,description)['eligible'])
            directory=root/'controllers/fixture';directory.mkdir(parents=True)
            boot=json.loads((node/'telemetry.json').read_text())
            status={**boot,'pid':53,'start_identity':'123','stop_dispatch':True,'active_local':0}
            (directory/'status.json').write_text(json.dumps(status))
            self.assertTrue(roll.assess(root,plan,job,description)['eligible'])
            status['active_local']=1;(directory/'status.json').write_text(json.dumps(status))
            self.assertFalse(roll.assess(root,plan,job,description)['eligible'])

    def test_one_create_unknown_never_retried_and_argv_only_names_change(self):
        with tempfile.TemporaryDirectory() as td:
            root,node,job,plan,description=self.setup_case(td)
            evidence=roll.assess(root,plan,job,description)
            dispatch={'active_workers_per_cloud_instance':4,'local_target_workers':4}
            config=root/'dispatch.json';config.write_text(json.dumps(dispatch))
            invoke=Mock(return_value={'returncode':None,'error_type':'TimeoutExpired'})
            receipt=root/'receipts'
            first=roll.replacement_once(receipt,job,evidence,dispatch,config,invoke=invoke)
            second=roll.replacement_once(receipt,job,evidence,dispatch,config,invoke=invoke)
            self.assertEqual(first['state'],'unknown');self.assertEqual(second['state'],'existing_request_never_repeated')
            invoke.assert_called_once()
            sent=invoke.call_args.args[0];old=job['submission']['argv']
            differences=[i for i,(a,b) in enumerate(zip(old,sent)) if a!=b]
            self.assertEqual(differences,[old.index('--job-name')+1,old.index('--name')+1])
            retired=json.loads((node/'retired.json').read_text())
            self.assertEqual(retired['job_name'],job['name']);self.assertEqual(retired['pid_namespace'],'pid:[99]')
            request=json.loads((receipt/job['new_name']/'request.json').read_text())
            self.assertEqual(request['generation'],'ops3');self.assertIn('scripts/bootstrap_bc_v3_node.py',request['source_sha256'])

    def test_retirement_conflict_never_creates(self):
        with tempfile.TemporaryDirectory() as td:
            root,node,job,plan,description=self.setup_case(td)
            evidence=roll.assess(root,plan,job,description)
            (node/'retired.json').write_text(json.dumps({'hostname':'different'}))
            config=root/'dispatch.json';config.write_text('{}');invoke=Mock()
            with self.assertRaises(ValueError):roll.replacement_once(root/'receipts',job,evidence,{},config,invoke=invoke)
            invoke.assert_not_called()
            self.assertEqual(roll.replacement_once(root/'receipts',job,evidence,{},config,invoke=invoke)['state'],'existing_request_never_repeated')

    def test_existing_claim_is_not_pending(self):
        with tempfile.TemporaryDirectory() as td:
            root,node,job,plan,description=self.setup_case(td)
            (root/'jobs/dsh/discard/q_099_r01/claim').mkdir(parents=True)
            self.assertFalse(roll.assess(root,plan,job,description)['eligible'])

    def test_dry_run_never_creates_or_retires(self):
        with tempfile.TemporaryDirectory() as td:
            root,node,job,plan,description=self.setup_case(td)
            (root/'plan.json').write_text(json.dumps(plan))
            config=root/'dispatch.json';config.write_text(json.dumps({'active_workers_per_cloud_instance':4,'local_target_workers':4}))
            args=SimpleNamespace(root=root,dispatch_config=config,submissions=root/'parents',receipts=root/'receipts',
                                 harness=['dsh'],strategy=['discard'],sco=Path('sco'),live=False)
            query=Mock(side_effect=[{'returncode':0,'stdout':json.dumps(description)},
                                    {'returncode':1,'stderr':'{"reason":"trainingJobNotFound"}'}])
            create=Mock()
            with patch.object(roll,'ops2_jobs',return_value=[job]): report=roll.cycle(args,query=query,create=create)
            self.assertTrue(report['jobs'][0]['eligible']);create.assert_not_called()
            self.assertFalse((node/'retired.json').exists());self.assertFalse(args.receipts.exists())

    def test_unknown_new_name_query_blocks_live_creation(self):
        with tempfile.TemporaryDirectory() as td:
            root,node,job,plan,description=self.setup_case(td)
            (root/'plan.json').write_text(json.dumps(plan))
            config=root/'dispatch.json';config.write_text(json.dumps({'active_workers_per_cloud_instance':4,'local_target_workers':4}))
            args=SimpleNamespace(root=root,dispatch_config=config,submissions=root/'parents',receipts=root/'receipts',
                                 harness=['dsh'],strategy=['discard'],sco=Path('sco'),live=True)
            query=Mock(side_effect=[{'returncode':0,'stdout':json.dumps(description)},
                                    {'returncode':None,'error_type':'TimeoutExpired'}])
            create=Mock()
            with patch.object(roll,'ops2_jobs',return_value=[job]): report=roll.cycle(args,query=query,create=create)
            self.assertFalse(report['jobs'][0]['eligible']);create.assert_not_called()
            self.assertFalse((node/'retired.json').exists())


if __name__=='__main__':unittest.main()
