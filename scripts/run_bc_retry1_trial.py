#!/usr/bin/env python3
"""Run exactly one ledger-authorized retry using unchanged native harnesses."""
import json
import os
from pathlib import Path
import sys
import run_bc_trial_v3 as native
import run_bc_trial_v3_routes1 as routed
from bc_claim_publication_io3 import operational_record, wait_for_owned_metadata
from bc_route_runtime_v1 import immutable_json
from bc_retry1 import validate_entry


def main():
    previous_validate = native.validate_spec
    previous_factory = routed.routed_native_command
    def validate(spec, out):
        entry = validate_entry(spec['campaign_root'], spec['job_id'])
        wait_for_owned_metadata(spec)
        result = previous_validate(spec, out)
        immutable_json(Path(out) / 'retry-provenance.json', entry)
        immutable_json(Path(out) / 'claim-publication-io3.json', operational_record())
        os.environ['ACL_OPERATIONAL_IO3_FILE'] = str(Path(out) / 'claim-publication-io3.json')
        return result
    def factory(original, prepared):
        base = previous_factory(original, prepared)
        def command(spec, out):
            cmd, result, timeout = base(spec, out)
            if spec['harness'] == 'dsh':
                old = str(native.ROOT / 'scripts/run_dsh_eval_v3_routes1.py')
                if cmd.count(old) != 1:
                    raise ValueError('Unexpected DSH native entry')
                cmd = [str(native.ROOT / 'scripts/run_dsh_eval_v3_routes2_io3.py') if x == old else x for x in cmd]
            return cmd, result, timeout
        return command
    native.validate_spec = validate
    routed.routed_native_command = factory
    try:
        routed.main()
    finally:
        native.validate_spec = previous_validate
        routed.routed_native_command = previous_factory


if __name__ == '__main__':
    main()
