#!/usr/bin/env python3
"""Offline, model-separated repeated-run and question-cluster inference. No API calls."""
import argparse
from collections import defaultdict, Counter
import csv
import json
from pathlib import Path
import statistics
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
METHODS = ['No Compression', 'Discard', 'Sliding Window', 'Summarize', 'VERA']


def interval(values, rng, draws=10000):
    """Resample independent question clusters, not repeated trajectories."""
    v = np.asarray(values, dtype=float)
    if not len(v): return [None, None]
    estimates = np.concatenate([v[rng.integers(0, len(v), (min(500, draws-i), len(v)))].mean(axis=1)
                                for i in range(0, draws, 500)])
    return np.quantile(estimates, [.025, .975]).tolist()


def paired_test(deltas, rng, draws=10000):
    """Two-sided question-cluster sign-flip randomization; Monte Carlo +1 correction."""
    d = np.asarray(deltas, dtype=float)
    if not len(d): return None
    observed = abs(d.mean())
    if not observed: return 1.0
    exceed = 0
    for i in range(0, draws, 500):
        signs = rng.choice([-1, 1], (min(500, draws-i), len(d)))
        exceed += np.count_nonzero(abs((signs*d).mean(axis=1)) >= observed - 1e-12)
    return float((exceed + 1)/(draws + 1))


def holm(values):
    order = sorted(range(len(values)), key=lambda i: values[i])
    out = [None]*len(values); previous = 0
    for rank, i in enumerate(order):
        previous = max(previous, min(1., values[i]*(len(values)-rank)))
        out[i] = previous
    return out


def index_rows(rows):
    indexed = {}; duplicates = []
    for r in rows:
        key = (r['method'], r['question_hash'], str(r['repeat']))
        if key in indexed:
            duplicates.append(key)
        else: indexed[key] = r
    # Ambiguous repeated exports must not silently count as independent repeats.
    for key in duplicates: indexed.pop(key, None)
    return indexed, duplicates


