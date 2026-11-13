"""The rendering downloader must receive the same operational proxy as inference."""
import contextlib
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('network_render_proxy_test', ROOT / 'scripts/network_entry_v13.py')
entry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entry)


class RenderingProxyPropagationTests(unittest.TestCase):
    def setUp(self):
        import httpx
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, {'HERMES_IMAGE_PROXY': 'http://stale.invalid:1'}))
        self.stack.enter_context(patch.object(httpx.Client, '__init__', httpx.Client.__init__))
        self.captured = []
        captured = self.captured

        class CapturePopen:
            def __init__(self, args, *a, **kw):
                captured.append((args, kw))

        self.stack.enter_context(patch.object(subprocess, 'Popen', CapturePopen))
        self.lab = types.SimpleNamespace(environment=lambda *a, **kw: ({'HERMES_IMAGE_PROXY': 'stale'}, {}))
        self.boot = types.SimpleNamespace(research_environment=lambda *a, **kw: {'HERMES_IMAGE_PROXY': 'stale'})
        self.transport = types.SimpleNamespace(install=lambda *a, **kw: None)
        self.stack.enter_context(patch.dict(sys.modules, {
            'lab': self.lab, 'bootstrap_mmbc100_cci': self.boot,
            'visual_transport_runtime_v4': self.transport,
        }))
        self.proxy = 'http://approved.invalid:7890'
        entry.apply(self.proxy)

    def test_process_and_both_environment_builders(self):
        self.assertEqual(os.environ['HERMES_IMAGE_PROXY'], self.proxy)
        self.assertEqual(self.lab.environment()[0]['HERMES_IMAGE_PROXY'], self.proxy)
        self.assertEqual(self.boot.research_environment({}, {})['HERMES_IMAGE_PROXY'], self.proxy)

    def test_python_child_replaces_explicit_stale_renderer_proxy(self):
        subprocess.Popen(['python', '/tmp/worker.py', '--live'], env={'HERMES_IMAGE_PROXY': 'stale'})
        command, kw = self.captured[-1]
        self.assertEqual(command[1:4], [str(entry.ENTRY), '--target', '/tmp/worker.py'])
        self.assertEqual(kw['env']['HERMES_IMAGE_PROXY'], self.proxy)

    def test_native_child_receives_renderer_proxy_without_python_wrapping(self):
        subprocess.Popen(['node', 'worker.mjs'], env={'HERMES_IMAGE_PROXY': 'stale'})
        command, kw = self.captured[-1]
        self.assertEqual(command, ['node', 'worker.mjs'])
        self.assertEqual(kw['env']['HERMES_IMAGE_PROXY'], self.proxy)


if __name__ == '__main__':
    unittest.main()
