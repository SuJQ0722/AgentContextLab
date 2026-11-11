import sys
from pathlib import Path
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from compression_inline_only import CompressionHostingRemoved
import preflight_visual_hosted_transport_v4 as preflight


class RetiredPreflightTests(unittest.TestCase):
    def test_no_upload_download_or_fixture_required(self):
        with patch('httpx.Client.send', side_effect=AssertionError('No network')), \
             patch('requests.sessions.Session.request', side_effect=AssertionError('No upload')):
            with self.assertRaises(CompressionHostingRemoved):
                preflight.check(Path('/nonexistent/retired-campaign'))
            with self.assertRaises(CompressionHostingRemoved):
                preflight.main()


if __name__ == '__main__':
    unittest.main()
