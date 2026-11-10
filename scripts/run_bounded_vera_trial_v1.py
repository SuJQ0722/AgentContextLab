#!/usr/bin/env python3
"""Bounded VERA immutable retry trial using the reviewed child cleanup and accounting lifecycle."""
import run_bc_trial_v3 as trial
from run_bc_trial_v3_io import HeartbeatAtomic
from lab import ROOT, python_for


def native_command(spec, out):
    if spec['harness'] != 'hermes' or spec.get('strategy') != 'visual' or spec.get('bounded_visual_protocol') != 'bounded-multimodal-pages-v1':
        raise ValueError('MMBC campaign authorizes Hermes only')
    return ([python_for(ROOT), str(ROOT/'scripts/hermes_bounded_mmbc_worker_v1.py'),
             '--spec', spec['_spec_path'], '--out', str(out/'native'), '--live'],
            out/'native/native-result.json', spec['timeout_seconds'])


def main():
    from prepare_bounded_vera_retry_v1 import validate_sources
    original = (trial.validate_sources, trial.native_command, trial.atomic)
    trial.validate_sources = validate_sources
    trial.native_command = native_command
    trial.atomic = HeartbeatAtomic(trial.atomic)
    try:
        trial.main()
    finally:
        trial.validate_sources, trial.native_command, trial.atomic = original


if __name__ == '__main__': main()
