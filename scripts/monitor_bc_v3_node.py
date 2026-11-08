#!/usr/bin/env python3
"""Local /proc and cgroup telemetry only; no model, retry, or worker control."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import signal
import socket
import time
import uuid

from lab import ROOT
import monitor_rebuttal

DEFAULT_ROOT = ROOT / 'outputs/campaigns/bc100-r3-hermes-parity-v3'
ROLE_SCRIPTS = {
    'run_bc_campaign_v3_capacity1.py': 'controller',
    'run_bc_trial_v3_capacity1.py': 'trial',
    'run_dsh_eval_v3_capacity1.py': 'dsh_worker',
    'run_bc_campaign_v3_io2.py': 'controller',
    'run_bc_trial_v3_io2.py': 'trial',
    'run_bc_campaign_v3_io.py': 'controller',
    'run_bc_trial_v3_io.py': 'trial',
    'run_bc_campaign_v3.py': 'controller',
    'run_bc_trial_v3.py': 'trial',
    'hermes_bc_worker_v3.py': 'hermes_worker',
    'run_dsh_eval_v3.py': 'dsh_worker',
}


def read(path):
    try:
        return path.read_text().strip()
    except OSError:
        return None


def number(path):
    value = read(path)
    try:
        return int(value) if value is not None and value != 'max' else None
    except ValueError:
        return None


def counters(path):
    value = read(path)
    if value is None:
        return None
    try:
        return {k: int(v) for k, v in (line.split() for line in value.splitlines())}
    except ValueError:
        return None


def cgroup_snapshot(base=Path('/sys/fs/cgroup')):
    """Read namespace-root cgroup v2 files; missing values stay unknown."""
    current = number(base / 'memory.current')
    stat = counters(base / 'memory.stat')
    inactive = (stat or {}).get('inactive_file')
    return {
        'path': str(base), 'version': 2 if (base / 'cgroup.controllers').exists() else None,
        'cpu': {'stat': counters(base / 'cpu.stat'), 'max': read(base / 'cpu.max'),
                'cpuset_effective': read(base / 'cpuset.cpus.effective'),
                'pressure': read(base / 'cpu.pressure')},
        'memory': {'current_bytes': current, 'max': read(base / 'memory.max'),
                   'inactive_file_bytes': inactive,
                   'working_set_estimate_bytes': max(0, current - inactive) if current is not None and inactive is not None else None,
                   'events': counters(base / 'memory.events'),
                   'events_local': counters(base / 'memory.events.local')},
        'pids': {'current': number(base / 'pids.current'), 'max': read(base / 'pids.max'),
                 'events': counters(base / 'pids.events')},
        'note': 'Cgroup counters include all processes/threads charged to this cgroup. pids.current counts tasks, not /proc process directories. CPU counters and OOM events are cumulative; working set subtracts inactive_file and is an estimate.'}


def process_census():
    monitor_rebuttal.SCRIPT_GROUPS.update({name: 'core_bc_v3' for name in ROLE_SCRIPTS})
    monitor_rebuttal.SCRIPT_GROUPS['monitor_bc_v3_node.py'] = 'resource_monitor'
    monitor_rebuttal.SCRIPT_GROUPS['monitor_bc_campaign_v3.py'] = 'resource_monitor'
    processes = monitor_rebuttal.process_snapshot()
    live = {pid: row for pid, row in processes.items() if row['state'] != 'Z'}
    core = {pid: row for pid, row in live.items() if row['group'] == 'core_bc_v3'}
    roles = {role: 0 for role in ROLE_SCRIPTS.values()}
    role_read_failures = 0
    node_count = 0
    for pid in core:
        try:
            # Used solely for exact script classification; never return arguments.
            process_dir = Path('/proc') / str(pid)
            argv = (process_dir / 'cmdline').read_bytes().split(b'\0')
            # Node 24 can report comm=MainThread, so classify its executable.
            try:
                executable = Path(os.readlink(process_dir / 'exe')).name
            except OSError:
                executable = Path(os.fsdecode(argv[0])).name if argv else ''
            if executable in ('node', 'nodejs'):
                node_count += 1
            for arg in argv:
                if b' ' in arg or b'\n' in arg:
                    continue
                role = ROLE_SCRIPTS.get(Path(os.fsdecode(arg)).name)
                if role:
                    roles[role] += 1
                    break
        except OSError:
            role_read_failures += 1
    return {'visible_total': len(processes), 'visible_live': len(live),
            'visible_zombie': len(processes) - len(live),
            'core_v3_subtree_live': len(core), 'core_v3_roles': roles,
            'core_v3_node_runtime_live': node_count, 'role_read_failures': role_read_failures,
            'scope': 'Local PID namespace /proc process directories, not all cluster hosts or threads. Descendants inherit v3 classification; role/node counts are overlapping subsets, not additive worker concurrency. Snapshot is best effort as processes start/exit.'}


def identity():
    hostname = socket.gethostname()
    boot_id = read(Path('/proc/sys/kernel/random/boot_id')) or 'unknown'
    try:
        namespace = os.readlink('/proc/self/ns/pid')
    except OSError:
        namespace = None
    return {'hostname': hostname, 'boot_id': boot_id, 'pid_namespace': namespace}


def snapshot(host=None):
    host = host or identity()
    return {'schema': 'bc-v3-node-telemetry-v1', 'timestamp': datetime.now(timezone.utc).isoformat(),
            **host, 'observer_pid': os.getpid(), 'processes': process_census(),
            'cgroup': cgroup_snapshot(), 'paid_model_calls': 0}


def node_directory(root, host):
    name = re.sub(r'[^A-Za-z0-9_.-]', '_', host['hostname'] + '-' + host['boot_id'])
    return root / 'runtime/nodes' / name


def write_snapshot(destination, row):
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_name('.telemetry.' + uuid.uuid4().hex + '.tmp')
    temp.write_text(json.dumps(row, ensure_ascii=False, indent=2) + '\n')
    temp.replace(destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=DEFAULT_ROOT)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--once', action='store_true', help='Write one snapshot (default).')
    mode.add_argument('--watch', action='store_true', help='Write immediately, then every 30 seconds.')
    args = parser.parse_args()
    host = identity()
    destination = node_directory(args.root.resolve(), host) / 'telemetry.json'
    stopping = False
    def stop(_signum, _frame):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    while not stopping:
        write_snapshot(destination, snapshot(host))
        if not args.watch:
            break
        # Short sleeps allow prompt bootstrap cleanup without signaling workers.
        for _ in range(30):
            if stopping:
                break
            time.sleep(1)


if __name__ == '__main__':
    main()
