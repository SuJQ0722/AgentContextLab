#!/usr/bin/env python3
"""Explicit Reader deployment 4->32 slots; dry-run by default, no model calls."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import time
import uuid
from urllib.parse import urlsplit

import requests
from lab import ROOT, read_env

CAMPAIGN = ROOT / 'outputs/campaigns/bc100-r3-hermes-parity-v3'
SERVICE = ROOT / 'scripts/local_reader_text_service.py'
OLD_CONFIG = ROOT / 'configs/reader-text-v1.json'
NEW_CONFIG = ROOT / 'configs/reader-text-v1-workers32.json'


def now(): return datetime.now(timezone.utc).isoformat()
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def boot(): return Path('/proc/sys/kernel/random/boot_id').read_text().strip()


def proc(pid):
    base = Path('/proc') / str(pid)
    try:
        fields = (base / 'stat').read_text().split(') ', 1)[1].split()
        return {'pid': pid, 'start_identity': fields[19], 'state': fields[0],
                'ppid': int(fields[1]), 'pgrp': int(fields[2]),
                'executable': os.readlink(base / 'exe'),
                '_argv': [os.fsdecode(x) for x in (base / 'cmdline').read_bytes().split(b'\0') if x],
                '_cwd': os.readlink(base / 'cwd')}
    except (OSError, ValueError, IndexError): return None


def public(identity): return {k: v for k, v in identity.items() if not k.startswith('_')}


def resolve_arg(value, cwd):
    path = Path(value)
    return (path if path.is_absolute() else Path(cwd) / path).resolve()


def is_reader(row):
    if not row: return False
    args = row['_argv']
    try:
        return (len(args) > 1 and resolve_arg(args[1], row['_cwd']) == SERVICE.resolve()
                and resolve_arg(args[args.index('--config') + 1], row['_cwd']) == OLD_CONFIG.resolve())
    except (ValueError, IndexError, OSError): return False


def validate_configs(old, new):
    expected = dict(old); expected['max_concurrent_requests'] = 32
    if old.get('max_concurrent_requests') != 4 or new != expected:
        raise ValueError('Deployment must change only max_concurrent_requests from 4 to 32')
    if new.get('host') != '127.0.0.1' or new.get('port') != 18080:
        raise ValueError('Unexpected Reader endpoint')


def owned_targets(parent, records):
    """No broad killpg: only verified same-group Python extraction descendants."""
    targets = [parent]; visited = {parent['pid']}
    while True:
        additions = [r for r in records if r['ppid'] in visited and r['pid'] not in visited]
        if not additions: break
        for row in additions:
            args = ' '.join(row['_argv'])
            if row['pgrp'] != parent['pgrp'] or row['executable'] != parent['executable'] or not any(
                    marker in args for marker in ('multiprocessing.spawn', 'multiprocessing.resource_tracker', '--multiprocessing-fork')):
                raise ValueError('Reader has an unrecognized child; refuse to signal it')
            targets.append(row); visited.add(row['pid'])
    return targets


def alive(row):
    actual = proc(row['pid'])
    return bool(actual and actual['state'] != 'Z' and actual['start_identity'] == row['start_identity'])


def signal_identity(row, signum, expected_boot):
    if boot() != expected_boot: raise RuntimeError('Boot identity changed')
    if alive(row): os.kill(row['pid'], signum)


def atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    tmp.write_text(json.dumps(data, indent=2) + '\n'); tmp.replace(path)


def affected_trials(root, expected_boot, records=None, partial_unknown=None):
    """Inspect local trial PIDs only; never enumerate the shared campaign tree."""
    rows = []; unknown = partial_unknown if partial_unknown is not None else []
    if boot() != expected_boot: raise RuntimeError('Boot changed during affected-trial inventory')
    if records is None:
        records = [r for p in Path('/proc').iterdir() if p.name.isdigit() and (r := proc(int(p.name)))]
    names = {'run_bc_trial_v3.py', 'run_bc_trial_v3_io.py', 'run_bc_trial_v3_io2.py'}
    namespace = os.readlink('/proc/self/ns/pid'); seen = set()
    jobs = Path(os.path.abspath(root / 'jobs'))
    for row in records:
        args = row.get('_argv', [])
        if row.get('state') == 'Z' or len(args) < 2 or Path(args[1]).name not in names: continue
        if row['pid'] in seen: continue
        seen.add(row['pid'])
        item = {'trial_pid': row['pid'], 'start_identity': row['start_identity']}
        try:
            script = resolve_arg(args[1], row['_cwd'])
            if script != ROOT / 'scripts' / script.name:
                unknown.append(dict(item, reason='unexpected_trial_script_path')); continue
            out = Path(os.path.abspath(os.path.join(row['_cwd'], args[args.index('--out') + 1])))
            spec = Path(os.path.abspath(os.path.join(row['_cwd'], args[args.index('--spec') + 1])))
            relative = out.relative_to(jobs)
            parts = relative.parts
            if len(parts) != 5 or parts[3:] != ('attempts', 'attempt_001') or spec != out.parents[1] / 'spec.json':
                unknown.append(dict(item, reason='unexpected_attempt_path')); continue
            item['job_id'] = '/'.join(parts[:3])
            # One small artifact per local PID. Initializing trials may not yet
            # have running.json: report unknown instead of hiding them.
            running = json.loads((out / 'running.json').read_text())
        except (ValueError, IndexError, OSError):
            unknown.append(dict(item, reason='missing_or_invalid_local_attempt_metadata')); continue
        if (running.get('hostname') != socket.gethostname() or running.get('boot_id') != expected_boot
                or running.get('pid_namespace') != namespace or running.get('pid') != row['pid']
                or running.get('start_identity') != row['start_identity']
                or running.get('job_id') != item['job_id']):
            unknown.append(dict(item, reason='attempt_identity_mismatch')); continue
        if not alive(row):
            unknown.append(dict(item, reason='process_exited_or_identity_changed_during_inventory')); continue
        rows.append({**item, 'effect': 'Potentially interrupted fetch; exact active tool request may be unknown. Model/trial process is not signalled.'})
    return rows


def clean_reader_env(pid):
    # Preserve the original Reader's runtime/proxy choices, never inherit cloud
    # credentials from the operator or copy arbitrary worker environment.
    allowed = {'PATH', 'HOME', 'LANG', 'LC_ALL', 'LD_LIBRARY_PATH', 'PYTHONPATH',
               'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NO_PROXY',
               'http_proxy', 'https_proxy', 'all_proxy', 'no_proxy',
               'OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'}
    env = {}
    for entry in (Path('/proc') / str(pid) / 'environ').read_bytes().split(b'\0'):
        if b'=' not in entry: continue
        k, v = entry.split(b'=', 1); name = os.fsdecode(k)
        if name in allowed: env[name] = os.fsdecode(v)
    # Operator-authorized egress repair: only six network settings from the
    # shared research dotenv, never model/cloud keys or arbitrary variables.
    network = {'http_proxy', 'https_proxy', 'no_proxy', 'HTTP_PROXY', 'HTTPS_PROXY', 'NO_PROXY'}
    shared = read_env(ROOT / '.env')
    env.update({k: v for k, v in shared.items() if k in network})
    env['PYTHONUNBUFFERED'] = '1'
    return env


def proxy_summary(env):
    result = {}
    for key in ('http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY'):
        value = env.get(key)
        if not value:
            result[key] = None
            continue
        try:
            parsed = urlsplit(value)
            result[key] = {'scheme': parsed.scheme, 'hostname': parsed.hostname, 'port': parsed.port,
                           'credentials_present': parsed.username is not None or parsed.password is not None}
        except ValueError:
            result[key] = {'invalid_proxy_url': True}
    result['no_proxy_configured'] = bool(env.get('no_proxy') or env.get('NO_PROXY'))
    result['source'] = 'Six allowlisted network variables from root .env override original Reader environment; credential values are never included here.'
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root', type=Path, default=CAMPAIGN)
    ap.add_argument('--pid', type=int)
    ap.add_argument('--start-identity')
    ap.add_argument('--boot-id')
    ap.add_argument('--live', action='store_true')
    args = ap.parse_args(); root = args.root.resolve()
    old = json.loads(OLD_CONFIG.read_text()); new = json.loads(NEW_CONFIG.read_text()); validate_configs(old, new)
    if sha(old['source_path']) != old['source_sha256']: raise ValueError('Frozen Reader upstream source changed')
    plan = json.loads((root / 'plan.json').read_text())
    if sha(SERVICE) != plan['definition']['implementation_sha256']['scripts/local_reader_text_service.py']:
        raise ValueError('Frozen Reader wrapper changed')
    records = [r for p in Path('/proc').iterdir() if p.name.isdigit() and (r := proc(int(p.name)))]
    candidates = [r for r in records if is_reader(r) and (args.pid is None or r['pid'] == args.pid)]
    if len(candidates) != 1: raise ValueError('Need exactly one matching original four-slot Reader')
    parent = candidates[0]; expected_boot = boot()
    if parent['pgrp'] != parent['pid']: raise ValueError('Original Reader is not its own process-group leader')
    if args.live and (args.pid is None or args.start_identity != parent['start_identity'] or args.boot_id != expected_boot):
        raise ValueError('Live replacement requires exact --pid --start-identity --boot-id from dry-run')
    targets = owned_targets(parent, records)
    env = clean_reader_env(parent['pid'])
    partial_unknown = []
    affected = affected_trials(root, expected_boot, records, partial_unknown)
    report = {'deployment_version': 'reader-text-v1-workers32-ops-v2', 'timestamp': now(),
              'hostname': socket.gethostname(), 'boot_id': expected_boot, 'live': args.live,
              'old_reader': public(parent), 'owned_extraction_children': [public(r) for r in targets[1:]],
              'source_sha256': old['source_sha256'], 'service_sha256': sha(SERVICE),
              'egress_proxy': proxy_summary(env), 'ops_script_sha256': sha(Path(__file__)), 'old_config_sha256': sha(OLD_CONFIG),
              'new_config_sha256': sha(NEW_CONFIG), 'old_slots': 4, 'new_slots': 32,
              'cache_reset_at': None, 'affected_in_progress_trials': affected,
              'affected_trials_partial_unknown': partial_unknown,
              'affected_trials_inventory': 'Local /proc trial entrypoints plus their running.json only; no cross-host AFS enumeration. Snapshot may race process start/exit.',
              'affected_trials_coverage': 'partial_unknown' if partial_unknown else 'local_snapshot_complete',
              'conditions_changed': 'Concurrency 4->32, allowlisted root .env egress proxy settings, and cold cache. Preserve maintenance interval in analyses; not identical service conditions.',
              'model_calls': 0, 'old_bootstrap_expected_behavior': 'Reader exit stops dispatch and drains; no model/trial processes are signalled by this script.'}
    if not args.live:
        print(json.dumps(report, indent=2)); return
    directory = root / 'runtime/nodes' / (socket.gethostname() + '-' + expected_boot) / 'reader-ops' / (str(time.time_ns()))
    report['state'] = 'replacement_started'; report['maintenance_started_at'] = now()
    atomic(directory / 'deployment.json', report)
    client = requests.Session(); client.trust_env = False
    try:
        # Recheck identity immediately before every signal. Never kill a whole
        # process group or any controller/model/trial PID.
        for row in targets: signal_identity(row, signal.SIGTERM, expected_boot)
        until = time.monotonic() + 3
        while any(alive(row) for row in targets) and time.monotonic() < until: time.sleep(.1)
        for row in reversed(targets): signal_identity(row, signal.SIGKILL, expected_boot)
        until = time.monotonic() + 3
        while any(alive(row) for row in targets) and time.monotonic() < until: time.sleep(.1)
        if any(alive(row) for row in targets): raise RuntimeError('Old Reader or extraction child still running')
        report['old_reader_stopped_at'] = now()
        with (directory / 'service.log').open('a') as log:
            child = subprocess.Popen([parent['executable'], str(SERVICE), '--config', str(NEW_CONFIG)],
                cwd=ROOT, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        report['cache_reset_at'] = now()
        report['egress_proxy_and_32_slots_effective_at'] = report['cache_reset_at']
        child_identity = proc(child.pid)
        if child_identity is None: raise RuntimeError('Cannot verify replacement Reader process identity')
        report['new_reader'] = public(child_identity)
        report['state'] = 'new_reader_started'; atomic(directory / 'deployment.json', report)
        deadline = time.monotonic() + 45
        while True:
            if child.poll() is not None: raise RuntimeError('Replacement Reader exited')
            try:
                response = client.get('http://127.0.0.1:18080/health', timeout=2)
                health = response.json()
                if response.status_code == 200 and health.get('source_sha256') == old['source_sha256'] and health.get('mode') == 'text': break
            except (requests.RequestException, ValueError): pass
            if time.monotonic() >= deadline: raise TimeoutError('Replacement Reader health deadline')
            time.sleep(.25)
        report['health_verified_at'] = now()
        url = 'https://example.com/?acl_reader_ops=' + uuid.uuid4().hex
        began = time.monotonic()
        report['cold_fetch'] = {'url': url, 'credentials_sent': False, 'success': False}
        try:
            response = client.post('http://127.0.0.1:18080/fetch', json={'url': url, 'extract_mode': 'text'}, timeout=65)
            data = response.json(); body = data.get('data') or ''
            report['cold_fetch'].update(http_status=response.status_code,
                success=data.get('success') is True and isinstance(body, str) and bool(body.strip()),
                content_chars=len(body) if isinstance(body, str) else None,
                content_sha256=hashlib.sha256(body.encode()).hexdigest() if isinstance(body, str) else None,
                cache_header=response.headers.get('X-Cached'))
        except BaseException as exc:
            report['cold_fetch']['error_type'] = type(exc).__name__
            raise
        finally:
            report['cold_fetch']['client_seconds'] = time.monotonic() - began
        if not report['cold_fetch']['success']: raise RuntimeError('Cold fetch returned no usable evidence')
        report['state'] = 'verified'; report['maintenance_finished_at'] = now()
    except BaseException as exc:
        report['state'] = 'failed'; report['error_type'] = type(exc).__name__
        report['error_errno'] = getattr(exc, 'errno', None); report['failed_at'] = now()
        atomic(directory / 'deployment.json', report)
        raise
    atomic(directory / 'deployment.json', report)
    print(json.dumps({'state': report['state'], 'report': str(directory / 'deployment.json'), 'new_reader': report['new_reader']}))


if __name__ == '__main__': main()
