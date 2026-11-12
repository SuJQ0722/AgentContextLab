"""Independent V11 dispatch with the unchanged retry3 and 16-slot controller."""
from pathlib import Path
import subprocess
from unittest.mock import patch
import run_seven_retry3_v10 as base
from lab import ROOT


def launch(command, *args, **kwargs):
    command = list(command)
    if Path(command[1]) != ROOT / 'scripts/run_visual_hosted_retry_trial_v1.py':
        raise ValueError('Unexpected trial entry')
    command[1] = str(ROOT / 'scripts/run_seven_retry3_trial_v11.py')
    return subprocess.Popen(command, *args, **kwargs)


def main():
    with patch.object(base, 'launch', launch): base.main()

if __name__ == '__main__': main()
