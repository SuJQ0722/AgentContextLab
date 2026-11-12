"""Offline integration: actual command routing, bytes, budgets and inherited retries."""
import base64,hashlib,io,json,os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch,Mock
from PIL import Image
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
import run_seven_retry3_trial_v11 as trial
import hermes_canvas_budget_worker_v11 as budget
from one_hour_timeout_retry_v10 import VERSION
from inline_route_contract_v2 import ROUTES

class RecoveryTests(unittest.TestCase):
    def contract(self):
        return {'one_hour_retry_version':VERSION,'runtime_recovery_version':budget.VERSION,
          'timeout_seconds':3600,'max_timeout_retries':2,'max_output_tokens':8192,
          'model':ROUTES[0],'model_route_policy':'four-route-rotation-v1','approved_model_routes':ROUTES,
          'image_transport':'inline-recent-ten-chunked-v1','transport_delivery_version':'inline-direct-v1',
          'transport_runtime_version':'visual-transport-runtime-v4','gateway_proxy':'http://10.120.0.246:7890'}
    def test_actual_eight_baseline_command_combinations(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);c=p/'config.json';cfg=self.contract();c.write_text(json.dumps(cfg))
            for harness in ['hermes','dsh']:
                for strategy in ['none','discard','summarize','sliding_window']:
                    spec={**cfg,'harness':harness,'strategy':strategy,'config_path':str(c),'question_id':'q',
                      'repeat':1,'campaign_root':str(p),'_spec_path':str(p/'spec'),'cohort_sha256':'fixture',
                      'native_cohort_path':str(p/'cohort'),'native_cohort_sha256':'native'}
                    cmd,_,limit=trial.native_command(spec,p/'out')
                    self.assertEqual(Path(cmd[1]).name,'hermes_baseline_retry3_v10.py'if harness=='hermes'else'dsh_retry3_worker_v11.py')
                    self.assertEqual(limit,3600)
                    if harness=='dsh':
                        self.assertEqual(cmd[cmd.index('--cohort-sha256')+1],'native')
                        self.assertEqual(cmd[cmd.index('--strategies')+1],'sliding_window_native'if strategy=='sliding_window'else strategy)
    def png(self,w,h):
        b=io.BytesIO();Image.frombytes('RGB',(w,h),os.urandom(w*h*3)).save(b,format='PNG');return b.getvalue()
    def image(self,raw):
        return {'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(raw).decode(),'detail':'high'}}
    def transform(self,parts,registry=()):
        raw=json.dumps({'model':ROUTES[0],'messages':[{'role':'user','content':parts}]}).encode()
        return raw,budget.transform(raw,rendered_registry=set(registry),max_images=10,
           page_budget={'history':5,'recent':2},max_canvas_pixels=2359296,max_body_bytes=3145728)
    def test_native_large_image_is_unchanged_and_not_canvas_charged(self):
        image=self.png(1024,1024);raw,(wire,audit)=self.transform([self.image(image)])
        self.assertGreater(len(raw),3145728);self.assertEqual(wire,raw)
        self.assertEqual(audit['canvas_budget_recovery']['canvas_base64_bytes'],0)
        self.assertEqual(audit['canvas_budget_recovery']['native_images_excluded_from_canvas_budget'],1)
    def pages(self,size):
        raw=self.png(size,size);parts=[]
        for segment,n in [('History',5),('Recent',2)]:
            for index in range(1,n+1):
                parts += [{'type':'text','text':f'[{segment} page {index}/{n} — linear scale 0.75, high detail]'},self.image(raw)]
        return raw,parts
    def test_seven_canvas_pages_above_three_mib_are_measured_not_rejected(self):
        raw,parts=self.pages(32);_,(wire,audit)=self.transform(parts,[hashlib.sha256(raw).hexdigest()])
        b=audit['canvas_budget_recovery'];self.assertEqual(b['verified_canvas_count'],7)
        self.assertEqual(b['canvas_base64_bytes'],7*4*((len(raw)+2)//3))
        raw,parts=self.pages(500)
        _,(_,audit)=self.transform(parts,[hashlib.sha256(raw).hexdigest()])
        self.assertGreater(audit['canvas_budget_recovery']['canvas_base64_bytes'],3*1024*1024)
        self.assertIsNone(audit['canvas_budget_recovery']['canvas_base64_limit'])
    def test_total_request_32mib_still_fails_closed(self):
        with patch.object(budget,'_ORIGINAL_TRANSFORM',side_effect=ValueError('request too large'))as f:
            with self.assertRaises(ValueError):budget.transform(b'{}')
        self.assertEqual(f.call_args.kwargs['max_body_bytes'],32*1024*1024)
    def test_prior_real_attempt_consumption_limits_new_retries_and_retains_costs(self):
        with tempfile.TemporaryDirectory()as d:
            p=Path(d);spec={'job_id':'j','prior_attempts_consumed':2,'prior_attempt_costs':['prior-native']};calls=[]
            def run(path,s,a,n,parent):
                calls.append(n);(a/'result.json').write_text(json.dumps({'job_id':'j','status':'timeout','attempt_number':n,
                  'one_hour_retry_version':VERSION,'native_cleanup_confirmed':True,'unconfirmed_child_termination':[],
                  'native_artifact_root':str(a/'native'),'end_to_end_seconds':3600}))
            r=trial.execute(p/'spec',spec,p,runner=run,should_stop=lambda _:False)
            self.assertEqual(calls,[1]);self.assertEqual(r['total_attempts_including_prior'],3)
            self.assertEqual(r['prior_attempt_costs'],['prior-native']);self.assertEqual(r['max_total_model_attempts'],3)
            self.assertEqual(trial.base.MAX_ATTEMPTS,3)
    def test_exhausted_or_invalid_prior_never_launches(self):
        runner=Mock();r=trial.execute(Path('x'),{'job_id':'j','prior_attempts_consumed':3},Path('none'),runner=runner)
        runner.assert_not_called();self.assertEqual(r['api_calls'],0)
        for n in [-1,4,True,1.0]:
            with self.assertRaises(ValueError):trial.prior_attempts({'prior_attempts_consumed':n})

    def test_new_bootstrap_accepts_unchanged_retry3_protocol(self):
        import bootstrap_seven_retry3_v11 as boot
        with tempfile.TemporaryDirectory() as d:
            cfg=Path(d)/'config.json';cfg.write_text(json.dumps(self.contract()))
            plan={'definition':{'one_hour_retry_version':VERSION},'jobs':[{**self.contract(),'config_path':str(cfg)}]}
            with patch('prepare_visual_hosted_retry_v1.load_validate',return_value=(plan,{})):
                actual,_=boot.load_validate(Path(d))
            self.assertEqual(actual,plan)
            self.assertEqual(boot.DEFAULT_ROOT.name,'seven-page-runtime-v11')

    def test_dsh_bridge_obeys_environment_32mib_config(self):
        import dsh_inline_transport_bridge_v1 as bridge
        cfg={'canvas_max_pixels':2359296,'max_request_bytes':32*1024*1024}
        request={'id':'fixture','body':'{}'};wire=[]
        def transform(body,**kw):wire.append(kw);return b'{}',{}
        with tempfile.TemporaryDirectory()as d,patch.object(sys,'argv',['bridge','--canvas-root',d]),patch.object(sys,'stdin',io.StringIO(json.dumps(request)+'\n')),patch.object(sys,'stdout',io.StringIO()),patch.dict(os.environ,{'ACL_INLINE_VISUAL_LIMITS':json.dumps(cfg),'ACL_PAGE_WINDOW_RENDERER':'null'}),patch.object(bridge,'transform',transform):bridge.main()
        self.assertEqual(wire[0]['max_body_bytes'],33554432)