def analyze(rows, draws=10000, seed=20261107):
    rng = np.random.default_rng(seed)
    groups = defaultdict(list)
    for r in rows:
        if r['canonical'] and r['method'] in METHODS:
            groups[(r['model'], r.get('harness', 'hermes'), r['benchmark'])].append(r)
    summaries, pairs, coverage, gaps, duplicate_audit = [], [], [], [], []
    for (model, harness, benchmark), rs in sorted(groups.items()):
        ix, duplicates = index_rows(rs)
        duplicate_audit.extend(dict(model=model,harness=harness, benchmark=benchmark, key=k) for k in duplicates)
        methods = [m for m in METHODS if any(k[0] == m for k in ix)]
        questions = sorted({k[1] for k in ix})
        repeats = sorted({k[2] for k in ix})
        scored = {k: float(r['score']) for k, r in ix.items() if r['score'] is not None}
        # Fixed common question cohort across ALL methods and ALL observed repeat labels.
        balanced = [q for q in questions if all((m, q, rep) in scored for m in methods for rep in repeats)]
        for m in methods:
            available = [k for k in ix if k[0] == m]
            full3 = sum(all((m,q,str(rep)) in scored for rep in range(1,4)) for q in questions)
            coverage.append(dict(model=model,harness=harness,benchmark=benchmark,method=m,questions_union=len(questions),
                observed_trajectories=sum(ix[k].get("observed", True) for k in available),scored_trajectories=sum(k in scored for k in available),
                observed_repeat_labels=','.join(repeats),questions_with_three_scored_repeats=full3))
            for q in questions:
                exemplar = next(r for k,r in ix.items() if k[1] == q)
                for rep in range(1,4):
                    k=(m,q,str(rep))
                    if k not in scored:
                        gaps.append(dict(model=model,harness=harness,benchmark=benchmark,method=m,question_hash=q,
                            question_id=exemplar['question_id'],repeat=rep,
                            action=('await_campaign_judging' if ix[k].get('campaign') else 'grade_existing_or_inspect') if k in ix else 'run_missing',
                            source_path=ix[k]['source_path'] if k in ix else exemplar['source_path'],
                            new_api_permitted=False if 'gemini' in model.lower() else None))
            rep_acc = [statistics.mean(scored[(m,q,rep)] for q in balanced) for rep in repeats] if balanced else []
            qmean = [statistics.mean(scored[(m,q,rep)] for rep in repeats) for q in balanced]
            lo,hi = interval(qmean,rng,draws)
            summaries.append(dict(model=model,harness=harness,benchmark=benchmark,method=m,balanced_questions=len(balanced),
                repeats=len(repeats),repeat_labels=','.join(repeats),mean_score=statistics.mean(rep_acc) if rep_acc else None,
                std_across_repeats=statistics.stdev(rep_acc) if len(rep_acc)>1 else None,
                bootstrap_low=lo,bootstrap_high=hi,repeat_means=rep_acc,avg3_satisfied=len(repeats)>=3 and bool(balanced)))
        if 'VERA' not in methods: continue
        for baseline in methods:
            if baseline == 'VERA': continue
            common = sorted({(q,rep) for m,q,rep in scored if m=='VERA'} &
                            {(q,rep) for m,q,rep in scored if m==baseline})
            clusters = defaultdict(list)
            for q,rep in common: clusters[q].append(scored[('VERA',q,rep)]-scored[(baseline,q,rep)])
            delta = [statistics.mean(v) for v in clusters.values()]
            lo,hi=interval(delta,rng,draws)
            if not delta: continue
            pairs.append(dict(model=model,harness=harness,benchmark=benchmark,baseline=baseline,paired_trajectories=len(common),
                question_clusters=len(delta),delta_vera_minus_baseline=statistics.mean(delta),bootstrap_low=lo,
                bootstrap_high=hi,p_raw=paired_test(delta,rng,draws)))
    for p,adj in zip(pairs,holm([p['p_raw'] for p in pairs])): p['p_holm_all_comparisons']=adj
    return dict(summary=summaries,paired_tests=pairs,coverage=coverage,avg3_gaps=gaps,duplicates_excluded=duplicate_audit,
                seed=seed,bootstrap_draws=draws)


def csvwrite(path, rows):
    with path.open('w') as f:
        if rows:
            w=csv.DictWriter(f,fieldnames=list(rows[0]),lineterminator="\n");w.writeheader();w.writerows(rows)


def fmt(x): return 'NA' if x is None else f'{100*x:.2f}'


