#!/usr/bin/env python3
"""Separate immutable vanilla trial, reusing reviewed timeout/cleanup/accounting."""
import run_bc_trial_v3 as trial
from run_bc_trial_v3_io import HeartbeatAtomic
from lab import ROOT, python_for


def native_command(spec, out):
    if spec['harness'] != 'hermes' or spec.get('method_label') != 'vanilla_visual':
        raise ValueError('Only the explicitly defined vanilla Hermes arm is authorized')
    return ([python_for(ROOT), str(ROOT/'scripts/hermes_mmbc_vanilla_worker_v1.py'),
             '--spec', spec['_spec_path'], '--out', str(out/'native'), '--live'],
            out/'native/native-result.json', spec['timeout_seconds'])


def main():
    from prepare_mmbc_vanilla import validate_sources
    original = trial.validate_sources, trial.native_command, trial.atomic
    trial.validate_sources, trial.native_command = validate_sources, native_command
    trial.atomic = HeartbeatAtomic(trial.atomic)
    try:
        trial.main()
    finally:
        trial.validate_sources, trial.native_command, trial.atomic = original


if __name__ == '__main__': main()
