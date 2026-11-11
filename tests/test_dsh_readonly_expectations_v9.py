"""Run the actual pinned Cordis/LlmRuntime pipeline with deeply frozen inputs."""
import os
from pathlib import Path
import subprocess
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from lab import runtime_path

class ReadonlyExpectationsTests(unittest.TestCase):
    def test_pinned_native_pipeline(self):
        env={**os.environ,'PATH':runtime_path(ROOT)}
        result=subprocess.run(['node','--test','tests/dsh-readonly-expectations-v9.test.mjs'],cwd=ROOT,env=env,capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
