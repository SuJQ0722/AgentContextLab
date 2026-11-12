"""Offline native turn-binding, cross-generation retry and dispatch checks."""
import ast,json,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch,Mock
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
import turns500_contract_v12 as policy
import run_turns500_trial_v12 as trial
from hermes_turns500_worker_v12 import checked_init
from dsh_turns500_worker_v12 import verify_observer
from one_hour_timeout_retry_v10 import VERSION as RETRY
from inline_route_contract_v2 import ROUTES

class TurnsTests(unittest.TestCase):
    def cfg(self):
        return {'one_hour_retry_version':RETRY,'turn_limit_version':policy.VERSION,'runtime_recovery_version':policy.RECOVERY_VERSION,
          'max_rounds':500,'max_attempts':3,'max_timeout_retries':2,'timeout_seconds':3600,'max_output_tokens':8192,
          'prior_attempts_consumed':0,'prior_attempt_costs':[],'model':ROUTES[0],
          'model_route_policy':'four-route-rotation-v1','approved_model_routes':ROUTES,
          'image_transport':'inline-recent-ten-chunked-v1','transport_delivery_version':'inline-direct-v1',
          'transport_runtime_version':'visual-transport-runtime-v4','gateway_proxy':'http://10.120.0.246:7890',
          **{section:{'max_rounds':500,'timeout_seconds':3600}for section in policy.SECTIONS}}
    def test_reject_partial_limits_or_reset_prior_ledger(self):
        c=self.cfg();policy.validate(c,c)
        for section in policy.SECTIONS:
            bad={**c,section:{'max_rounds':60,'timeout_seconds':3600}}
            with self.assertRaises(ValueError):policy.validate(c,bad)
        for change in [{'max_rounds':500.0},{'max_attempts':4},{'prior_attempts_consumed':1},
                       {'prior_attempts_consumed':0,'prior_attempt_costs':[{'result_path':'old'}]},
                       {'prior_attempts_consumed':2,'prior_attempt_costs':[{'result_path':'x'},{'result_path':'x'}]}]:
            with self.assertRaises(ValueError):policy.validate({**c,**change},c)
    def test_final_native_source_expressions_use_500(self):
        cfg=self.cfg()
        tree=ast.parse((ROOT/'scripts/hermes_bc_worker_v3.py').read_text());values=[]
        for node in ast.walk(tree):
            if isinstance(node,ast.Call)and isinstance(node.func,ast.Name)and node.func.id=='AIAgent':
                values.extend(k.value for k in node.keywords if k.arg=='max_iterations')
        self.assertEqual(len(values),1)
        self.assertEqual(eval(compile(ast.Expression(values[0]),'<native-hermes>','eval'),{'cfg':cfg}),500)
        tree=ast.parse((ROOT/'scripts/run_dsh_eval_v3.py').read_text());values=[]
        for node in ast.walk(tree):
            if isinstance(node,ast.Dict):values.extend(v for k,v in zip(node.keys,node.values)if isinstance(k,ast.Constant)and k.value=='maxSteps')
        self.assertEqual(len(values),1)
        self.assertEqual(eval(compile(ast.Expression(values[0]),'<native-dsh>','eval'),{'cfg':cfg,'args':SimpleNamespace(dataset='bc100')}),500)
    def test_actual_constructor_observer_writes_bound_limit(self):
        with tempfile.TemporaryDirectory()as d:
            class Agent:pass
            seen=[]
            def init(self,**kw):seen.append(kw);self.max_iterations=kw['max_iterations']
            wrapped=checked_init(init,d);obj=Agent();wrapped(obj,max_iterations=500)
            self.assertEqual(seen,[{'max_iterations':500}]);r=json.loads((Path(d)/'metrics/turn-limit-binding-v12.json').read_text());self.assertEqual(r['actual_agent_max_iterations'],500)
            with self.assertRaises(ValueError):wrapped(obj,max_iterations=60)
    def test_actual_dsh_observer_config_is_checked(self):
        with tempfile.TemporaryDirectory()as d:
            p=Path(d);w=p/'workspace';w.mkdir();f=p/'evaluation.patch.json'
            f.write_text(json.dumps([{'insert':[{'id':'acl-evaluation','config':{'maxSteps':500}}]}]));verify_observer({'ACL_WORKSPACE':str(w)})
            self.assertEqual(json.loads((w/'metrics/turn-limit-binding-v12.json').read_text())['actual_evaluation_maxSteps'],500)
            f.write_text(json.dumps([{'insert':[{'id':'acl-evaluation','config':{'maxSteps':60}}]}]))
            with self.assertRaises(ValueError):verify_observer({'ACL_WORKSPACE':str(w)})
    def test_all_eight_baselines_use_actual_turn_observer_entry(self):
        with tempfile.TemporaryDirectory()as d:
            p=Path(d);cfg=self.cfg();f=p/'cfg.json';f.write_text(json.dumps(cfg))
            for harness in ['hermes','dsh']:
                for strategy in ['none','discard','summarize','sliding_window']:
                    s={**cfg,'harness':harness,'strategy':strategy,'question_id':'q','repeat':1,'campaign_root':str(p),
                       'config_path':str(f),'_spec_path':str(p/'spec'),'cohort_sha256':'c','native_cohort_path':str(p/'cohort'),'native_cohort_sha256':'c'}
                    cmd,_,seconds=trial.native_command(s,p/'out');self.assertEqual(Path(cmd[1]).name,harness+'_turns500_worker_v12.py');self.assertEqual(seconds,3600)
    def test_cross_generation_prior_two_allows_only_one_more(self):
        with tempfile.TemporaryDirectory()as d:
            p=Path(d);cfg=self.cfg();f=p/'cfg.json';f.write_text(json.dumps(cfg));s={**cfg,'job_id':'j','config_path':str(f),'prior_attempts_consumed':2,
                 'prior_attempt_costs':[{'result_path':'v10/native/result.json'},{'result_path':'v11/native/result.json'}]};calls=[]
            def run(path,spec,a,n,parent):
                calls.append(n);(a/'result.json').write_text(json.dumps({'job_id':'j','status':'timeout','attempt_number':n,'one_hour_retry_version':RETRY,
                    'native_cleanup_confirmed':True,'unconfirmed_child_termination':[],'end_to_end_seconds':3600,'native_artifact_root':str(a/'native')}))
            r=trial.execute(p/'spec',s,p,runner=run,should_stop=lambda _:False);self.assertEqual(calls,[1]);self.assertEqual(r['total_attempts_including_prior'],3)
            self.assertEqual(len(r['prior_attempt_costs']),2);self.assertEqual(r['turn_limit_version'],policy.VERSION);self.assertEqual(r['max_rounds'],500)
    def test_non_timeout_never_retries(self):
        with tempfile.TemporaryDirectory()as d:
            p=Path(d);cfg=self.cfg();f=p/'cfg';f.write_text(json.dumps(cfg));s={**cfg,'job_id':'j','config_path':str(f)};calls=[]
            def run(path,spec,a,n,parent):
                calls.append(n);(a/'result.json').write_text(json.dumps({'job_id':'j','status':'failed','failure_category':'output_limit','attempt_number':n,'one_hour_retry_version':RETRY,'native_cleanup_confirmed':True,'unconfirmed_child_termination':[],'native_artifact_root':str(a/'native')}))
            r=trial.execute(p/'spec',s,p,runner=run,should_stop=lambda _:False);self.assertEqual(calls,[1]);self.assertEqual(r['retry_stop_reason'],'not_timeout')
