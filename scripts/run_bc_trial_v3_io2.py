#!/usr/bin/env python3
"""Heartbeat I/O maintenance v2: one frozen validation, then maintenance marker."""
import hashlib
import json
from pathlib import Path

import run_bc_trial_v3 as frozen_trial
from run_bc_trial_v3_io import HeartbeatAtomic, RETRY_DELAYS, RETRY_ERRNOS
from lab import ROOT
import errno

MAINTENANCE_VERSION = 'bc-v3-heartbeat-io-v2'


def maintenance_record():
    files = ['scripts/run_bc_trial_v3_io.py', 'scripts/run_bc_trial_v3_io2.py',
             'scripts/run_bc_campaign_v3_io2.py']
    return {'maintenance_version': MAINTENANCE_VERSION,
            'implementation_sha256': {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in files},
            'frozen_validation': 'Original validate_spec/validate_sources invoked once by original trial main; marker is written only after successful validation',
            'scope': 'Reuses v1 heartbeat-only retries. Model, tools, context, budget, claims, terminal writes and pending-only resume unchanged.',
            'retry_errno_names': sorted(errno.errorcode[n] for n in RETRY_ERRNOS),
            'max_heartbeat_write_attempts': len(RETRY_DELAYS) + 1}


def validated_marker(original_validate, strict_atomic):
    def validate(spec, out):
        result = original_validate(spec, out)
        out = Path(out)
        if not (out / 'result.json').exists():
            marker = out / 'maintenance.json'
            record = maintenance_record()
            if marker.exists():
                if json.loads(marker.read_text()) != record:
                    raise ValueError('Maintenance identity differs; preserve existing attempt')
            else:
                strict_atomic(marker, record)
        return result
    return validate


def main():
    original_validate = frozen_trial.validate_spec
    strict_atomic = frozen_trial.atomic
    frozen_trial.validate_spec = validated_marker(original_validate, strict_atomic)
    frozen_trial.atomic = HeartbeatAtomic(strict_atomic)
    try:
        # This call owns argument parsing, the single original validation,
        # immutable attempt guard, and native launch. No extra git/source pass.
        frozen_trial.main()
    finally:
        frozen_trial.validate_spec = original_validate
        frozen_trial.atomic = strict_atomic


if __name__ == '__main__': main()
