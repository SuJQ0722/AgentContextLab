#!/usr/bin/env python3
"""Offline six-method MMBC intersection, retaining execution completions, never answers."""
import argparse
import datetime
import hashlib
import json
from collections import Counter
from pathlib import Path
import statistics

ROOT = Path(__file__).resolve().parents[1]
METHODS = ('none', 'discard', 'summarize', 'sliding_window', 'visual', 'vanilla_visual')
WAVES = ('visual-hosted-failure-retry-v1', 'visual-hosted-transport-v4',
         'visual-inline-failure-retry-v5', 'visual-inline-canary-v6')


def retain(current, candidate):
    """The first completed execution wins, even wrong or ungraded."""
    return current if current['prediction_status'] == 'completed' else candidate


def summarize(rows):
    ix = {m: {} for m in METHODS}
    identity = {}
    for row in rows:
        key = (row['question_id'], row['repeat'])
        if key in ix[row['method']]:
            raise ValueError('Duplicate method slot')
        ix[row['method']][key] = row
        if identity.setdefault(key[0], row['question_sha256']) != row['question_sha256']:
            raise ValueError('Question identity differs')
    common = set.intersection(*(set(v) for v in ix.values()))
    complete = {k for k in common if all(ix[m][k]['prediction_status'] == 'completed' for m in METHODS)}
    scored = {k for k in complete if all(type(ix[m][k]['score']) in (int, float) and ix[m][k]['score'] in (0, 1) for m in METHODS)}
    balanced = sorted(q for q in {k[0] for k in scored} if all((q, rep) in scored for rep in (1, 2, 3)))
    result = {'planned_common_slots': len(common), 'all_completed_slots': len(complete),
              'completed_missing_any_grade': len(complete - scored), 'slots': len(scored),
              'unique_questions': len({q for q, _ in scored}),
              'repeat_counts': dict(Counter(rep for _, rep in scored)),
              'slot_keys': [list(k) for k in sorted(scored)],
              'strict_three_repeat_questions': balanced, 'methods': {}}
    for method, data in ix.items():
        scores = [data[k]['score'] for k in scored]
        per = [statistics.mean(data[q, rep]['score'] for q in balanced) for rep in (1, 2, 3)] if balanced else []
        result['methods'][method] = {'correct': sum(scores), 'denominator': len(scores),
            'accuracy': statistics.mean(scores) if scores else None,
            'strict_three_repeat': {'questions': len(balanced), 'denominator': len(balanced) * 3,
                'correct': sum(data[q, rep]['score'] for q in balanced for rep in (1, 2, 3)),
                'repeat_accuracy': per, 'avg3': statistics.mean(per) if per else None,
                'sample_std_across_repeats': statistics.stdev(per) if per else None}}
    return result


