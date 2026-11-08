#!/usr/bin/env python3
"""Bounded pre-native owner-publication wait over unchanged routes2 trial."""
import argparse
import json
import os
from pathlib import Path
import sys
import time
import run_bc_trial_v3_routes2 as frozen_routes
from run_bc_campaign_v3 import owner_alive
from bc_claim_publication_io3 import (StartupRoutePlan,operational_record,wait_for_owned_metadata,
    check_never_started,validate_recovery,immutable_json,verify_operational_record,ROOT)


def maintenance_record():
    return {**frozen_routes.maintenance_record(),'claim_publication_io3':operational_record()}


def operational_native_command(original_factory,original,prepared):
    routed=original_factory(original,prepared)
    def command(spec,out):
        cmd,result,timeout=routed(spec,out)
        verify_operational_record(Path(out)/'claim-publication-io3.json')
        if spec['harness']=='dsh':
            source=str(ROOT/'scripts/run_dsh_eval_v3_routes1.py')
            target=str(ROOT/'scripts/run_dsh_eval_v3_routes2_io3.py')
            if cmd.count(source)!=1:raise ValueError('Unexpected DSH native entry before operational CLI repair')
            cmd=[target if value==source else value for value in cmd]
        return cmd,result,timeout
    return command


def main():
    parser=argparse.ArgumentParser(add_help=False)
    parser.add_argument('--recovery-authorization',type=Path)
    args,remaining=parser.parse_known_args()
    argv=sys.argv[:];previous=frozen_routes.RoutePlan;previous_wait=StartupRoutePlan.on_wait
    previous_factory=frozen_routes.routed_native_command;previous_env=os.environ.get('ACL_OPERATIONAL_IO3_FILE')
    try:
        sys.argv=[argv[0],*remaining]
        if '--live' in remaining:
            spec_path=Path(remaining[remaining.index('--spec')+1]).resolve()
            out=Path(remaining[remaining.index('--out')+1]).resolve();spec=json.loads(spec_path.read_text())
            if out!=(Path(spec['campaign_root'])/'jobs'/spec['job_id']/'attempts/attempt_001').resolve():
                raise ValueError('Operational trial output mismatch')
            check_never_started(out)
            out.mkdir(parents=True,exist_ok=True)
            def record_wait(number,delay):
                with (out/'claim-publication-io3-events.jsonl').open('a') as stream:
                    stream.write(json.dumps({'event':'metadata_publication_wait','time_unix':time.time(),
                        'attempt_number':number,'delay_seconds':delay,'paid_api_retry':False})+'\n')
            wait_for_owned_metadata(spec,on_wait=record_wait)
            claim=json.loads((Path(spec['campaign_root'])/'jobs'/spec['job_id']/'claim/owner.json').read_text())
            if not args.recovery_authorization and owner_alive(claim) is not True:
                raise ValueError('Inactive or cross-namespace claim requires explicit never-started recovery authorization')
            if args.recovery_authorization:
                recovery=validate_recovery(spec,spec_path,out,args.recovery_authorization)
                immutable_json(out/'claim-publication-recovery.json',recovery)
            immutable_json(out/'claim-publication-io3.json',operational_record())
            os.environ['ACL_OPERATIONAL_IO3_FILE']=str(out/'claim-publication-io3.json')
            StartupRoutePlan.on_wait=staticmethod(record_wait)
        frozen_routes.RoutePlan=StartupRoutePlan
        frozen_routes.routed_native_command=lambda original,prepared:operational_native_command(previous_factory,original,prepared)
        # Original routes2 -> original io2 -> original trial main. Its exclusive
        # worker-started create remains the only final permission to launch native.
        frozen_routes.main()
    finally:
        frozen_routes.RoutePlan=previous;StartupRoutePlan.on_wait=previous_wait;sys.argv=argv
        frozen_routes.routed_native_command=previous_factory
        if previous_env is None:os.environ.pop('ACL_OPERATIONAL_IO3_FILE',None)
        else:os.environ['ACL_OPERATIONAL_IO3_FILE']=previous_env


if __name__=='__main__':main()
