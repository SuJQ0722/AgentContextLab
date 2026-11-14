"""Sixteen slots in one independent one-pass shard."""
import json
import subprocess
from pathlib import Path
from unittest.mock import patch
import run_turns500_v12 as controller
import run_turns500_transport_v12 as transport
from recovery_once_contract_v23 import validate_authorization

original = controller.controller


def checked(root, *args, **kwargs):
    for job in json.loads((Path(root) / 'plan.json').read_text())['jobs']:
        validate_authorization({**job, 'campaign_root': str(root)})
    return original(root, *args, **kwargs)


def launch(command, *args, **kwargs):
    command = list(command)
    if Path(command[1]).name != 'run_visual_hosted_retry_trial_v1.py':
        raise ValueError('Unexpected trial entry')
    command[1] = str(Path(__file__).with_name('run_recovery_once_trial_v23.py'))
    return subprocess.Popen(command, *args, **kwargs)


if __name__ == '__main__':
    with patch.object(controller, 'launch', launch), patch.object(controller, 'controller', checked):
        transport.main()
