"""DSH prompt parsing recovery with the frozen inline transport unchanged."""
from pathlib import Path
from unittest.mock import patch
import run_visual_hosted_retry_trial_v3 as parent
from lab import ROOT

OriginalNative = parent.native_command


def native_command(spec, out):
    if spec.get('harness') != 'dsh' or spec.get('dsh_cli_prompt_separator') != 'before-task-v1':
        raise ValueError('Explicit DSH prompt recovery required')
    command, result, timeout = OriginalNative(spec, out)
    if Path(command[1]) != ROOT / 'scripts/dsh_hosted_bc_worker_v3.py':
        raise ValueError('Unexpected DSH inline entry')
    command[1] = str(ROOT / 'scripts/dsh_inline_bc_worker_v4.py')
    return command, result, timeout


def main():
    with patch.object(parent, 'native_command', native_command):
        parent.main()


if __name__ == '__main__':
    main()
