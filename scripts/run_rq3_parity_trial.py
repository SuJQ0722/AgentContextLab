#!/usr/bin/env python3
"""Use the proven v3 subreaper/deadline supervisor with a separate RQ3 source validator."""
from pathlib import Path
import run_bc_trial_v3 as trial
from run_rq3_parity_v3 import validate_trial, ROOT


def main():
    original_validate=trial.validate_spec;original_command=trial.native_command
    def native(spec,out):
        command,result,timeout=original_command(spec,out)
        old=str(ROOT/'scripts/hermes_bc_worker_v3.py');new=str(ROOT/'scripts/rq3_hermes_parity_worker.py')
        if command.count(old)!=1:raise ValueError('Unexpected RQ3 native command')
        return [new if value==old else value for value in command],result,timeout
    trial.validate_spec=validate_trial;trial.native_command=native
    try:trial.main()
    finally:trial.validate_spec=original_validate;trial.native_command=original_command


if __name__=='__main__':main()
