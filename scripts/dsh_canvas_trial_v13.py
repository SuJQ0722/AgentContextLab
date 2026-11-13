"""Independent DSH bridge repair for the unchanged V12 retry accounting."""
from pathlib import Path
from unittest.mock import patch
import run_turns500_trial_v12 as previous
from lab import ROOT
original=previous.native_command

def native_command(spec,out):
    if spec.get('harness')!='dsh' or spec.get('strategy')!='visual':raise ValueError('DSH visual repair only')
    command,result,timeout=original(spec,out)
    if Path(command[1])!=ROOT/'scripts/dsh_turns500_worker_v12.py':raise ValueError('Unexpected native entry')
    command[1]=str(ROOT/'scripts/dsh_canvas_worker_v13.py')
    return command,result,timeout

def main():
    with patch.object(previous,'native_command',native_command):previous.main()
if __name__=='__main__':main()
