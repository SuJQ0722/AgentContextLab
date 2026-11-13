import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from summary_prefix_fit_v14 import fit_prefix, boundaries


class SummaryPrefixFitTests(unittest.TestCase):
    def test_overshoot_is_only_exact_source_prefix(self):
        text = 'known fact. ' * 1000
        seen = []
        def measured(candidate):
            self.assertTrue(text.startswith(candidate))
            seen.append(candidate)
            return 1000 + len(candidate)
        result = fit_prefix(text, 5500, 1000, 12000, measured)
        self.assertEqual(result['status'], 'matched')
        self.assertTrue(5390 <= result['provider_prompt_tokens'] <= 5610)
        self.assertLessEqual(len(seen), 10)

    def test_undershoot_never_pads_or_measures(self):
        def forbidden(_):
            self.fail('No request permitted for an undershoot')
        result = fit_prefix('short', 5000, 1000, 2000, forbidden)
        self.assertEqual(result['status'], 'undershoot_requires_separate_generation')

    def test_unknown_halts_without_retry(self):
        calls = []
        result = fit_prefix('内容，事实。' * 100, 300, 100, 800,
                            lambda candidate: calls.append(candidate))
        self.assertEqual(result['status'], 'unknown_usage_stop')
        self.assertEqual(len(calls), 1)

    def test_unicode_boundaries_not_bytes(self):
        text = '中文🙂 end'
        for boundary in boundaries(text):
            self.assertEqual(text[:boundary].encode().decode(), text[:boundary])
        self.assertNotIn(6, boundaries('a_long_word'))


if __name__ == '__main__':
    unittest.main()
