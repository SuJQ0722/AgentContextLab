#!/usr/bin/env python3
"""One immutable scientific attempt with separately verified fixed-route native inputs."""
import argparse
import json
import os
from pathlib import Path
import sys
import run_bc_trial_v3 as frozen_trial
import run_bc_trial_v3_io2 as io2
from run_bc_trial_v3_capacity1 import maintenance_record as capacity_maintenance
from bc_route_runtime_v1 import RoutePlan, prepare_runtime, implementation_hashes, VERSION
from lab import ROOT


def maintenance_record():
    return {**capacity_maintenance(),'fixed_route_runtime_version':VERSION,
            'fixed_route_implementation_sha256':implementation_hashes()}


def validated_runtime(original_validate,prepared,route_path=None,route_sha=None):
    def validate(spec,out):
        result=original_validate(spec,out)
        out=Path(out)
        if (out/'result.json').exists() or (out/'worker-started.json').exists():return result
        owner=json.loads((Path(spec['campaign_root'])/'jobs'/spec['job_id']/'claim/owner.json').read_text())
        routes=RoutePlan(spec['campaign_root'],route_path or owner.get('route_plan_path'),
                         route_sha or owner.get('route_plan_sha256'))
        runtime,lineage=prepare_runtime(spec,out,routes)
        prepared.update(spec=runtime,lineage=lineage,route_plan=routes)
        os.environ['ACL_ROUTE_LINEAGE_FILE']=str(out/'route-lineage.json')
        return result
    return validate


def routed_native_command(original,prepared):
    def command(spec,out):
        if 'spec' not in prepared:raise ValueError('Original validation and fixed route lineage required before native launch')
        prepared['route_plan'].check_unchanged()
        runtime=prepared['spec']
        if runtime['job_id']!=spec['job_id']:raise ValueError('Prepared runtime belongs to another job')
        cmd,result,timeout=original(runtime,out)
        if spec['harness']=='hermes':
            old=str(ROOT/'scripts/hermes_bc_worker_v3.py');new=str(ROOT/'scripts/hermes_bc_worker_routes1.py')
        else:
            old=str(ROOT/'scripts/run_dsh_eval_v3.py');new=str(ROOT/'scripts/run_dsh_eval_v3_routes1.py')
        if cmd.count(old)!=1:raise ValueError('Unexpected frozen native entrypoint')
        cmd=[new if value==old else value for value in cmd]
        return cmd,result,timeout
    return command


def main():
    parser=argparse.ArgumentParser(add_help=False)
    parser.add_argument('--route-plan',type=Path);parser.add_argument('--route-plan-sha256')
    args,remaining=parser.parse_known_args()
    argv=sys.argv[:];sys.argv=[argv[0],*remaining]
    original_validate=frozen_trial.validate_spec;original_command=frozen_trial.native_command
    previous=os.environ.get('ACL_ROUTE_LINEAGE_FILE');prepared={}
    frozen_trial.validate_spec=validated_runtime(original_validate,prepared,args.route_plan,args.route_plan_sha256)
    frozen_trial.native_command=routed_native_command(original_command,prepared)
    try:io2.main()
    finally:
        frozen_trial.validate_spec=original_validate;frozen_trial.native_command=original_command;sys.argv=argv
        if previous is None:os.environ.pop('ACL_ROUTE_LINEAGE_FILE',None)
        else:os.environ['ACL_ROUTE_LINEAGE_FILE']=previous


if __name__=='__main__':main()
