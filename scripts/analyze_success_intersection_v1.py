#!/usr/bin/env python3
"""Offline paired successful-completion intersections; never performs API calls."""
import argparse
from collections import Counter
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
METHODS = ('none', 'discard', 'summarize', 'sliding_window', 'visual')

def read(path):
    return json.loads(Path(path).read_text())

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def rows(path):
    p = Path(path)
    return [json.loads(s) for s in p.read_text().splitlines() if s.strip()] if p.suffix == '.jsonl' else read(p)

def index_rows(observations, methods):
    index = {m: {} for m in methods}
    identity = {}
    for r in observations:
        if r['method'] not in index:
            continue
        key = (r['question_id'], r['repeat'])
        digest = r.get('question_hash', r.get('question_sha256'))
        if not digest:
            raise ValueError('Missing question content identity')
        if key[0] in identity and identity[key[0]] != digest:
            raise ValueError('Question identity mismatch')
        identity[key[0]] = digest
        if key in index[r['method']]:
            raise ValueError('Duplicate method/question/repeat')
        index[r['method']][key] = r
    return index

def summarize(index, keys):
    keys = sorted(keys)
    complete_questions = sorted(q for q in {q for q, _ in keys} if all((q, rep) in keys for rep in (1, 2, 3)))
    return {'slots': len(keys), 'unique_questions': len({q for q, _ in keys}),
            'repeat_counts': dict(Counter(rep for _, rep in keys)), 'balanced_three_repeat_questions': len(complete_questions),
            'slot_keys': [list(k) for k in keys], 'methods': {
                m: {'correct': sum(v[k]['score'] for k in keys), 'denominator': len(keys),
                    'accuracy': sum(v[k]['score'] for k in keys) / len(keys) if keys else None,
                    'missing_scores': sum(v[k]['score'] not in (0, 1) for k in keys)} for m, v in index.items()}}

ERROR_PATTERN = re.compile(r'APIConnectionError|APITimeoutError|ReadTimeout|WriteTimeout|ConnectTimeout|RateLimitError|InternalServerError|Traceback \(most recent call last\)|Retrying request to /chat/completions|Error code: [45][0-9]{2}')

@lru_cache(maxsize=None)
def audit_attempt(attempt):
    p = Path(attempt)
    result = read(p / 'result.json')
    evidence = []; unknown = []
    if result.get('status') != 'completed' or result.get('error_type') or result.get('failure_category') or result.get('exit_code') not in (0, None):
        evidence.append('nonclean_terminal_result')
    metric = p / 'native/metrics'
    if not metric.exists():
        candidates = list((p / 'native').glob('*/*/workspace/metrics'))
        metric = candidates[0] if len(candidates) == 1 else None
    for name in ('calls.jsonl', 'call-starts.jsonl', 'web.jsonl'):
        if metric is None or not (metric / name).exists():
            unknown.append('missing_' + name)
    if metric is not None:
        logs = {}
        for name in ('calls.jsonl', 'call-starts.jsonl', 'web.jsonl'):
            f = metric / name
            if f.exists():
                try: logs[name] = rows(f)
                except (ValueError, OSError): unknown.append('unreadable_' + name)
        calls = logs.get('calls.jsonl', [])
        starts = logs.get('call-starts.jsonl', [])
        if not calls: unknown.append('no_call_records')
        if not starts: unknown.append('no_call_starts')
        if any(not c.get('call_id') for c in calls + starts): unknown.append('missing_call_identity')
        if {c.get('call_id') for c in starts} != {c.get('call_id') for c in calls}: unknown.append('unmatched_call_starts')
        for name, records in logs.items():
            for c in records:
                finish = c.get('finish') or {}
                status = c.get('proxy_http_status')
                if c.get('error_type') or c.get('error') or finish.get('kind') in ('error', 'abort', 'aborted') or c.get('success') is False or c.get('http_success') is False or (isinstance(status, int) and status >= 400):
                    evidence.append(name + ':reported_error')
        # SDK calls can include internally retried HTTP requests. These ledgers do not prove zero wire errors.
    candidates = [p / 'worker.log', p / 'launcher.log'] + list((p / 'native').glob('*/*/stderr.log'))
    for f in candidates:
        if f.exists():
            for match in set(ERROR_PATTERN.findall(f.read_text(errors='replace'))): evidence.append(f.name + ':' + match)
    return {'state': 'observed_error' if evidence else ('coverage_unknown' if unknown else 'no_observed_error'),
            'error_evidence': sorted(set(evidence)), 'coverage_unknown': sorted(set(unknown)),
            'strict_zero_wire_errors_certified': False}

