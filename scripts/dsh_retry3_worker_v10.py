"""Retry3 DSH entry retains V9 immutable-options and final CLI separator repair."""
import argparse
import json
from pathlib import Path
from unittest.mock import patch
import dsh_readonly_recovery_worker_v9 as recovery
import dsh_baseline_inline_worker_v8 as baseline
from one_hour_timeout_retry_v10 import VERSION, validate

def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--timeout', type=int, required=True)
    args, _ = parser.parse_known_args()
    config = json.loads(args.config.read_text())
    validate(config, config)
    if args.timeout != 3600: raise ValueError('Retry3 requires a one-hour native attempt')
    with patch.object(baseline, 'VERSION', VERSION):
        recovery.main()

if __name__ == '__main__': main()
