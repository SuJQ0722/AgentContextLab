#!/usr/bin/env python3
"""Four-route inline recovery using immutable claims and 16 workers per cell."""
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
    command[1] = str(ROOT / 'scripts/run_controlled_input_reuse_trial_v1.py')
    return subprocess.Popen(command, *args, **kwargs)


def controller(root, shard, concurrency=16, limit=None):
    if concurrency != 16:
        raise ValueError('Canary retains the configured per-cell concurrency of16')
    from prepare_visual_hosted_retry_v1 import load_validate
    plan, _ = load_validate(root)
    if any(j.get('controlled_input_reuse_version') != 'controlled-frozen-input-reuse-v1' for j in plan['jobs']):
        raise ValueError('Explicit input-reuse supplement required')
    if plan['definition'].get('canary_version') != 'visual-inline-canary-v6' or len(plan['jobs']) != 1:
        raise ValueError('Only one frozen canary trial per cell is permitted')
    if any(j.get('transport_runtime_version') != 'visual-transport-runtime-v4' for j in plan['jobs']):
        raise ValueError('Explicit 429-aware recovery jobs required')
    import json
    from inline_route_contract_v2 import validate_routes
    config = json.loads((Path(root) / 'experiment.json').read_text())
    for job in plan['jobs']:
        validate_routes(job, config)
    return OriginalController(root, shard, concurrency, popen=launch, limit=limit)


def main():
    with patch.object(parent, 'controller', controller):
        parent.main()


if __name__ == '__main__':
    main()
