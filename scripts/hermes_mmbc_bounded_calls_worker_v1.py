"""New MMBC-only worker; opt-in bounded routes, unchanged scientific settings."""
import argparse
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import hermes_core_recent_ten_worker_v23 as previous
import hermes_visual_inline_retry_worker_v4 as visual_worker
import mmbc_bounded_route_runtime_v1 as runtime

VERSION = 'hermes-mmbc-bounded-calls-worker-v1'


def validate(spec, config):
    previous.validate(spec, config)
    if spec.get('experiment_kind') != 'mmbc':
        raise ValueError('Optimization is restricted to MMBC + Hermes visual')
    for document in (spec, config):
        if document.get('mmbc_request_budget_version') != runtime.VERSION:
            raise ValueError('Explicit independent MMBC request-budget protocol required')
        if document.get('mmbc_max_http_attempts_per_request') != 3:
            raise ValueError('MMBC candidate requires three HTTP sends per logical request')
    if config.get('transport_runtime_policy', {}).get('max_failed_sends') != 3:
        raise ValueError('Declared failed-send budget must match enforcement')


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--spec', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args, _ = parser.parse_known_args()
    spec = json.loads(args.spec.read_text())
    config_path = Path(spec['config_path'])
    config = json.loads(config_path.read_text())
    validate(spec, config)
    path = args.out/'metrics/mmbc-request-budget-binding-v1.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'version': VERSION, 'runtime': runtime.VERSION,
        'max_http_attempts_per_request': 3, 'spec_sha256': hashlib.sha256(args.spec.read_bytes()).hexdigest(),
        'config_sha256': hashlib.sha256(config_path.read_bytes()).hexdigest(),
        'scientific_settings_changed': False, 'failure_is_not_task_score': True}, indent=2)+'\n')
    with patch.object(visual_worker, 'runtime', runtime.install):
        previous.main()


if __name__ == '__main__':
    main()
