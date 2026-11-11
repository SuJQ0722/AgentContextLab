"""Join audited historical and current completed subsets without inference."""
import collections
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import statistics

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'outputs/analysis/multimodel-success-subsets-v1'
DOC = ROOT / 'docs/statistics/multimodel-harness-success-subsets-2026-11-11.md'
METHODS = ('none', 'discard', 'summarize', 'sliding_window', 'visual', 'vanilla_visual')
NAMES = ('No Compression', 'Discard-All', 'Summarization', 'Sliding Window', 'VERA', 'Vanilla')
SOURCES = {}


def read(relative):
    path = ROOT / relative
    raw = path.read_bytes(); SOURCES[relative] = hashlib.sha256(raw).hexdigest()
    if path.suffix == '.jsonl':
        return [json.loads(line) for line in raw.splitlines() if line.strip()]
    return json.loads(raw)


def cross(rows):
    index = collections.defaultdict(dict)
    for label, row in rows:
        key = (row.get('question_hash', row.get('question_sha256')), int(row['repeat']))
        if not key[0] or key in index[label]:
            raise ValueError('Missing identity or duplicate cross-configuration slot')
        index[label][key] = row
    keys = set.intersection(*(set(x) for x in index.values()))
    complete = {k for k in keys if all(x[k]['prediction_status'] == 'completed'
                and x[k].get('clean_completed', True) for x in index.values())}
    scored = {k for k in complete if all(type(x[k].get('score')) in (int, float)
                and x[k]['score'] in (0, 1) for x in index.values())}
    balanced = sorted(q for q in {q for q, r in scored}
                      if all((q, r) in scored for r in (1, 2, 3)))
    values = {}
    for label, ix in index.items():
        correct = sum(ix[k]['score'] for k in scored)
        rates = [statistics.mean(ix[q, r]['score'] for q in balanced) for r in (1, 2, 3)] if balanced else []
        values[label] = {'correct': correct, 'denominator': len(scored),
            'accuracy': correct / len(scored) if scored else None,
            'strict_avg3': {'questions': len(balanced),
                'mean': statistics.mean(rates) if rates else None,
                'sample_std_ddof1': statistics.stdev(rates) if rates else None}}
    return {'slots': len(scored), 'unique_questions': len({q for q, r in scored}),
            'complete_missing_grade': len(complete - scored), 'slot_keys': sorted(scored),
            'methods': values}


def cell(value):
    return f"{100*value['accuracy']:.2f}% ({value['correct']:g}/{value['denominator']})" if value and value['accuracy'] is not None else '—'


