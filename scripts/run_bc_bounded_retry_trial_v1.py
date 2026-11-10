#!/usr/bin/env python3
"""One immutable bounded BC native attempt with original cleanup and raw accounting."""
import run_bc_trial_v3 as trial
from run_bc_trial_v3_io import HeartbeatAtomic
from lab import ROOT, python_for

_original_native = trial.native_command

def native_command(spec,out):
    if spec.get('bounded_bc_protocol')!='bc-bounded-pages-v1' or spec.get('strategy')!='visual':
        raise ValueError('Only frozen bounded BC VERA jobs permitted')
    if spec['harness']=='hermes':
        return ([python_for(ROOT),str(ROOT/'scripts/hermes_bounded_bc_worker_v1.py'),
            '--spec',spec['_spec_path'],'--out',str(out/'native'),'--live'],
            out/'native/native-result.json',spec['timeout_seconds'])
    if spec['harness']!='dsh':raise ValueError('Unknown harness')
    command,result,timeout=_original_native(spec,out)
    command[1]=str(ROOT/'scripts/dsh_bounded_bc_worker_v1.py')
    return command,result,timeout


def main():
    from prepare_bc_bounded_retry_v1 import validate_sources
    previous=trial.validate_sources,trial.native_command,trial.atomic
    trial.validate_sources=validate_sources;trial.native_command=native_command
    trial.atomic=HeartbeatAtomic(trial.atomic)
    try:trial.main()
    finally:trial.validate_sources,trial.native_command,trial.atomic=previous

if __name__=='__main__':main()
