"""Offline behavior checks for bounded sequential timeout recovery and SDK binding."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import one_hour_timeout_retry_v10 as policy
import run_seven_retry3_trial_v10 as worker
import dsh_inline_bc_worker_v7 as dsh
from dsh_image_preservation import preservation_patches
from inline_route_contract_v2 import ROUTES
from lab import runtime_path


class RetryTests(unittest.TestCase):
    def spec(self):
        return {'job_id':'hermes/visual/q_fixture_r01','harness':'hermes','strategy':'visual','question_id':'q_fixture',
                'repeat':1,'model':ROUTES[0],'one_hour_retry_version':policy.VERSION,
                'timeout_seconds':3600,'max_timeout_retries':2}

    def result(self, spec, out, number, status='timeout', **kwargs):
        row = {**spec,'status':status,'attempt_number':number,'native_cleanup_confirmed':True,
               'unconfirmed_child_termination':[],'end_to_end_seconds':3600 if status=='timeout' else 20,
               'native_artifact_root':str(out/'native'),'native_result_path':str(out/'native/result.json'),
               'slot_released':False, 'score':0, **kwargs}
        (out/'result.json').write_text(json.dumps(row))
        return row

    def run_fake(self, spec, out, statuses, **kwargs):
        calls=[]
        def run(path, value, attempt, number, parent):
            calls.append(number)
            self.assertEqual(len(calls),number)
            self.assertFalse((parent/'result.json').exists())
            if number>1:
                previous=parent/'runs'/f'attempt_{number-1:03d}'/'result.json'
                self.assertEqual(json.loads(previous.read_text())['status'],'timeout')
            self.result(value,attempt,number,statuses[min(number-1,len(statuses)-1)],**kwargs)
        result=worker.execute(Path('fixture.json'),spec,out,runner=run,should_stop=lambda s:False)
        return calls,result

    def test_contract_rejects_ambiguous_deadlines_and_retry_counts(self):
        spec=self.spec();config={**spec,'max_output_tokens':8192}
        policy.validate(spec,config)
        for key,values in [('timeout_seconds',[1800,7200,3600.0,True]),('max_timeout_retries',[1,3,5,2.0,True])]:
            for value in values:
                with self.subTest(key=key,value=value),self.assertRaises(ValueError):
                    policy.validate({**spec,key:value},config)

    def test_exactly_three_serial_attempts_all_artifacts_and_elapsed_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory);calls,result=self.run_fake(self.spec(),out,['timeout'])
            self.assertEqual(calls,list(range(1,4)))
            self.assertEqual(result['timeout_retries_used'],2)
            self.assertEqual(result['retry_stop_reason'],'timeout_retries_exhausted')
            self.assertEqual(result['end_to_end_seconds'],10800)
            self.assertEqual(len(result['attempts']),3)
            self.assertEqual(len(set(result['usage_attempt_paths'])),3)
            for item in result['attempts']:
                self.assertEqual(worker.trial.digest(Path(item['result_path']).read_bytes()),item['result_sha256'])
            self.assertIn('one question-repeat',result['statistical_unit'])
            self.assertIsNone(result['score'])

    def test_completed_wrong_failed_and_interrupted_never_retry(self):
        for status in ['completed','failed','interrupted','not_started']:
            with self.subTest(status=status),tempfile.TemporaryDirectory() as directory:
                calls,result=self.run_fake(self.spec(),Path(directory),[status])
                self.assertEqual(calls,[1]);self.assertEqual(result['status'],status)

    def test_unknown_cleanup_never_retries_and_unknown_latency_is_not_zero(self):
        for kwargs in [{'native_cleanup_confirmed':False},{'unconfirmed_child_termination':[{'pid':123}]},
                       {'native_cleanup_confirmed':None}]:
            with tempfile.TemporaryDirectory() as directory:
                calls,result=self.run_fake(self.spec(),Path(directory),['timeout'],end_to_end_seconds=None,**kwargs)
                self.assertEqual(calls,[1]);self.assertEqual(result['retry_stop_reason'],'cleanup_unconfirmed')
                self.assertIsNone(result['end_to_end_seconds'])

    def test_resume_keeps_prior_timeout_and_stops_at_first_completed_even_wrong(self):
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory);spec=self.spec();prior=out/'runs/attempt_001';prior.mkdir(parents=True)
            self.result(spec,prior,1);saved=(prior/'result.json').read_bytes();calls=[]
            def run(path,value,attempt,number,parent):
                calls.append(number);self.result(value,attempt,number,'completed',score=0)
            result=worker.execute(Path('fixture'),spec,out,runner=run,should_stop=lambda s:False)
            self.assertEqual(calls,[2]);self.assertEqual(result['end_to_end_seconds'],3620)
            self.assertEqual((prior/'result.json').read_bytes(),saved)
            second=worker.execute(Path('fixture'),spec,out,runner=lambda *a:self.fail('Completed attempt replayed'),should_stop=lambda s:False)
            self.assertEqual(second['attempt_count'],2)

    def test_incomplete_attempt_blocks_resume_and_stop_blocks_new_attempt(self):
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory);attempt=out/'runs/attempt_001';attempt.mkdir(parents=True)
            (attempt/'worker-started.json').write_text('{}');runner=Mock()
            with self.assertRaisesRegex(RuntimeError,'incomplete'):
                worker.execute(Path('fixture'),self.spec(),out,runner=runner,should_stop=lambda s:False)
            runner.assert_not_called()
        with tempfile.TemporaryDirectory() as directory:
            runner=Mock();result=worker.execute(Path('fixture'),self.spec(),Path(directory),runner=runner,should_stop=lambda s:True)
            runner.assert_not_called();self.assertEqual(result['status'],'not_started')

    def test_deadline_evidence_does_not_treat_generic_error_as_timeout(self):
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory);metrics=out/'native/metrics';metrics.mkdir(parents=True)
            file=metrics/'inline-images-wire-dsh-v1.jsonl'
            file.write_text(json.dumps({'event':'route_transport_error','error_type':'AbortError'})+'\n')
            self.assertIsNone(worker.deadline_evidence(out))
            with file.open('a') as stream:stream.write(json.dumps({'event':'trial_transport_deadline','at_unix':123})+'\n')
            self.assertEqual(worker.deadline_evidence(out)['event'],'trial_transport_deadline')


    def test_old_generation_contract_and_attempt_cannot_be_reused(self):
        import one_hour_timeout_retry_v1 as old
        spec=self.spec(); config={**spec,'max_output_tokens':8192}
        with self.assertRaises(ValueError): old.validate(spec,config)
        with self.assertRaises(ValueError): policy.validate({**spec,'one_hour_retry_version':old.VERSION},config)
        self.assertEqual(old.MAX_ATTEMPTS,6)
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory);a=out/'runs/attempt_001';a.mkdir(parents=True)
            self.result(spec,a,1,one_hour_retry_version=old.VERSION)
            with self.assertRaisesRegex(ValueError,'identity'):
                worker.execute(Path('fixture'),spec,out,runner=Mock(),should_stop=lambda _:False)

    def test_baseline_wrappers_restore_historical_module_defaults(self):
        import hermes_baseline_retry3_v10 as hb
        import dsh_retry3_worker_v10 as dw
        import one_hour_timeout_retry_v1 as old
        original=hb.worker.validate
        with patch.object(hb.worker,'main',side_effect=lambda: self.assertIs(hb.worker.validate,policy.validate)):
            hb.main()
        self.assertIs(hb.worker.validate,original)
        with tempfile.TemporaryDirectory() as directory:
            cfg=Path(directory)/'cfg.json';cfg.write_text(json.dumps({**self.spec(),'max_output_tokens':8192}))
            def check(): self.assertEqual(dw.baseline.VERSION,policy.VERSION)
            with patch.object(sys,'argv',['worker','--config',str(cfg),'--timeout','3600']),patch.object(dw.recovery,'main',side_effect=check):dw.main()
        self.assertEqual(dw.baseline.VERSION,old.VERSION)

    def test_dsh_visual_command_uses_v9_repair_wrapper(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);cfg=root/'cfg.json';cfg.write_text(json.dumps({**self.spec(),'max_output_tokens':8192}))
            spec={**self.spec(),'config_path':str(cfg)}
            old=[sys.executable,str(ROOT/'scripts/dsh_hosted_bc_worker_v1.py'),'--strategies','visual_native']
            with patch.object(worker,'validate_routes'),patch.object(worker.native,'native_command',return_value=(old,root/'result',3600)):
                cmd,_,deadline=worker.native_command(spec,root)
            self.assertEqual(Path(cmd[1]).name,'dsh_retry3_worker_v10.py');self.assertEqual(deadline,3600)

    def test_bootstrap_is_new_generation_and_keeps_readiness_wrapper(self):
        import bootstrap_seven_retry3_v10 as b
        args=Mock(reader_python='python',root=Path('/fixture'),harness='hermes')
        cmd=b.commands(args)['controller']
        self.assertEqual(Path(cmd[1]).name,'run_seven_transport_v10.py')
        self.assertEqual(b.DEFAULT_ROOT.name,'seven-page-retry3-v10')
        with patch('prepare_visual_hosted_retry_v1.load_validate',return_value=({'definition':{'one_hour_retry_version':'visual-inline-one-hour-retry5-v8'},'jobs':[]},{})):
            with self.assertRaises(ValueError):b.load_validate(Path('/fixture'))
