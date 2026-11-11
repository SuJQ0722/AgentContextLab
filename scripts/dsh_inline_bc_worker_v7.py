"""One-hour DSH worker; SDK and route deadlines match the per-attempt deadline."""
from pathlib import Path
from unittest.mock import patch
import dsh_inline_bc_worker_v6 as previous
from lab import ROOT

VERSION = 'dsh-buffered-sdk-watchdog-one-hour-v3'


def validate_timeout(value):
    if type(value) is not int or value != 3600:
        raise ValueError('Explicit 3600-second DSH attempt deadline required')


def adapt_patches(patches, *, timeout_seconds):
    validate_timeout(timeout_seconds)
    with patch.object(previous, 'validate_timeout', validate_timeout):
        return previous.adapt_patches(patches, timeout_seconds=timeout_seconds)


def main():
    original = previous.native.command
    def command(root, harness, prompt, env):
        old = str(ROOT / 'scripts/dsh_hosted_wire_v4.mjs')
        if env.get('NODE_OPTIONS', '').count(old) != 1:
            raise ValueError('Expected one buffered inline wire preload')
        env['NODE_OPTIONS'] = env['NODE_OPTIONS'].replace(old, str(ROOT / 'scripts/dsh_inline_wire_v5.mjs'))
        return original(root, harness, prompt, env)
    with patch.object(previous, 'validate_timeout', validate_timeout), \
         patch.object(previous, 'VERSION', VERSION), \
         patch.object(previous.native, 'command', command):
        previous.main()


if __name__ == '__main__':
    main()
