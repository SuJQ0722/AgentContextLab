"""Freeze the literal MMBC VERA non-timeout cohort and first-intervention evidence.

Read-only source inspection. No model requests, rendering, downloading, or answer
lookup. Missing proof remains an explicit cohort member with execution=blocked.
"""
import argparse
import base64
import collections
import concurrent.futures
import copy
import datetime
import gzip
import hashlib
import json
from pathlib import Path
import threading

from lab import ROOT

VERSION = 'controlled-mmbc-vera-nontimeout-cohort-v17'
DEFAULT = ROOT / 'outputs/controlled-mmbc-vera-nontimeout-v17'
REPORT = ROOT / 'outputs/reports/once24h-v15/latest.json'
_PLAN_CACHE = {}
_PLAN_LOCK = threading.Lock()


def digest(raw): return hashlib.sha256(raw).hexdigest()
def sha(path): return digest(Path(path).read_bytes())
def read(path): return json.loads(Path(path).read_text())
def lines(path):
    if not Path(path).exists(): return []
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]

def save(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    blob = (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode()
    if path.exists():
        if path.read_bytes() != blob: raise ValueError('Frozen derived artifact differs: ' + str(path))
    else:
        with path.open('xb') as stream: stream.write(blob)
    return sha(path)


def seconds(value): return datetime.datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()


def select_cohort(report):
    rows = [r for r in report['observations'] if (r['benchmark'], r['harness'], r['method']) == ('mmbc100', 'hermes', 'visual')]
    keys = [(r['question_id'], r['repeat']) for r in rows]
    if len(rows) != 300 or len(set(keys)) != 300: raise ValueError('Expected 300 unique MMBC VERA slots')
    return sorted([copy.deepcopy(r) for r in rows if r['status'] != 'timeout_unresolved'], key=lambda r: (r['question_id'], r['repeat']))


def source_job(path, identity):
    root = Path(str(path).split('/jobs/', 1)[0]); plan_path = root / 'plan.json'
    with _PLAN_LOCK:
        if str(plan_path) not in _PLAN_CACHE:
            raw = plan_path.read_bytes(); plan = json.loads(raw)
            _PLAN_CACHE[str(plan_path)] = ({j['job_id']: j for j in plan['jobs']}, digest(raw))
        jobs, plan_sha = _PLAN_CACHE[str(plan_path)]
    job = jobs[identity]
    return job, {'path': str(plan_path), 'sha256': plan_sha}


def core_job_valid(job, row):
    return (job.get('experiment_kind') in (None, 'mmbc', 'mmbc100')
        and job.get('benchmark') in (None, 'mmbc100')
        and not job.get('controlled_spec_path') and not job.get('calibration_not_scored')
        and job.get('harness') == 'hermes' and job.get('strategy') == 'visual'
        and job.get('question_id') == row['question_id'] and job.get('repeat') == row['repeat']
        and job.get('job_id', '').endswith(f"hermes/visual/{row['question_id']}_r{row['repeat']:02d}")
        and digest(job['question'].encode()) == row['question_sha256'])


def core_corrected_report(root, report):
    """Reject controlled continuations mistakenly aliased into a core slot."""
    corrected = root / 'source-report-core-corrected.json'
    if corrected.exists(): return read(corrected), corrected
    observations = copy.deepcopy(report['observations']); problems = []; checked = 0
    for row in observations:
        if (row['benchmark'], row['harness'], row['method']) != ('mmbc100', 'hermes', 'visual'): continue
        for key in ['selected_result_path', 'latest_terminal_result_path']:
            if not row.get(key): continue
            value = read(row[key]); job, plan = source_job(row[key], value['job_id']); checked += 1
            if not core_job_valid(job, row):
                problems.append({'slot_id': row['slot_id'], 'field': key, 'path': row[key], 'sha256': sha(row[key]),
                    'source_experiment_kind': job.get('experiment_kind'), 'source_controlled_spec_path': job.get('controlled_spec_path'),
                    'source_job_id': job['job_id'], 'source_plan': plan})
    fullpath = Path('/mnt/data/acl-once24h-20261113/full-slot-manifest.json')
    full = {r['slot_id']: r for r in read(fullpath)['slots']}; corrections = []
    for sid in sorted({p['slot_id'] for p in problems}):
        row = next(r for r in observations if r['slot_id'] == sid); candidates = []
        for candidate in full[sid]['result_evidence']:
            path = Path(candidate['path'])
            if sha(path) != candidate['sha256']: raise ValueError('Historical candidate changed')
            result = read(path); job, plan = source_job(path, result['job_id'])
            if core_job_valid(job, row): candidates.append(candidate)
        if not candidates: raise ValueError('Invalid core source has no auditable core candidate')
        completed = sorted([c for c in candidates if c['status'] == 'completed'], key=lambda c: c['finish_unix'])
        # These detected collisions had no successful core trajectory. A new
        # successful candidate must be scored through the main grader, not guessed.
        if completed: raise ValueError('Unexpected completed core candidate requires graded binding')
        latest = max(candidates, key=lambda c: c['finish_unix']); value = read(latest['path'])
        old = {k: row.get(k) for k in ['status', 'score', 'selected_result_path', 'selected_result_sha256', 'latest_terminal_result_path']}
        row.update(status='timeout_unresolved' if latest['status'] == 'timeout' else 'system_or_unclassified_failed',
            score=None, task_valid_score=None, selected_result_path=None, selected_result_sha256=None,
            grade_path=None, grade_sha256=None, latest_terminal_result_path=latest['path'],
            latest_terminal_result_sha256=latest['sha256'], latest_terminal_status=latest['status'],
            latest_failure_category=value.get('failure_category'), failure_classification_proof=None)
        corrections.append({'slot_id': sid, 'before': old, 'after': copy.deepcopy(row), 'valid_core_candidates': candidates})
    document = {'version': VERSION + '-core-source-correction', 'at': report['at'],
        'source_report_path': str(root / 'source-report.json'), 'source_report_sha256': sha(root / 'source-report.json'),
        'scope': 'Cohort-only source correction; original report and measured results are unchanged.',
        'checked_core_slot_sources': checked, 'invalid_source_bindings': problems,
        'full_slot_audit_path': str(fullpath), 'full_slot_audit_sha256': sha(fullpath),
        'corrections': corrections, 'observations': observations}
    save(corrected, document)
    return document, corrected


def bind_wire_images(archived, retained):
    # Segment budgeting may remove pages before the inline ledger reindexes
    # part positions. Exact ordered payload identities, not stale offsets, bind it.
    position = 0; mapping = []
    for image in retained:
        while position < len(archived):
            candidate = archived[position]; position += 1
            if candidate['sha256'] == image['sha256'] and (candidate.get('detail') or 'auto') == (image.get('detail') or 'auto'):
                mapping.append({'wire_message_index': image.get('message_index'), 'wire_part_index': image.get('original_part_index'),
                    'archive_message_index': candidate['message_index'], 'archive_part_index': candidate['part_index'],
                    'sha256': candidate['sha256']}); break
        else: raise ValueError('post_wire_image_SHA_not_from_archived_ordered_subsequence')
    return mapping


def image_ledger(messages):
    result = []
    for mi, message in enumerate(messages):
        content = message.get('content')
        for pi, part in enumerate(content if isinstance(content, list) else []):
            if not isinstance(part, dict) or part.get('type') != 'image_url': continue
            obj = part['image_url']; url = obj.get('url', '') if isinstance(obj, dict) else obj
            if not isinstance(url, str) or not url.startswith('data:image/'): raise ValueError('unfrozen_native_image')
            header, encoded = url.split(',', 1); raw = base64.b64decode(encoded, validate=True)
            result.append({'message_index': mi, 'part_index': pi, 'sha256': digest(raw), 'bytes': len(raw),
                'media_type': header[5:].split(';')[0], 'detail': obj.get('detail') if isinstance(obj, dict) else None,
                'part_sha256': digest(json.dumps(part, sort_keys=True, ensure_ascii=False).encode())})
    return result


def archived_pair(path, post_id):
    previous = None; generated_ids = set(); requests = 0
    with gzip.open(path, 'rt') as stream:
        for line in stream:
            row = json.loads(line)
            if row.get('type') == 'request':
                requests += 1
                if row['call_id'] == post_id:
                    if previous is None: raise ValueError('first_post_call_has_no_previous_request')
                    return previous, row, generated_ids, requests
                previous = row; generated_ids = set()
            elif previous is not None and row.get('call_id') == previous['call_id']:
                value = row.get('chunk') if row.get('type') == 'stream_chunk' else row.get('response')
                for choice in (value or {}).get('choices', []):
                    message = choice.get('delta') or choice.get('message') or {}
                    generated_ids.update(t['id'] for t in (message.get('tool_calls') or []) if t.get('id'))
    raise ValueError('post_request_missing_from_archive')


def reconstruct_prefix(previous, post, generated_ids):
    """Append only the actual prior response/tool results, never a final answer."""
    prior_ids = {t['id'] for m in previous['messages'] for t in (m.get('tool_calls') or []) if t.get('id')}
    for index, message in enumerate(post['messages']):
        calls = {t['id'] for t in (message.get('tool_calls') or []) if t.get('id')}
        if not calls or not calls.isdisjoint(prior_ids): continue
        if calls != generated_ids: raise ValueError('fresh_tool_round_not_bound_to_previous_response')
        tail = post['messages'][index:]
        if tail[0]['role'] != 'assistant' or not any(m.get('role') == 'tool' for m in tail): raise ValueError('fresh_round_incomplete')
        if any(m.get('role') == 'assistant' for m in tail[1:]): raise ValueError('more_than_one_fresh_round')
        if {m['tool_call_id'] for m in tail if m.get('role') == 'tool'} != calls: raise ValueError('fresh_tool_results_incomplete')
        return {k: copy.deepcopy(v) for k, v in previous.items() if k in ['model', 'max_tokens']} | {'messages': copy.deepcopy(previous['messages'] + tail)}, {
            'previous_call_id': previous['call_id'], 'post_call_id': post['call_id'],
            'new_tool_call_ids': sorted(calls), 'post_tail_start': index,
            'previous_message_count': len(previous['messages']), 'appended_message_count': len(tail),
            'construction': 'Previous actual SDK request plus the next response/tool round preserved verbatim in the first post-compression request.'}
    raise ValueError('no_response_bound_tool_round_after_compression')


def native_input_files(native):
    rows = lines(native / 'metrics/input.jsonl'); result = []
    for row in rows:
        for image in row.get('images', []):
            p = Path(image['path'])
            if not p.is_file() or sha(p) != image['sha256']: raise ValueError('original_input_image_missing_or_changed')
            result.append({'path': str(p), 'sha256': image['sha256'], 'media_type': image.get('media_type')})
    return result


def no_compression_proof(native, observation):
    if not observation['status'].startswith('completed'): raise ValueError('noncompleted_without_compression_target')
    conversation = read(native / 'conversation.json')
    if conversation.get('completed') is not True or conversation.get('error'): raise ValueError('source_native_conversation_not_complete')
    starts = lines(native / 'metrics/call-starts.jsonl'); calls = lines(native / 'metrics/calls.jsonl')
    if not starts or {r['call_id'] for r in starts} != {r['call_id'] for r in calls}: raise ValueError('call_journal_not_complete')
    policy = lines(native / 'metrics/policy.jsonl')
    if not any(r.get('verified') is True and r.get('strategy') == 'visual' for r in policy): raise ValueError('native_visual_policy_unverified')
    stats = native / 'context_images/compression_stats.json'
    if stats.exists() and read(stats).get('compressions', 0) != 0: raise ValueError('compression_stats_conflict')
    wire_path = native / 'metrics/inline-images-wire-v1.jsonl'
    if not wire_path.exists(): wire_path = native / 'metrics/hosted-images-wire-v3.jsonl'
    wires = lines(wire_path)
    pre = lines(native / 'metrics/vision-pre-retention.jsonl')
    legacy = lines(native / 'metrics/vision-wire.jsonl')
    if not wires and not legacy: raise ValueError('no_final_wire_no_compression_proof')
    if not wires and (not legacy or any(r.get('event') != 'final_http_payload' or r.get('compression_count') != 0 or r.get('expected_images', 0) != 0 for r in legacy)):
        raise ValueError('legacy_final_wire_not_zero_compression')
    if any(r.get('compression_count', 0) for r in pre): raise ValueError('prewire_compression_count_conflict')
    for row in wires:
        for image in row.get('selection', {}).get('retained', []):
            if image.get('origin') not in ('native',): raise ValueError('wire_contains_non_native_canvas')
    if any((native / 'context_images').glob('*manifest.json')): raise ValueError('renderer_artifact_without_compression_journal')
    return {'valid': True, 'paid_calls': 0, 'source_agent_calls': len(calls),
        'policy_sha256': sha(native / 'metrics/policy.jsonl'), 'calls_sha256': sha(native / 'metrics/calls.jsonl'),
        'wire_sha256': sha(wire_path if wires else native / 'metrics/vision-wire.jsonl'),
        'wire_schema': wire_path.name if wires else 'legacy-final-http-payload',
        'reuse_semantics': 'One measured no-intervention trajectory shared by both conditional controls; not two independent runs or duplicated spend.'}


def extract(row, root):
    out = root / 'extracted' / f"{row['question_id']}_r{row['repeat']:02d}"
    result_path = Path(row.get('selected_result_path') or row['latest_terminal_result_path'])
    expected = row.get('selected_result_sha256') or row['latest_terminal_result_sha256']
    result = {'slot_id': row['slot_id'], 'qid': row['question_id'], 'question_id': row['question_id'], 'repeat': row['repeat'],
        'source_status': row['status'], 'source_result_path': str(result_path), 'source_result_sha256': expected,
        'execution': 'blocked', 'reason': None, 'paid_calls': 0}
    try:
        if sha(result_path) != expected: raise ValueError('source_result_SHA_changed')
        result.update(source_grade_path=None, source_grade_sha256=None, source_score=None)
        if row.get('grade_path'):
            grade = read(row['grade_path'])
            if sha(row['grade_path']) != row.get('grade_sha256') or grade.get('result_sha256') != expected or grade.get('question_sha256') != row['question_sha256']:
                raise ValueError('source_grade_binding_invalid')
            if grade.get('status') in ('completed', 'scored') and grade.get('score') is not None:
                result.update(source_grade_path=row['grade_path'], source_grade_sha256=row['grade_sha256'], source_score=grade['score'])
        source = read(result_path); native = Path(source['native_artifact_root'])
        job, plan = source_job(result_path, source['job_id'])
        if not core_job_valid(job, row): raise ValueError('source_scope_not_core_mmbc_vera')
        if digest(job['question'].encode()) != row['question_sha256']: raise ValueError('source_question_changed')
        result.update(question=job['question'], source_native_root=str(native), source_plan=plan,
            source_config_path=job['config_path'], source_config_sha256=sha(job['config_path']),
            source_model=job['model'], source_execution_version=source.get('execution_version'),
            original_input_images=native_input_files(native), native_asset_roots=[str(native / 'workspace')])
        compressions = [r for r in lines(native / 'metrics/compression.jsonl') if r.get('count_delta', 0) > 0]
        result['source_compression_events'] = len(compressions)
        if not compressions:
            proof = no_compression_proof(native, row); result.update(execution='no_compression_reuse', reason='source_completed_without_intervention', no_compression_proof=proof)
        else:
            first = compressions[0]; calls_path = native / 'metrics/calls.jsonl'
            calls = sorted([r for r in lines(calls_path) if r.get('purpose') == 'agent'], key=lambda r: r['started_at'])
            after = [r for r in calls if seconds(r['started_at']) >= seconds(first['timestamp'])]
            if not after: raise ValueError('no_provider_call_after_first_compression')
            call = after[0]; target = (call.get('raw_provider_usage') or {}).get('prompt_tokens')
            if not isinstance(target, int) or target <= 0: raise ValueError('first_post_compression_prompt_usage_unknown')
            archive = native / 'metrics/requests-responses.jsonl.gz'
            previous, post, generated_ids, traversed = archived_pair(archive, call['call_id'])
            prefix, reconstruction = reconstruct_prefix(previous, post, generated_ids)
            pre_images = image_ledger(prefix['messages']); post_images = image_ledger(post['messages'])
            prefix_path = out / 'prefix.json'; prefix_sha = save(prefix_path, prefix)
            post_path = out / 'source-post-request.json'; post_sha = save(post_path, post)
            start, end = seconds(call['started_at']), seconds(call['ended_at'])
            wire_path = native / 'metrics/inline-images-wire-v1.jsonl'
            if not wire_path.exists(): wire_path = native / 'metrics/hosted-images-wire-v3.jsonl'
            wires = [r for r in lines(wire_path) if start <= r.get('at_unix', -1) <= end]
            if not wires:
                legacy_path = native / 'metrics/vision-wire.jsonl'; legacy = lines(legacy_path)
                if len(legacy) != len(calls) or len(legacy) < traversed: raise ValueError('post_wire_selection_not_bound_to_call_window')
                legacy_row = legacy[traversed - 1]
                if legacy_row.get('event') != 'final_http_payload' or legacy_row.get('compression_count') != 1: raise ValueError('legacy_post_wire_compression_index_mismatch')
                actual = legacy_row.get('images', [])
                if [(x['payload_sha256'], x.get('detail') or 'auto') for x in actual] != [(x['sha256'], x.get('detail') or 'auto') for x in post_images]:
                    raise ValueError('legacy_post_wire_image_fingerprint_mismatch')
                native_digests = {x['sha256'] for x in pre_images}
                retained = [dict(x, original_part_index=x['part_index'], origin='native' if x['sha256'] in native_digests else 'canvas') for x in post_images]
                wires = [{'legacy_ordinal_binding': {'request_ordinal': traversed, 'total_call_count': len(calls), 'total_wire_count': len(legacy)},
                    'network_send_authorized': True, 'selection': {'retained': retained}, 'legacy_row': legacy_row}]
                wire_path = legacy_path
            selected = []
            for wire in wires:
                if wire.get('network_send_authorized') is False: continue
                retained = wire.get('selection', {}).get('retained')
                if retained is None: raise ValueError('wire_retention_missing')
                wire['archive_image_subsequence_binding'] = bind_wire_images(post_images, retained)
                selected.append(retained)
            if not selected: raise ValueError('post_wire_never_sent')
            signatures = [[(x['sha256'], x.get('detail'), x.get('origin')) for x in selection] for selection in selected]
            if any(signature != signatures[0] for signature in signatures[1:]): raise ValueError('post_call_wire_image_selection_changed_across_attempts')
            native_post = [x for x in selected[0] if x.get('origin') == 'native']
            canvas = [x for x in selected[0] if x.get('origin') != 'native']
            manifests = sorted((native / 'context_images').glob('compact_1_*manifest.json'))
            if not manifests: manifests = sorted((native / 'context_images').glob('compact_0_*manifest.json'))
            render = read(manifests[0]) if manifests else {}
            evidence = {'version': VERSION, 'source_result_path': str(result_path), 'source_result_sha256': expected,
                'source_call_id': call['call_id'], 'source_calls_path': str(calls_path), 'source_calls_sha256': sha(calls_path),
                'source_call': call, 'first_actual_prompt_tokens': target, 'target_is_provider_measured': True,
                'source_archive_path': str(archive), 'source_archive_sha256': sha(archive),
                'prefix_sha256': prefix_sha, 'post_request_sha256': post_sha, 'reconstruction': reconstruction,
                'first_compression': first, 'source_compression_events': len(compressions),
                'wire_ledger_path': str(wire_path), 'wire_ledger_sha256': sha(wire_path), 'post_wire_rows': wires,
                'prefix_native_images': pre_images, 'source_post_native_images': native_post, 'source_post_canvas_images': canvas,
                'native_standalone_exact_parity': [(x['sha256'], x['detail']) for x in pre_images] == [(x['sha256'], x.get('detail')) for x in native_post],
                'renderer_manifest_path': str(manifests[0]) if manifests else None,
                'renderer_manifest_sha256': sha(manifests[0]) if manifests else None,
                'renderer_version': render.get('version'), 'renderer_source_image_occurrences': len(render.get('source_images', [])) if manifests else None,
                'image_token_equality_required': False, 'comparison': 'VERA embeds visual evidence in canvas; text controls retain source native images separately. Match total first prompt within 2%, not image-token equality.',
                'source_selected_outcome_is_not_replayed_visual_continuation': True,
                'source_subsequent_compressions': max(0, len(compressions) - 1)}
            evidence_path = out / 'target-evidence.json'; evidence_sha = save(evidence_path, evidence)
            result.update(prefix_path=str(prefix_path), prefix_sha256=prefix_sha, target_evidence_path=str(evidence_path),
                target_evidence_sha256=evidence_sha, source_post_prompt_tokens=target,
                source_post_request_path=str(post_path), source_post_request_sha256=post_sha,
                native_image_count=len(pre_images), zero_native_prefix=not pre_images, source_post_native_image_count=len(native_post), source_post_canvas_count=len(canvas),
                native_standalone_exact_parity=evidence['native_standalone_exact_parity'],
                renderer_source_image_occurrences=evidence['renderer_source_image_occurrences'], renderer_version=evidence['renderer_version'],
                source_post_model=post['model'], execution='matched_continuation', reason='measured_source_target_and_reconstructed_prefix')
            if len(pre_images) > 10: result.update(execution='blocked', reason='source_native_images_exceed_ten_preserve_all_guard')
    except (ValueError, KeyError, OSError, TypeError, IndexError) as exc:
        result.update(execution='blocked', reason=str(exc) if isinstance(exc, ValueError) else type(exc).__name__)
    save(out / 'source-audit.json', result)
    return result


def prepare(root, workers=4):
    root = Path(root).resolve(); root.mkdir(parents=True, exist_ok=True)
    snapshot = root / 'source-report.json'
    if not snapshot.exists():
        with snapshot.open('xb') as stream: stream.write(REPORT.read_bytes())
    report, snapshot = core_corrected_report(root, read(snapshot)); cohort = select_cohort(report)
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        slots = list(pool.map(lambda row: extract(row, root), cohort))
    result = {'version': VERSION, 'source_snapshot_path': str(snapshot), 'source_snapshot_sha256': sha(snapshot),
        'source_snapshot_at': report['at'], 'population': 300, 'non_timeout_slots': len(cohort),
        'completed_source_slots': sum(r['source_status'].startswith('completed') for r in slots),
        'non_timeout_failed_source_slots': sum(not r['source_status'].startswith('completed') for r in slots),
        'timeout_excluded': 300 - len(cohort), 'selection_uses_accuracy': False, 'paid_calls': 0,
        'execution_counts': dict(collections.Counter(r['execution'] for r in slots)),
        'blocked_reasons': dict(collections.Counter(r['reason'] for r in slots if r['execution'] == 'blocked')),
        'no_compression_reuse_is_not_independent_replication': True,
        'methods': ['summary_native', 'window_native'], 'per_method_concurrency': 16,
        'source_sha256': sha(__file__), 'slots': slots}
    save(root / 'cohort.json', result)
    return result


def main():
    p = argparse.ArgumentParser(); p.add_argument('--root', type=Path, default=DEFAULT); p.add_argument('--workers', type=int, default=4)
    args = p.parse_args(); result = prepare(args.root, args.workers)
    print(json.dumps({k: v for k, v in result.items() if k != 'slots'}, ensure_ascii=False, indent=2))


if __name__ == '__main__': main()
