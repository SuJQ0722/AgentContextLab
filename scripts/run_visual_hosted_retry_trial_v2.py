#!/usr/bin/env python3
"""Independent resilient hosted trial; original cleanup and raw usage accounting."""
from pathlib import Path
from unittest.mock import patch
import run_visual_hosted_retry_trial_v1 as parent
from lab import ROOT

OriginalNative = parent.native_command
WORKERS = {
    'controlled_hosted_visual_worker_v1.py': 'controlled_hosted_visual_worker_v2.py',
    'hermes_visual_hosted_retry_worker_v1.py': 'hermes_visual_hosted_retry_worker_v2.py',
    'dsh_hosted_bc_worker_v1.py': 'dsh_hosted_bc_worker_v2.py',
}


def native_command(spec, out):
    if spec.get('hosted_runtime_version') != 'verified-hosted-images-v4' or spec.get('image_transport') != 'verified-imgbb-url-v2':
        raise ValueError('Explicit resilient hosted runtime required')
    command, result, timeout = OriginalNative(spec, out)
    old = Path(command[1])
    if old.parent != ROOT / 'scripts' or old.name not in WORKERS:
        raise ValueError('Unexpected hosted worker command')
    command[1] = str(ROOT / 'scripts' / WORKERS[old.name])
    return command, result, timeout


def main():
    with patch.object(parent, 'native_command', native_command):
        parent.main()


if __name__ == '__main__':
    main()
