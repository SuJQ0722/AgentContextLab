#!/usr/bin/env python3
"""Resilient hosted recovery; pending immutable jobs, 16 workers per cell."""
from pathlib import Path
import subprocess
from unittest.mock import patch
import run_visual_hosted_retry_v1 as parent
from lab import ROOT

OriginalController = parent.controller


def launch(command, *args, **kwargs):
    command = list(command)
    if Path(command[1]) != ROOT / 'scripts/run_visual_hosted_retry_trial_v1.py':
        raise ValueError('Unexpected trial command')
    command[1] = str(ROOT / 'scripts/run_visual_hosted_retry_trial_v2.py')
    return subprocess.Popen(command, *args, **kwargs)


def controller(root, shard, concurrency=16, limit=None):
    from prepare_visual_hosted_retry_v1 import load_validate
    plan, _ = load_validate(root)
    if any(j.get('hosted_runtime_version') != 'verified-hosted-images-v4' or j.get('image_transport') != 'verified-imgbb-url-v2' for j in plan['jobs']):
        raise ValueError('Explicit resilient hosted recovery jobs required')
    return OriginalController(root, shard, concurrency, popen=launch, limit=limit)


def main():
    with patch.object(parent, 'controller', controller):
        parent.main()


if __name__ == '__main__':
    main()
