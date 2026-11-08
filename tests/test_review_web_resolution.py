"""Final resolved web settings cannot escape the offline fixture gate."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from review_execution import enforce_resolved_web


class ReviewWebResolutionTests(unittest.TestCase):
    def test_actual_environment_override_and_reader_mode_are_checked(self):
        selected = {'search': {'url': '127.0.0.1'}, 'fetch': {'base_url': 'http://127.0.0.1:1', 'extract_mode': 'text'}}
        env = {'ACL_WEB_SECRETS': json.dumps(selected)}
        enforce_resolved_web(env, offline_fixture=True)
        with self.assertRaisesRegex(ValueError, 'loopback'):
            enforce_resolved_web({**env, 'FETCH_SERVER_URL': 'http://10.13.64.17:8080'}, offline_fixture=True)
        selected['fetch']['extract_mode'] = 'markdown'
        with self.assertRaisesRegex(ValueError, 'text mode'):
            enforce_resolved_web({'ACL_WEB_SECRETS': json.dumps(selected)}, offline_fixture=True)

    def test_missing_resolved_settings_fail_closed(self):
        with self.assertRaisesRegex(ValueError, 'loopback'):
            enforce_resolved_web({}, offline_fixture=True)


if __name__ == '__main__':
    unittest.main()
