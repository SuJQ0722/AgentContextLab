#!/usr/bin/env python3
"""Validate fixed paid-retry scope before delegating to unchanged scientific trial."""
from pathlib import Path
import run_rq3_parity_trial as frozen
from run_rq3_scale0700_paid_retry1 import validate_scope


def guarded_validator(spec,out):
    root=Path(spec['campaign_root']).resolve();_,authorization=validate_scope(root)
    if spec['job_id'] not in authorization['authorized_job_ids']:raise ValueError('Trial outside15 authorized paid retries')
    if Path(spec['slot_path']).parent!=Path(authorization['shared_slot_root']):raise ValueError('Trial escaped shared16 capacity')
    return ORIGINAL_VALIDATE(spec,out)

ORIGINAL_VALIDATE=frozen.validate_trial

def main():
    original=frozen.validate_trial;frozen.validate_trial=guarded_validator
    try:frozen.main()
    finally:frozen.validate_trial=original

if __name__=='__main__':main()
