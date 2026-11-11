"""No-network tests for exact canonical response alias and inherited retries."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import info_loss_model_alias_v10 as alias


class AliasTests(unittest.TestCase):
    def fixture(self, directory, models, codes=None):
        out=Path(directory); attempt=out/'conditions/case/canvas_1/attempts/attempt_001'; attempt.mkdir(parents=True)
        manifest={'model':alias.previous.ROUTES[0], 'thinking':{'type':'disabled'},
                  'parent_manifest':str(out/'old/manifest.json'), 'max_requests':40}
        sent=[]
        class HTTP:
            def __init__(self, **kwargs): self.kwargs=kwargs
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def post(self, url, **kwargs):
                number=len(sent); sent.append(kwargs['json'])
                raw={'model':models[number], 'choices':[{'message':{'content':'offline test'},'finish_reason':'stop'}],
                     'usage':{'prompt_tokens':12,'completion_tokens':5,'total_tokens':17,'prompt_tokens_details':{'cached_tokens':4}}}
                return type('Response',(),{'status_code':codes[number] if codes else 200, 'json':lambda self:raw})()
        env={'HTTPS_PROXY':alias.runtime.PROXY,'TOKENHUB_BASE_URL':'http://fixture/v1','TOKENHUB_API_KEY':'offline-secret'}
        return out,attempt,manifest,sent,HTTP,env

    def test_exact_alias_accepted_and_raw_model_usage_kept_cache_prevents_repeat(self):
        with tempfile.TemporaryDirectory() as directory:
            out,attempt,manifest,sent,HTTP,env=self.fixture(directory,[alias.ALIAS])
            with patch.object(alias.previous,'environment',return_value=(env,{})),patch.object(alias.previous.httpx,'Client',HTTP):
                client=alias.Client(out,manifest,attempt)
                result=client.call('key','prompt'); cached=client.call('key','prompt')
            self.assertEqual(len(sent),1);self.assertEqual(result,cached)
            self.assertEqual(result['status'],'completed');self.assertEqual(result['returned_model'],alias.ALIAS)
            self.assertEqual(result['original_model_identity_status'],'model_identity_mismatch')
            folder=attempt/'calls/key_001';raw=json.loads((folder/'raw-response.json').read_text())
            self.assertEqual(raw['model'],alias.ALIAS);self.assertEqual(raw['usage'],result['usage'])
            proof=json.loads((folder/'model-alias-acceptance.json').read_text())
            self.assertEqual(proof['original_response_sha256'],alias.previous.phase.sha(proof['original_response_path']))
            self.assertEqual(json.loads(Path(proof['original_response_path']).read_text())['status'],'model_identity_mismatch')
            self.assertEqual(proof['raw_response_sha256'],alias.previous.phase.sha(folder/'raw-response.json'))
            self.assertEqual(json.loads((out/'request-counter.json').read_text())['count'],1)

    def test_unknown_model_still_rejected_without_alias_or_cache_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            out,attempt,manifest,sent,HTTP,env=self.fixture(directory,['deepseek-unapproved'])
            with patch.object(alias.previous,'environment',return_value=(env,{})),patch.object(alias.previous.httpx,'Client',HTTP):
                result=alias.Client(out,manifest,attempt).call('key','prompt')
            self.assertEqual(result['status'],'model_identity_mismatch')
            self.assertFalse(list(out.glob('completed-calls/*')))
            self.assertFalse(list(attempt.glob('calls/*/model-alias-acceptance.json')))

    def test_four_route_rotation_and_all_failed_request_usage_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            out,attempt,manifest,sent,HTTP,env=self.fixture(directory,[alias.ALIAS]*5,[503]*4+[200])
            with patch.object(alias.previous,'environment',return_value=(env,{})),patch.object(alias.previous.httpx,'Client',HTTP),patch.object(alias.previous.time,'sleep') as sleep:
                result=alias.Client(out,manifest,attempt).call('key','prompt')
            self.assertEqual(result['status'],'completed')
            self.assertEqual([s['model'] for s in sent],alias.previous.ROUTES+[alias.previous.ROUTES[0]])
            rows=[json.loads(p.read_text()) for p in sorted(attempt.glob('calls/*/response.json'))]
            self.assertEqual([r['status'] for r in rows],['provider_error']*4+['completed'])
            self.assertEqual(sum(r['usage']['total_tokens'] for r in rows),85)
            sleep.assert_called_once_with(60)

    def test_inherited_timeout_contract_still_six_one_hour_attempts(self):
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory);manifest={'cases':[{'id':'case'}]};(out/'manifest.json').write_text(json.dumps(manifest))
            with patch.object(alias.previous,'Client',return_value=object()), \
                 patch.object(alias.previous.phase,'prepare_case',side_effect=alias.previous.Deadline()), \
                 patch.object(alias.previous.signal,'alarm') as alarm:
                result=alias.previous.run_condition((str(out),'case','canvas_1'))
            self.assertEqual(result['status'],'timeout');self.assertEqual(result['attempt'],6)
            self.assertEqual(sum(c.args==(3600,) for c in alarm.call_args_list),6)
            self.assertEqual(len(list(out.glob('conditions/*/*/attempts/*/result.json'))),6)

    def test_historical_canonical_false_negative_reused_without_modifying_original(self):
        with tempfile.TemporaryDirectory() as directory:
            out,attempt,manifest,sent,HTTP,env=self.fixture(directory,[alias.ALIAS])
            with patch.object(alias.previous,'environment',return_value=(env,{})),patch.object(alias.previous.httpx,'Client',HTTP):
                rejected=alias.ORIGINAL_CLIENT(out,manifest,attempt).call('key','prompt')
            self.assertEqual(rejected['status'],'model_identity_mismatch')
            before={p:p.read_bytes() for p in attempt.glob('calls/*/*.json')}
            fresh=out/'fresh'
            reused=alias.reuse_alias_responses(out,fresh)
            self.assertEqual(len(reused),1)
            restored=json.loads(Path(reused[0]['target']).read_text())
            self.assertEqual(restored['status'],'completed');self.assertEqual(restored['usage'],rejected['usage'])
            self.assertEqual(restored['returned_model'],alias.ALIAS)
            self.assertFalse(restored['new_request'])
            for path,raw in before.items():self.assertEqual(path.read_bytes(),raw)
            self.assertEqual(alias.reuse_alias_responses(out,fresh),[])

    def test_v10_verify_retains_v9_provenance_checks_and_exact_contract(self):
        manifest={'reused_successes':[],'model_alias_policy':{'additional_exact_alias':alias.ALIAS,'raw_returned_model_preserved':True,'raw_usage_preserved':True},
            'concurrency':16,'attempt_timeout_seconds':3600,'max_timeout_retries':5,'max_attempts':6,'max_images':10}
        observed=[]
        with patch.object(alias.runtime,'verify',side_effect=lambda *_:observed.append(alias.runtime.VERSION)):
            alias.verify(Path('fixture'),manifest)
            with self.assertRaises(ValueError):alias.verify(Path('fixture'),{**manifest,'max_timeout_retries':4})
            with self.assertRaises(ValueError):alias.verify(Path('fixture'),{**manifest,'model_alias_policy':{}})
        self.assertEqual(observed,[alias.VERSION]*3)
        self.assertEqual(alias.runtime.VERSION,'info-loss-inline-runtime-v9')
