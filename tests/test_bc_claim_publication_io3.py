import json
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import test_bc_route_runtime_v2 as fixtures
from test_bc_route_runtime_v2 import put,GOOD
import bc_claim_publication_io3 as io3
import run_bc_campaign_v3_routes2_io3 as controller
import run_bc_trial_v3_routes2_io3 as trial
import bc_route_runtime_v2 as frozen_runtime


class PublicationTests(unittest.TestCase):
    def fixture(self,td):
        root,jobs,data,parent,plan=fixtures.RevisionTests().fixture(td);plan.bind()
        return root,jobs,io3.PublicationRoutePlan(root,plan.path,plan.expected_sha256)

    def test_missing_owner_is_pending_and_never_a_legacy_claim(self):
        with tempfile.TemporaryDirectory() as td:
            root,jobs,plan=self.fixture(td);job=jobs[-1];claim=root/'jobs'/job['job_id']/'claim';claim.mkdir(parents=True)
            with self.assertRaises(io3.ClaimPublicationPending):plan.assignment(job)
            with patch.object(controller,'ROUTE_PLAN',plan),patch.object(controller,'ORIGINAL_ACQUIRE_CLAIM') as acquire:
                self.assertIsNone(controller.acquire_claim(root,jobs[-2],{}));acquire.assert_not_called()

    def test_publication_race_after_own_claim_keeps_reservation_for_waiting_trial(self):
        with tempfile.TemporaryDirectory() as td:
            root,jobs,plan=self.fixture(td);job=jobs[-2];sibling=jobs[-1]
            original=controller.ORIGINAL_ACQUIRE_CLAIM
            def acquire(*args,**kwargs):
                result=original(*args,**kwargs)
                (root/'jobs'/sibling['job_id']/'claim').mkdir(parents=True)
                return result
            with patch.object(controller,'ROUTE_PLAN',plan),patch.object(controller,'ORIGINAL_ACQUIRE_CLAIM',side_effect=acquire):
                result=controller.acquire_claim(root,job,{'controller_id':'fixture'})
            self.assertIsNotNone(result)
            self.assertTrue((result[0]/'claim/owner.json').exists())

    def test_real_owner_published_after_directory_is_waited_for(self):
        with tempfile.TemporaryDirectory() as td:
            root,jobs,plan=self.fixture(td);job=jobs[-1];metadata=plan.claim_metadata(job)
            claim=root/'jobs'/job['job_id']/'claim';claim.mkdir(parents=True)
            ready=threading.Event()
            def publish():
                ready.wait();time.sleep(.025);io3.immutable_json(claim/'owner.json',{'job_id':job['job_id'],**metadata})
            thread=threading.Thread(target=publish);thread.start()
            startup=io3.StartupRoutePlan(root,plan.path,plan.expected_sha256);startup.retry_delays=(.01,)*20
            ready.set();self.assertEqual(startup.assignment(job),GOOD);thread.join()

    def test_wrong_or_malformed_owner_not_retried(self):
        for value in ['{broken',json.dumps({'job_id':'wrong'})]:
            with self.subTest(value=value),tempfile.TemporaryDirectory() as td:
                root,jobs,plan=self.fixture(td);job=jobs[-1];p=root/'jobs'/job['job_id']/'claim/owner.json';p.parent.mkdir(parents=True);p.write_text(value)
                startup=io3.StartupRoutePlan(root,plan.path,plan.expected_sha256);startup.sleep=Mock()
                with self.assertRaises(ValueError):startup.assignment(job)
                startup.sleep.assert_not_called()

    def test_wait_is_bounded_and_only_pending_exception_retried(self):
        op=Mock(side_effect=io3.ClaimPublicationPending());sleep=Mock()
        with self.assertRaises(io3.ClaimPublicationPending):io3.retry_publication(op,delays=(.1,.2),sleep=sleep)
        self.assertEqual(op.call_count,3);self.assertEqual(sleep.call_count,2)
        op=Mock(side_effect=FileNotFoundError('different metadata'))
        with self.assertRaises(FileNotFoundError):io3.retry_publication(op,delays=(.1,),sleep=sleep)
        self.assertEqual(op.call_count,1)

    def test_faulting_scheduler_drains_children_without_signals(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);control=root/'control';control.mkdir();child=Mock();child.poll.side_effect=[None,None,0]
            def crash(*args):
                args[-1]['children']['job']=child;args[-1]['routes']['job']='route';raise FileNotFoundError('owner')
            with patch.object(controller,'_dispatch_loop',side_effect=crash),patch.object(controller.time,'sleep'):
                with self.assertRaises(FileNotFoundError):controller.dispatch_loop(None,root,{},[],control,{},'id',None)
            self.assertEqual(child.poll.call_count,3);child.terminate.assert_not_called();child.kill.assert_not_called()
            state=json.loads((control/'status.json').read_text());self.assertTrue(state['stop_dispatch']);self.assertEqual(state['active_local'],0)

    def recovery_fixture(self,td):
        root,jobs,plan=self.fixture(td);job=jobs[-1];metadata=plan.claim_metadata(job);out=root/'jobs'/job['job_id']/'attempts/attempt_001';out.mkdir(parents=True)
        slot=root/'cells/dsh/visual/slots/00';slot.mkdir(parents=True)
        owner={**metadata,'job_id':job['job_id'],'controller_id':'old','slot':str(slot),
               'hostname':'pt-abc-worker-0','boot_id':'oldboot','pid_namespace':'pid:[99]','pid':99,'start_identity':'123'}
        claim=put(root/'jobs'/job['job_id']/'claim/owner.json',owner);put(slot/'owner.json',owner)
        spec={**job,'campaign_root':str(root),'controller_id':'old','slot_path':str(slot),'config_path':str(root/'experiment.json')}
        spec_path=put(root/'jobs'/job['job_id']/'spec.json',spec)
        describe=put(root/'proof/describe.json',{'workspace_name':'rl','state':'FAILED','name':'cloudjob','uid':'abc'})
        bootstrap=put(root/'proof/node/bootstrap.json',{k:owner[k] for k in ['hostname','boot_id','pid_namespace']}|{'started_at_unix':10})
        exit_path=put(root/'proof/node/exit.json',{'controller_exit_code':1,'finished_at_unix':20})
        evidence={'schema':'acp-terminated-namespace-v1','namespace_terminated':True,'platform_state':'FAILED','uid':'abc','name':'cloudjob',
                  **{k:owner[k] for k in ['hostname','boot_id','pid_namespace']}}
        for key,path in [('describe',describe),('bootstrap',bootstrap),('exit',exit_path)]:evidence.update({key+'_path':str(path),key+'_sha256':io3.sha(path)})
        ep=put(root/'proof/namespace.json',evidence)
        auth=put(root/'recovery-authorization.json',{'version':'bc-v3-never-started-recovery-batch-v1',
             'terminated_namespace_evidence_path':str(ep),'terminated_namespace_evidence_sha256':io3.sha(ep),
             'entries':[{'job_id':job['job_id'],'attempt_path':str(out),'spec_sha256':io3.sha(spec_path),
                        'claim_owner_sha256':io3.sha(claim),'slot_owner_sha256':io3.sha(slot/'owner.json')}]})
        return root,jobs,plan,spec,spec_path,out,auth

    def test_recovery_requires_actual_failed_namespace_and_preserves_inputs(self):
        with tempfile.TemporaryDirectory() as td:
            root,jobs,plan,spec,sp,out,auth=self.recovery_fixture(td)
            before={p:p.read_bytes() for p in [sp,root/'jobs'/spec['job_id']/'claim/owner.json',Path(spec['slot_path'])/'owner.json']}
            result=io3.validate_recovery(spec,sp,out,auth);self.assertEqual(result['job_id'],spec['job_id'])
            for p,raw in before.items():self.assertEqual(p.read_bytes(),raw)
            describe=root/'proof/describe.json';d=json.loads(describe.read_text());d['state']='RUNNING';put(describe,d)
            evidence_path=root/'proof/namespace.json';e=json.loads(evidence_path.read_text());e['describe_sha256']=io3.sha(describe);put(evidence_path,e)
            a=json.loads(auth.read_text());a['terminated_namespace_evidence_sha256']=io3.sha(evidence_path);put(auth,a)
            with self.assertRaisesRegex(ValueError,'Official ACP'):io3.validate_recovery(spec,sp,out,auth)

    def test_any_started_native_terminal_or_unknown_evidence_blocks_recovery(self):
        for name in ['worker-started.json','command.json','running.json','heartbeat.json','result.json','native','calls.jsonl']:
            with self.subTest(name=name),tempfile.TemporaryDirectory() as td:
                root,jobs,plan,spec,sp,out,auth=self.recovery_fixture(td)
                if name=='native':(out/name).mkdir()
                else:(out/name).write_text('{}')
                with self.assertRaisesRegex(ValueError,'evidence'):io3.validate_recovery(spec,sp,out,auth)

    def test_recovery_trial_delegates_once_and_started_guard_blocks_second_launch(self):
        with tempfile.TemporaryDirectory() as td:
            root,jobs,plan,spec,sp,out,auth=self.recovery_fixture(td);calls=[]
            def original_main():
                # Same exclusive boundary as the frozen main. A repeated wrapper
                # must not even delegate once this durable start evidence exists.
                with (out/'worker-started.json').open('x') as stream:stream.write('{}')
                calls.append('native')
            argv=['io3','--spec',str(sp),'--out',str(out),'--recovery-authorization',str(auth),'--live']
            with patch.object(sys,'argv',argv),patch.object(trial.frozen_routes,'main',side_effect=original_main):trial.main()
            with patch.object(sys,'argv',argv),patch.object(trial.frozen_routes,'main',side_effect=original_main):
                with self.assertRaises(ValueError):trial.main()
            self.assertEqual(calls,['native'])

    def test_operational_entry_change_keeps_existing_frozen_route_lineage_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            root,jobs,plan,spec,sp,out,auth=self.recovery_fixture(td)
            value={**spec,'_spec_path':str(sp)}
            frozen_runtime.prepare_runtime(value,out,plan)
            before=(out/'route-lineage.json').read_bytes()
            io3.immutable_json(out/'claim-publication-io3.json',io3.operational_record())
            cmd=['python',str(io3.ROOT/'scripts/run_dsh_eval_v3_routes1.py'),'--config','same']
            factory=lambda original,prepared:lambda spec,out:(cmd,Path('result'),60)
            actual,_,timeout=trial.operational_native_command(factory,None,{})(spec,out)
            self.assertEqual(actual[1],str(io3.ROOT/'scripts/run_dsh_eval_v3_routes2_io3.py'))
            self.assertEqual(actual[2:],cmd[2:]);self.assertEqual(timeout,60)
            self.assertEqual((out/'route-lineage.json').read_bytes(),before)
            marker=out/'claim-publication-io3.json';data=json.loads(marker.read_text());data['implementation_sha256']['scripts/run_dsh_eval_v3_routes2_io3.py']='f'*64;put(marker,data)
            with self.assertRaises(ValueError):trial.operational_native_command(factory,None,{})(spec,out)

    def test_recovery_and_pending_share_total_and_route_pool(self):
        with tempfile.TemporaryDirectory() as td:
            root,jobs,plan,spec,sp,out,auth=self.recovery_fixture(td);control=root/'control';control.mkdir()
            recovery={'job_id':spec['job_id'],'spec_path':str(sp),'attempt_path':str(out),'authorization_path':str(auth),
                      'authorization_sha256':io3.sha(auth),'job':jobs[-1]}
            selected=[jobs[-1],jobs[-2]];states={spec['job_id']:'unknown',jobs[-2]['job_id']:'pending'}
            policy=Mock();policy.refresh.return_value={'valid':True,'target':2,'per_route_caps':{GOOD:2}}
            args=SimpleNamespace(limit=2,dispatch_role='cloud',concurrency=2,unstarted_recovery_manifest=None)
            children=[]
            def spawn(*args,**kwargs):child=Mock();child.poll.return_value=0;children.append(child);return child
            with patch.object(controller,'ROUTE_PLAN',plan),patch.object(controller,'load_recoveries',return_value={spec['job_id']:recovery}),\
                 patch.object(controller,'job_state',side_effect=lambda p:states['/'.join(p.parts[-3:])]),\
                 patch.object(controller,'validate_sources'),patch.object(controller.subprocess,'Popen',side_effect=spawn),patch.object(controller.time,'sleep'):
                result=controller.dispatch_loop(args,root,{'definition':{'cohort_sha256':'c'*64}},selected,control,{},'new',policy)
            self.assertEqual(result['new_launches'],2);self.assertEqual(len(children),2)
            self.assertTrue((out/'claim-publication-recovery-dispatch.json').exists())
            # Old claim/controller/slot remain untouched for the recovered item.
            self.assertEqual(json.loads((root/'jobs'/spec['job_id']/'claim/owner.json').read_text())['controller_id'],'old')


if __name__=='__main__':unittest.main()
