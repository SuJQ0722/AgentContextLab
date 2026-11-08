import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from preflight_bc_v3_web import evidence_summary, endpoint


class PreflightWebTests(unittest.TestCase):
    def test_search_success_requires_real_nonempty_results(self):
        self.assertTrue(evidence_summary({'content': [{'type': 'text', 'text': '{"success":true,"data":{"web":[{"title":"x"}]}}'}]}, 'search')['usable_evidence'])
        self.assertFalse(evidence_summary({'content': [{'type': 'text', 'text': '{"success":false,"error":"bad"}'}]}, 'search')['usable_evidence'])

    def test_fetch_http_success_does_not_override_tool_failure(self):
        self.assertFalse(evidence_summary({'content': [{'type': 'text', 'text': '{"results":[{"content":"", "error":"unavailable"}]}'}]}, 'fetch')['usable_evidence'])
        self.assertTrue(evidence_summary({'content': [{'type': 'text', 'text': '{"results":[{"content":"Evidence", "error":null}]}'}]}, 'fetch')['usable_evidence'])

    def test_endpoint_never_exports_credentials_or_query(self):
        self.assertEqual(endpoint('http://user:secret@127.0.0.1:18080/fetch?api_key=secret#frag'), 'http://127.0.0.1:18080/fetch')


if __name__ == '__main__':
    unittest.main()
