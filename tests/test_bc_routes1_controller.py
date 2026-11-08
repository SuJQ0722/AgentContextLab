import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from collections import Counter
import unittest
from unittest.mock import Mock,patch

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
import run_bc_campaign_v3_routes1 as controller
import run_bc_campaign_v3 as original

ORDER=['deepseek-v4.1-flash-1017/'+s for s in ['huoshan/huoshan','zijian/sfb','huoshan/sfc','zijian/sfc']]


class ControllerTests(unittest.TestCase):
    def config(self):
        return {'worker_ceiling_per_instance':32,'active_workers_per_cloud_instance':16,'local_target_workers':2,
                'per_route_cloud_caps':dict(zip(ORDER,[1,5,5,5])),
                'per_route_local_caps':dict(zip(ORDER,[0,1,1,1]))}

    def test_round_robin_does_not_exhaust_old_route_first(self):
        jobs=[];assignment={}
        for index,route in enumerate(ORDER):
            for number in range(3):
                q=f'q{index}{number}';assignment[q,1]=route;jobs.append({'question_id':q,'repeat':1})
        plan=SimpleNamespace(data={'allowed_routes':ORDER},assignments=assignment)
        selected=list(controller.route_round_robin(jobs,plan))
        self.assertEqual([assignment[j['question_id'],1] for j in selected[:4]],ORDER)
        shifted=list(controller.route_round_robin(jobs,plan,2))
        self.assertEqual(assignment[shifted[0]['question_id'],1],ORDER[2])
        self.assertEqual(len(selected),len(jobs))

    def test_caps_and_total_target_both_apply_and_hot_change_is_audited(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'ops.json';config=self.config();path.write_text(json.dumps(config))
            cloud=controller.DispatchPolicy(path,'cloud',Path(td)/'control')
            policy=cloud.refresh();self.assertTrue(policy['valid'])
            self.assertFalse(controller.can_route_dispatch(policy,{ORDER[0]:1},ORDER[0]))
            self.assertTrue(controller.can_route_dispatch(policy,{ORDER[1]:4},ORDER[1]))
            self.assertFalse(controller.can_route_dispatch(policy,{ORDER[1]:5},ORDER[1]))
            self.assertFalse(controller.can_dispatch(policy,16))
            local=controller.DispatchPolicy(path,'local').refresh()
            self.assertFalse(controller.can_route_dispatch(local,{},ORDER[0]));self.assertEqual(local['target'],2)
            config['per_route_cloud_caps'][ORDER[1]]=0;path.write_text(json.dumps(config));policy=cloud.refresh()
            self.assertFalse(controller.can_route_dispatch(policy,{},ORDER[1]))
            self.assertEqual(len(list((Path(td)/'control/dispatch-decisions').glob('*.json'))),2)

    def test_missing_or_invalid_caps_pause_without_zero_inference(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'ops.json';config=self.config();del config['per_route_cloud_caps'];path.write_text(json.dumps(config))
            policy=controller.DispatchPolicy(path,'cloud').refresh()
            self.assertFalse(policy['valid']);self.assertIsNone(policy['target'])
            self.assertFalse(controller.can_dispatch(policy,0))

    def test_claim_uses_original_shared_slots_and_adds_fixed_route_identity(self):
        route=Mock();route.claim_metadata.return_value={'actual_route':ORDER[1],'route_plan_sha256':'a'*64}
        original_acquire=Mock(return_value=('jobdir','slot'))
        with patch.object(controller,'ROUTE_PLAN',route),patch.object(controller,'ORIGINAL_ACQUIRE_CLAIM',original_acquire):
            self.assertEqual(controller.acquire_claim(Path('/fixture'),{'job_id':'fixture'},{'controller_id':'controller'}),('jobdir','slot'))
        self.assertEqual(original_acquire.call_args.args[-1],32)
        self.assertEqual(original_acquire.call_args.args[2]['actual_route'],ORDER[1])
        self.assertEqual(original_acquire.call_args.args[2]['controller_id'],'controller')
        self.assertIs(controller.validate_sources,original.validate_sources)

    def test_actual_dispatch_loop_admits_1_5_5_5_not_sixteen_old_route_jobs(self):
        self.check_dispatch([1,5,5,5])

    def test_actual_dispatch_loop_holds_sfc_pairs_and_admits_1_15(self):
        self.check_dispatch([1,15,0,0])

    def check_dispatch(self,caps):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);control=root/'control';control.mkdir();(root/'plan.json').write_text('{}')
            path=root/'ops.json';config=self.config();config['per_route_cloud_caps']=dict(zip(ORDER,caps));path.write_text(json.dumps(config))
            jobs=[];assignments={};claimed=set();spawned=[]
            for i,route in enumerate(ORDER):
                for n in range(16):
                    q=f'q_{i}_{n}';job={'job_id':f'dsh/visual/{q}_r01','question_id':q,'repeat':1}
                    jobs.append(job);assignments[q,1]=route
            route_plan=SimpleNamespace(data={'allowed_routes':ORDER},assignments=assignments,
                                       expected_sha256='a'*64,check_unchanged=Mock())
            def claim(campaign,job,owner):
                if job['job_id'] in claimed:return None
                claimed.add(job['job_id']);jobdir=root/'jobs'/job['job_id'];jobdir.mkdir(parents=True)
                slot=root/'slots'/str(len(claimed));slot.mkdir(parents=True);return jobdir,slot
            class Child:
                def poll(self):return 0
                def send_signal(self,*unused):raise AssertionError('Never signal existing trials')
            def popen(command,**kwargs):
                spec=json.loads(Path(command[command.index('--spec')+1]).read_text())
                spawned.append(assignments[spec['question_id'],spec['repeat']])
                self.assertEqual(Path(command[1]).name,'run_bc_trial_v3_routes1.py');return Child()
            args=SimpleNamespace(limit=16,dispatch_role='cloud',concurrency=16)
            with patch.object(controller,'ROUTE_PLAN',route_plan),patch.object(controller,'ROOT',root),\
                 patch.object(controller,'acquire_claim',side_effect=claim),patch.object(controller,'validate_sources'),\
                 patch.object(controller,'job_state',side_effect=lambda p:'unfinished' if str(p.relative_to(root/'jobs')) in claimed else 'pending'),\
                 patch.object(controller.subprocess,'Popen',side_effect=popen),patch.object(controller.signal,'signal'),patch.object(controller.time,'sleep'):
                policy=controller.DispatchPolicy(path,'cloud')
                result=controller.dispatch_loop(args,root,{'definition':{'cohort_sha256':'c'*64}},jobs,control,{},'test',policy)
            self.assertEqual(result['new_launches'],16);self.assertEqual(Counter(spawned),Counter({route:cap for route,cap in zip(ORDER,caps) if cap}))
            self.assertEqual(len(claimed),16)


if __name__=='__main__':unittest.main()
