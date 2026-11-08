"""Only the intended upload key crosses the Hermes/DSH credential boundary."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from local_web import configure_image_upload


class ImageUploadConfigTests(unittest.TestCase):
    def test_only_upload_key_is_shared_and_explicit_override_wins(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'hermes-agent').mkdir()
            (root / 'hermes-agent/.env').write_text('IMAGE_UPLOAD_API_KEY=base-fixture\n')
            (root / 'hermes-agent/.env.local').write_text(
                'IMAGE_UPLOAD_API_KEY="local-fixture"\nTOKENHUB_API_KEY=old-route\nUNRELATED=private\n')
            for harness in ('hermes', 'dsh'):
                with self.subTest(harness=harness):
                    env = {'TOKENHUB_API_KEY': 'shared-route'}
                    status = configure_image_upload(root, env)
                    self.assertEqual(env, {'TOKENHUB_API_KEY': 'shared-route', 'IMAGE_UPLOAD_API_KEY': 'local-fixture'})
                    self.assertEqual(status, {'provider': 'imgbb', 'configured': True})
                    env['IMAGE_UPLOAD_API_KEY'] = 'explicit-fixture'
                    configure_image_upload(root, env)
                    self.assertEqual(env['IMAGE_UPLOAD_API_KEY'], 'explicit-fixture')

    def test_missing_key_remains_absent(self):
        with tempfile.TemporaryDirectory() as directory:
            env = {}
            self.assertFalse(configure_image_upload(Path(directory), env)['configured'])
            self.assertEqual(env, {})


if __name__ == '__main__':
    unittest.main()
