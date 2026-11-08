import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock,patch
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import roll_sco_bc_v3_rate_ops4 as roll
PARENT_NAME='acl-bc-v3-hermes-visual-ops3'
NAME='acl-bc-v3-hermes-visual-ops4'


class Ops4RollTests(unittest.TestCase):
    def fixture(self,td):
        root=Path(td);submissions=root/'parents';directory=submissions/PARENT_NAME;directory.mkdir(parents=True)
        request={'name':PARENT_NAME,'generation':'ops3','operation':'create','harness':'hermes','strategy':'visual','requested_at_unix':100,
                 'argv':['sco','acp','jobs','create','--workspace-name','rl','--job-name',PARENT_NAME,'--name',PARENT_NAME,
                         '--worker-nodes','1','--worker-spec','N4lS.Iu.I80.8c32g','--container-image-url','unchanged:tag',
                         '--storage-mount','same-afs','--command','unchanged bootstrap command']}
        (directory/'request.json').write_text(json.dumps(request));(directory/'response.json').write_text(json.dumps({'state':'submitted','returncode':0}))
        job=roll.parent_job(submissions,'hermes','visual')
        node=root/'runtime/nodes/old-host-old-boot';node.mkdir(parents=True)
        evidence={'hostname':'old-host','node_directory':str(node),'retired_boot_id':'old-boot','retired_pid_namespace':'pid:[99]',
                  'bootstrap_exit':'bound-clean-exit','acp_state':'SUCCEEDED'}
        config=root/'dispatch.json';config.write_text('{}')
        return root,submissions,job,evidence,config

    def test_parent_is_only_successfully_submitted_hermes_visual_ops3(self):
        with tempfile.TemporaryDirectory() as td:
            root,submissions,job,evidence,config=self.fixture(td)
            self.assertEqual(job['new_name'],NAME)
            p=submissions/PARENT_NAME/'request.json';row=json.loads(p.read_text());row['harness']='dsh';p.write_text(json.dumps(row))
            with self.assertRaises(ValueError):roll.parent_job(submissions,'hermes','visual')

    def test_one_create_preserves_every_argument_except_names_and_retires_parent(self):
        with tempfile.TemporaryDirectory() as td:
            root,submissions,job,evidence,config=self.fixture(td)
            invoke=Mock(return_value={'returncode':0})
            result=roll.replacement_once(root/'receipts',job,evidence,{},config,invoke=invoke)
            self.assertEqual(result['state'],'submitted')
            request=json.loads((root/'receipts'/NAME/'request.json').read_text())
            self.assertEqual(request['generation'],'ops4');self.assertEqual(request['replaces'],PARENT_NAME)
            self.assertEqual(request['active_workers_this_cell'],1)
            old=job['submission']['argv'];new=invoke.call_args.args[0]
            self.assertEqual([i for i,(a,b) in enumerate(zip(old,new)) if a!=b],[old.index('--job-name')+1,old.index('--name')+1])
            retired=json.loads((Path(evidence['node_directory'])/'retired.json').read_text())
            self.assertEqual(retired['job_name'],PARENT_NAME);self.assertEqual(retired['pid_namespace'],'pid:[99]')

    def test_unknown_create_never_retried(self):
        with tempfile.TemporaryDirectory() as td:
            root,submissions,job,evidence,config=self.fixture(td);invoke=Mock(return_value={'returncode':None,'error_type':'TimeoutExpired'})
            self.assertEqual(roll.replacement_once(root/'receipts',job,evidence,{},config,invoke=invoke)['state'],'unknown')
            self.assertEqual(roll.replacement_once(root/'receipts',job,evidence,{},config,invoke=invoke)['state'],'existing_request_never_repeated')
            invoke.assert_called_once()

    def test_conflicting_retired_namespace_never_creates(self):
        with tempfile.TemporaryDirectory() as td:
            root,submissions,job,evidence,config=self.fixture(td);invoke=Mock()
            (Path(evidence['node_directory'])/'retired.json').write_text('{"pid_namespace":"different"}')
            with self.assertRaises(ValueError):roll.replacement_once(root/'receipts',job,evidence,{},config,invoke=invoke)
            invoke.assert_not_called()

    def cycle_fixture(self,td):
        root,submissions,job,evidence,config=self.fixture(td)
        config.write_text(json.dumps({'active_workers_per_cloud_instance':1,'local_target_workers':2}))
        (root/'plan.json').write_text('{"jobs":[]}')
        args=SimpleNamespace(root=root,submissions=submissions,receipts=root/'receipts',dispatch_config=config,
             harness=['hermes','dsh'],strategy=['none','summarize','sliding_window','discard','visual'],sco=Path('sco'),live=False)
        return args,job,evidence

    def test_partial_parent_inventory_waits_per_cell_and_dryrun_does_not_create(self):
        with tempfile.TemporaryDirectory() as td:
            args,job,evidence=self.cycle_fixture(td)
            query=Mock(side_effect=[{'returncode':0,'stdout':'{}'},{'returncode':1,'stderr':'{"reason":"trainingJobNotFound"}'}]);create=Mock()
            with patch.object(roll.parent,'assess',return_value={'name':NAME,'eligible':True,'reason':'Ready',**evidence}):
                report=roll.cycle(args,query=query,create=create)
            self.assertEqual(len(report['jobs']),10)
            self.assertEqual(sum(r.get('state')=='awaiting_parent_submitted' for r in report['jobs']),9)
            self.assertEqual(sum(r.get('eligible') is True for r in report['jobs']),1)
            create.assert_not_called();self.assertFalse(args.receipts.exists())

    def test_not_drained_parent_or_unknown_new_name_never_creates(self):
        with tempfile.TemporaryDirectory() as td:
            args,job,evidence=self.cycle_fixture(td);args.live=True;create=Mock()
            query=Mock(return_value={'returncode':0,'stdout':'{}'})
            with patch.object(roll.parent,'assess',return_value={'name':NAME,'eligible':False,'reason':'Waiting for ACP SUCCEEDED'}):
                roll.cycle(args,query=query,create=create)
            query.assert_called_once();create.assert_not_called()
            query=Mock(side_effect=[{'returncode':0,'stdout':'{}'},{'returncode':None,'error_type':'TimeoutExpired'}])
            with patch.object(roll.parent,'assess',return_value={'name':NAME,'eligible':True,'reason':'Ready',**evidence}):
                roll.cycle(args,query=query,create=create)
            create.assert_not_called()

    def test_only_cloud1_local2_accepted(self):
        with tempfile.TemporaryDirectory() as td:
            args,job,evidence=self.cycle_fixture(td)
            args.dispatch_config.write_text(json.dumps({'active_workers_per_cloud_instance':4,'local_target_workers':4}))
            query=Mock();create=Mock()
            with self.assertRaises(ValueError):roll.cycle(args,query=query,create=create)
            query.assert_not_called();create.assert_not_called()

    def test_parent_already_at_one_is_not_rolled(self):
        with tempfile.TemporaryDirectory() as td:
            args,job,evidence=self.cycle_fixture(td);args.live=True
            p=args.submissions/PARENT_NAME/'request.json';row=json.loads(p.read_text())
            row['operational_dispatch']={'active_workers_per_cloud_instance':1,'local_target_workers':2};p.write_text(json.dumps(row))
            query=Mock();create=Mock();report=roll.cycle(args,query=query,create=create)
            self.assertEqual(sum(r.get('state')=='already_target_no_roll' for r in report['jobs']),1)
            query.assert_not_called();create.assert_not_called()

    def test_prior_visual_ops4_receipt_also_blocks_duplicate_create(self):
        with tempfile.TemporaryDirectory() as td:
            args,job,evidence=self.cycle_fixture(td);args.live=True
            legacy=Path(td)/'legacy';(legacy/NAME).mkdir(parents=True)
            query=Mock();create=Mock()
            with patch.object(roll,'LEGACY_VISUAL_RECEIPTS',legacy):report=roll.cycle(args,query=query,create=create)
            self.assertEqual(sum(r.get('state')=='existing_other_receipt_never_repeated' for r in report['jobs']),1)
            query.assert_not_called();create.assert_not_called()


if __name__=='__main__':unittest.main()