def main():
    g = read('outputs/analysis/gemini-matched-completion-v1/report.json')
    gr = read('outputs/analysis/gemini-matched-completion-v1/rows.json')
    b = read('outputs/analysis/bc-completion-intersection-v3-snapshot/report.json')
    br = read('outputs/analysis/bc-completion-intersection-v3-snapshot/selected-observations.jsonl')
    mm = read('outputs/analysis/mmbc-sixmethod-completed-intersection-v3/report.json')
    mr = read('outputs/analysis/mmbc-sixmethod-completed-intersection-v3/rows.json')
    paired_bc = cross([(f"gemini/hermes/{r['method']}", r) for r in gr if r['benchmark'] == 'bc']
        + [(f"deepseek/{r['harness']}/{r['method']}", r) for r in br])
    paired_mm = cross([(f"gemini/hermes/{r['method']}", r) for r in gr if r['benchmark'] == 'mmbrowsecomp']
        + [(f"deepseek/hermes/{r['method']}", r) for r in mr])
    report = {'at': datetime.now(timezone.utc).isoformat(), 'model_calls': 0,
        'own_configuration_subsets': {'gemini_bc': g['scopes']['bc'],
            'deepseek_bc_hermes': b['scopes']['hermes'], 'deepseek_bc_dsh': b['scopes']['dsh'],
            'gemini_mmbc': g['scopes']['mmbrowsecomp'], 'deepseek_mmbc': mm['summary']},
        'cross_configuration_subsets': {'bc_all15': paired_bc, 'mmbc_all11': paired_mm,
            'deepseek_bc_all10': b['scopes']['cross_harness_all10']},
        'deepseek_bc_status': b['status_by_method'], 'deepseek_mmbc_status': mm['selected_status_counts'],
        'gemini_status': {k: {m: v['statuses'] for m, v in s['methods'].items()} for k, s in g['scopes'].items()},
        'limitations': ['Completion, not answer correctness, determines membership.',
            'A successful-completion subset is conditional and cannot replace full-cohort accuracy.',
            'Historical Gemini protocols and recovery engineering versions differ; question matching is not experimental control.',
            'Gemini is an archived gateway alias, not independently provider-attested. No Gemini DSH campaign exists.',
            'Missing historical records are unknown, not timeouts or failures. Gemini MMBC only has repeat1.',
            'Counts use one current state per slot, not cumulative HTTP errors or all retry attempts.'],
        'source_sha256': SOURCES}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    lines = ['# 多模型 / 多 harness：全部方法正常完成子集', '', f"生成时间：{report['at']}", '',
        '已有配置为历史 Gemini + Hermes、新 DeepSeek + Hermes / DSH；没有 Gemini + DSH。DeepSeek 版本为 deepseek-v4.1-flash-1017；Gemini 归档别名为 gemini-3.5-flash-thinking。', '',
        '同一题目内容哈希和同一 repeat 匹配，全部方法正常完成并有有效绑定评分才纳入；答错的完成轨迹保留。恢复只替换执行失败，不使用按答案筛选的 bounded 重跑。零模型调用。', '',
        '## 每个配置内部的共同子集', '',
        '每行使用自己的全方法交集，不能跨行直接当作同题比较。N为题次，不是独立题数；不是完整100×3准确率。', '',
        '| 模态 / 数据集 | 模型 / harness | 共同题次 | 独立题 | '+' | '.join(NAMES)+' |',
        '|---|---|---:|---:|'+'---:|'*6]
    own = [('文本 BC','Gemini / Hermes',g['scopes']['bc']),
           ('文本 BC','DeepSeek / Hermes',b['scopes']['hermes']),
           ('文本 BC','DeepSeek / DSH',b['scopes']['dsh']),
           ('多模态 MMBC','Gemini / Hermes',g['scopes']['mmbrowsecomp']),
           ('多模态 MMBC','DeepSeek / Hermes',mm['summary'])]
    for modality, label, s in own:
        n=s.get('unique_questions',s.get('independent_questions'))
        lines.append('| '+' | '.join([modality,label,str(s['slots']),str(n)]+[cell(s['methods'].get(m)) for m in METHODS])+' |')
    for label, stats, prefixes in [('BC：三配置15种组合均完成',paired_bc,('gemini/hermes','deepseek/hermes','deepseek/dsh')),
                                    ('MMBC：两模型11种组合均完成',paired_mm,('gemini/hermes','deepseek/hermes'))]:
        lines += ['', '## '+label, '', f"共同{stats['slots']}题次、{stats['unique_questions']}道题。同题匹配仍不能消除历史协议、工具和时间差异。", '',
            '| 配置 | '+' | '.join(NAMES)+' |', '|---|'+'---:|'*6]
        for prefix in prefixes:
            lines.append('| '+prefix+' | '+' | '.join(cell(stats['methods'].get(prefix+'/'+m)) for m in METHODS)+' |')
    lines += ['', '## 各方法全范围超时 / 其他失败', '',
        '单元格为超时数 / 其他终态失败数；每槽保留任意已完成结果，否则按最新恢复状态计一次。不是本轮V7-only统计，也不是累计attempt数。BC与DeepSeek MMBC每方法300题次；Gemini MMBC仅100题×repeat1。', '',
        '| 数据集 / 配置 | '+' | '.join(NAMES)+' |', '|---|'+'---:|'*6]
    coverage=[]
    for label, scope in [('BC Gemini/Hermes','bc'),('MMBC Gemini/Hermes','mmbrowsecomp')]:
        counts=report['gemini_status'][scope];coverage.append((label,counts))
    for h in ('hermes','dsh'):
        coverage.append(('BC DeepSeek/'+h,{m:b['status_by_method'][h+'/'+m] for m in METHODS[:-1]}))
    coverage.append(('MMBC DeepSeek/Hermes',mm['selected_status_counts']))
    for label, counts in coverage:
        lines.append('| '+label+' | '+' | '.join(f"{counts[m].get('timeout',0)}/{counts[m].get('failed',0)}" if m in counts else '—' for m in METHODS)+' |')
    lines += ['', 'BC Gemini 无记录数（None/Discard/Summary/Window/VERA）：'+
        '/'.join(str(report['gemini_status']['bc'][m].get('missing_archive_record',0)) for m in METHODS[:-1])+ '；这些缺失不算作失败。', '',
        '所有方法的completed、运行/待跑、清理未确认和缺评分计数见对应JSON报告；运行中的恢复不重复算作旧失败。', '',
        '## 严格同题三repeat统计', '',
        '| 配置 | 完整三repeat题数 | '+' | '.join(NAMES)+' |', '|---|---:|'+'---:|'*6]
    for modality,label,s in own:
        cells=[]; n=0
        for m in METHODS:
            x=s['methods'].get(m)
            if not x:cells.append('—');continue
            st=x.get('balanced_avg3',x.get('strict_three_repeat',{}));n=st.get('questions',0)
            mean=st.get('mean',st.get('avg3'));sd=st.get('sample_std_ddof1',st.get('sample_std_across_repeats'))
            cells.append(f'{100*mean:.2f} ± {100*sd:.2f}' if mean is not None else 'NA')
        lines.append('| '+modality+' '+label+' | '+str(n)+' | '+' | '.join(cells)+' |')
    lines += ['', '标准差为三次repeat准确率的样本标准差。MMBC DeepSeek完整三repeat只有2题，Gemini只有repeat1，不能用小样本100±0论证稳定性。', '',
        '解释：DeepSeek Hermes的BC VERA在自身共同子集领先；DSH上与其他压缩基线持平。MMBC VERA仅比vanilla多答对1题次，与None和Summary持平，目前不支持优于所有方法。', '',
        '## 可复核来源', '', '- `outputs/analysis/multimodel-success-subsets-v1/report.json`',
        '- `outputs/analysis/bc-completion-intersection-v3-snapshot/`',
        '- `outputs/analysis/mmbc-sixmethod-completed-intersection-v3/`',
        '- `outputs/analysis/gemini-matched-completion-v1/`', '',
        '各分析保留原始结果/评分/plan的SHA和subset成员，不修改、删除或重跑预测。']
    DOC.write_text('\n'.join(lines)+'\n')
    print(json.dumps({'bc_all15':paired_bc['slots'],'mmbc_all11':paired_mm['slots'],'doc':str(DOC)}))


if __name__ == '__main__':
    main()
