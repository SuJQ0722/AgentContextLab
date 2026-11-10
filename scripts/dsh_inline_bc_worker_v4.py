"""Preserve leading-hyphen questions at the final DSH CLI argument boundary."""
from pathlib import Path
from unittest.mock import patch
import dsh_hosted_bc_worker_v3 as parent
from lab import ROOT


def separate_prompt(command):
    if not isinstance(command, (list, tuple)) or len(command) < 3:
        return command
    if Path(command[1]) != ROOT / 'deepseekHarness/apps/cli/lib/bin.js':
        return command
    command = list(command)
    if '--json' not in command or '--approval-policy' not in command:
        raise ValueError('Expected the final reviewed DSH headless command')
    # The launcher forwards everything after --json to the headless parser.
    # Insert after the final options, so this delimiter reaches that parser.
    if command[-2] != '--':
        command.insert(len(command) - 1, '--')
    return command


def main():
    original = parent.parent.native.subprocess.Popen
    def popen(command, *args, **kwargs):
        return original(separate_prompt(command), *args, **kwargs)
    with patch.object(parent.parent.native.subprocess, 'Popen', popen):
        parent.main()


if __name__ == '__main__':
    main()
