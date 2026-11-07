import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('acl_render', Path(__file__).resolve().parents[1] / 'scripts/render_dsh_history.py')
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


class RenderBridgeTests(unittest.TestCase):
    def test_partial_history_failure_invalidates_render(self):
        def partial(*args, **kwargs):
            bridge.renderer_module.logger.error('Visual: far history rendering failed: missing decoder')
            return [{'content': [{'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,AA=='}}]}]
        with patch.object(bridge, 'render_visual_compression', partial):
            with self.assertRaisesRegex(RuntimeError, 'far history rendering failed'):
                bridge.render({'messages': [], 'history_scale': .75})

    def test_pil_fallback_is_never_valid_evidence(self):
        with self.assertRaisesRegex(RuntimeError, 'PIL fallback'):
            bridge.reject_fallback()

    def test_text_only_return_is_not_misreported_as_compression(self):
        with patch.object(bridge, 'render_visual_compression', lambda messages, **kwargs: messages):
            with self.assertRaisesRegex(ValueError, 'not rendered'):
                bridge.render({'messages': [], 'history_scale': .75})
