"""Zero-model, SHA-bound metrics for the selected successful native execution.

The retained answer determines the native attempt, never its grade. Prior failed
executions remain in the campaign cost ledger and are not mixed into these paired
successful-execution metrics. Missing telemetry is not inferred as zero.
"""
from collections import defaultdict
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import sys

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
from monitor_bc_campaign_v3 import aggregate, analyze_usage, accounting
from visual_inline_route_accounting_v5 import collect_transport

VERSION = 'once24h-selected-native-metrics-v1'
FIELDS = ('prompt', 'cached_input', 'noncache_input', 'output', 'total')
ARCHIVE = Path('/mnt/data/acl-results-20261112/selected_lineage_cost.json')
LEDGERS = ('transport-phases-v3.jsonl', 'inline-images-wire-dsh-v1.jsonl')
TERMINAL_EVENTS = {'stream_complete', 'route_failed', 'route_transport_error', 'route_http_error', 'send_error', 'stream_error', 'stream_abandoned', 'global_authentication_rejected'}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) and x >= 0


def default_metrics():
    return {'version': VERSION, 'scope': 'selected_successful_native_execution',
            'complete_tokens': {k: None for k in FIELDS}, 'known_token_subtotals': {k: None for k in FIELDS},
            'tokens_complete': False, 'usage_observations': None, 'unknown_usage_requests': None,
            'cache_token_hit_rate': None, 'cache_request_hit_rate': None,
            'cache_request_hits': None, 'cache_request_known_count': None, 'cache_request_missing_count': None,
            'compression_count': None, 'compression_count_known_subtotal': None,
            'client_http_seconds': None, 'client_http_seconds_known_subtotal': None,
            'client_http_observations': None, 'client_http_missing_count': None,
            'client_sdk_seconds': None, 'render_seconds': None, 'render_seconds_known_subtotal': None,
            'end_to_end_seconds': None, 'provider_internal_seconds': None,
            'source_records': [], 'issues': []}


def cached_metrics(record):
    """Only a one-native archived row can represent one successful execution."""
    out = default_metrics(); acc = record['accounting']; fields = acc['usage']['fields']
    if acc.get('native_attempts') != 1:
        raise ValueError('Archived row pools multiple native executions')
    complete = not acc.get('missing_instrumentation_attempts') and not acc['usage'].get('conservation_issues')
    out['complete_tokens'] = {k: fields.get(k, {}).get('complete_total') if complete else None for k in FIELDS}
    out['known_token_subtotals'] = {k: fields.get(k, {}).get('known_subtotal') for k in FIELDS}
    out['tokens_complete'] = all(out['complete_tokens'][k] is not None for k in FIELDS)
    out['usage_observations'] = acc.get('http_or_fallback_observations')
    out['unknown_usage_requests'] = acc.get('unknown_usage_requests')
    p, c = out['complete_tokens']['prompt'], out['complete_tokens']['cached_input']
    out['cache_token_hit_rate'] = c / p if number(p) and p > 0 and number(c) else None
    out['compression_count'] = record.get('compression_count_complete')
    out['compression_count_known_subtotal'] = acc.get('compression_count_known_subtotal')
    out['render_seconds'] = record.get('render_seconds_complete')
    out['render_seconds_known_subtotal'] = acc.get('render_seconds_known_subtotal') if not acc.get('attempts_without_render_metrics') else None
    out['end_to_end_seconds'] = record.get('e2e_seconds_complete')
    n = acc.get('http_latency_observations', 0); expected = out['usage_observations']
    out['client_http_observations'] = n
    out['client_http_seconds_known_subtotal'] = acc.get('http_client_seconds_known_subtotal') if n else None
    out['client_http_seconds'] = out['client_http_seconds_known_subtotal'] if expected and n == expected else None
    out['client_http_missing_count'] = max(0, expected-n) if isinstance(expected, int) else None
    out['issues'].append({'kind': 'archived_request_cache_hit_count_unavailable'})
    return out


