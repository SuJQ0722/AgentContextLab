#!/usr/bin/env python3
from pathlib import Path
import run_rq3_parity_trial as frozen
from recover_rq3_pre_native_third_once import validate_scope,exit_proof,JOB
ORIGINAL=frozen.validate_trial

def guard(spec,out):
    _,a=validate_scope(Path(spec['campaign_root']));proof,state=exit_proof(a)
    if spec['job_id']!=JOB or proof is None:raise ValueError('Pre-native recovery scope/proof unavailable')
    if Path(spec['slot_path']).parent!=Path(a['shared_slot_root']):raise ValueError('Recovery escaped shared16 slots')
    return ORIGINAL(spec,out)

def main():
    original=frozen.validate_trial;frozen.validate_trial=guard
    try:frozen.main()
    finally:frozen.validate_trial=original
if __name__=='__main__':main()
