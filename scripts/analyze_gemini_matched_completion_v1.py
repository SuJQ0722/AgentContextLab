"""Read archived Gemini results on the current DeepSeek question cohorts; no API calls."""
import collections
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import statistics

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'outputs/analysis/gemini-matched-completion-v1'
METHODS = ('none', 'discard', 'summarize', 'sliding_window', 'visual')
LABELS = dict(zip(('No Compression', 'Discard', 'Summarize', 'Sliding Window', 'VERA'), METHODS))
HASHES = {}


def read(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    HASHES[str(path)] = hashlib.sha256(raw).hexdigest()
    return json.loads(raw)


def question_sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def load_archive(row):
    source = (ROOT / row['source_path']).resolve()
    data = read(source)
    if (question_sha(data['question']) != row['question_hash']
            or data.get('session_id') != row['session_id']
            or data.get('status') != row['status']
            or data.get('model') != 'gemini-3.5-flash-thinking'
            or int(data['repeat_index']) != int(row['repeat'])):
        raise ValueError('Archive identity differs: ' + str(source))
    final = data.get('model_response') or ''
    completed = (data['status'] == 'success' and bool(final.strip())
                 and data.get('final_assistant_valid') is not False)
    status = 'completed' if completed else 'failure_timeout_unknown'
    history_path = (ROOT / row['history_path']).resolve()
    if not completed and history_path.exists():
        history = read(history_path)
        if (history.get('session_id') == data.get('session_id')
                and question_sha(history['question']) == row['question_hash']):
            if history.get('timed_out') is True:
                status = 'timeout'
            elif history.get('timed_out') is False:
                status = 'failed'
    parts = source.parts
    pos = parts.index('conv')
    grade_path = Path(*parts[:pos], 'judge', *parts[pos + 1:])
    score = None
    score_reason = 'not_completed'
    if completed:
        score_reason = 'missing_grade'
        if grade_path.exists():
            grade = read(grade_path)
            if (question_sha(grade['question']) != row['question_hash']
                    or int(grade['repeat_index']) != int(row['repeat'])
                    or grade['question_id'] != data['question_id']
                    or grade.get('prediction', '').strip() != final.strip()):
                raise ValueError('Archive grade does not bind to prediction: ' + str(grade_path))
            score_reason = grade.get('status')
            if (grade.get('status') == 'judged' and grade.get('pred_status') == 'success'
                    and type(grade.get('score')) in (int, float) and grade['score'] in (0, 1)):
                score = grade['score']
    return {'benchmark': row['benchmark'], 'model': data['model'], 'harness': 'hermes',
            'method': LABELS[row['method']], 'question_hash': row['question_hash'],
            'question_id': data['question_id'], 'repeat': int(row['repeat']),
            'prediction_status': status, 'clean_completed': completed, 'score': score,
            'score_reason': score_reason, 'source_path': str(source),
            'source_sha256': HASHES[str(source)], 'grade_path': str(grade_path),
            'grade_sha256': HASHES.get(str(grade_path)),
            'history_path': str(history_path), 'legacy_alias_not_provider_attested': True}


def summarize(rows, benchmark, questions, repeats):
    index = {m: {} for m in METHODS}
    for row in rows:
        if row['benchmark'] != benchmark:
            continue
        key = (row['question_hash'], row['repeat'])
        if key in index[row['method']]:
            raise ValueError('Duplicate archive method/question/repeat')
        index[row['method']][key] = row
    expected = {(q, r) for q in questions for r in repeats}
    complete = {k for k in expected if all(index[m].get(k, {}).get('clean_completed') for m in METHODS)}
    scored = {k for k in complete if all(index[m][k]['score'] in (0, 1) for m in METHODS)}
    balanced = sorted(q for q in questions if all((q, r) in scored for r in (1, 2, 3)))
    methods = {}
    for method in METHODS:
        ix = index[method]
        counts = collections.Counter(ix[k]['prediction_status'] if k in ix else 'missing_archive_record' for k in expected)
        rates = [statistics.mean(ix[q, r]['score'] for q in balanced) for r in (1, 2, 3)] if balanced else []
        correct = sum(ix[k]['score'] for k in scored)
        methods[method] = {'correct': correct, 'denominator': len(scored),
            'accuracy': correct / len(scored) if scored else None, 'statuses': dict(counts),
            'balanced_avg3': {'questions': len(balanced),
                'mean': statistics.mean(rates) if rates else None,
                'sample_std_ddof1': statistics.stdev(rates) if rates else None}}
    return {'cohort_questions': len(questions), 'target_repeat_indices': repeats,
            'expected_slots_per_method': len(expected), 'completed_slots': len(complete),
            'slots': len(scored), 'unique_questions': len({q for q, r in scored}),
            'completed_missing_any_grade': len(complete - scored),
            'slot_keys': sorted(scored), 'methods': methods}


def main():
    bc_path = ROOT / 'outputs/grading/bc100-v3-deepseek-sfb-v1/analysis/selected-observations.jsonl'
    raw = bc_path.read_bytes(); HASHES[str(bc_path)] = hashlib.sha256(raw).hexdigest()
    bc = {json.loads(line)['question_hash'] for line in raw.splitlines() if line.strip()}
    mm = {r['question_sha256'] for r in read(ROOT / 'outputs/grading/mmbc100-deepseek-hermes-v1/observations.json')}
    if len(bc) != 100 or len(mm) != 100:
        raise ValueError('Expected the fixed 100-question cohorts')
    cache = ROOT / 'outputs/experiment1/reconstructed.jsonl'
    raw = cache.read_bytes(); HASHES[str(cache)] = hashlib.sha256(raw).hexdigest()
    selected = []
    for line in raw.splitlines():
        row = json.loads(line)
        if not row.get('canonical') or row.get('model') != 'gemini-3.5-flash-thinking':
            continue
        if ((row['benchmark'] == 'bc' and row['question_hash'] in bc)
                or (row['benchmark'] == 'mmbrowsecomp' and row['question_hash'] in mm)):
            selected.append(row)
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(load_archive, selected))
    report = {'at': datetime.now(timezone.utc).isoformat(), 'paid_calls': 0,
        'selection': 'Existing canonical archive naming only; no selection by answer correctness; exact content hash and repeat matched.',
        'limitations': 'Historical model alias is not provider-attested. Historical protocols differ from DeepSeek. Missing archive records are not failed trials. MMBC archive only has repeat 1.',
        'scopes': {'bc': summarize(rows, 'bc', bc, [1, 2, 3]),
                   'mmbrowsecomp': summarize(rows, 'mmbrowsecomp', mm, [1])},
        'source_sha256': HASHES, 'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'rows.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2) + '\n')
    (OUT / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report['scopes'], ensure_ascii=False))


if __name__ == '__main__':
    main()
