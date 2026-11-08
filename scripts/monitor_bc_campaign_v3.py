#!/usr/bin/env python3
"""Read-only v3 accounting observer. No retry, inference, process kill, or judging."""
import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timezone
import json
import hashlib
import math
import re
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


# Process-local only. A released slot is written after descendant termination;
# no active producer may be cached. File/dir metadata also invalidates a cached
# result if archived metrics are later repaired or appended. Missing remains
# missing: this is an I/O optimization, never an accounting substitution.
_TERMINAL_CACHE = {}
_TERMINAL_STATES = {'completed', 'failed', 'timeout', 'interrupted', 'not_started'}
_METRIC_NAMES = ('calls.jsonl', 'call-starts.jsonl', 'web.jsonl',
                 'shared-policy.jsonl', 'compression.jsonl', 'render.jsonl',
                 'wire/raw-usage.jsonl', 'wire/requests.jsonl')


def _known_metric_path(attempt, harness):
    # Formal v3 trial layout, including io/capacity maintenance entrypoints.
    if (attempt.parent.name != 'attempts' or len(attempt.parents) < 4
            or attempt.parents[3].name != harness): return None
    if harness == 'hermes': return attempt/'native/metrics'
    if harness == 'dsh':
        strategy=attempt.parents[2].name
        mapped={'visual':'visual_native','sliding_window':'sliding_window_native'}.get(strategy,strategy)
        trial=attempt.parents[1].name
        question=re.sub(r'_r[0-9]+$', '', trial)
        if question == trial: return None
        return attempt/'native'/mapped/question/'workspace/metrics'
    return None


def _metric_directories(attempt, harness=None):
    known=_known_metric_path(attempt,harness)
    if known is not None:
        return [known] if known.is_dir() else []
    # Standalone/legacy fixtures: one traversal, never three recursive walks.
    found=set()
    for path in attempt.rglob('*.jsonl'):
        if path.name in ('calls.jsonl','call-starts.jsonl'): found.add(path.parent)
        elif path.name=='raw-usage.jsonl' and path.parent.name=='wire': found.add(path.parent.parent)
    return sorted(found)


def _cache_metadata_paths(attempt,harness,metric_dirs):
    paths={attempt/'result.json',attempt/'heartbeat.json',attempt}
    known=_known_metric_path(attempt,harness)
    directories=set(metric_dirs)
    if known is not None: directories.add(known)
    else: paths.update(p for p in attempt.rglob('*') if p.is_dir())
    for directory in directories:
        paths.update(directory/name for name in _METRIC_NAMES)
        paths.add(directory/'wire')
        parent=directory
        while parent != attempt and parent.is_relative_to(attempt):
            paths.add(parent);parent=parent.parent
    return tuple(sorted(paths))


def _metadata_signature(paths):
    values = []
    for path in paths:
        try:
            stat = path.stat()
            values.append((str(path), stat.st_mtime_ns, stat.st_size, stat.st_ino))
        except FileNotFoundError:
            values.append((str(path), None))
        except OSError:
            return None  # AFS errors cannot authorize using stale accounting.
    return tuple(values)


def _cacheable_terminal(attempt):
    result = read_json(attempt / 'result.json')
    return (isinstance(result, dict) and result.get('status') in _TERMINAL_STATES
            and result.get('slot_released') is True
            and result.get('unconfirmed_child_termination') == [])


def inspect_attempt(attempt, harness):
    attempt = Path(attempt)
    key = (str(attempt.absolute()), harness)
    cached = _TERMINAL_CACHE.get(key)
    if cached is not None:
        paths, signature, value = cached
        if _metadata_signature(paths) == signature:
            return deepcopy(value)
        del _TERMINAL_CACHE[key]
    metric_dirs = _metric_directories(attempt, harness)
    eligible = _cacheable_terminal(attempt)
    paths = _cache_metadata_paths(attempt,harness,metric_dirs) if eligible else ()
    before = _metadata_signature(paths) if eligible else None
    value = _inspect_attempt_uncached(attempt, harness, metric_dirs)
    after = _metadata_signature(paths) if eligible else None
    if eligible and before is not None and before == after and _cacheable_terminal(attempt):
        _TERMINAL_CACHE[key] = (paths, after, deepcopy(value))
    return value


