import importlib.util
from pathlib import Path
import unittest
spec=importlib.util.spec_from_file_location('monitor_dsh',Path(__file__).parents[1]/'scripts/monitor_dsh.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


class DshMetricsTests(unittest.TestCase):
    def test_pi_zero_omission_does_not_drop_cached_input_from_total(self):
        u=module.normalized_usage({'usage':{'inputTokens':10,'cacheReadTokens':90,'outputTokens':20,'totalTokens':120}})
        self.assertTrue(u['conserved']);self.assertEqual(u['total_input'],100);self.assertEqual(u['cache_hit_rate'],.9)

    def test_missing_usage_is_missing_and_weighted_rate_is_not_mean(self):
        calls=[{'usage':{'inputTokens':1,'cacheReadTokens':9,'outputTokens':2,'totalTokens':12}},
               {'usage':{'inputTokens':90,'outputTokens':3,'totalTokens':93}}, {'usage':None}]
        u=module.sum_usage(calls)
        self.assertEqual(u['cache_hit_rate'],.09);self.assertEqual(u['missing_usage'],1)
        self.assertIsNone(module.normalized_usage(calls[-1])['output'])

    def test_bad_totals_are_flagged(self):
        self.assertFalse(module.normalized_usage({'usage':{'inputTokens':1,'outputTokens':2,'totalTokens':9}})['conserved'])

    def test_transport_error_zero_placeholder_is_not_provider_usage(self):
        value=module.normalized_usage({'usage':{'inputTokens':0,'outputTokens':0,'totalTokens':0},
                                       'finish':{'kind':'error','failure':{'code':'TRANSPORT'}}})
        self.assertIsNone(value['total_tokens'])

    def test_interrupted_stream_zero_placeholder_is_unknown(self):
        value=module.normalized_usage({'usage':{'inputTokens':0,'outputTokens':0,'totalTokens':0},'finish':None})
        self.assertIsNone(value['total_tokens'])

    def test_judge_openai_usage_does_not_double_count_cached_prompt(self):
        call=module.judge_call({'usage':{'prompt_tokens':100,'prompt_tokens_details':{'cached_tokens':90},
                                       'completion_tokens':20,'total_tokens':120}})
        self.assertEqual(module.normalized_usage(call)['total_tokens'],120)
        self.assertEqual(module.normalized_usage(call)['non_cache_input'],10)
