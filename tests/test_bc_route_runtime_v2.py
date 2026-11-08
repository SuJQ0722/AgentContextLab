import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
import bc_route_runtime_v1 as v1
import bc_route_runtime_v2 as v2
import run_bc_trial_v3_routes2 as trial
import run_bc_campaign_v3_routes2 as controller

OLD='deepseek-v4.1-flash-1017/huoshan/huoshan'
GOOD='deepseek-v4.1-flash-1017/zijian/sfb'
BAD='deepseek-v4.1-flash-1017/huoshan/sfc'


def put(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value));return path


class RevisionTests(unittest.TestCase):
    def fixture(self,temporary):
        root=Path(temporary);jobs=[]
        for q in ['old','good','bad']:
            for h in ['hermes','dsh']:
                jobs.append({'job_id':f'{h}/visual/{q}_r01','question_id':q,'repeat':1,'harness':h,
                             'strategy':'visual','model':OLD,'question':'offline fixture','timeout_seconds':60})
        put(root/'plan.json',{'jobs':jobs});put(root/'experiment.json',{'model':OLD,'max_output_tokens':8192})
        parent={'version':v1.VERSION,'parent_plan_sha256':v1.sha(root/'plan.json'),'logical_model':OLD,
                'allowed_routes':sorted(v1.ROUTES),'assignments':[{'question_id':q,'repeat':1,'actual_route':route}
                    for q,route in [('old',OLD),('good',GOOD),('bad',BAD)]]}
        pp=put(root/'route-plan-v1.json',parent);parent_plan=v1.RoutePlan(root,pp,v1.sha(pp));parent_plan.bind()
        identity={'hostname':'fixture','boot_id':'b','pid_namespace':'pid:[1]','pid':12,'start_identity':'123','stop_dispatch':True}
        status=put(root/'controllers/old/status.json',identity);snapshot=put(root/'cutover/old.json',identity)
        config=put(root/'cutover/dispatch.json',{'per_route_cloud_caps':{r:0 for r in v2.MIGRATABLE_ROUTES},
                                               'per_route_local_caps':{r:0 for r in v2.MIGRATABLE_ROUTES}})
        ack=put(root/'cutover/ack.json',{'schema':'routes2-dispatch-cutover-v1','parent_route_plan_sha256':v1.sha(pp),
                'dispatch_config_path':str(config),'dispatch_config_sha256':v1.sha(config),
                'controller_statuses':[{'source_path':str(status),'snapshot_path':str(snapshot),'snapshot_sha256':v1.sha(snapshot)}]})
        data={**parent,'version':v2.VERSION,'parent_route_plan_path':str(pp),'parent_route_plan_sha256':v1.sha(pp),
              'revision_reason':'Two rejected sfc routes moved only before any pair claim',
              'cutover_ack_path':str(ack),'cutover_ack_sha256':v1.sha(ack),
              'assignments':[{**row,'actual_route':GOOD if row['actual_route']==BAD else row['actual_route']} for row in parent['assignments']]}
        path=put(root/'route-plan-v2.json',data)
        return root,jobs,data,parent_plan,v2.RoutePlanV2(root,path,v2.sha(path))

    def claim(self,root,job,metadata):
        return put(root/'jobs'/job['job_id']/'claim/owner.json',{'job_id':job['job_id'],**metadata})

    def reload(self,root,data):
        path=put(root/'route-plan-v2.json',data);return v2.RoutePlanV2(root,path,v2.sha(path))

    def test_parent_artifacts_and_native_input_preserved_with_independent_binding(self):
        with tempfile.TemporaryDirectory() as td:
            root,jobs,data,parent,plan=self.fixture(td)
            original={p:p.read_bytes() for p in [root/'plan.json',root/'experiment.json',parent.path,root/'runtime/routes1-plan-binding.json']}
            plan.bind();job=jobs[-1];self.claim(root,job,plan.claim_metadata(job))
            out=root/'attempt';out.mkdir();spec={**job,'config_path':str(root/'experiment.json'),'campaign_root':str(root)}
            source=put(root/'original-spec.json',spec);spec['_spec_path']=str(source)
            runtime,lineage=v2.prepare_runtime(spec,out,plan)
            self.assertEqual(runtime['model'],GOOD);self.assertEqual(lineage['parent_route_plan_sha256'],parent.expected_sha256)
            self.assertTrue(set(v1.SOURCE_FILES)<=set(lineage['implementation_sha256']))
            self.assertIn('scripts/bc_route_runtime_v2.py',lineage['implementation_sha256'])
            for p,b in original.items():self.assertEqual(p.read_bytes(),b)
            for p in [root/'runtime/routes1-plan-binding.json',root/'runtime/routes2-plan-binding.json']:self.assertTrue(p.exists())
            resumed=v2.RoutePlanV2(root,plan.path,plan.expected_sha256);resumed.bind()
            self.assertEqual(resumed.assignment(jobs[-2]),GOOD)

    def test_changed_pair_any_parent_claim_or_empty_claim_or_attempt_rejected(self):
        for kind in ['parent','empty_claim','attempt']:
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as td:
                root,jobs,data,parent,plan=self.fixture(td);job=jobs[-1]
                if kind=='parent':self.claim(root,job,parent.claim_metadata(job))
                else:(root/'jobs'/job['job_id']/('claim' if kind=='empty_claim' else 'attempts')).mkdir(parents=True)
                with self.assertRaises((ValueError,FileNotFoundError)):plan.bind()
                self.assertFalse(plan.binding_path.exists())

    def test_only_sfc_to_sfb_revision_and_exact_allowlist_allowed(self):
        with tempfile.TemporaryDirectory() as td:
            root,jobs,data,parent,plan=self.fixture(td)
            bad={**data,'assignments':[{**r,'actual_route':GOOD} for r in data['assignments']]}
            with self.assertRaisesRegex(ValueError,'Only unclaimed'):self.reload(root,bad)
            with self.assertRaisesRegex(ValueError,'allowlist'):self.reload(root,{**data,'allowed_routes':[OLD,GOOD]})

    def test_parent_claim_unchanged_accepted_but_unprepared_sibling_waits(self):
        with tempfile.TemporaryDirectory() as td:
            root,jobs,data,parent,plan=self.fixture(td);job=jobs[2];self.claim(root,job,parent.claim_metadata(job))
            plan.bind();self.assertEqual(plan.assignment(jobs[3]),GOOD)
            with self.assertRaises(v2.ParentPreparationPending):plan.claim_metadata(jobs[3])
            attempt=root/'jobs'/job['job_id']/'attempts/attempt_001'
            put(attempt/'route-lineage.json',{'route_plan_sha256':parent.expected_sha256,'actual_route':GOOD,'job_id':job['job_id']})
            with self.assertRaises(v2.ParentPreparationPending):plan.claim_metadata(jobs[3])
            put(attempt/'worker-started.json',{'started_at':'fixture'})
            self.assertEqual(plan.claim_metadata(jobs[3])['route_plan_sha256'],plan.expected_sha256)

    def test_terminal_parent_sibling_needs_no_reexecution(self):
        with tempfile.TemporaryDirectory() as td:
            root,jobs,data,parent,plan=self.fixture(td);self.claim(root,jobs[2],parent.claim_metadata(jobs[2]));plan.bind()
            put(root/'jobs'/jobs[2]['job_id']/'attempts/attempt_001/result.json',{'status':'running'})
            with self.assertRaises(v2.ParentPreparationPending):plan.claim_metadata(jobs[3])
            put(root/'jobs'/jobs[2]['job_id']/'attempts/attempt_001/result.json',{'status':'failed'})
            self.assertEqual(plan.claim_metadata(jobs[3])['runtime_route_version'],v2.VERSION)

    def test_wrong_parent_hash_and_partial_routed_claim_fail_closed(self):
        for metadata in [{'actual_route':GOOD,'logical_model':OLD,'route_plan_sha256':'f'*64}, {'route_plan_sha256':'f'*64}]:
            with self.subTest(metadata=metadata),tempfile.TemporaryDirectory() as td:
                root,jobs,data,parent,plan=self.fixture(td);self.claim(root,jobs[2],metadata)
                with self.assertRaises(ValueError):plan.bind()

    def test_modified_parent_or_existing_new_binding_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root,jobs,data,parent,plan=self.fixture(td);plan.bind()
            plan.path.write_text(plan.path.read_text()+' ')
            with self.assertRaises(ValueError):plan.check_unchanged()
            with self.assertRaisesRegex(ValueError,'routes2 binding'):v2.RoutePlanV2(root,plan.path,v2.sha(plan.path))
        with tempfile.TemporaryDirectory() as td:
            root,jobs,data,parent,plan=self.fixture(td);parent.path.write_text(parent.path.read_text()+' ')
            with self.assertRaises(ValueError):plan.check_unchanged()

    def test_cutover_live_stop_required_and_all_controllers_covered(self):
        for mode in ['resumed','omitted']:
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as td:
                root,jobs,data,parent,plan=self.fixture(td)
                p=root/'controllers/old/status.json' if mode=='resumed' else root/'controllers/unlisted/status.json'
                put(p,{'stop_dispatch':mode!='resumed'})
                with self.assertRaises(ValueError):plan.bind()
                self.assertFalse(plan.binding_path.exists())

    def test_inactive_local_exception_needs_proven_gone_identity(self):
        for gone in [True,False]:
            with self.subTest(gone=gone),tempfile.TemporaryDirectory() as td:
                root,jobs,data,parent,plan=self.fixture(td)
                status=put(root/'controllers/inactive/status.json',{'stop_dispatch':False,'pid':99,'start_identity':'456'})
                snap=put(root/'cutover/inactive.json',json.loads(status.read_text()));ack=json.loads(plan.cutover_ack_path.read_text())
                ack['inactive_local_controllers']=[{'source_path':str(status),'snapshot_path':str(snap),'snapshot_sha256':v2.sha(snap)}]
                put(plan.cutover_ack_path,ack);data['cutover_ack_sha256']=v2.sha(plan.cutover_ack_path);plan=self.reload(root,data)
                with patch.object(v2,'same_host',return_value=True),patch.object(v2,'owner_alive',return_value=not gone):
                    if gone:plan.bind()
                    else:
                        with self.assertRaises(ValueError):plan.bind()

    def test_controller_defers_old_unprepared_pair_without_new_claim(self):
        with tempfile.TemporaryDirectory() as td:
            root,jobs,data,parent,plan=self.fixture(td);self.claim(root,jobs[2],parent.claim_metadata(jobs[2]));plan.bind()
            with patch.object(controller,'ROUTE_PLAN',plan),patch.object(controller,'ORIGINAL_ACQUIRE_CLAIM') as acquire:
                self.assertIsNone(controller.acquire_claim(root,jobs[3],{}));acquire.assert_not_called()
            self.assertFalse((root/'jobs'/jobs[3]['job_id']/'claim').exists())

    def test_actual_controller_claim_uses_original_slots_and_new_identity_once(self):
        with tempfile.TemporaryDirectory() as td:
            root,jobs,data,parent,plan=self.fixture(td);plan.bind();job=jobs[-1]
            with patch.object(controller,'ROUTE_PLAN',plan):
                jobdir,slot=controller.acquire_claim(root,job,{'controller_id':'offline'},cap=1)
                owner=json.loads((jobdir/'claim/owner.json').read_text())
                self.assertEqual(owner['actual_route'],GOOD)
                self.assertEqual(owner['route_plan_sha256'],plan.expected_sha256)
                self.assertEqual(owner['parent_route_plan_sha256'],parent.expected_sha256)
                self.assertEqual(slot,root/'cells/dsh/visual/slots/00')
                self.assertIsNone(controller.acquire_claim(root,job,{'controller_id':'other'},cap=1))
                self.assertEqual(json.loads((jobdir/'claim/owner.json').read_text()),owner)

    def test_trial_refuses_parent_claim_even_with_explicit_v2_override(self):
        with tempfile.TemporaryDirectory() as td:
            root,jobs,data,parent,plan=self.fixture(td);job=jobs[2];self.claim(root,job,parent.claim_metadata(job));plan.bind()
            spec={**job,'campaign_root':str(root)};out=root/'attempt';out.mkdir()
            wrapper=trial.validated_runtime(Mock(return_value=root),{},plan.path,plan.expected_sha256)
            with self.assertRaisesRegex(ValueError,'own new routes2 claim'):wrapper(spec,out)
            self.assertFalse((out/'route-lineage.json').exists())


if __name__=='__main__':unittest.main()
