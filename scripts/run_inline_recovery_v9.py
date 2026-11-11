"""Independent recovery controller; existing 16-slot and retry5 contracts preserved."""
from pathlib import Path
import subprocess
from unittest.mock import patch
import run_visual_inline_retry5_v8 as base
from lab import ROOT


def launch(command,*args,**kwargs):
    command=list(command)
    if Path(command[1])!=ROOT/'scripts/run_visual_hosted_retry_trial_v1.py':raise ValueError('Unexpected trial')
    command[1]=str(ROOT/'scripts/run_inline_recovery_trial_v9.py')
    return subprocess.Popen(command,*args,**kwargs)


if __name__=='__main__':
    with patch.object(base,'launch',launch):base.main()
