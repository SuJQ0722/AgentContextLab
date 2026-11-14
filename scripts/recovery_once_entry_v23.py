"""Versioned budget adapter propagated to children; native scientific code stays pinned.

Invoke under network_entry_v13.py, which owns all proxy credential handling.
"""
import runpy
import subprocess
import sys
from pathlib import Path
import recovery_once_contract_v23 as contract

ENTRY = Path(__file__).resolve()


def install_contract():
    import one_hour_timeout_retry_v10 as retry
    import turns500_contract_v12 as turns
    old_retry, old_turns = retry.validate, turns.validate
    for module in list(sys.modules.values()):
        if module is None:
            continue
        for name, value in list(vars(module).items()):
            if value is old_retry:
                setattr(module, name, contract.validate_retry)
            elif value is old_turns:
                setattr(module, name, contract.validate_turns)
    retry.MAX_ATTEMPTS = 1
    retry.MAX_TIMEOUT_RETRIES = 0


def main():
    if len(sys.argv) < 3 or sys.argv[1] != '--target':
        raise SystemExit('Expected --target script.py')
    target, argv = Path(sys.argv[2]).resolve(), sys.argv[3:]
    install_contract()
    original = subprocess.Popen
    class Propagate(original):
        def __init__(self, args, *a, **kw):
            command = list(args) if isinstance(args, (list, tuple)) else args
            if isinstance(command, list) and len(command) > 1 and 'python' in Path(str(command[0])).name:
                script = Path(str(command[1]))
                if script.suffix == '.py' and script.resolve() != ENTRY and script.name != 'network_entry_v13.py':
                    command = [command[0], str(ENTRY), '--target', str(script), *command[2:]]
            super().__init__(command, *a, **kw)
    subprocess.Popen = Propagate
    sys.argv = [str(target), *argv]
    runpy.run_path(str(target), run_name='__main__')


if __name__ == '__main__':
    main()
