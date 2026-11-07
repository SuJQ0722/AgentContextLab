import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from info_loss_report import summarize_usage

class UsageSummaryTests(unittest.TestCase):
    def test_partial_null_and_pending_remain_unknown(self):
        rows=[{'usage':{'prompt_tokens':100,'completion_tokens':None}},
              {'usage':{'completion_tokens':7,'prompt_tokens_details':{'cached_tokens':4}}},
              {'usage':None}]
        r=summarize_usage(rows,4)
        self.assertEqual(r['input_tokens_known'],100)
        self.assertEqual(r['output_tokens_known'],7)
        self.assertEqual(r['prompt_unknown_calls'],3)
        self.assertEqual(r['output_unknown_calls'],3)
        self.assertEqual(r['cached_unknown'],2)
        self.assertEqual(r['noncache_observed_calls'],0)
        self.assertEqual(r['derived_total_observed_calls'],0)
        self.assertIsNone(r['full_noncache_input_tokens'])
        self.assertIsNone(r['full_total_tokens'])
        self.assertFalse(r['usage_complete'])

    def test_zero_cache_is_known_and_conservation_is_per_call(self):
        rows=[{'usage':{'prompt_tokens':100,'completion_tokens':5,'total_tokens':105,
                        'prompt_tokens_details':{'cached_tokens':0}}}]
        r=summarize_usage(rows,1)
        self.assertEqual(r['cached_unknown'],0)
        self.assertEqual(r['full_noncache_input_tokens'],100)
        self.assertEqual(r['full_total_tokens'],105)
        self.assertTrue(r['usage_complete'])
        rows.append({'usage':{'prompt_tokens':3,'completion_tokens':2,'total_tokens':99,
                             'prompt_tokens_details':{'cached_tokens':4}}})
        r=summarize_usage(rows,2)
        self.assertEqual(r['known_noncache_input_tokens'],100)
        self.assertEqual(r['conservation_error_calls'],1)
        self.assertEqual(r['cache_conservation_error_calls'],1)
        self.assertFalse(r['usage_complete'])
        self.assertIsNone(r['full_total_tokens'])
        self.assertIsNone(r['full_noncache_input_tokens'])