def load_campaign(path):
    """Include every planned job, retaining ungraded/missing outcomes as None."""
    if not (path/'plan.json').exists(): return []
    plan=json.loads((path/'plan.json').read_text())
    methods={'none':'No Compression','discard':'Discard','sliding_window':'Sliding Window','summarize':'Summarize','visual':'VERA'}
    rows=[]
    for j in plan['jobs']:
        directory=path/'jobs'/j['job_id']
        grade=json.loads((directory/'judge.json').read_text()) if (directory/'judge.json').exists() else {}
        rows.append(dict(model=j['model'],harness=j['harness'],benchmark='bc100-new',method=methods[j['strategy']],
            canonical=True,question_hash=j['question_id'],question_id=j['question_id'],repeat=str(j['repeat']),
            score=grade.get('score') if grade.get('status')=='scored' else None,
            source_path=str(directory),status='planned_or_running',campaign=True,
            observed=any(directory.glob('attempts/*/result.json'))))
    return rows


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--input',type=Path,default=ROOT/'outputs/experiment1/reconstructed.jsonl')
    ap.add_argument('--output',type=Path,default=ROOT/'outputs/experiment4')
    ap.add_argument('--docs',type=Path,default=ROOT/'docs/experiment4')
    ap.add_argument('--campaign', type=Path, default=ROOT/'outputs/campaigns/bc100-r3-all-strategies')
    ap.add_argument('--draws',type=int,default=10000)
    args=ap.parse_args(); rows=[json.loads(s) for s in args.input.read_text().splitlines() if s.strip()]
    campaign_rows=load_campaign(args.campaign)
    rows.extend(campaign_rows)
    result=analyze(rows,args.draws)
    for out in (args.output,args.docs):
        out.mkdir(parents=True,exist_ok=True)
        for key in ['summary','paired_tests','coverage']: csvwrite(out/f'{key}.csv',result[key])
    (args.output/'analysis.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    (args.output/'avg3-gaps.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in result['avg3_gaps']))
    # Separate scale campaigns are exploratory; not claimed to reproduce paper Table 5.
    scales=defaultdict(list)
    for r in rows:
        if r['method'].startswith('scale'): scales[(r['model'],r['benchmark'],r['method'],r['group'])].append(r)
    scale_stats=[]
    for (model,bench,scale,group),rs in sorted(scales.items()):
        scored=[r for r in rs if r['score'] is not None]; qs=defaultdict(list)
        for r in scored: qs[r['question_hash']].append(float(r['score']))
        vals=[statistics.mean(v) for v in qs.values()]
        lo,hi=interval(vals,np.random.default_rng(20261107),args.draws)
        scale_stats.append(dict(model=model,benchmark=bench,scale=scale,group=group,observed=len(rs),scored=len(scored),
            scored_questions=len(vals),question_weighted_score=statistics.mean(vals) if vals else None,
            bootstrap_low=lo,bootstrap_high=hi,table5_mapping='unverified',missing_scores=len(rs)-len(scored)))
    csvwrite(args.output/'rq3-exploratory.csv',scale_stats); csvwrite(args.docs/'rq3-exploratory.csv',scale_stats)
    lines=['# 实验 4：历史日志的重复方差与配对统计', '',
      '按用户最新决定，采用 avg@3，不追加第四 repeat。本报告离线重建，无新增模型调用。模型、benchmark 分开统计；历史 Gemini 不能与新 DeepSeek 混成 avg@3。论文源码/表格映射尚未核实，以下为归档 canonical 实验，不能直接宣称完整复现 Table 1/2/5。', '',
      'mean ± std：在所有方法、所有已观察 repeat 标签均有评分的相同题集上，先算各 repeat 的平均得分，再算均值及样本标准差。单 repeat 的 std 为 NA。repeat 标签不等于已验证的随机 seed。缺失评分不当作 0；完整案例分析可能存在选择偏差。', '',
      f'95% CI：以题为 cluster 重采样 {args.draws} 次，保留同一题的所有重复；覆盖题目抽样不确定性，不代表新增 seed 的不确定性。配对检验对同题同 repeat 求差，先按题平均，再进行双侧 sign-flip 随机化检验；跨本报告全部比较做 Holm 校正。p 不显著不能写“统计等价”，除非预先给定等价界值并做等价检验。', '',
      '| Model / Harness | Benchmark | Method | Balanced Q | Repeats | Mean ± std (%) | 95% CI (%) |','|---|---|---|---:|---:|---|---|']
    for r in result['summary']:
        lines.append(f"| {r['model']} / {r['harness']} | {r['benchmark']} | {r['method']} | {r['balanced_questions']} | {r['repeats']} | {fmt(r['mean_score'])} ± {fmt(r['std_across_repeats'])} | [{fmt(r['bootstrap_low'])}, {fmt(r['bootstrap_high'])}] |")
    lines += ['', '| Model / Harness | Benchmark | Baseline | Paired Q | Δ VERA (pp) | 95% CI (pp) | p (Holm) |','|---|---|---|---:|---:|---|---:|']
    for r in result['paired_tests']:
        lines.append(f"| {r['model']} / {r['harness']} | {r['benchmark']} | {r['baseline']} | {r['question_clusters']} | {fmt(r['delta_vera_minus_baseline'])} | [{fmt(r['bootstrap_low'])}, {fmt(r['bootstrap_high'])}] | {r['p_holm_all_comparisons']:.4g} |")
    counts=Counter(r['action'] for r in result['avg3_gaps'])
    lines += ['', f"avg@3 缺口：缺轨迹 {counts['run_missing']}，历史已有轨迹缺评分 {counts['grade_existing_or_inspect']}，新 campaign 待评分 {counts['await_campaign_judging']}；详细到题/方法/repeat 的清单在 outputs/experiment4/avg3-gaps.jsonl。禁止新 Gemini 的当前约束下，历史 Gemini 的缺口不能直接补跑。新 DeepSeek 三个 repeat 应作为独立模型实验统计。", '',
      '当前 BC 跨五方法、三个 repeat 的完整评分交集非常小（见 Balanced Q），选择偏差严重，不代表全体题目准确率。新 DeepSeek 在 judge.json 产生后自动按 harness 单独纳入；未评分时均为 NA。', '',
      'RQ3：发现 Qwen 分辨率 scale 归档，但评分覆盖很低，Table 5 对应关系未验证。rq3-exploratory.csv 仅给已评分子集的题级 bootstrap；不得据此宣称平滑衰减、画未评分的点或当作完整 Table 5。', '',
      '建议 Finding 3 改为：“在本实验配置及已观测样本中，我们观察到……趋势；其稳定性仍需更多独立重复验证。”文本任务应按 benchmark 报差异和 CI；当前不能统一写成“统计上持平，且成本更低”。成本方向必须引用独立的配对成本数据。', '',
      '复现：`python scripts/analyze_significance.py`。不调用 API。新增评分后重跑即可更新；缺口清单仅为审计，不会自动触发付费任务。']
    text='\n'.join(lines)+'\n'
    (args.output/'experiment4.md').write_text(text);(args.docs/'experiment4.md').write_text(text)
    plot(result['summary'],args.output,args.docs)
    plot_scales(scale_stats,args.output,args.docs)
    print(json.dumps(dict(groups=len(result['summary']),comparisons=len(result['paired_tests']),gap_counts=counts,scale_groups=len(scale_stats))))


