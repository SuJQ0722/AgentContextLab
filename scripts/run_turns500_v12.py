"""Sixteen independent slots, validated 500 turns, no new retry allowance."""
import json,subprocess
from pathlib import Path
from unittest.mock import patch
import run_seven_retry3_v10 as base
from lab import ROOT
from turns500_contract_v12 import validate
_ORIGINAL=base.controller

def launch(command,*args,**kwargs):
    command=list(command)
    if Path(command[1]) != ROOT/'scripts/run_visual_hosted_retry_trial_v1.py':raise ValueError('Unexpected trial')
    command[1]=str(ROOT/'scripts/run_turns500_trial_v12.py')
    return subprocess.Popen(command,*args,**kwargs)

def controller(root,shard,concurrency=16,limit=None):
    from prepare_visual_hosted_retry_v1 import load_validate
    plan,_=load_validate(root)
    for job in plan['jobs']:validate(job,json.loads(Path(job['config_path']).read_text()))
    return _ORIGINAL(root,shard,concurrency,limit)

def main():
    with patch.object(base,'launch',launch),patch.object(base,'controller',controller):base.main()

if __name__=='__main__':main()
