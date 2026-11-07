#!/usr/bin/env python3
"""Run the existing evaluation harness with root TokenHub configuration."""
import json
import subprocess
import sys
from pathlib import Path
from lab import ROOT, environment, python_for


def main():
    env, cfg = environment(ROOT, 'hermes')
    args = sys.argv[1:]
    if args[:1] == ['--']:
        args = args[1:]
    # Defaults precede caller options, so explicit experiment flags win.
    cmd = [python_for(ROOT), '-m', 'browsecomp_eval.run', '--model', cfg['model'],
           '--provider', 'custom', '--base-url', env['TOKENHUB_BASE_URL'],
           '--api-key-env', 'TOKENHUB_API_KEY', *args]
    if '--print-command' in args:
        cmd.remove('--print-command')
        print(json.dumps(cmd, indent=2))
        return 0
    if not env['TOKENHUB_API_KEY'] and '--help' not in args and '--dry-run' not in args:
        raise SystemExit('Configure TOKENHUB_API_KEY in the root .env first')
    return subprocess.call(cmd, cwd=ROOT / 'hermes-agent/Browsecomp_eval', env=env)


if __name__ == '__main__':
    raise SystemExit(main())
