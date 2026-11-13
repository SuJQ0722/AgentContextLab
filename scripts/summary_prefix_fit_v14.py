#!/usr/bin/env python3
"""Offline-only audit and deterministic prefix fitter; never sends model requests.

Future integration must supply a metered, explicitly authorized measurement
callback. A measured full-summary overshoot is a bracket, not proof that any
shorter prefix meets the provider budget. No source text or padding is added.
"""
import argparse
import gzip
import hashlib
import json
import math
import re
from pathlib import Path

VERSION = 'summary-prefix-fit-v14-offline'


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def boundaries(text):
    """Unicode codepoint boundaries at whitespace/punctuation, plus CJK chars."""
    ends = {0, len(text)}
    for i, char in enumerate(text):
        if char.isspace() or char in '.!?;。！？；' or '\u3400' <= char <= '\u9fff':
            ends.add(i + 1)
    return sorted(ends)


def fit_prefix(summary, target, native_tokens, full_tokens, measure, max_measurements=10):
    """Return a measured prefix or an explicit failure; mutate no native parts.

    ``measure(prefix)`` must measure the identical full request template/native
    images and persist its own request/usage ledger before returning an integer.
    Search assumes approximately monotonic tokens only for candidate selection;
    acceptance always uses an actual measured count, never interpolation.
    """
    lower, upper = math.ceil(target * .98), min(16384, math.floor(target * 1.02))
    if not all(type(n) is int and n > 0 for n in (target, native_tokens, full_tokens)):
        raise ValueError('Known positive provider measurements required')
    base = {'version': VERSION, 'source_sha256': digest(summary), 'lower': lower,
            'upper': upper, 'target': target, 'measurements': [], 'new_generation': False}
    if native_tokens > upper:
        return dict(base, status='native_over_budget')
    if lower <= full_tokens <= upper:
        return dict(base, status='matched', summary=summary, provider_prompt_tokens=full_tokens)
    if full_tokens < lower:
        return dict(base, status='undershoot_requires_separate_generation')
    cuts = boundaries(summary)
    lo, hi = 1, len(cuts) - 2  # known empty/full measurements are reused
    for _ in range(max_measurements):
        if lo > hi:
            break
        mid = (lo + hi) // 2
        candidate = summary[:cuts[mid]]
        count = measure(candidate)
        if type(count) is not int or count <= 0:
            return dict(base, status='unknown_usage_stop')
        base['measurements'].append({'characters': cuts[mid], 'sha256': digest(candidate),
                                     'provider_prompt_tokens': count})
        if lower <= count <= upper:
            return dict(base, status='matched', summary=candidate, provider_prompt_tokens=count)
        if count < lower:
            lo = mid + 1
        else:
            hi = mid - 1
    return dict(base, status='no_measured_match')


def audit_attempt(attempt):
    """Read actual generation + calibration responses; never copy private text out."""
    attempt = Path(attempt)
    control = json.loads((attempt / 'compression-control.json').read_text())
    calls = [json.loads(line) for line in (attempt / 'metrics/calls.jsonl').read_text().splitlines()]
    purposes = {c['call_id']: c.get('purpose') for c in calls}
    requests, responses = {}, {}
    with gzip.open(attempt / 'metrics/requests-responses.jsonl.gz', 'rt') as stream:
        for line in stream:
            row = json.loads(line)
            if row.get('type') == 'request':
                requests[row['call_id']] = row
            elif row.get('type') == 'response':
                responses[row['call_id']] = row['response']
    candidates = {}
    for call_id, response in responses.items():
        if purposes.get(call_id) != 'compaction':
            continue
        choice = (response.get('choices') or [{}])[0]
        message = choice.get('message') or {}
        if choice.get('finish_reason') != 'stop' or message.get('tool_calls'):
            continue
        try:
            parsed = json.loads(message.get('content') or '')
        except (TypeError, ValueError):
            continue
        if not isinstance(parsed, dict) or set(parsed) != {'summary'} or not isinstance(parsed['summary'], str):
            continue
        summary = parsed['summary'].strip()
        if not summary or 'data:image/' in summary or re.search(r'<(?:\|)?(?:DSML|tool_call|function)|<\|(?:tool|function)', summary, re.I):
            continue
        candidates[summary] = {'generation_call_id': call_id, 'summary_sha256': digest(summary),
                               'characters': len(summary), 'safe_prefix_boundaries': len(boundaries(summary))}
    measured = []
    for call_id, request in requests.items():
        if purposes.get(call_id) != 'budget_calibration':
            continue
        count = (responses.get(call_id, {}).get('usage') or {}).get('prompt_tokens')
        if type(count) is not int or count <= 0:
            continue
        for message in request.get('messages', []):
            content = message.get('content')
            if not isinstance(content, list):
                continue
            for part in content:
                summary = part.get('text') if isinstance(part, dict) else None
                if summary in candidates:
                    measured.append(dict(candidates[summary], calibration_call_id=call_id, provider_prompt_tokens=count))
    target = control['shared_target_tokens']
    lower, upper = math.ceil(target*.98), min(16384, math.floor(target*1.02))
    overshoot = [m for m in measured if m['provider_prompt_tokens'] > upper]
    matched = [m for m in measured if lower <= m['provider_prompt_tokens'] <= upper]
    return {'version': VERSION, 'attempt': str(attempt.resolve()), 'target': target,
            'native_only_prompt_tokens': control.get('native_only_prompt_tokens'),
            'prefix_sha256': control['prefix_sha256'], 'native_hashes': control['native_hashes'],
            'lower': lower, 'upper': upper, 'candidates': measured,
            'classification': 'existing_match' if matched else 'overshoot_bracket_only' if overshoot else 'undershoot_or_no_valid_candidate',
            'matched_shorter_prefix_verified': False, 'new_api_calls': 0,
            'cost_policy': 'All original generation/calibration charges retained; future probes require their own ledger.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--attempt', action='append', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    report = {'version': VERSION, 'paid_calls': 0, 'attempts': [audit_attempt(p) for p in args.attempt]}
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
