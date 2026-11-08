"""Compare the shared adapter to actual Hermes policies, without model APIs."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from shared_context_policy import apply_policy, make_engine, policy_config, context_config


def history(rounds=14):
    messages = [{'role': 'system', 'content': 'System fixture', '_dsh_original_id': 'system'},
                {'role': 'user', 'content': 'Original task', '_dsh_original_id': 'task'}]
    for i in range(rounds):
        messages += [{'role': 'assistant', 'content': f'Reasoning {i}', '_dsh_original_id': f'a{i}',
                      'tool_calls': [{'id': f't{i}', 'type': 'function', 'function': {'name': 'web_search', 'arguments': '{}'}}]},
                     {'role': 'tool', 'tool_call_id': f't{i}', 'content': ('Evidence ' + str(i) + ' ') * 100,
                      '_dsh_original_id': f't{i}'}]
    return messages


def request(strategy, **kwargs):
    return {'strategy': strategy, 'messages': history(),
            'config': {'model': 'fixture-model', 'context_length': 65536, 'threshold_tokens': 32768,
                       'strategy_config': {'keep_rounds': 0} if strategy == 'discard' else {}},
            'provider_usage': {'prompt_tokens': 40000, 'completion_tokens': 20}, **kwargs}


class SharedPolicyTests(unittest.TestCase):
    def test_developer_role_follows_actual_hermes_policy_without_relabelling(self):
        developer = {'role': 'developer', 'content': [{'type': 'text', 'text': 'Native runtime instructions'}],
                     '_dsh_original_id': 'developer-original'}
        for strategy in ('none', 'discard', 'sliding_window'):
            with self.subTest(strategy=strategy):
                req = request(strategy)
                req['messages'].insert(2, developer)
                engine = make_engine(strategy, req['config'])
                expected = (engine.compress(copy.deepcopy(req['messages']), current_tokens=40000)
                            if engine is not None else req['messages'])
                result = apply_policy(req)
                self.assertEqual(result['messages'], expected)
                if strategy != 'discard':
                    self.assertIn(developer, result['messages'])
                else:
                    self.assertNotIn(developer, result['messages'])

    def test_none_is_identity_even_without_usage_and_missing_usage_does_not_trigger(self):
        req = request('none', provider_usage=None)
        self.assertEqual(apply_policy(req)['messages'], req['messages'])
        for strategy in ('discard', 'sliding_window', 'summarize', 'visual'):
            with self.subTest(strategy=strategy):
                result = apply_policy(request(strategy, provider_usage=None))
                self.assertEqual(result['status'], 'awaiting_usage')
                self.assertFalse(result['compression_triggered'])

    def test_threshold_and_real_engine_output_parity(self):
        for strategy in ('discard', 'sliding_window'):
            with self.subTest(strategy=strategy):
                req = request(strategy)
                engine = make_engine(strategy, req['config'])
                engine.update_from_response(req['provider_usage'])
                direct = engine.compress(copy.deepcopy(req['messages']), current_tokens=40000)
                result = apply_policy(req)
                self.assertEqual(result['messages'], direct)
                self.assertEqual(result['compression_count'], engine.compression_count)
                self.assertTrue(result['changed'])
                low = request(strategy, provider_usage={'prompt_tokens': 32767})
                self.assertFalse(apply_policy(low)['compression_triggered'])
                exact = request(strategy, provider_usage={'prompt_tokens': 32768})
                self.assertTrue(apply_policy(exact)['compression_triggered'])
                # Retained original IDs and real tool-role frames are not flattened.
                self.assertEqual(result['messages'][1]['_dsh_original_id'], 'task')
                if strategy == 'sliding_window':
                    self.assertTrue(any(m['role'] == 'tool' for m in result['messages']))

    def test_state_resume_and_configuration_change_rejection(self):
        req = request('discard')
        first = apply_policy(req)
        req['messages'] = first['messages'] + history(2)[2:]
        req['state'] = first['state']
        second = apply_policy(req)
        self.assertEqual(second['compression_count'], 2)
        req['config']['threshold_tokens'] = 30000
        with self.assertRaisesRegex(ValueError, 'lineage'):
            apply_policy(req)

    def test_summary_exact_prompt_two_phase_and_real_engine_assembly(self):
        req = request('summarize')
        req['config']['strategy_config'] = {'protect_first_n': 3, 'protect_last_n': 3, 'summary_target_ratio': .1}
        pending = apply_policy(req)
        self.assertEqual(pending['status'], 'awaiting_summary')
        self.assertEqual(pending['messages'], req['messages'])
        self.assertEqual(pending['state']['engine']['compression_count'], 0)
        self.assertGreaterEqual(pending['timings']['engine_seconds'], 0)
        self.assertEqual(pending['timings']['renderer_calls'], 0)
        self.assertGreaterEqual(pending['timings']['policy_total_seconds'], pending['timings']['engine_seconds'])
        captured = []
        def fixture_call(**kwargs):
            captured.append(kwargs)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='Fixture checkpoint content.'))])
        direct = make_engine('summarize', req['config'])
        direct.update_from_response(req['provider_usage'])
        from agent import auxiliary_client
        with patch.object(auxiliary_client, 'call_llm', fixture_call):
            expected = direct.compress(copy.deepcopy(req['messages']), current_tokens=40000)
        self.assertEqual(captured[0]['messages'], pending['pending_call']['messages'])
        self.assertEqual(captured[0]['max_tokens'], pending['pending_call']['max_tokens'])
        req['state'] = pending['state']
        req['summary_response'] = {'request_sha256': pending['pending_call']['request_sha256'],
                                   'content': 'Fixture checkpoint content.', 'usage': None, 'call_id': 'fixture-aux'}
        completed = apply_policy(req)
        self.assertEqual(completed['messages'], expected)
        self.assertEqual(completed['status'], 'compressed')
        self.assertEqual(completed['timings']['renderer_seconds'], 0)
        self.assertIsNone(completed['auxiliary_calls'][0]['usage'])
        self.assertEqual(completed['state']['engine']['_previous_summary'], 'Fixture checkpoint content.')
        req['summary_response']['request_sha256'] = 'wrong'
        with self.assertRaisesRegex(ValueError, 'transaction') as rejected:
            apply_policy(req)
        self.assertGreaterEqual(rejected.exception.policy_timings['engine_seconds'], 0)

    def test_summary_input_mutation_rejected_and_error_uses_hermes_fallback(self):
        req = request('summarize')
        pending = apply_policy(req)
        self.assertEqual(pending['status'], 'awaiting_summary')
        req['summary_response'] = {'request_sha256': pending['pending_call']['request_sha256'], 'error': 'fixture error', 'usage': None}
        failed = apply_policy(req)
        self.assertEqual(failed['status'], 'compressed')
        self.assertTrue(any('Summary generation was unavailable' in str(m['content']) for m in failed['messages']))
        req['messages'][1]['content'] = 'Changed task'
        with self.assertRaisesRegex(ValueError, 'transaction'):
            apply_policy(req)

    def test_shared_config_agrees_with_hermes_context_and_does_not_leak_credentials(self):
        cfg = {'model': 'fixture', 'context_window': 65536, 'pilot': {'compression_trigger_tokens': 32768},
               'visual_renderer': {'font_size': 16, 'history_scale': 1}}
        for strategy in ('none', 'discard', 'sliding_window', 'summarize', 'visual'):
            policy = policy_config(strategy, cfg, '/tmp/fixture-canvas')
            context = context_config(strategy, cfg, '/tmp/fixture-canvas')
            self.assertEqual(policy['strategy_config'], context['strategy_config'])
        req = request('discard')
        req['config']['api_key'] = 'must-not-serialize'
        with self.assertRaisesRegex(ValueError, 'credentials'):
            apply_policy(req)

    def test_expired_summary_cooldown_is_stable_across_pending_replay(self):
        req = request('summarize')
        pending = apply_policy(req)
        req['summary_response'] = {'request_sha256': pending['pending_call']['request_sha256'], 'error': 'fixture'}
        failed = apply_policy(req)
        state = failed['state']
        state['summary_cooldown_until_unix'] = time.time() - 1
        req['state'] = state
        del req['summary_response']
        pending = apply_policy(req)
        self.assertEqual(pending['status'], 'awaiting_summary')
        self.assertEqual(pending['state']['summary_cooldown_until_unix'], 0)
        req['state'] = pending['state']
        req['summary_response'] = {'request_sha256': pending['pending_call']['request_sha256'], 'content': 'Recovered summary'}
        self.assertEqual(apply_policy(req)['status'], 'compressed')


if __name__ == '__main__':
    unittest.main()
