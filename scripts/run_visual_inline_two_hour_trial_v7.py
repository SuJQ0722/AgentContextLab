"""Independent 7200-second native trial; retained lifecycle and raw usage accounting."""
import json
from pathlib import Path
from unittest.mock import patch
import run_visual_hosted_retry_trial_v1 as parent
from lab import ROOT
from inline_route_contract_v2 import validate_routes

OriginalNative = parent.native_command
WORKERS = {'controlled_hosted_visual_worker_v1.py': 'controlled_visual_inline_worker_v5.py',
           'hermes_visual_hosted_retry_worker_v1.py': 'hermes_visual_inline_retry_worker_v4.py',
           'dsh_hosted_bc_worker_v1.py': 'dsh_inline_bc_worker_v6.py'}


def validate_deadline(spec, config):
    if spec.get('two_hour_recovery_version') != 'visual-inline-two-hour-v7':
        raise ValueError('Only reviewed V7 recovery specs allowed')
    if spec.get('timeout_seconds') != 7200 or config.get('timeout_seconds') != 7200:
        raise ValueError('Spec and configuration must agree on 7200 seconds')
    if config.get('max_output_tokens') != 8192:
        raise ValueError('Output token budget must remain 8192')
    if spec.get('controlled_spec_path'):
        source = json.loads(Path(spec['controlled_spec_path']).read_text())
        if source.get('timeout_seconds') != 7200 or source.get('config_path') != spec['config_path']:
            raise ValueError('Controlled native spec must use the same deadline/config')
        if spec.get('controlled_input_reuse_version') != 'controlled-frozen-input-reuse-v1':
            raise ValueError('Controlled inputs must use certified frozen bytes')


def native_command(spec, out):
    config = json.loads(Path(spec['config_path']).read_text())
    validate_routes(spec, config); validate_deadline(spec, config)
    command, result, unused_timeout = OriginalNative(spec, out)
    old = Path(command[1])
    if old.parent != ROOT / 'scripts' or old.name not in WORKERS:
        raise ValueError('Unexpected native command')
    command[1] = str(ROOT / 'scripts' / WORKERS[old.name])
    # DSH's older launcher adds 240 seconds; V7 explicitly has the same hard
    # deadline as Hermes, its native CLI and the per-route worker budget.
    return command, result, 7200


def main():
    with patch.object(parent, 'native_command', native_command):
        parent.main()


if __name__ == '__main__': main()
