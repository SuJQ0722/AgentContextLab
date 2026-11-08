#!/usr/bin/env python3
"""Pending-only capacity1 trial, retaining original validation and io2 heartbeat repair."""
import json
from pathlib import Path
import run_bc_trial_v3 as frozen_trial
import run_bc_trial_v3_io2 as io2
from dsh_image_preservation_capacity1 import runtime_record
from lab import ROOT


def maintenance_record():
    return {**io2.maintenance_record(), 'runtime_capacity_repair': runtime_record()}


def routed_native_command(original):
    def native_command(spec, out):
        cmd, result, timeout = original(spec, out)
        if spec['harness'] == 'dsh':
            old = str(ROOT / 'scripts/run_dsh_eval_v3.py')
            if cmd.count(old) != 1:
                raise ValueError('Unexpected DSH entrypoint; refusing implicit route replacement')
            cmd = [str(ROOT / 'scripts/run_dsh_eval_v3_capacity1.py') if value == old else value for value in cmd]
        return cmd, result, timeout
    return native_command


def validated_lineage(original, strict_atomic):
    def validate(spec, out):
        result = original(spec, out)
        out = Path(out)
        # Original trial's guards own these immutable completed or already-started attempts.
        if (out / 'result.json').exists() or (out / 'worker-started.json').exists():
            return result
        record = {**runtime_record(), 'parent_plan_sha256': spec['plan_sha256'],
                  'job_id': spec['job_id'], 'harness': spec['harness'],
                  'native_transport_changed': spec['harness'] == 'dsh',
                  'hermes_route': 'Original hermes_bc_worker_v3.py command unchanged'}
        marker = out / 'runtime-lineage.json'
        if marker.exists():
            if json.loads(marker.read_text()) != record:
                raise ValueError('Runtime lineage changed; preserve this attempt')
        else:
            strict_atomic(marker, record)
        return result
    return validate


def main():
    original_validate = frozen_trial.validate_spec
    original_command = frozen_trial.native_command
    frozen_trial.validate_spec = validated_lineage(original_validate, frozen_trial.atomic)
    frozen_trial.native_command = routed_native_command(original_command)
    try:
        io2.main()
    finally:
        frozen_trial.validate_spec = original_validate
        frozen_trial.native_command = original_command


if __name__ == '__main__':
    main()