def run(output):
    hashes = {}
    def read(path):
        path = Path(path).resolve()
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if str(path) in hashes and hashes[str(path)] != digest:
            raise ValueError('Source changed during snapshot: ' + str(path))
        hashes[str(path)] = digest
        return json.loads(raw)

    def result_row(row, attempt, plan, job, grading_root, wave, recovery=None):
        rp = attempt / 'result.json'
        result = read(rp)
        if any(result.get(k) != job[k] for k in ('job_id', 'question_id', 'repeat', 'harness', 'strategy', 'model')):
            raise ValueError('Result identity mismatch')
        if result.get('slot_released') is not True or result.get('unconfirmed_child_termination') != []:
            raise ValueError('Unconfirmed execution cleanup')
        question_sha = hashlib.sha256(job['question'].encode()).hexdigest()
        if question_sha != row['question_sha256']:
            raise ValueError('Question text changed')
        value = dict(row, prediction_status=result['status'], attempt=str(attempt),
            result_sha256=hashes[str(rp.resolve())], score=None, score_reason='not_completed',
            prediction_wave=wave, grading_source=None)
        if result['status'] != 'completed':
            return value
        gp = grading_root / 'jobs' / job['job_id'] / 'grade.json'
        if recovery is not None:
            entry = recovery.get((row.get('cell'), job['job_id']))
            if entry:
                old = read(entry['old_grade_path'])
                if hashes[str(Path(entry['old_grade_path']).resolve())] != entry['old_grade_sha256']:
                    raise ValueError('Recovery old grade changed')
                if old.get('status') != 'http_error' or old.get('http_status') != 429:
                    raise ValueError('Recovery did not replace explicit judge 429')
                gp = Path(entry['grade_path'])
        value['score_reason'] = 'completed_grade_missing'
        if gp.exists():
            grade = read(gp)
            for k, expected in {'result_sha256': value['result_sha256'],
                'question_sha256': question_sha, 'attempt_path': str(attempt),
                'plan_sha256': hashes[str(plan.resolve())]}.items():
                if grade.get(k) != expected:
                    raise ValueError('Grade binding mismatch: ' + k)
            value['grading_source'] = str(gp)
            value['score_reason'] = grade.get('status')
            if grade.get('status') == 'scored' and type(grade.get('score')) in (int, float) and grade['score'] in (0, 1):
                value.update(score=grade['score'], score_reason='judged_completed')
        return value

    selected = {}
    for name in ('mmbc100-deepseek-hermes-v1', 'mmbc100-hermes-vanilla-v1'):
        grading = ROOT / 'outputs/grading' / name
        observations = read(grading / 'observations.json')
        binding = read(grading / 'source-binding.json')
        root = Path(binding['root']); pp = root / 'plan.json'; plan = read(pp)
        if hashes[str(pp.resolve())] != binding['plan_sha256']:
            raise ValueError('Base plan changed')
        jobs = {j['job_id']: j for j in plan['jobs']}
        for row in observations:
            key = (row['method'], row['question_id'], row['repeat'])
            candidate = result_row(row, Path(row['attempt']), pp, jobs[row['job_id']], grading, name)
            if row['result_sha256'] != candidate['result_sha256']:
                raise ValueError('Original observation result changed')
            selected[key] = candidate

    recover_root = ROOT / 'outputs/grading/visual-inline-judge-recovery-v1'
    recovery_rows = read(recover_root / 'summary.json')['results']
    recovery = {(r['cell'], r['job_id']): r for r in recovery_rows}
    read(recover_root / 'observations-merged.json')
    overlays = []
    for wave in WAVES:
        grading = ROOT / 'outputs/grading' / wave
        observations = read(grading / 'observations.json')
        for cell, method in [('mmbc_vera', 'visual'), ('mmbc_vanilla', 'vanilla_visual')]:
            binding = read(grading / 'cells' / cell / 'source-binding.json')
            root = Path(binding['root']); pp = root / 'plan.json'; plan = read(pp)
            if hashes[str(pp.resolve())] != binding['plan_sha256'] or plan['definition'].get('selection_uses_answers') is not False:
                raise ValueError('Invalid fixed failure overlay')
            jobs = {j['job_id']: j for j in plan['jobs']}
            replaced = Counter()
            for row in observations:
                if row['cell'] != cell:
                    continue
                key = (method, row['question_id'], row['repeat']); old = selected[key]
                if old['prediction_status'] == 'completed':
                    replaced['retained_earlier_completed'] += 1
                    continue
                job = jobs[row['job_id']]; attempt = root / 'jobs' / job['job_id'] / 'attempts/attempt_001'
                if not (attempt / 'result.json').exists():
                    replaced['new_result_missing_kept_predecessor'] += 1
                    continue
                candidate = result_row(dict(old, cell=cell), attempt, pp, job, grading / 'cells' / cell,
                    wave, recovery if wave == 'visual-inline-failure-retry-v5' else None)
                selected[key] = retain(old, candidate)
                replaced['new_' + candidate['prediction_status']] += 1
            overlays.append({'wave': wave, 'cell': cell, 'counts': dict(replaced)})

    rows = sorted(selected.values(), key=lambda r: (r['method'], r['question_id'], r['repeat']))
    if len(rows) != 1800:
        raise ValueError('Expected exactly six methods x100x3')
    stats = summarize(rows)
    hashes[str(Path(__file__).resolve())] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    report = {'as_of_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'paid_calls': 0, 'methods': METHODS, 'summary': stats, 'overlays': overlays,
        'excluded_answer_selected_namespace': 'outputs/campaigns/mmbc-vera-bounded-retry-v1',
        'selection_policy': 'Earliest completed execution retained irrespective of score; only execution failures replaced by subsequent fixed operational recovery. Answer-selected bounded namespace excluded.',
        'interpretation': 'Post-execution intersection, mixed protocol recovery. Descriptive paired subset, not full benchmark accuracy or unbiased superiority. Strict avg3/std uses only questions with all three scored repeats common to all six methods.',
        'source_sha256': hashes,
        'selected_status_counts': {m: dict(Counter(r['prediction_status'] for r in rows if r['method'] == m)) for m in METHODS}}
    output.mkdir(parents=True, exist_ok=True)
    (output / 'rows.json').write_text(json.dumps(rows, indent=2) + '\n')
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    lines = ['# MMBC 六方法共同完成交集', '', report['selection_policy'], '',
        f"共同 completed {stats['all_completed_slots']} 题次；共同 completed+scored {stats['slots']} 题次，独立题 {stats['unique_questions']}，repeat覆盖 {stats['repeat_counts']}。", '',
        '| 方法 | 正确/分母 | Accuracy | 三repeat齐全子集 avg3 ± sample std |',
        '|---|---:|---:|---:|']
    for m in METHODS:
        v = stats['methods'][m]; strict = v['strict_three_repeat']
        acc = f"{v['accuracy']*100:.2f}%" if v['accuracy'] is not None else 'NA'
        avg = f"{strict['avg3']*100:.2f} ± {strict['sample_std_across_repeats']*100:.2f}%" if strict['avg3'] is not None else 'NA'
        lines.append(f"| {m} | {v['correct']:g}/{v['denominator']} | {acc} | {avg} |")
    lines += ['', f"严格三repeat齐全子集：{len(stats['strict_three_repeat_questions'])}道题，每方法{3*len(stats['strict_three_repeat_questions'])}题次。", '', report['interpretation']]
    (output / 'summary.md').write_text('\n'.join(lines) + '\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'outputs/analysis/mmbc-sixmethod-completed-intersection-v2')
    args = parser.parse_args()
    print(json.dumps(run(args.output)['summary'], ensure_ascii=False))
