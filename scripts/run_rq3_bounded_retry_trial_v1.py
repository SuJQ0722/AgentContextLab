#!/usr/bin/env python3
"""Bounded RQ3 trial with original deadline, raw accounting and child cleanup."""
import run_bc_trial_v3 as trial
from run_bc_trial_v3_io import HeartbeatAtomic
from lab import ROOT, python_for
from prepare_rq3_bounded_retry_v1 import validate_trial, PROTOCOL


def native_command(spec,out):
    if spec['harness']!='hermes' or spec['strategy']!='visual' or spec.get('bounded_rq3_protocol')!=PROTOCOL:
        raise ValueError('Unexpected bounded RQ3 worker contract')
    return ([python_for(ROOT),str(ROOT/'scripts/hermes_bounded_rq3_worker_v1.py'),
             '--spec',spec['_spec_path'],'--out',str(out/'native'),'--live'],
            out/'native/native-result.json',spec['timeout_seconds'])


def main():
    previous=trial.validate_spec,trial.native_command,trial.atomic
    trial.validate_spec,trial.native_command=validate_trial,native_command
    trial.atomic=HeartbeatAtomic(trial.atomic)
    try:trial.main()
    finally:trial.validate_spec,trial.native_command,trial.atomic=previous


if __name__=='__main__': main()
