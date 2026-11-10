"""Independent DSH prompt recovery using the original immutable claim machinery."""
from pathlib import Path
import subprocess
from unittest.mock import patch
import run_visual_hosted_retry_v3 as parent
from lab import ROOT

OriginalController = parent.controller


def launch(command, *args, **kwargs):
    command = list(command)
    if Path(command[1]) != ROOT / 'scripts/run_visual_hosted_retry_trial_v1.py':
        raise ValueError('Unexpected trial entry')
    command[1] = str(ROOT / 'scripts/run_dsh_prompt_retry_trial_v1.py')
    return subprocess.Popen(command, *args, **kwargs)


def controller(root, shard, concurrency=16, limit=None):
    from prepare_visual_hosted_retry_v1 import load_validate
    plan, _ = load_validate(root)
    if shard != 'dsh' or any(j.get('harness') != 'dsh' or j.get('dsh_cli_prompt_separator') != 'before-task-v1' for j in plan['jobs']):
        raise ValueError('Only explicit DSH prompt recovery jobs allowed')
    with patch.object(parent, 'launch', launch):
        return OriginalController(root, shard, concurrency, limit=limit)


def main():
    with patch.object(parent, 'controller', controller):
        parent.main()


if __name__ == '__main__':
    main()
