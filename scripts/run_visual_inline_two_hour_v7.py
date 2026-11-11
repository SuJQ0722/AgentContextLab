"""Sixteen concurrent failure-only two-hour trials per independent experiment cell."""
import json
from pathlib import Path
import subprocess
from unittest.mock import patch
import run_visual_hosted_retry_v1 as parent
from lab import ROOT
from run_visual_inline_two_hour_trial_v7 import validate_deadline
from inline_route_contract_v2 import validate_routes

OriginalController = parent.controller


def launch(command, *args, **kwargs):
    command = list(command)
    if Path(command[1]) != ROOT / 'scripts/run_visual_hosted_retry_trial_v1.py':
        raise ValueError('Unexpected trial entry')
    command[1] = str(ROOT / 'scripts/run_visual_inline_two_hour_trial_v7.py')
    return subprocess.Popen(command, *args, **kwargs)


def controller(root, shard, concurrency=16, limit=None):
    if concurrency != 16:
        raise ValueError('Exactly sixteen slots per cell required')
    from prepare_visual_hosted_retry_v1 import load_validate
    plan, _ = load_validate(root)
    if plan['definition'].get('two_hour_recovery_version') != 'visual-inline-two-hour-v7':
        raise ValueError('Only the independent V7 campaign is allowed')
    config = json.loads((Path(root) / 'experiment.json').read_text())
    for job in plan['jobs']:
        validate_routes(job, config); validate_deadline(job, config)
    return OriginalController(root, shard, concurrency, popen=launch, limit=limit)


def main():
    with patch.object(parent, 'controller', controller):
        parent.main()


if __name__ == '__main__': main()
