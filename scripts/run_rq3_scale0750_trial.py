#!/usr/bin/env python3
"""Explicit .75 scope, unchanged proven native supervisor and ownership checks."""
import run_bc_trial_v3 as trial
from run_rq3_parity_v3 import validate_trial as frozen_validate,ROOT
from prepare_rq3_scale0750_v1 import validate_authorized_spec

def validate_spec(spec,out):
    root=frozen_validate(spec,out)
    validate_authorized_spec(spec)
    return root

def main():
    original_validate=trial.validate_spec;original_command=trial.native_command
    def native(spec,out):
        command,result,timeout=original_command(spec,out)
        old=str(ROOT/'scripts/hermes_bc_worker_v3.py');new=str(ROOT/'scripts/rq3_scale0750_worker.py')
        if command.count(old)!=1:raise ValueError('Unexpected native command')
        return [new if arg==old else arg for arg in command],result,timeout
    trial.validate_spec=validate_spec;trial.native_command=native
    try:trial.main()
    finally:trial.validate_spec=original_validate;trial.native_command=original_command
if __name__=='__main__':main()