class MetricsIndex:
    def __init__(self, root, slots, archive_path=ARCHIVE, cache_path=None):
        self.root = Path(root); self.slots = slots; self.cache = {}; self.archive = {}; self.archive_source = None
        self.cache_path = Path(cache_path) if cache_path else self.root/'outputs/reports/once24h-v15/selected-metrics-cache.json'
        try:
            raw = self.cache_path.read_bytes(); cached = json.loads(raw)
            if cached.get('version') == VERSION:
                self.cache = cached.get('records', {})
        except (OSError, ValueError):
            pass
        try:
            raw = Path(archive_path).read_bytes(); value = json.loads(raw)
            self.archive_source = {'path': str(archive_path), 'sha256': sha(raw)}
            for row in value.get('rows', []):
                if row.get('result_sha256') and row.get('accounting', {}).get('native_attempts') == 1:
                    self.archive[row['result_sha256']] = row
        except (OSError, ValueError):
            pass

    def checkpoint(self):
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.cache_path.with_suffix('.tmp')
        temp.write_text(json.dumps({'version': VERSION, 'records': self.cache}, ensure_ascii=False))
        temp.replace(self.cache_path)

    def _read(self, path, out, lines=False):
        path = Path(path)
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            return [] if lines else None
        out['source_records'].append({'path': str(path), 'sha256': sha(raw)})
        if not lines:
            return json.loads(raw)
        rows = []
        for i, line in enumerate(raw.splitlines(), 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError('not object')
                rows.append(row)
            except ValueError:
                out['issues'].append({'kind': 'invalid_jsonl', 'path': str(path), 'line': i})
        return rows

    def _selected_native(self, path, result, out):
        outer = path.parent
        native = Path(result.get('native_artifact_root') or str(outer/'native'))
        native.resolve().relative_to(outer.resolve())
        physical = native.parent
        if physical.resolve() == outer.resolve():
            return physical, native, result
        child_path = physical/'result.json'; child = self._read(child_path, out)
        if not child or child.get('status') != 'completed':
            raise ValueError('Selected native child is not completed')
        for key in ('job_id', 'harness', 'strategy', 'question_id', 'repeat', 'model'):
            if child.get(key) != result.get(key):
                raise ValueError('Selected child identity mismatch')
        references = [r for r in result.get('attempts', []) if Path(r.get('result_path', '/missing')).resolve() == child_path.resolve()]
        if references and not any(r.get('result_sha256') == out['source_records'][-1]['sha256'] for r in references):
            raise ValueError('Selected child result SHA mismatch')
        return physical, native, child

    def observe(self, observation):
        result_sha = observation.get('selected_result_sha256'); path = observation.get('selected_result_path')
        if not result_sha or not path:
            return default_metrics()
        if result_sha in self.cache:
            return deepcopy(self.cache[result_sha])
        out = default_metrics()
        try:
            path = Path(path); result = self._read(path, out)
            if not result or out['source_records'][0]['sha256'] != result_sha or result.get('status') != 'completed':
                raise ValueError('Selected completed result SHA mismatch')
            archive = self.archive.get(result_sha)
            if archive and archive.get('harness') == observation['harness']:
                sources = out['source_records']; out = cached_metrics(archive)
                out['source_records'] = sources + [self.archive_source]
                out['source_kind'] = 'sha_bound_single_native_archive'
            else:
                physical, native, child = self._selected_native(path, result, out)
                out['physical_attempt_path'] = str(physical)
                out['source_kind'] = 'selected_native_raw_metrics'
                self._scan(physical, native, child, observation, out)
            if observation.get('method') == 'none':
                out['compression_count'] = 0
                out['compression_count_known_subtotal'] = 0
                out['issues'].append({'kind': 'compression_disabled_by_method'})
            out['selected_result_path'] = str(path); out['selected_result_sha256'] = result_sha
            self.cache[result_sha] = deepcopy(out)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            out['issues'].append({'kind': 'metrics_quarantined', 'error_type': type(exc).__name__})
        return out

    def _scan(self, physical, native, child, observation, out):
        harness = observation['harness']
        directories = [native/'metrics'] if harness == 'hermes' else list(native.glob('*/*/workspace/metrics'))
        directories = [p for p in directories if p.is_dir()]
        events = []; sdk = []; sdk_times = []; render_values = []; compression_values = []; comp_present = False
        for directory in directories:
            for name in LEDGERS:
                for p in (directory/name, directory/'wire'/name):
                    events.extend((str(p), row) for row in self._read(p, out, lines=True))
            # Capture exact sources used by the established fallback accounting.
            for name in ('calls.jsonl', 'call-starts.jsonl', 'wire/raw-usage.jsonl', 'wire/requests.jsonl'):
                self._read(directory/name, out, lines=True)
            rows, _, _, timing = accounting(directory, harness, out['issues']); sdk.extend(rows)
            if timing['sdk_client_seconds_missing_count'] == 0 and rows:
                sdk_times.append(timing['sdk_client_seconds_known_subtotal'])
            else:
                sdk_times.append(None)
            cf = directory/('shared-policy.jsonl' if harness == 'dsh' else 'compression.jsonl')
            if cf.exists():
                comp_present = True
                for row in self._read(cf, out, lines=True):
                    compression_values.append(row.get('compression_count_delta' if harness == 'dsh' else 'count_delta'))
                    if harness == 'dsh':
                        render_values.append(row.get('render_seconds'))
            if harness == 'hermes':
                render_values.extend(row.get('render_seconds') for row in self._read(directory/'render.jsonl', out, lines=True))
        transport, _ = collect_transport(physical, events, out['issues'])
        usage = transport if transport else sdk
        out['usage_source'] = 'http_transport' if transport else 'sdk_raw_fallback' if sdk else 'missing'
        out['sdk_usage_observations_suppressed'] = len(sdk) if transport else 0
        agg = aggregate(usage); fields = agg['fields']
        sound = not agg['conservation_issues'] and not any(r.get('kind') == 'invalid_jsonl' for r in out['issues'])
        out['complete_tokens'] = {k: fields[k]['complete_total'] if sound else None for k in FIELDS}
        out['known_token_subtotals'] = {k: fields[k]['known_subtotal'] if usage else None for k in FIELDS}
        out['tokens_complete'] = bool(usage) and all(out['complete_tokens'][k] is not None for k in FIELDS)
        out['usage_observations'] = len(usage) if usage else None
        out['unknown_usage_requests'] = sum(not isinstance(row.get('raw_provider_usage'), dict) or not row.get('raw_provider_usage') or row.get('_incomplete', False) for row in usage) if usage else None
        cache_values = []
        for row in usage:
            values, errors = analyze_usage(row.get('raw_provider_usage'))
            cache_values.append(values['cached_input'] if not errors and not row.get('_incomplete') else None)
        known = [v for v in cache_values if v is not None]
        out['cache_request_known_count'] = len(known) if usage else None
        out['cache_request_missing_count'] = len(cache_values)-len(known) if usage else None
        out['cache_request_hits'] = sum(v > 0 for v in known) if known else None
        out['cache_request_hit_rate'] = sum(v > 0 for v in known)/len(known) if known and len(known) == len(cache_values) else None
        p, c = out['complete_tokens']['prompt'], out['complete_tokens']['cached_input']
        out['cache_token_hit_rate'] = c/p if number(p) and p > 0 and number(c) else None
        durations = {}
        for _, row in events:
            identity = row.get('request_id') or row.get('attempt_id')
            seconds = row.get('request_wall_seconds', row.get('elapsed_seconds', row.get('client_seconds')))
            if identity and row.get('event') in TERMINAL_EVENTS and number(seconds):
                durations[identity] = max(durations.get(identity, 0), seconds)
        out['client_http_observations'] = len(durations)
        out['client_http_seconds_known_subtotal'] = sum(durations.values()) if durations else None
        out['client_http_missing_count'] = max(0, len(transport)-len(durations)) if transport else None
        out['client_http_seconds'] = sum(durations.values()) if transport and len(durations) == len(transport) else None
        out['client_sdk_seconds'] = sum(sdk_times) if sdk_times and all(number(v) for v in sdk_times) else None
        out['compression_count_known_subtotal'] = sum(v for v in compression_values if number(v)) if comp_present else None
        out['compression_count'] = sum(compression_values) if comp_present and all(number(v) for v in compression_values) else None
        out['render_seconds_known_subtotal'] = sum(v for v in render_values if number(v)) if any(number(v) for v in render_values) else None
        out['render_seconds'] = sum(render_values) if render_values and all(number(v) for v in render_values) else None
        out['end_to_end_seconds'] = child.get('end_to_end_seconds') if number(child.get('end_to_end_seconds')) else None
        out['issues'].extend({'kind': 'usage_conservation', 'field': k, 'count': v} for k, v in agg['conservation_issues'].items())


_FAILURE_CACHE = {}
TRUNCATION_ERROR = 'Response remained truncated after 4 continuation attempts'


def classify_failure(result_path, result_sha256):
    """Derive one precise model-budget failure without changing frozen results.

    A broad string such as "truncated" is insufficient: require the exact native
    continuation-limit error, false completed/true partial flags, and the final
    successful SDK response explicitly ending by length at the fixed 8192 limit.
    """
    if result_sha256 in _FAILURE_CACHE:
        return deepcopy(_FAILURE_CACHE[result_sha256])
    path = Path(result_path)
    out = {'derived_failure_category': None, 'original_failure_category': None,
           'result_path': str(path), 'result_sha256': result_sha256, 'proof': [], 'evidence': {}, 'issues': []}
    def read_bound(p, lines=False):
        raw = p.read_bytes(); out['proof'].append({'path': str(p), 'sha256': sha(raw)})
        return [json.loads(line) for line in raw.splitlines() if line.strip()] if lines else json.loads(raw)
    try:
        result = read_bound(path)
        if out['proof'][0]['sha256'] != result_sha256:
            raise ValueError('Result SHA mismatch')
        out['original_failure_category'] = result.get('failure_category')
        if (result.get('harness') != 'hermes' or result.get('status') != 'failed'
                or result.get('failure_category') != 'execution_error'):
            return out
        native = Path(result['native_artifact_root']); native.resolve().relative_to(path.parent.resolve())
        conversation = read_bound(native/'conversation.json')
        if not (conversation.get('completed') is False and conversation.get('partial') is True
                and conversation.get('error') == TRUNCATION_ERROR):
            return out
        calls = [r for r in read_bound(native/'metrics/calls.jsonl', lines=True) if r.get('purpose') == 'agent']
        length_calls = [r for r in calls if r.get('finish', {}).get('kind') == 'length'
                        and r.get('error_type') is None]
        # Native continuation counting can include additional calls or increase
        # max_tokens. Record those observations; do not invent four 8192 calls.
        if not calls or calls[-1] not in length_calls or (calls[-1].get('raw_provider_usage') or {}).get('completion_tokens') != 8192:
            return out
        out['derived_failure_category'] = 'output_limit'
        out['evidence'] = {'exact_error': TRUNCATION_ERROR, 'completed': False, 'partial': True,
                           'last_finish_kind': 'length', 'last_output_tokens': 8192,
                           'length_calls_observed': len(length_calls),
                           'length_output_tokens_observed': [(r.get('raw_provider_usage') or {}).get('completion_tokens') for r in length_calls],
                           'configured_initial_output_tokens_is_not_all_continuation_call_limit': True,
                           'last_call_id': calls[-1].get('call_id'), 'original_result_preserved': True}
        _FAILURE_CACHE[result_sha256] = deepcopy(out)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        out['issues'].append({'kind': 'failure_derivation_unavailable', 'error_type': type(exc).__name__})
    return out
