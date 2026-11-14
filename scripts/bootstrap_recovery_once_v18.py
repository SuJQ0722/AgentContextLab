"""Existing verified cloud lifecycle with an explicit independent one-pass root."""
from pathlib import Path
from unittest.mock import patch
import bootstrap_turns500_v12 as previous
from lab import ROOT

original = previous.commands


def commands(args):
    result = original(args)
    result['controller'][1] = str(Path(__file__).with_name('run_recovery_once_v18.py'))
    result['telemetry'][1] = str(Path(__file__).resolve())
    return result


if __name__ == '__main__':
    roles = {**previous.ROLES, 'run_recovery_once_v18.py': 'controller',
             'run_recovery_once_trial_v18.py': 'trial', 'dsh_canvas_worker_v13.py': 'worker'}
    with patch.object(previous, 'commands', commands), patch.object(previous, 'ROLES', roles), \
         patch.object(previous, 'DEFAULT_ROOT', ROOT / 'outputs/campaigns/mmbc-timeout-once-v18'):
        previous.main()
