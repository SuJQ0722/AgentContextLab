"""Zero-model dependency warmup before any V7 trial clock starts."""
import json
import os
from pathlib import Path
import socket
import subprocess
import time
import uuid
from lab import ROOT


def command(harness):
    if harness == 'hermes':
        return [str(ROOT / 'hermes-agent/.venv/bin/python'), '-c',
                "import sys;sys.path[:0]=['hermes-agent','scripts'];import run_agent;import plugins.context_engine.visual.render;print('imports_complete')"]
    if harness == 'dsh':
        return [str(ROOT / '.tools/node-v24.11.0-linux-x64/bin/node'),
                str(ROOT / 'deepseekHarness/apps/cli/lib/bin.js'), '--help']
    raise ValueError('Unknown harness')


def warm(root, harness):
    out = Path(root) / 'runtime/dependency-warmup' / socket.gethostname() / uuid.uuid4().hex
    out.mkdir(parents=True)
    start = time.monotonic()
    with (out / 'stdout.log').open('w') as log:
        result = subprocess.run(command(harness), cwd=ROOT, env=dict(os.environ),
                                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, timeout=180)
    value = {'harness': harness, 'exit_code': result.returncode, 'client_seconds': time.monotonic() - start,
             'before_trial_dispatch': True, 'provider_api_latency_seconds': None, 'model_calls': 0}
    (out / 'result.json').write_text(json.dumps(value, indent=2) + '\n')
    if result.returncode: raise RuntimeError('Dependency warmup failed; no native dispatch')
    return value
