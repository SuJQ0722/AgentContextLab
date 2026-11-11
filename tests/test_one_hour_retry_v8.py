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
import one_hour_timeout_retry_v1 as policy
import run_visual_inline_retry5_trial_v8 as worker
import dsh_inline_bc_worker_v7 as dsh
from dsh_image_preservation import preservation_patches
from inline_route_contract_v2 import ROUTES
from lab import runtime_path


class RetryTests(unittest.TestCase):
    def spec(self):
        return {'job_id':'hermes/visual/q_fixture_r01','harness':'hermes','strategy':'visual','question_id':'q_fixture',
                'repeat':1,'model':ROUTES[0],'one_hour_retry_version':policy.VERSION,
                'timeout_seconds':3600,'max_timeout_retries':5}

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
        for key,values in [('timeout_seconds',[1800,7200,3600.0,True]),('max_timeout_retries',[4,6,5.0,True])]:
            for value in values:
                with self.subTest(key=key,value=value),self.assertRaises(ValueError):
                    policy.validate({**spec,key:value},config)

    def test_exactly_six_serial_attempts_all_artifacts_and_elapsed_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory);calls,result=self.run_fake(self.spec(),out,['timeout'])
            self.assertEqual(calls,list(range(1,7)))
            self.assertEqual(result['timeout_retries_used'],5)
            self.assertEqual(result['retry_stop_reason'],'timeout_retries_exhausted')
            self.assertEqual(result['end_to_end_seconds'],21600)
            self.assertEqual(len(result['attempts']),6)
            self.assertEqual(len(set(result['usage_attempt_paths'])),6)
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

    def test_real_local_native_process_keeps_slot_and_mirrors_heartbeat(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);parent=root/'attempt_001';out=parent/'runs/attempt_001';out.mkdir(parents=True)
            spec={**self.spec(),'slot_path':str(root/'slot'),'config_path':str(root/'config.json')}
            spec_path=root/'spec.json';spec_path.write_text(json.dumps(spec));native_result=out/'native/native-result.json'
            code='import pathlib,json;pathlib.Path('+repr(str(native_result))+').write_text(json.dumps({"status":"completed","final":"fixture"}))'
            command=[sys.executable,'-c',code]
            with patch.object(worker,'validate_spec',return_value=root), \
                 patch.object(worker.trial,'environment',return_value=({'PATH':os.environ['PATH']},{})), \
                 patch('review_execution.enforce'), \
                 patch.object(worker,'native_command',return_value=(command,native_result,10)), \
                 patch.object(worker.trial,'release_slot') as release:
                worker.run_attempt(spec_path,spec,out,1,parent)
                release.assert_not_called()
            result=json.loads((out/'result.json').read_text())
            self.assertEqual(result['status'],'completed');self.assertTrue(result['native_cleanup_confirmed'])
            self.assertFalse(result['slot_released']);self.assertTrue(result['slot_held_for_question_retries'])
            self.assertEqual(json.loads((parent/'heartbeat.json').read_text())['attempt_number'],1)

    def test_main_releases_slot_only_after_durable_aggregate(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);out=root/'attempt_001';spec={**self.spec(),'config_path':str(root/'config.json'),'slot_path':str(root/'slot')}
            (root/'config.json').write_text(json.dumps({**spec,'max_output_tokens':8192}));path=root/'spec.json';path.write_text(json.dumps(spec))
            result={**spec,'status':'completed','native_cleanup_confirmed':True,'unconfirmed_child_termination':[], 'attempts':[{'status':'timeout'},{'status':'completed'}]}
            def release(slot):
                saved=json.loads((out/'result.json').read_text());self.assertEqual(saved['attempts'],result['attempts']);self.assertTrue(saved['slot_released'])
            with patch.object(sys,'argv',['worker','--spec',str(path),'--out',str(out),'--live']), \
                 patch.object(worker,'validate_routes'),patch.object(worker,'validate_spec'), \
                 patch.object(worker,'execute',return_value=result),patch.object(worker.trial,'release_slot',side_effect=release) as released:
                worker.main();released.assert_called_once()

    def test_stop_after_timeout_prevents_second_attempt(self):
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory);stop=[False];calls=[]
            def run(path,spec,attempt,number,parent):
                calls.append(number);self.result(spec,attempt,number);stop[0]=True
            result=worker.execute(Path('fixture'),self.spec(),out,runner=run,should_stop=lambda spec:stop[0])
            self.assertEqual(calls,[1]);self.assertEqual(result['retry_stop_reason'],'dispatch_stopped')

    def test_resume_foreign_attempt_identity_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory);attempt=out/'runs/attempt_001';attempt.mkdir(parents=True)
            self.result({**self.spec(),'job_id':'another-question'},attempt,1)
            runner=Mock()
            with self.assertRaisesRegex(ValueError,'identity'):
                worker.execute(Path('fixture'),self.spec(),out,runner=runner,should_stop=lambda spec:False)
            runner.assert_not_called()

    def test_actual_signal_interrupt_cleans_native_child_without_retry_or_slot_release(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);parent=root/'attempt_001';out=parent/'runs/attempt_001';out.mkdir(parents=True)
            spec={**self.spec(),'slot_path':str(root/'slot'),'config_path':str(root/'config.json')}
            spec_path=root/'spec.json';spec_path.write_text(json.dumps(spec));native_result=out/'native/native-result.json'
            code='import os,signal,time;os.kill(os.getppid(),signal.SIGTERM);time.sleep(30)'
            with patch.object(worker,'validate_spec',return_value=root), \
                 patch.object(worker.trial,'environment',return_value=({'PATH':os.environ['PATH']},{})), \
                 patch('review_execution.enforce'), \
                 patch.object(worker,'native_command',return_value=([sys.executable,'-c',code],native_result,10)), \
                 patch.object(worker.trial,'release_slot') as release:
                worker.run_attempt(spec_path,spec,out,1,parent);release.assert_not_called()
            result=json.loads((out/'result.json').read_text())
            self.assertEqual(result['status'],'interrupted');self.assertTrue(result['native_cleanup_confirmed'])
            self.assertEqual(result['unconfirmed_child_termination'],[])
            self.assertEqual(policy.retry_decision(result,1),(False,'not_timeout'))

    def test_per_job_config_and_slot_owner_remain_bound_in_mixed_campaign(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);config=root/'job-configs/summarization.json';config.parent.mkdir()
            config.write_text(json.dumps({**self.spec(),'max_output_tokens':8192}))
            job={**self.spec(),'strategy':'summarization','config_path':str(config),'config_sha256':worker.trial.digest(config.read_bytes())}
            plan={'definition':{'cohort_sha256':'fixture-cohort'},'jobs':[job]}
            (root/'plan.json').write_text(json.dumps(plan));slot=root/'slots/00';slot.mkdir(parents=True)
            claim=root/'jobs'/job['job_id']/'claim';claim.mkdir(parents=True)
            owner={'job_id':job['job_id'],'controller_id':'owner','slot':str(slot)}
            (claim/'owner.json').write_text(json.dumps(owner));(slot/'owner.json').write_text(json.dumps(owner))
            spec={**job,'campaign_root':str(root),'slot_path':str(slot),'controller_id':'owner',
                  'plan_sha256':worker.trial.digest((root/'plan.json').read_bytes()),'cohort_sha256':'fixture-cohort'}
            out=root/'jobs'/job['job_id']/'attempts/attempt_001'
            with patch.object(worker,'validate_sources'):
                self.assertEqual(worker.validate_spec(spec,out),root)
                with self.assertRaisesRegex(ValueError,'owner'):
                    worker.validate_spec({**spec,'controller_id':'other'},out)
                with self.assertRaisesRegex(ValueError,'Output'):
                    worker.validate_spec(spec,root/'other-output')
                config.write_text('{}')
                with self.assertRaisesRegex(ValueError,'config'):
                    worker.validate_spec(spec,out)

    def test_dsh_native_sdk_and_wire_one_hour_bindings(self):
        patches=preservation_patches({'TOKENHUB_BASE_URL':'http://localhost/v1','ACL_MODEL':ROUTES[0],
            'ACL_INPUT_MODALITIES':'["text","image"]','ACL_CONTEXT_WINDOW':'131072','ACL_MAX_OUTPUT_TOKENS':'8192'})
        before=copy.deepcopy(patches);adapted=dsh.adapt_patches(patches,timeout_seconds=3600)
        provider=adapted[1]['config']['providers']['tokenhub']
        self.assertEqual(provider['timeoutMs'],3600000);self.assertEqual(provider['streamIdleTimeoutMs'],3600000)
        self.assertEqual(provider['retryPolicy']['maxRetries'],0);self.assertEqual(before,patches)
        for value in [1800,7200,3600.0,True]:
            with self.assertRaises(ValueError):dsh.adapt_patches(patches,timeout_seconds=value)
        code="""
import assert from 'node:assert/strict';
import {resolveProfiles} from './deepseekHarness/packages/llm/llm-pi-ai/src/config.ts';
import {guardedFetch,ROUTES} from './scripts/dsh_inline_wire_v5.mjs';
const p=resolveProfiles(PROVIDERS).get('tokenhub');assert.equal(p.timeoutMs,3600000);assert.equal(p.streamIdleTimeoutMs,3600000);assert.equal(p.retryPolicy.maxRetries,0);
let clock=0,calls=0;const events=[];const endpoint='http://fixture/v1/chat/completions';
const f=guardedFetch({original:async()=>{calls++;return new Response('ok')},transform:async wire=>({wire,ledger:{}}),endpoint,emit:r=>events.push(r),now:()=>clock});
const init={method:'POST',body:JSON.stringify({model:ROUTES[0],messages:[]})};
clock=1800001;assert.equal(await(await f(endpoint,init)).text(),'ok');
clock=3599999;assert.equal(await(await f(endpoint,init)).text(),'ok');
clock=3600000;await assert.rejects(()=>f(endpoint,init),/deadline/);assert.equal(calls,2);assert(events.some(r=>r.event==='trial_transport_deadline'));
""".replace('PROVIDERS',json.dumps({'tokenhub':provider}))
        env={**os.environ,'PATH':runtime_path(ROOT)};env.pop('ACL_INLINE_DSH_LEDGER',None)
        run=subprocess.run(['node','--input-type=module','-e',code],cwd=ROOT,env=env,capture_output=True,text=True,timeout=30)
        self.assertEqual(run.returncode,0,run.stdout+run.stderr)