def _inspect_attempt_uncached(attempt, harness, metric_dirs=None):
    issues, all_rows, counts = [], [], Counter()
    by_purpose = defaultdict(list)
    sdk_known, sdk_missing = 0, 0
    web, compression, rendering = Counter(), 0, []
    if metric_dirs is None: metric_dirs = _metric_directories(attempt, harness)
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


def _retired_generation_proven(root, name, evidence):
    node = Path(evidence.get('node_directory') or '/missing')
    try: node.relative_to(root / 'runtime/nodes')
    except ValueError: return False
    marker = read_json(node / 'retired.json') or {}
    exited = read_json(Path(evidence.get('bootstrap_exit') or '/missing')) or {}
    drained = exited.get('controller_exit_code') == 0 and exited.get('stopped') is True
    clean = evidence.get('clean_drain', {})
    if exited.get('controller_exit_code') == 0 and clean.get('kind') == 'controller_stop_and_drain':
        status_path = Path(clean.get('status_path') or '/missing')
        try:
            status_path.relative_to(root/'controllers')
            status = read_json(status_path) or {}
            boot = read_json(Path(evidence.get('bootstrap_path') or '/missing')) or {}
            drained = (hashlib.sha256(status_path.read_bytes()).hexdigest() == clean.get('status_sha256')
                       and all(status.get(k) and status.get(k) == boot.get(k) == marker.get(k)
                               for k in ('hostname','boot_id','pid_namespace'))
                       and status.get('pid') == boot.get('controller_pid') and bool(status.get('start_identity'))
                       and status.get('stop_dispatch') is True and status.get('active_local') == 0)
        except (OSError,ValueError): drained = False
    return bool(evidence.get('acp_state') == 'SUCCEEDED' and marker.get('job_name') == name
                and marker.get('hostname') == evidence.get('hostname')
                and marker.get('boot_id') == evidence.get('retired_boot_id')
                and isinstance(marker.get('pid_namespace'), str) and marker['pid_namespace']
                and marker['pid_namespace'] == evidence.get('retired_pid_namespace')
                and drained)


def _rate_generations(root, rate_root, active, retired, planned, issues):
    by_name = {row['name']:row for row in active}
    candidates = []
    sources=[(rate_root,'ops3','ops2'),(rate_root.parent/'visual-rate-replacements','ops4','ops3'),
             (rate_root.parent/'final-rate-replacements','ops4','ops3')]
    directories=[(directory,generation,parent) for folder,generation,parent in sources if folder.is_dir()
                 for directory in sorted(folder.iterdir()) if directory.is_dir()]
    for directory,generation,parent in directories:
        request = read_json(directory/'request.json')
        response = read_json(directory/'response.json') or {'state':'unknown'}
        if not isinstance(request, dict):
            issues.append({'kind':'unknown_rate_replacement_request','path':str(directory)}); continue
        candidates.append((request.get('requested_at_unix',0),directory,request,response,generation,parent))
    replaced = set()
    for _,directory,request,response,generation,parent in sorted(candidates,key=lambda item:(int(item[4][3:]),item[0])):
        name, previous, original = request.get('name'), request.get('replaces'), request.get('original_name')
        if not (isinstance(original,str) and name == original+'-'+generation and previous == original+'-'+parent
                and directory.name == name and previous not in replaced):
            issues.append({'kind':'invalid_rate_generation_binding','path':str(directory)}); continue
        replaced.add(previous)
        evidence = request.get('evidence',{})
        if previous not in by_name or not _retired_generation_proven(root,previous,evidence):
            issues.append({'kind':'rate_parent_retirement_unproven','name':name})
        else:
            del by_name[previous]
            retired.append({'name':previous,'state':'succeeded_rate_rollover',
                            'retirement_path':str(Path(evidence['node_directory'])/'retired.json')})
        state = response.get('state')
        if state in ('rejected','not_sent_stopping','not_sent_source_changed'):
            planned.append({'name':original,'replacement':name,'reason':'rate_replacement_'+state}); continue
        argv = request.get('argv',[])
        try: nodes = int(argv[argv.index('--worker-nodes')+1])
        except (ValueError,IndexError,TypeError): nodes = None
        if nodes != 1:
            issues.append({'kind':'invalid_rate_replacement_node_count','name':name}); nodes = None
        if state not in ('submitted','unknown'):
            issues.append({'kind':'unknown_rate_replacement_state','name':name}); state = 'unknown'
        if state == 'unknown': issues.append({'kind':'rate_replacement_submission_outcome_unknown','name':name})
        by_name[name] = {'name':name,'replaces':previous,'original_name':original,'generation':generation,'state':state,
                        'expected_nodes':nodes,'active_workers_per_instance':request.get('active_workers_this_cell',request.get('operational_dispatch',{}).get('active_workers_per_cloud_instance')),
                        'worker_ceiling':request.get('worker_ceiling'),'receipt':str(directory)}
    return list(by_name.values())


