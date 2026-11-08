import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock,patch

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
import bc_route_runtime_v1 as routes
import run_bc_trial_v3_routes1 as trial
import run_bc_trial_v3 as frozen

OLD='deepseek-v4.1-flash-1017/huoshan/huoshan'
NEW='deepseek-v4.1-flash-1017/zijian/sfb'


class RouteTests(unittest.TestCase):
    def fixture(self,td):
        root=Path(td);jobs=[]
        for q in ['q_001','q_002']:
            for harness in ['hermes','dsh']:
                jobs.append({'job_id':f'{harness}/visual/{q}_r01','question_id':q,'repeat':1,
                    'harness':harness,'strategy':'visual','model':OLD,'question':'fixture','timeout_seconds':60})
        (root/'plan.json').write_text(json.dumps({'jobs':jobs}))
        cfg={'model':OLD,'execution_version':'hermes-parity-v3','max_output_tokens':8192,'nested':{'unchanged':[1,2]}}
        (root/'experiment.json').write_text(json.dumps(cfg))
        data={'version':routes.VERSION,'parent_plan_sha256':routes.sha(root/'plan.json'),'logical_model':OLD,
              'allowed_routes':[OLD,NEW],'assignments':[{'question_id':q,'repeat':1,'actual_route':NEW} for q in ['q_001','q_002']]}
        path=root/'route-plan-v1.json';path.write_text(json.dumps(data));expected=routes.sha(path)
        (root/'route-plan-v1.sha256').write_text(expected+'\n')
        return root,jobs,data,routes.RoutePlan(root)

    def test_shared_pair_route_and_legacy_claim_anchor(self):
        with tempfile.TemporaryDirectory() as td:
            root,jobs,data,plan=self.fixture(td)
            self.assertEqual(plan.assignment(jobs[0]),plan.assignment(jobs[1]))
            claim=root/'jobs'/jobs[0]['job_id']/'claim';claim.mkdir(parents=True)
            (claim/'owner.json').write_text(json.dumps({'job_id':jobs[0]['job_id']}))
            with self.assertRaisesRegex(ValueError,'anchored'):plan.assignment(jobs[1])
            (claim/'owner.json').write_text(json.dumps({**plan.claim_metadata(jobs[2]),'job_id':jobs[0]['job_id']}))
            self.assertEqual(plan.assignment(jobs[1]),NEW)

    def test_duplicate_missing_and_wrong_family_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root,jobs,data,plan=self.fixture(td);path=root/'route-plan-v1.json'
            for bad in [{**data,'assignments':data['assignments'][:1]},
                        {**data,'assignments':data['assignments']+[data['assignments'][0]]},
                        {**data,'allowed_routes':[OLD,'deepseek-v4.1-flash-0910/huoshan/huoshan']}]:
                path.write_text(json.dumps(bad))
                with self.assertRaises(ValueError):routes.RoutePlan(root,path,routes.sha(path))

    def test_hot_change_and_new_hash_after_binding_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root,jobs,data,plan=self.fixture(td);plan.bind()
            data['assignments'][0]['actual_route']=OLD;path=root/'route-plan-v1.json';path.write_text(json.dumps(data))
            with self.assertRaises(ValueError):plan.assignment(jobs[0])
            changed=routes.RoutePlan(root,path,routes.sha(path))
            with self.assertRaisesRegex(ValueError,'Immutable'):changed.bind()

    def test_original_inputs_unchanged_and_only_native_model_diff(self):
        with tempfile.TemporaryDirectory() as td:
            root,jobs,data,plan=self.fixture(td);out=root/'attempt';out.mkdir()
            spec={**jobs[0],'config_path':str(root/'experiment.json'),'campaign_root':str(root)}
            source=root/'original-spec.json';source.write_text(json.dumps(spec));original_hash=routes.sha(source)
            spec['_spec_path']=str(source);cfg_hash=routes.sha(root/'experiment.json')
            with patch.object(routes,'implementation_hashes',return_value={'fixture':'a'*64}):
                runtime,lineage=routes.prepare_runtime(spec,out,plan)
            self.assertEqual(routes.sha(source),original_hash);self.assertEqual(routes.sha(root/'experiment.json'),cfg_hash)
            self.assertEqual({k for k in spec if spec[k]!=runtime[k]},{'model','config_path','_spec_path'})
            derived=json.loads(Path(runtime['config_path']).read_text());original=json.loads((root/'experiment.json').read_text())
            self.assertEqual({k for k in original if original[k]!=derived[k]},{'model'})
            self.assertEqual(lineage['logical_model'],OLD);self.assertEqual(lineage['actual_route'],NEW)
            with self.assertRaises(ValueError):routes.immutable_json(out/'runtime-config.json',{})

    def test_validation_failure_does_not_prepare_or_launch(self):
        with tempfile.TemporaryDirectory() as td:
            original=Mock(side_effect=ValueError('original frozen validation failed'));prepared={}
            with patch.object(trial,'RoutePlan') as constructor:
                with self.assertRaises(ValueError):trial.validated_runtime(original,prepared)({},Path(td))
                constructor.assert_not_called()
            self.assertEqual(prepared,{})
            with self.assertRaises(ValueError):trial.routed_native_command(Mock(),prepared)({},Path(td))

    def test_routes_use_derived_spec_and_config_only_after_prepare(self):
        with tempfile.TemporaryDirectory() as td:
            root,jobs,data,plan=self.fixture(td);out=root/'attempt';out.mkdir()
            for job in jobs[:2]:
                spec={**job,'config_path':str(root/'experiment.json'),'campaign_root':str(root),'_spec_path':str(root/'original.json'),
                      'cohort_sha256':'c'*64}
                runtime={**spec,'model':NEW,'config_path':str(out/'runtime-config.json'),'_spec_path':str(out/'runtime-spec.json')}
                command,result,timeout=trial.routed_native_command(frozen.native_command,{'spec':runtime,'route_plan':plan})(spec,out)
                expected='hermes_bc_worker_routes1.py' if job['harness']=='hermes' else 'run_dsh_eval_v3_routes1.py'
                self.assertEqual(Path(command[1]).name,expected)
                self.assertIn(runtime['_spec_path'] if job['harness']=='hermes' else runtime['config_path'],command)

    def test_trial_main_validates_original_once_before_runtime_and_restores_bindings(self):
        with tempfile.TemporaryDirectory() as td:
            root,jobs,data,plan=self.fixture(td);out=root/'attempt';out.mkdir()
            job=jobs[0];metadata=plan.claim_metadata(job);claim=root/'jobs'/job['job_id']/'claim';claim.mkdir(parents=True)
            (claim/'owner.json').write_text(json.dumps({**metadata,'job_id':job['job_id']}))
            spec={**job,'config_path':str(root/'experiment.json'),'campaign_root':str(root),'cohort_sha256':'c'*64}
            source=root/'original-spec.json';source.write_text(json.dumps(spec));before=source.read_bytes();events=[]
            def validation(value,path):
                events.append('original_validation');self.assertEqual(value['model'],OLD)
                self.assertFalse((out/'route-lineage.json').exists());return root
            validator=Mock(side_effect=validation)
            def main():
                value={**spec,'_spec_path':str(source)};frozen.validate_spec(value,out)
                self.assertTrue((out/'route-lineage.json').exists());events.append('lineage')
                command,_,_=frozen.native_command(value,out);self.assertIn(str(out/'runtime-spec.json'),command)
                events.append('native_command')
            original_command=frozen.native_command
            with patch.object(frozen,'validate_spec',validator),patch.object(frozen,'main',main),patch.object(sys,'argv',['routes1']),patch.dict(os.environ,clear=False):
                trial.main();self.assertIs(frozen.native_command,original_command);self.assertIs(frozen.validate_spec,validator)
            validator.assert_called_once();self.assertEqual(events,['original_validation','lineage','native_command'])
            self.assertEqual(source.read_bytes(),before)


if __name__=='__main__':unittest.main()
