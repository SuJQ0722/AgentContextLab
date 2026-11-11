#!/usr/bin/env python3
"""Independent four-route inline trial with unchanged native cleanup/accounting."""
from pathlib import Path
from unittest.mock import patch
import run_visual_hosted_retry_trial_v1 as parent
from lab import ROOT
from inline_route_contract_v2 import validate_routes

OriginalNative = parent.native_command
WORKERS = {
    'controlled_hosted_visual_worker_v1.py': 'controlled_visual_inline_worker_v5.py',
    'hermes_visual_hosted_retry_worker_v1.py': 'hermes_visual_inline_retry_worker_v4.py',
    'dsh_hosted_bc_worker_v1.py': 'dsh_inline_bc_worker_v5.py',
}


def native_command(spec, out):
    import json
    validate_routes(spec, json.loads(Path(spec['config_path']).read_text()))
    command, result, timeout = OriginalNative(spec, out)
    old = Path(command[1])
    if old.parent != ROOT / 'scripts' or old.name not in WORKERS:
        raise ValueError('Unexpected inline worker command')
    command[1] = str(ROOT / 'scripts' / WORKERS[old.name])
    return command, result, timeout


def main():
    with patch.object(parent, 'native_command', native_command):
        parent.main()


if __name__ == '__main__':
    main()
