#!/usr/bin/env python3
"""Read-only v3 accounting observer. No retry, inference, process kill, or judging."""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
import math
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


def snapshot(root):
    monitor_rebuttal.SCRIPT_GROUPS.update({
        'run_bc_campaign_v3.py': 'core_bc_v3', 'run_bc_trial_v3.py': 'core_bc_v3',
        'hermes_bc_worker_v3.py': 'core_bc_v3', 'run_dsh_eval_v3.py': 'core_bc_v3',
        'monitor_bc_campaign_v3.py': 'resource_monitor'})
    processes = monitor_rebuttal.process_snapshot()
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