def _replacement_generations(root, submissions_root, active, issues):
    """Read-only lifecycle overlay; never rewrite original submission receipts."""
    resume_root = submissions_root.parent / 'reader-resume'
    replacements_root = submissions_root.parent / 'replacement-submissions'
    retired, planned, holds = [], [], []
    by_name = {row['name']: row for row in active}
    proven = {}
    for name in list(by_name):
        request = read_json(resume_root / name / 'request.json') or {}
        response = read_json(resume_root / name / 'response.json') or {}
        evidence = request.get('evidence', {})
        text = str(response.get('stderr', '')) + str(response.get('stdout', ''))
        for _ in range(4): text = text.replace('\\"', '"')
        if not (response.get('state') == 'rejected' and response.get('returncode') not in (None, 0)
                and re.search(r'"reason"\s*:\s*"tjUpdateNotSupportStart"', text)
                and request.get('job', {}).get('name') == name and evidence.get('acp_state') == 'SUCCEEDED'):
            continue
        node = Path(evidence.get('node_directory') or '/missing')
        try: node.relative_to(root / 'runtime/nodes')
        except ValueError:
            issues.append({'kind':'invalid_retirement_path','name':name}); continue
        marker = read_json(node / 'retired.json') or {}
        exited = read_json(Path(evidence.get('bootstrap_exit') or '/missing')) or {}
        if not (marker.get('job_name') == name and marker.get('hostname') == evidence.get('hostname')
                and marker.get('boot_id') == evidence.get('retired_boot_id')
                and isinstance(marker.get('pid_namespace'), str) and marker['pid_namespace']
                and marker['pid_namespace'] == evidence.get('retired_pid_namespace')
                and exited.get('controller_exit_code') == 0 and exited.get('stopped') is True):
            issues.append({'kind':'unproven_original_generation_retirement','name':name}); continue
        proven[name] = request
        retired.append({'name':name,'state':'succeeded_start_unsupported', 'retirement_path':str(node/'retired.json')})
        del by_name[name]
    seen = set()
    for directory in sorted(replacements_root.iterdir()) if replacements_root.is_dir() else []:
        if not directory.is_dir(): continue
        request = read_json(directory / 'request.json')
        response = read_json(directory / 'response.json') or {'state':'unknown'}
        if not isinstance(request, dict):
            issues.append({'kind':'unknown_replacement_request','path':str(directory)}); continue
        name, original = request.get('name'), request.get('replaces')
        if not isinstance(original, str) or name != original + '-ops2' or directory.name != name or original in seen:
            issues.append({'kind':'invalid_or_duplicate_replacement_binding','path':str(directory)}); continue
        seen.add(original)
        if original not in proven:
            issues.append({'kind':'replacement_original_not_proven_terminal','name':name})
        state = response.get('state')
        if state in ('rejected', 'not_sent_stopping'):
            planned.append({'name':original,'replacement':name,'reason':'replacement_' + state}); continue
        argv = request.get('argv', [])
        try: nodes = int(argv[argv.index('--worker-nodes') + 1])
        except (ValueError, IndexError, TypeError): nodes = None
        if nodes != 1:
            issues.append({'kind':'invalid_replacement_node_count','name':name}); nodes = None
        if state not in ('submitted', 'unknown'):
            issues.append({'kind':'unknown_replacement_state','name':name}); state = 'unknown'
        if state == 'unknown': issues.append({'kind':'replacement_submission_outcome_unknown','name':name})
        by_name[name] = {'name':name,'replaces':original,'generation':'ops2','state':state,'expected_nodes':nodes,
                         'active_workers_per_instance':request.get('operational_dispatch', {}).get('active_workers_per_cloud_instance'),
                         'worker_ceiling':request.get('worker_ceiling'), 'receipt':str(directory)}
    for name, request in proven.items():
        if name in seen: continue
        strategy = request.get('job', {}).get('strategy')
        item = {'name':name,'reason':'visual_intentionally_held' if strategy == 'visual' else 'awaiting_replacement'}
        planned.append(item)
        if strategy == 'visual': holds.append(item)
    active = _rate_generations(root,submissions_root.parent/'rate-replacements',list(by_name.values()),retired,planned,issues)
    return active, retired, planned, holds


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
    active, retired_generations, planned_not_running, holds = _replacement_generations(root, submissions_root, active, issues)
    if any(item['expected_nodes'] is None for item in active): registry_complete = False
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
        retired = read_json(path.parent / 'retired.json')
        identity_fields = ('hostname', 'boot_id', 'pid_namespace')
        if (isinstance(retired, dict)
                and all(isinstance(item.get(field), str) and item[field]
                        and retired.get(field) == item[field] for field in identity_fields)):
            row.update(status='retired_namespace', retired_at=retired.get('retired_at'),
                       retirement_path=str(path.parent / 'retired.json'))
            nodes.append(row)
            continue
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
    unknown_nodes = sum(row['status'] not in ('fresh', 'local_duplicate', 'duplicate_superseded', 'retired_namespace') for row in nodes)
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
             'retired_generations': retired_generations, 'planned_not_running': planned_not_running, 'holds': holds,
             'coverage_complete': coverage, 'issues': issues,
             'matching_scope': 'Count coverage only: submission receipts do not identify host/boot. Queued/submitting nodes remain expected until a terminal receipt is recorded.'}
    total = {'complete': complete, 'fields': fields, 'local_identity': local_identity,
             'local_snapshot_age_seconds': round(local_age, 3), 'counted_remote_nodes': len(fresh),
             'expected_unreported_remote_nodes': missing, 'unusable_telemetry_nodes': unknown_nodes,
             'scope': 'Sum of observed local PID namespaces, not physical-host process totals or threads. Hostname+boot duplicates are excluded; stale/missing nodes are unknown, never zero.'}
    return cloud, total