def plot_scales(rows,out,docs):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,ax=plt.subplots(figsize=(9,5),layout='constrained')
    labels=[]
    for i,r in enumerate(rows):
        value=r['question_weighted_score']
        labels.append(f"{r['scale']}\nscored {r['scored']}/{r['observed']}")
        if value is not None:
            ax.errorbar(i,value*100,yerr=[[max(0,value-r['bootstrap_low'])*100],[max(0,r['bootstrap_high']-value)*100]],fmt='o',capsize=4)
    ax.set_xticks(range(len(rows)),labels)
    ax.set_ylabel('Scored-subset mean (%) / question-bootstrap 95% CI')
    ax.set_title('Exploratory Qwen scale archives; Table 5 mapping unverified')
    ax.grid(axis='y',alpha=.2)
    for d in (out,docs): fig.savefig(d/'rq3-exploratory-ci.png',dpi=150);fig.savefig(d/'rq3-exploratory-ci.pdf')
    plt.close(fig)


def plot(rows,out,docs):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    rs=[r for r in rows if r['mean_score'] is not None]
    fig,ax=plt.subplots(figsize=(10,max(4,len(rs)*.25)),layout='constrained')
    for i,r in enumerate(rs):
        m=r['mean_score']*100
        ax.errorbar(m,i,xerr=[[max(0,m-r['bootstrap_low']*100)],[max(0,r['bootstrap_high']*100-m)]],fmt='o',capsize=2)
    ax.set_yticks(range(len(rs)),[f"{r['model'][:10]} / {r['harness']} / {r['benchmark']} / {r['method']} (r={r['repeats']})" for r in rs],fontsize=8)
    ax.set_xlabel('Mean score (%) and question-cluster bootstrap 95% CI')
    ax.set_title('Matched complete cases; actual repeat coverage shown');ax.grid(axis='x',alpha=.2)
    for d in (out,docs): fig.savefig(d/'accuracy-ci.png',dpi=150);fig.savefig(d/'accuracy-ci.pdf')
    plt.close(fig)

if __name__=='__main__': main()
