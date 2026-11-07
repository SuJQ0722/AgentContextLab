#!/usr/bin/env python3
"""Audit historical exported usage without treating missing measurements as zero."""
import argparse
import collections
import csv
import hashlib
import json
import os
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=None)
def summary_by_session(group):
    path = Path(group) / 'summary.jsonl'
    result = {}
    if path.exists():
        for line in path.read_text().splitlines():
            try:
                row = json.loads(line)
                if row.get('session_id'):
                    result[row['session_id']] = row
            except (ValueError, AttributeError):
                continue
    return result


def enrich(row):
    summary = summary_by_session(row['group']).get(row.get('session_id'), {})
    row['end_to_end_source'] = row.get('end_to_end_source') or ('conv:wall_seconds' if row.get('end_to_end_seconds') not in (None, '') else None)
    if row.get('session_span_seconds') in (None, '') and summary.get('duration_seconds') is not None:
        row['session_span_seconds'] = summary['duration_seconds']
        row['session_span_source'] = 'summary.jsonl:session_id'
    return row


def records(root):
    # Do not traverse per-task workspaces, screenshots, or environment trees.
    for directory, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in {
            'workspace', 'history', 'compress_trace', 'context_images',
            'node_modules', '.cache', '.git', 'venv', '.venv', 'judge',
        })
        if 'conv' not in Path(directory).relative_to(root).parts:
            continue
        for name in sorted(files):
            if name.endswith('.json'):
                yield Path(directory) / name


def extract(path, data):
    usage = data.get('token_usage') or {}
    # Hermes canonical input_tokens excludes cache reads/writes; do not apply
    # the OpenAI raw prompt_tokens interpretation to this exported format.
    uncached = usage.get('input_tokens')
    cached = usage.get('cache_read_tokens')
    writes = usage.get('cache_write_tokens')
    output = usage.get('output_tokens')
    total_input = sum((uncached, cached, writes)) if all(
        isinstance(v, (int, float)) for v in (uncached, cached, writes)) else None
    total = total_input + output if total_input is not None and output is not None else None
    parts = path.parts
    conv_index = parts.index('conv')
    judge_path = Path(*parts[:conv_index], 'judge', *parts[conv_index + 1:])
    score = None
    if judge_path.exists():
        judge = json.loads(judge_path.read_text())
        score = judge.get('score')
    error = str(data.get('error', '')).lower()
    failure = 'none' if data.get('status') == 'success' else 'unclassified'
    if any(s in error for s in ('context_length', 'context window', 'maximum context')):
        failure = 'context_limit'
    elif data.get('round_limit_reached'):
        failure = 'round_limit'
    elif error:
        failure = 'recorded_error'
    return enrich({
        'path': str(path), 'group': str(Path(*parts[:conv_index])),
        'session_id': data.get('session_id'), 'question_id': data.get('question_id'),
        'repeat': data.get('repeat_index'), 'model': data.get('model'),
        'status': data.get('status'), 'score': score, 'failure_category': failure,
        'rounds': data.get('rounds'), 'recorded_compression_count': data.get('compression_count'),
        'compression_count_quality': 'unverified_export',
        'cached_input': cached, 'uncached_input': uncached, 'cache_write_input': writes,
        'output': output, 'total_input': total_input, 'total_tokens': total,
        'cache_hit_rate': cached / total_input if total_input and cached is not None else None,
        'usage_quality': 'recorded_harness_aggregate_not_invoice',
        'end_to_end_seconds': data.get('wall_seconds'),
        'session_span_seconds': data.get('duration_seconds'), 'session_span_source': None,
        'api_seconds': None, 'render_seconds': None,
        'tokenhub_billed_usd': None, 'gemini_hypothetical_usd': None,
    })


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--refresh-summary', action='store_true', help='Join summaries onto the existing CSV without rereading large trajectories')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if args.refresh_summary:
        csv_path = args.output / 'records.csv'
        with csv_path.open() as stream:
            rows = [enrich(row) for row in csv.DictReader(stream)]
        available = collections.Counter()
        sums = collections.Counter()
        for row in rows:
            value = row.get('session_span_seconds')
            if value not in (None, ''):
                available[row['group']] += 1
                sums[row['group']] += float(value)
        with csv_path.open('w') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        report_path = args.output / 'audit.json'
        report = json.loads(report_path.read_text())
        for group, values in report['groups'].items():
            values['session_span_seconds_available'] = available[group]
            values['session_span_seconds_sum'] = sums[group]
        report['summary_join'] = 'Exact session_id within each run group; no question-only joins'
        report_path.write_text(json.dumps(report, indent=2))
        print(json.dumps({'session_span_seconds_recovered': sum(available.values())}))
        return
    seen = set()
    groups = collections.defaultdict(collections.Counter)
    counts = collections.Counter()
    writer = None
    with (args.output / 'records.csv').open('w') as stream:
        for path in records(args.root):
            counts['files'] += 1
            try:
                raw = path.read_bytes()
                data = json.loads(raw)
                # Exact copies are duplicates. Session IDs alone are insufficient:
                # re-exports can contain corrected or extended measurements.
                digest = hashlib.sha256(raw).hexdigest()
                if digest in seen:
                    counts['identical_copies'] += 1
                    continue
                seen.add(digest)
                row = extract(path, data)
            except (ValueError, TypeError, OSError, AttributeError):
                counts['unreadable_or_invalid'] += 1
                continue
            if writer is None:
                writer = csv.DictWriter(stream, fieldnames=list(row))
                writer.writeheader()
            writer.writerow(row)
            counts['distinct_exports'] += 1
            group = groups[row['group']]
            group['records'] += 1
            group['success'] += row['status'] == 'success'
            for key in ('cached_input', 'uncached_input', 'output', 'total_tokens', 'score', 'end_to_end_seconds', 'api_seconds', 'render_seconds'):
                if row[key] is not None:
                    group[key + '_available'] += 1
                    group[key + '_sum'] += row[key]
            group['failure_' + row['failure_category']] += 1
            if counts['files'] % 1000 == 0:
                print(json.dumps(dict(counts)), flush=True)
    report = {'counts': counts, 'groups': groups, 'limitations': [
        'Distinct exports are not necessarily independent trials; select a canonical cohort before statistical analysis.',
        'Usage is a harness aggregate; original provider responses and invoices are not recovered by this audit.',
        'Compression counters in old exports may be lower bounds; do not infer no compression from zero.',
        'Missing API and render timing remains null. CLI duration is not API latency.',
        'Cost remains null until dated route-specific prices or invoices are supplied.',
    ]}
    (args.output / 'audit.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(counts), flush=True)


if __name__ == '__main__':
    main()
