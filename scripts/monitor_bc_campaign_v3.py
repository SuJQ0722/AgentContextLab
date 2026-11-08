#!/usr/bin/env python3
"""Read-only v3 accounting observer. No retry, inference, process kill, or judging."""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
import math
import os
import socket
from pathlib import Path
import time
import uuid
from lab import ROOT
import monitor_rebuttal

DEFAULT_ROOT = ROOT / 'outputs/campaigns/bc100-r3-hermes-parity-v3'
FIELDS = ('prompt', 'cached_input', 'noncache_input', 'output', 'total')
ALIASES = {
    'prompt': ('prompt_tokens', 'input_tokens'),
    'cached_input': ('prompt_tokens_details.cached_tokens', 'input_tokens_details.cached_tokens', 'prompt_cache_hit_tokens', 'cached_tokens'),
    'noncache_input': ('prompt_cache_miss_tokens',),
    'output': ('completion_tokens', 'output_tokens'),
    'total': ('total_tokens',),
}


def count(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def numeric(value):
    return isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def analyze_usage(raw):
    """Only raw aliases; explicit null/conflicting counters never become zeros."""
    raw = raw if isinstance(raw, dict) else {}
    values, errors = {}, []
    for field, paths in ALIASES.items():
        found = []
        for path in paths:
            node = raw
            for key in path.split('.'):
                if not isinstance(node, dict) or key not in node:
                    break
                node = node[key]
            else:
                found.append(node)
        if found and (not all(count(v) for v in found) or len(set(found)) != 1):
            errors.append(field + '_invalid_or_conflicting')
            values[field] = None
        else:
            values[field] = found[0] if found else None
    p, c, n, o, t = (values[k] for k in FIELDS)
    if p is not None and c is not None:
        if c > p:
            errors.append('cached_exceeds_prompt')
            values['cached_input'] = values['noncache_input'] = None
        elif n is not None and c + n != p:
            errors.append('cache_split_not_conserved')
            values['cached_input'] = values['noncache_input'] = None
        elif n is None and 'noncache_input_invalid_or_conflicting' not in errors:
            values['noncache_input'] = p - c
    if p is not None and n is not None and n > p:
        errors.append('noncache_exceeds_prompt')
        values['noncache_input'] = None
    if p is not None and o is not None and t is not None and p + o != t:
        errors.append('prompt_output_total_not_conserved')
    return values, errors


def aggregate(rows):
    totals = {k: {'known_subtotal': 0, 'known_count': 0, 'missing_count': 0, 'complete_total': None} for k in FIELDS}
    errors = Counter()
    for row in rows:
        values, failures = analyze_usage(row.get('raw_provider_usage'))
        errors.update(failures)
        if row.get('_incomplete'):
            values = {k: None for k in FIELDS}
        for k, v in values.items():
            totals[k]['missing_count' if v is None else 'known_count'] += 1
            if v is not None:
                totals[k]['known_subtotal'] += v
    for data in totals.values():
        if data['known_count'] and not data['missing_count']:
            data['complete_total'] = data['known_subtotal']
    return {'observations': len(rows), 'fields': totals, 'conservation_issues': dict(errors),
            'note': 'Known subtotals need not conserve across different missing-field cohorts; conservation is checked per request. No derived total replaces missing provider total.'}


def read_json(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def jsonl(path, issues):
    try:
        with path.open() as stream:
            for lineno, line in enumerate(stream, 1):
                try:
                    row = json.loads(line)
                    if isinstance(row, dict):
                        yield row
                    else:
                        raise ValueError('not object')
                except ValueError:
                    issues.append({'kind': 'invalid_or_inflight_jsonl_line', 'file': str(path), 'line': lineno})
    except OSError:
        issues.append({'kind': 'unreadable_metrics', 'file': str(path)})


def unique_rows(rows, key, issues):
    result = {}
    for index, row in enumerate(rows):
        identity = row.get(key)
        if identity is None:
            identity = ('missing_id', index)
            issues.append({'kind': 'missing_record_identity', 'field': key})
        if identity in result and result[identity] != row:
            issues.append({'kind': 'conflicting_duplicate_record', 'field': key})
        result[identity] = row
    return result


def accounting(metrics, harness, issues):
    calls = list(jsonl(metrics / 'calls.jsonl', issues)) if (metrics / 'calls.jsonl').exists() else []
    starts = list(jsonl(metrics / 'call-starts.jsonl', issues)) if (metrics / 'call-starts.jsonl').exists() else []
    calls_by_id = unique_rows(calls, 'call_id', issues)
    starts_by_id = unique_rows(starts, 'call_id', issues)
    sdk_open = [v for k, v in starts_by_id.items() if k not in calls_by_id]
    states = Counter(sdk_started=len(starts_by_id), sdk_terminal=len(calls_by_id), sdk_unresolved=len(sdk_open))
    if harness == 'dsh':
        path = metrics / 'wire/raw-usage.jsonl'
        records = list(jsonl(path, issues)) if path.exists() else []
        began = unique_rows([r for r in records if r.get('event') == 'response_started'], 'request_id', issues)
        ended = unique_rows([r for r in records if r.get('event') != 'response_started'], 'request_id', issues)
        sent_path = metrics / 'wire/requests.jsonl'
        sent = unique_rows([r for r in jsonl(sent_path, issues) if r.get('request_sent') is True],
                           'request_id', issues) if sent_path.exists() else {}
        no_response = [dict(r, purpose='title' if r.get('is_title_request') else 'unknown')
                       for key, r in sent.items() if key not in began and key not in ended]
        unresolved = [v for k, v in began.items() if k not in ended]
        states.update(http_request_sent=len(sent), http_response_started=len(began),
                      http_terminal=len(ended), http_response_inflight=len(unresolved),
                      http_sent_without_response=len(no_response))
        rows = []
        for row in ended.values():
            row = dict(row)
            row['_incomplete'] = row.get('response_complete') is not True
            states['http_complete' if not row['_incomplete'] else 'http_incomplete_terminal'] += 1
            rows.append(row)
        rows += [dict(r, raw_provider_usage=None, _incomplete=True) for r in unresolved]
        rows += [dict(r, raw_provider_usage=None, _incomplete=True) for r in no_response]
        # Missing HTTP records must not disappear or fall back to SDK zero defaults.
        if not records and not sent and (calls or starts):
            issues.append({'kind': 'missing_raw_http_usage', 'metrics': str(metrics)})
            rows = [dict(r, raw_provider_usage=None, _incomplete=True) for r in list(calls_by_id.values()) + sdk_open]
    else:
        rows = [dict(r, _incomplete=bool(r.get('error_type'))) for r in calls_by_id.values()]
        rows += [dict(r, raw_provider_usage=None, _incomplete=True) for r in sdk_open]
    latency = [r.get('client_stream_seconds') for r in calls_by_id.values()]
    by_purpose = defaultdict(list)
    for row in rows:
        by_purpose[row.get('purpose') or 'unknown'].append(row)
    return rows, dict(states), {k: aggregate(v) for k, v in by_purpose.items()}, {
        'sdk_client_seconds_known_subtotal': sum(v for v in latency if numeric(v)),
        'sdk_client_seconds_missing_count': sum(not numeric(v) for v in latency),
        'provider_internal_seconds': None,
        'definition': 'SDK client wall time, including retries; DSH normalized calls used only for latency, never token accounting. Not provider-internal latency; not additive with nested render/IPC.'}


def inspect_attempt(attempt, harness):
    issues, all_rows, counts = [], [], Counter()
    by_purpose = defaultdict(list)
    sdk_known, sdk_missing = 0, 0
    web, compression, rendering = Counter(), 0, []
    metric_dirs = sorted({p.parent for p in attempt.rglob('calls.jsonl')} | {p.parent for p in attempt.rglob('call-starts.jsonl')} | {p.parent.parent for p in attempt.rglob('raw-usage.jsonl') if p.parent.name == 'wire'})
    for metrics in metric_dirs:
        rows, states, _, latency = accounting(metrics, harness, issues)
        all_rows += rows
        counts.update(states)
        sdk_known += latency['sdk_client_seconds_known_subtotal']
        sdk_missing += latency['sdk_client_seconds_missing_count']
        for row in rows:
            by_purpose[row.get('purpose') or 'unknown'].append(row)
        f = metrics / 'web.jsonl'
        if f.exists():
            webrows = list(jsonl(f, issues))
            keyed = [r for r in webrows if r.get('transport_id')]
            webrows = list(unique_rows(keyed, 'transport_id', issues).values()) + [r for r in webrows if not r.get('transport_id')]
            for r in webrows:
                value = str(r.get('cache_header')).lower()
                status = 'hits' if value == 'true' else 'misses' if value == 'false' else 'unknown'
                web[f"{r.get('kind', 'unknown')}_{status}"] += 1
        if harness == 'dsh':
            policy = metrics / 'shared-policy.jsonl'
            if policy.exists():
                for r in jsonl(policy, issues):
                    delta = r.get('compression_count_delta')
                    if count(delta): compression += delta
                    else: issues.append({'kind': 'missing_compression_delta', 'file': str(policy)})
                    rendering.append(r.get('render_seconds'))
        else:
            f = metrics / 'compression.jsonl'
            if f.exists():
                for r in jsonl(f, issues):
                    delta = r.get('count_delta')
                    if count(delta): compression += delta
                    else: issues.append({'kind': 'missing_compression_delta', 'file': str(f)})
            f = metrics / 'render.jsonl'
            if f.exists(): rendering += [r.get('render_seconds') for r in jsonl(f, issues)]
    compression_files = [m / ('shared-policy.jsonl' if harness == 'dsh' else 'compression.jsonl') for m in metric_dirs]
    result = read_json(attempt / 'result.json')
    heartbeat = read_json(attempt / 'heartbeat.json')
    if not result and (counts.get('sdk_unresolved') or counts.get('http_response_inflight') or counts.get('http_sent_without_response')):
        issues.append({'kind': 'unresolved_requests_not_proof_of_live_process'})
    if not result and (attempt / 'heartbeat.json').exists() and time.time() - (attempt / 'heartbeat.json').stat().st_mtime > 180:
        issues.append({'kind': 'stale_attempt_heartbeat', 'seconds': round(time.time() - (attempt / 'heartbeat.json').stat().st_mtime)})
    row = {'attempt': str(attempt), 'harness': harness, 'state': (result or {}).get('status', 'unfinished'),
           'result_present': bool(result), 'metrics_directories': len(metric_dirs), 'requests': dict(counts),
           'usage': aggregate(all_rows), 'usage_by_purpose': {k: aggregate(v) for k, v in by_purpose.items()},
           'web_cache': dict(web), 'compression_count_known_subtotal': compression,
           'compression_metrics_present': any(p.exists() for p in compression_files),
           'render_metrics_present': bool(rendering),
           'render_seconds_known_subtotal': sum(v for v in rendering if numeric(v)),
           'render_seconds_missing_count': sum(not numeric(v) for v in rendering),
           'sdk_client_seconds_known_subtotal': sdk_known, 'sdk_client_seconds_missing_count': sdk_missing,
           'end_to_end_seconds': (result or {}).get('end_to_end_seconds'), 'usd': None,
           'heartbeat_present': heartbeat is not None, 'issues': issues}
    return row, all_rows


def node_process_totals(root, local_counts, *, now_unix=None, local_identity=None,
                        submissions_root=None, local_observed_unix=None):
    """Observed PID-namespace counts; incomplete cloud coverage never becomes zero."""
    now_unix = time.time() if now_unix is None else now_unix
    local_identity = local_identity or {'hostname': socket.gethostname(),
        'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
        'pid_namespace': os.readlink('/proc/self/ns/pid')}
    local_key = (local_identity.get('hostname'), local_identity.get('boot_id'))
    directory = root / 'runtime/nodes'
    submissions_root = submissions_root or ROOT / 'outputs/cloud-runtime/submissions'
    issues, active, terminal = [], [], {'completed', 'succeeded', 'failed', 'submission_failed', 'cancelled', 'canceled', 'stopped', 'deleted', 'terminated'}
    active_states = {'submitting', 'submitted', 'queued', 'pending', 'scheduled', 'starting', 'running', 'active'}
    registry_complete = submissions_root.is_dir()
    for path in sorted(submissions_root.glob('*.json')):
        item = read_json(path)
        if not isinstance(item, dict):
            registry_complete = False; issues.append({'kind': 'unreadable_submission', 'path': str(path)}); continue
        if item.get('mode') == 'dry_run' or item.get('state') in terminal: continue
        if item.get('state') not in active_states:
            registry_complete = False; issues.append({'kind': 'unknown_submission_state', 'name': item.get('name', path.stem)}); continue
        # `workers: 32` is harness concurrency, never 32 cloud nodes.
        nodes = item.get('worker_nodes', 1)
        argv = item.get('argv', [])
        if isinstance(argv, list) and '--worker-nodes' in argv:
            try: nodes = int(argv[argv.index('--worker-nodes') + 1])
            except (ValueError, IndexError, TypeError): nodes = None
        if not count(nodes) or nodes < 1:
            registry_complete = False; nodes = None
        active.append({'name': item.get('name', path.stem), 'state': item.get('state'), 'expected_nodes': nodes})
    expected = sum(item['expected_nodes'] or 0 for item in active) if registry_complete else None
    if not registry_complete: issues.append({'kind': 'submission_registry_incomplete'})
    nodes, chosen = [], {}
    for path in sorted(directory.glob('*/telemetry.json')):
        item = read_json(path)
        row = {'path': str(path), 'status': 'invalid', 'counted': False}
        if not isinstance(item, dict) or item.get('schema') != 'bc-v3-node-telemetry-v1':
            issues.append({'kind': 'invalid_node_telemetry', 'path': str(path)}); nodes.append(row); continue
        row.update({key: item.get(key) for key in ('timestamp', 'hostname', 'boot_id', 'pid_namespace')})
        row.update(processes=item.get('processes') if isinstance(item.get('processes'), dict) else None,
                   cgroup=item.get('cgroup') if isinstance(item.get('cgroup'), dict) else None)
        key = (item.get('hostname'), item.get('boot_id'))
        if not all(isinstance(v, str) and v for v in key):
            issues.append({'kind': 'missing_node_identity', 'path': str(path)}); nodes.append(row); continue
        try:
            timestamp = datetime.fromisoformat(item['timestamp'].replace('Z', '+00:00'))
            if timestamp.tzinfo is None: raise ValueError('timezone required')
            age = now_unix - timestamp.timestamp()
        except (ValueError, TypeError, KeyError, AttributeError):
            issues.append({'kind': 'invalid_node_timestamp', 'path': str(path)}); nodes.append(row); continue
        row.update(age_seconds=round(age, 3), status='fresh' if -5 <= age <= 90 else 'stale' if age > 90 else 'future_timestamp')
        if key == local_key:
            row['status'] = 'local_duplicate'
            if item.get('pid_namespace') != local_identity.get('pid_namespace'):
                issues.append({'kind': 'local_pid_namespace_conflict', 'path': str(path)})
        elif key in chosen:
            previous = chosen[key]
            if previous.get('pid_namespace') != row.get('pid_namespace'):
                issues.append({'kind': 'remote_pid_namespace_conflict', 'hostname': key[0]})
            if row['age_seconds'] < previous['age_seconds']:
                previous['status'] = 'duplicate_superseded'; chosen[key] = row
            else: row['status'] = 'duplicate_superseded'
        else: chosen[key] = row
        nodes.append(row)
    fresh = [row for row in chosen.values() if row['status'] == 'fresh']
    for row in fresh: row['counted'] = True
    unknown_nodes = sum(row['status'] not in ('fresh', 'local_duplicate', 'duplicate_superseded') for row in nodes)
    missing = max(0, expected - len(fresh)) if expected is not None else None
    local_age = max(0, now_unix - (now_unix if local_observed_unix is None else local_observed_unix))
    coverage = registry_complete and missing == 0 and unknown_nodes == 0 and not issues and local_age <= 90
    fields = {}
    for key in ('visible_total', 'visible_live', 'core_v3_subtree_live'):
        values = [local_counts.get(key)] + [(row.get('processes') or {}).get(key) for row in fresh]
        known = [value for value in values if count(value)]
        complete = coverage and len(known) == len(values)
        fields[key] = {'known_subtotal': sum(known), 'known_nodes': len(known),
                       'missing_count_nodes': len(values) - len(known),
                       'complete_total': sum(known) if complete else None}
    complete = coverage and all(value['complete_total'] is not None for value in fields.values())
    cloud = {'telemetry_root': str(directory), 'freshness_seconds': 90, 'nodes': nodes,
             'fresh_unique_remote_nodes': len(fresh), 'expected_active_cloud_nodes': expected,
             'missing_fresh_nodes': missing, 'unusable_telemetry_nodes': unknown_nodes,
             'active_submissions': active, 'submission_registry_complete': registry_complete,
             'coverage_complete': coverage, 'issues': issues,
             'matching_scope': 'Count coverage only: submission receipts do not identify host/boot. Queued/submitting nodes remain expected until a terminal receipt is recorded.'}
    total = {'complete': complete, 'fields': fields, 'local_identity': local_identity,
             'local_snapshot_age_seconds': round(local_age, 3), 'counted_remote_nodes': len(fresh),
             'expected_unreported_remote_nodes': missing, 'unusable_telemetry_nodes': unknown_nodes,
             'scope': 'Sum of observed local PID namespaces, not physical-host process totals or threads. Hostname+boot duplicates are excluded; stale/missing nodes are unknown, never zero.'}
    return cloud, total


def snapshot(root):
    monitor_rebuttal.SCRIPT_GROUPS.update({
        'run_bc_campaign_v3.py': 'core_bc_v3', 'run_bc_trial_v3.py': 'core_bc_v3',
        'run_bc_campaign_v3_io.py': 'core_bc_v3', 'run_bc_trial_v3_io.py': 'core_bc_v3',
        'hermes_bc_worker_v3.py': 'core_bc_v3', 'run_dsh_eval_v3.py': 'core_bc_v3',
        'monitor_bc_campaign_v3.py': 'resource_monitor'})
    processes = monitor_rebuttal.process_snapshot()
    process_observed_unix = time.time()
    live = {k: v for k, v in processes.items() if v['state'] != 'Z'}
    attempts, rows, cells, purposes = [], [], defaultdict(list), defaultdict(list)
    for path in sorted((root / 'jobs').glob('*/*/*/attempts/attempt_*')):
        rel = path.relative_to(root / 'jobs').parts
        if not path.is_dir(): continue
        row, usage = inspect_attempt(path, rel[0])
        row.update(strategy=rel[1], trial=rel[2])
        attempts.append(row); rows += usage; cells['/'.join(rel[:2])] += usage
        for r in usage: purposes[r.get('purpose') or 'unknown'].append(r)
    states = Counter(r['state'] for r in attempts)
    requests, web = Counter(), Counter()
    for attempt in attempts:
        requests.update(attempt['requests']); web.update(attempt['web_cache'])
    local_processes = {'visible_total': len(processes), 'visible_live': len(live),
                       'core_v3_subtree_live': sum(v['group'] == 'core_bc_v3' for v in live.values())}
    cloud_nodes, global_counts = node_process_totals(root, local_processes, local_observed_unix=process_observed_unix)
    return {'schema': 'bc-v3-monitor-v1', 'as_of': datetime.now(timezone.utc).isoformat(), 'root': str(root),
            'attempt_states': dict(states), 'attempt_count': len(attempts),
            'requests': dict(requests), 'web_cache': dict(web),
            'compression_count_known_subtotal': sum(r['compression_count_known_subtotal'] for r in attempts),
            'attempts_without_compression_metrics': sum(not r['compression_metrics_present'] for r in attempts),
            'render_seconds_known_subtotal': sum(r['render_seconds_known_subtotal'] for r in attempts),
            'attempts_without_render_metrics': sum(not r['render_metrics_present'] for r in attempts),
            'render_seconds_missing_count': sum(r['render_seconds_missing_count'] for r in attempts),
            'sdk_client_seconds_known_subtotal': sum(r['sdk_client_seconds_known_subtotal'] for r in attempts),
            'sdk_client_seconds_missing_count': sum(r['sdk_client_seconds_missing_count'] for r in attempts),
            'usage': aggregate(rows), 'usage_by_cell': {k: aggregate(v) for k, v in cells.items()},
            'usage_by_purpose': {k: aggregate(v) for k, v in purposes.items()}, 'attempts': attempts,
            'controllers': [{'path': str(p), 'status': read_json(p)} for p in sorted((root / 'controllers').glob('*/status.json'))],
            'processes': {'visible_total': len(processes), 'visible_live': len(live),
                          'core_v3_subtree_live': sum(v['group'] == 'core_bc_v3' for v in live.values()),
                          'scope': 'This local /proc namespace only; not cross-host concurrency or threads.'},
            'cloud_nodes': cloud_nodes, 'global_process_counts': global_counts,
            'usd': None, 'provider_internal_latency_seconds': None,
            'definitions': {'usage': 'All attempts, raw counters only; incomplete observations remain unknown. No price inference.',
                            'latency': 'SDK client duration includes retries; not provider internal latency. Rendering is separately timed and nested inside compression; never sum render+IPC+API as end-to-end.',
                            'web_cache': 'X-Cached transport evidence only, separate from provider cached input tokens.',
                            'compression': 'Observed counter deltas; absent metric files cannot prove zero compression.'}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=DEFAULT_ROOT)
    parser.add_argument('--watch', action='store_true')
    args = parser.parse_args()
    out = args.root / 'monitor'; out.mkdir(parents=True, exist_ok=True)
    while True:
        report = snapshot(args.root.resolve())
        tmp = out / ('status.' + uuid.uuid4().hex + '.tmp')
        tmp.write_text(json.dumps(report, ensure_ascii=False, indent=2))
        tmp.replace(out / 'status.json')
        history = {k: v for k, v in report.items() if k not in ('attempts', 'controllers')}
        with (out / 'history.jsonl').open('a') as stream: stream.write(json.dumps(history) + '\n')
        print(json.dumps({'as_of': report['as_of'], 'attempt_states': report['attempt_states'], 'processes': report['processes']}), flush=True)
        if not args.watch: break
        time.sleep(30)


if __name__ == '__main__':
    main()