def snapshot(root):
    scan_started = datetime.now(timezone.utc).isoformat()
    monitor_rebuttal.SCRIPT_GROUPS.update({
        'run_bc_campaign_v3_capacity_ops.py':'core_bc_v3',
        'run_bc_campaign_v3_capacity1.py': 'core_bc_v3', 'run_bc_trial_v3_capacity1.py': 'core_bc_v3',
        'run_dsh_eval_v3_capacity1.py': 'core_bc_v3',
        'run_bc_campaign_v3_io2.py': 'core_bc_v3', 'run_bc_trial_v3_io2.py': 'core_bc_v3',
        'run_bc_campaign_v3.py': 'core_bc_v3', 'run_bc_trial_v3.py': 'core_bc_v3',
        'run_bc_campaign_v3_io.py': 'core_bc_v3', 'run_bc_trial_v3_io.py': 'core_bc_v3',
        'run_bc_campaign_v3_io2.py': 'core_bc_v3', 'run_bc_trial_v3_io2.py': 'core_bc_v3',
        'hermes_bc_worker_v3.py': 'core_bc_v3', 'run_dsh_eval_v3.py': 'core_bc_v3',
        'monitor_bc_campaign_v3.py': 'resource_monitor'})
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
    controller_rows=[{'path': str(p), 'status': read_json(p)} for p in sorted((root / 'controllers').glob('*/status.json'))]
    processes = monitor_rebuttal.process_snapshot()
    process_observed_unix = time.time()
    live = {k: v for k, v in processes.items() if v['state'] != 'Z'}
    local_processes = {'visible_total': len(processes), 'visible_live': len(live),
                       'core_v3_subtree_live': sum(v['group'] == 'core_bc_v3' for v in live.values())}
    cloud_nodes, global_counts = node_process_totals(root, local_processes, local_observed_unix=process_observed_unix)
    scan_finished=datetime.now(timezone.utc).isoformat()
    return {'schema': 'bc-v3-monitor-v1', 'as_of': scan_finished, 'scan_started_at':scan_started,
            'scan_finished_at':scan_finished, 'root': str(root),
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
            'controllers':controller_rows,
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
