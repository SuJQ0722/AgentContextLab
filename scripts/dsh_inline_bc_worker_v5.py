"""Adapt DSH's SDK watchdog to buffered route retries without raising task budgets.

The wire adapter retains its 300-second per-attempt limit and the native runner
retains the explicit task timeout. The SDK sees buffered responses, so its idle
watchdog must not preempt an otherwise live multi-route request after 300s.
"""
import argparse
import copy
import json
import subprocess
from pathlib import Path
from unittest.mock import patch
import dsh_inline_bc_worker_v4 as parent
from inline_route_contract_v2 import validate_routes
from lab import ROOT

VERSION = 'dsh-buffered-sdk-watchdog-v1'
native = parent.parent.parent.native


def validate_timeout(timeout_seconds):
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int) or not 1 <= timeout_seconds <= 1800:
        raise ValueError('DSH BC task timeout must remain within its approved 1800-second budget')


def adapt_patches(patches, *, timeout_seconds):
    validate_timeout(timeout_seconds)
    result = copy.deepcopy(patches)
    matches = [p for p in result if p.get('id') == 'llm-pi-ai']
    if len(matches) != 1:
        raise ValueError('Expected exactly one pinned pi-ai provider patch')
    provider = matches[0]['config']['providers']['tokenhub']
    if 'streamIdleTimeoutMs' in provider:
        raise ValueError('Unexpected existing SDK watchdog override')
    provider['streamIdleTimeoutMs'] = timeout_seconds * 1000
    return result


def configure_proxy(env, proxy):
    if proxy != 'http://10.120.0.246:7890':
        raise ValueError('Explicit approved DSH gateway proxy required')
    for key in ('HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy'):
        env[key] = proxy
    for key in ('ALL_PROXY', 'all_proxy'):
        env.pop(key, None)
    code = """
import {resolveProxyPolicy,proxyForUrl} from './deepseekHarness/packages/util/http-proxy/src/policy.ts';
const env=JSON.parse(process.argv[1]);
const {policy}=resolveProxyPolicy({get:key=>env[key]===undefined?undefined:{value:env[key]}});
if(proxyForUrl(policy,new URL(process.argv[2]))!==process.argv[3])process.exit(1);
"""
    safe = {key: value for key, value in env.items() if key.lower() in ('http_proxy','https_proxy','no_proxy')}
    run = subprocess.run(['node', '--input-type=module', '-e', code, json.dumps(safe),
                          env['TOKENHUB_BASE_URL'], proxy], cwd=ROOT,
                         env={'PATH': env['PATH']}, capture_output=True, timeout=30)
    if run.returncode:
        raise ValueError('Pinned DSH proxy resolver did not select the approved gateway proxy')


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--timeout', required=True, type=int)
    args, _ = parser.parse_known_args()
    validate_timeout(args.timeout)
    config = json.loads(args.config.read_text())
    if config.get('dsh_buffered_watchdog_version') != VERSION:
        raise ValueError('Explicit versioned DSH buffered watchdog approval required')
    original = native.preservation_patches
    def preservation(env):
        configure_proxy(env, config['gateway_proxy'])
        patches = adapt_patches(original(env), timeout_seconds=args.timeout)
        metrics = Path(env['ACL_WORKSPACE']) / 'metrics'
        metrics.mkdir(parents=True, exist_ok=True)
        (metrics / 'buffered-sdk-watchdog-v1.json').write_text(json.dumps({
            'version': VERSION, 'sdk_idle_timeout_ms': args.timeout * 1000,
            'outer_task_timeout_seconds': args.timeout,
            'wire_attempt_timeout_seconds': 300,
            'max_output_tokens': int(env['ACL_MAX_OUTPUT_TOKENS']),
            'gateway_proxy': config['gateway_proxy'],
            'campaign_transport_policy': config['transport_runtime_version'],
            'dsh_wire_implementation': 'dsh-inline-wire-v1',
            'python_transport_runtime_executed': False,
            'output_budget_changed': False, 'task_budget_changed': False,
            'reason': 'SDK cannot observe progress while complete route responses are buffered',
        }, indent=2))
        return patches
    with patch.object(native, 'preservation_patches', preservation), patch.object(parent.parent, 'validate_routes', validate_routes):
        parent.main()


if __name__ == '__main__':
    main()