def analyze(observations, methods, audit=True):
    ix = index_rows(observations, methods)
    common = set.intersection(*(set(v) for v in ix.values()))
    completed = {k for k in common if all(ix[m][k]['prediction_status'] == 'completed' for m in methods)}
    graded = {k for k in completed if all(type(ix[m][k].get('score')) in (int,float) and ix[m][k]['score'] in (0,1) for m in methods)}
    value = {'planned_common_slots': len(common), 'all_completed_slots': len(completed), 'completed_but_missing_any_grade': len(completed - graded), 'completed_and_scored': summarize(ix, graded)}
    if audit:
        attempts = sorted({ix[m][k]['attempt'] for k in completed for m in methods})
        with ThreadPoolExecutor(max_workers=16) as pool:
            audits = dict(zip(attempts, pool.map(audit_attempt, attempts)))
        clean = {k for k in graded if all(audits[ix[m][k]['attempt']]['state'] == 'no_observed_error' for m in methods)}
        value.update(no_observed_errors=summarize(ix, clean), attempt_audit=audits,
                     audit_counts=dict(Counter(a['state'] for a in audits.values())))
    return value

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output', type=Path, default=ROOT/'outputs/analysis/success-intersection-v1')
    ap.add_argument('--doc', type=Path, default=ROOT/'docs/statistics/success-intersection-2026-11-11.md')
    args = ap.parse_args()
    paths = [ROOT/'outputs/grading/bc100-v3-deepseek-sfb-v1/analysis/selected-observations.jsonl', ROOT/'outputs/grading/mmbc100-deepseek-hermes-v1/observations.json', ROOT/'outputs/grading/mmbc100-hermes-vanilla-v1/observations.json']
    bc = rows(paths[0]); mm = rows(paths[1]) + rows(paths[2])
    scopes = {f'BC {h} five methods': analyze([r for r in bc if r['harness']==h], METHODS) for h in ('hermes','dsh')}
    scopes['MMBC hermes six methods'] = analyze(mm, METHODS+('vanilla_visual',))
    scopes['MMBC hermes five methods sensitivity'] = analyze(mm, METHODS)
    report = {'source_sha256': {str(p.relative_to(ROOT)): sha(p) for p in paths}, 'script_sha256':sha(__file__), 'scopes':scopes,
              'paid_calls':0, 'later_visual_only_retries_included':False, 'strict_zero_wire_errors_certified':False,
              'interpretation':'Same question content and repeat intersection, selected by operational completion and optionally no observed logged errors, never by answer correctness. Post-treatment successful subset; not full benchmark or unbiased method superiority. Existing BC fixed failed-retry selection retained. Not balanced avg3; no std fabricated. Missing scores exclude the whole paired slot for all methods. SDK internal retries may be unobserved.'}
    args.output.mkdir(parents=True, exist_ok=True); (args.output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    lines=['# 所有方法成功交集：离线配对统计','', '固定同一题目内容和同一repeat，先取全部方法 completed 的交集，再删除任一方法缺评分的整组。没有按答案正误筛选。BC沿用原有固定失败恢复选择；不混入后续按答案筛选的VERA-only补跑。', '', '**口径A：全部方法完成且有评分**。这不证明过程中没有恢复过的API错误。', '', '| Scope | 配对题次 | 独立题数 | repeat 1/2/3数量 | No Compression | Discard | Summary | Window | VERA | Vanilla |','|---|---:|---:|---|---:|---:|---:|---:|---:|---:|']
    def table_row(label, s):
        cells=[]
        for m in METHODS+('vanilla_visual',):
            v=s['methods'].get(m);cells.append(f"{100*v['accuracy']:.2f}% ({int(v['correct'])}/{v['denominator']})" if v and v['accuracy'] is not None else 'NA')
        return '| '+ ' | '.join([label,str(s['slots']),str(s['unique_questions']),'/'.join(str(s['repeat_counts'].get(i,0)) for i in (1,2,3))]+cells)+' |'
    for label,v in scopes.items(): lines.append(table_row(label,v['completed_and_scored']))
    lines += ['', '**口径B：全部方法完成、有评分，且所检查日志中没有已记录错误**。要求calls/call-starts/web日志存在、模型调用ID闭合，并剔除结构化API/工具失败及日志中明确的连接/超时/重试标记。SDK内部重试未必逐HTTP记录，因此这里是“未观察到错误”，不能冒称严格零错误。', '', '| Scope | 配对题次 | 独立题数 | repeat 1/2/3数量 | No Compression | Discard | Summary | Window | VERA | Vanilla |','|---|---:|---:|---|---:|---:|---:|---:|---:|---:|']
    for label,v in scopes.items(): lines.append(table_row(label,v['no_observed_errors']))
    lines += ['', '## 覆盖与解释', '', '成功交集是运行结果之后的筛选，容易保留较容易的题目。不能取代完整cohort的成功率、超时率和准确率，也不能用来证明总体优越性。各repeat覆盖不相同，以上是题次等权准确率，不标作完整avg@3 ± std。MMBC六方法和五方法交集不同，不能跨行直接归因vanilla带来的效果。', '']
    for label,v in scopes.items(): lines.append(f"- {label}: completed交集{v['all_completed_slots']}，因缺评分整组排除{v['completed_but_missing_any_grade']}；审计轨迹状态{v['audit_counts']}；口径A具有完整三个repeat的题数{v['completed_and_scored']['balanced_three_repeat_questions']}。")
    lines += ['', '原始输入SHA、纳入题目/repeat清单、逐attempt错误与覆盖记录：`outputs/analysis/success-intersection-v1/report.json`。', '', '复现：`python scripts/analyze_success_intersection_v1.py`。零模型调用，不修改原始日志或冻结实验。']
    args.doc.parent.mkdir(parents=True,exist_ok=True);args.doc.write_text('\n'.join(lines)+'\n')
    print(json.dumps({k:{'completed':v['completed_and_scored'],'no_observed_error':v['no_observed_errors'],'audit_counts':v['audit_counts']} for k,v in scopes.items()},ensure_ascii=False))

if __name__ == '__main__':main()
