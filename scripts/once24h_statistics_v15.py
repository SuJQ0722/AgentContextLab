"""Zero-model, fixed-cohort inference and explicitly hypothetical repricing."""
from collections import defaultdict, Counter
import hashlib
import json
from pathlib import Path
import statistics
import numpy as np

DRAWS=10000
SEED=20261113
TOKEN_KEYS=('cached_input','noncache_input','output','total')


def finite(value):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and np.isfinite(value) and value>=0


def bootstrap(values,rng,draws=DRAWS):
    values=np.asarray(values,dtype=float)
    if not len(values):return [None,None]
    sampled=np.concatenate([values[rng.integers(0,len(values),(min(500,draws-i),len(values)))].mean(axis=1) for i in range(0,draws,500)])
    return np.quantile(sampled,[.025,.975]).tolist()


def paired_p(deltas,rng,draws=DRAWS):
    values=np.asarray(deltas,dtype=float)
    if not len(values):return None
    observed=abs(values.mean())
    if observed==0:return 1.
    exceed=0
    for i in range(0,draws,500):
        signs=rng.choice([-1,1],(min(500,draws-i),len(values)))
        exceed+=np.count_nonzero(abs((signs*values).mean(axis=1))>=observed-1e-12)
    return float((exceed+1)/(draws+1))


def holm(values):
    result=[None]*len(values);previous=0
    order=sorted((i for i,p in enumerate(values) if p is not None),key=lambda i:values[i])
    for rank,i in enumerate(order):
        previous=max(previous,min(1.,values[i]*(len(order)-rank)));result[i]=previous
    return result


def strict_summary(index,method,questions,rng,draws):
    means=[statistics.mean(index[(method,q,rep)]['score'] for q in questions) for rep in (1,2,3)] if questions else []
    qmeans=[statistics.mean(index[(method,q,rep)]['score'] for rep in (1,2,3)) for q in questions]
    return {'questions':len(questions),'trajectories':3*len(questions),'repeat_labels':[1,2,3],
            'repeat_means':means,'mean':statistics.mean(means) if means else None,
            'sample_std':statistics.stdev(means) if means else None,'bootstrap95':bootstrap(qmeans,rng,draws),
            'full_100x3':len(questions)==100,'question_hashes':questions}


def reference_cost(tokens,price):
    if not all(finite(tokens.get(k)) for k in TOKEN_KEYS):return None
    if tokens['cached_input']+tokens['noncache_input']+tokens['output']!=tokens['total']:return None
    return (tokens['cached_input']*price['cached_input_per_million']+
            tokens['noncache_input']*price['non_cache_input_per_million']+
            tokens['output']*price['output_per_million'])/1e6


def pareto_front(points):
    return [i for i,p in enumerate(points) if not any(
        j!=i and other['reference_usd_mean']<=p['reference_usd_mean'] and other['accuracy']>=p['accuracy']
        and (other['reference_usd_mean']<p['reference_usd_mean'] or other['accuracy']>p['accuracy'])
        for j,other in enumerate(points))]


def observed_metric(metrics,key):
    values=[m[key] for m in metrics if finite(m.get(key))]
    return {'observed_trajectories':len(values),'missing_trajectories':len(metrics)-len(values),
            'mean_observed':statistics.mean(values) if values else None,
            'complete_cohort_mean':statistics.mean(values) if values and len(values)==len(metrics) else None}


def analyze(rows,metrics,price,draws=DRAWS):
    rng=np.random.default_rng(SEED);groups=defaultdict(list)
    for row in rows:groups[(row['benchmark'],row['harness'])].append(row)
    summaries=[];pairs=[];cost_groups=[];metric_groups=[]
    for (benchmark,harness),group in sorted(groups.items()):
        methods=sorted({r['method'] for r in group});question_union=sorted({r['question_sha256'] for r in group})
        scored={(r['method'],r['question_sha256'],r['repeat']):r for r in group
                if r['status']=='completed_scored' and r['score'] in (0,1)}
        common3=[q for q in question_union if all((method,q,rep) in scored for method in methods for rep in (1,2,3))]
        group_identity={'benchmark':benchmark,'harness':harness,'methods':methods}
        for method in methods:
            own3=[q for q in question_union if all((method,q,rep) in scored for rep in (1,2,3))]
            summaries.append({**group_identity,'method':method,
                              'all_methods_complete_three_repeats':strict_summary(scored,method,common3,rng,draws),
                              'method_only_complete_three_repeats':strict_summary(scored,method,own3,rng,draws)})
            mr=[metrics[r['slot_id']] for r in group if r['method']==method and r['slot_id'] in metrics]
            metric_groups.append({**group_identity,'method':method,'selected_successful_trajectories':len(mr),
                'fields':{key:observed_metric(mr,key) for key in ('compression_count','cache_token_hit_rate','cache_request_hit_rate','client_http_seconds','render_seconds','end_to_end_seconds')}})
        anchor='scale_1.0' if benchmark=='rq3' else 'visual'
        for baseline in methods:
            if baseline==anchor or anchor not in methods:continue
            # Each pair retains ALL three repeats of exactly the same question clusters.
            qs=[q for q in question_union if all((method,q,rep) in scored for method in (anchor,baseline) for rep in (1,2,3))]
            deltas=[statistics.mean(scored[(anchor,q,r)]['score']-scored[(baseline,q,r)]['score'] for r in (1,2,3)) for q in qs]
            pairs.append({**group_identity,'anchor':anchor,'baseline':baseline,'question_hashes':qs,'question_clusters':len(qs),
                          'paired_trajectories':3*len(qs),'delta':statistics.mean(deltas) if deltas else None,
                          'bootstrap95':bootstrap(deltas,rng,draws),'p_raw':paired_p(deltas,rng,draws),
                          'scope':'pair-specific complete-three-repeat cohort; do not compare different pairs as one common cohort'})
        # Every plotted method shares precisely these (question, repeat) slots for BOTH axes.
        common_cost=[]
        for q in question_union:
            for rep in (1,2,3):
                if all((method,q,rep) in scored and metrics.get(scored[(method,q,rep)]['slot_id'],{}).get('tokens_complete')
                       and reference_cost(metrics[scored[(method,q,rep)]['slot_id']]['complete_tokens'],price) is not None
                       for method in methods):common_cost.append((q,rep))
        points=[]
        for method in methods:
            rr=[scored[(method,q,rep)] for q,rep in common_cost];mm=[metrics[r['slot_id']] for r in rr]
            if not rr:continue
            token_means={key:statistics.mean(m['complete_tokens'][key] for m in mm) for key in TOKEN_KEYS}
            prompt_sum=sum(m['complete_tokens']['cached_input']+m['complete_tokens']['noncache_input'] for m in mm)
            points.append({'method':method,'n':len(rr),'question_count':len({q for q,r in common_cost}),
                           'repeat_denominators':dict(Counter(r for q,r in common_cost)),
                           'accuracy':statistics.mean(r['score'] for r in rr),
                           'reference_usd_mean':statistics.mean(reference_cost(m['complete_tokens'],price) for m in mm),
                           'mean_tokens':token_means,'token_weighted_cache_hit_rate':sum(m['complete_tokens']['cached_input'] for m in mm)/prompt_sum if prompt_sum else None,
                           'client_http_seconds':observed_metric(mm,'client_http_seconds'),
                           'render_seconds':observed_metric(mm,'render_seconds'),
                           'end_to_end_seconds':observed_metric(mm,'end_to_end_seconds'),
                           'compression_count':observed_metric(mm,'compression_count'),
                           'slot_ids':[r['slot_id'] for r in rr]})
        cost_groups.append({**group_identity,'common_question_repeat_pairs':[[q,r] for q,r in common_cost],
                            'common_n':len(common_cost),'available':bool(common_cost),'points':points,
                            'pareto_front_methods':[points[i]['method'] for i in pareto_front(points)],
                            'population':'All methods completed/scored with complete selected-successful-execution usage; conditional complete cases, not full-cohort avg3 or total experiment expenditure.'})
    adjusted=holm([p['p_raw'] for p in pairs])
    for pair,p in zip(pairs,adjusted):pair['p_holm']=p
    return {'version':'once24h-offline-statistics-v1','model_calls':0,'bootstrap_draws':draws,'random_seed':SEED,
            'strict_three_repeat_summaries':summaries,'paired_tests':pairs,'selected_execution_metrics':metric_groups,
            'paired_cost_groups':cost_groups,'archived_reference_price':price,
            'inference_notes':['Cluster bootstrap resamples questions, retaining their three repeats; sample std is across three repeat accuracies.',
            'Holm correction covers every non-empty anchor-versus-baseline comparison across both BC harnesses, MMBC and RQ3 in this snapshot.',
            'Pairwise tests use pair-specific complete-three-repeat cohorts; primary all-method means use a separate single common three-repeat cohort.',
            'Complete-case selection can be biased. Non-significance does not demonstrate equivalence. Intermediate p values are descriptive monitoring, not sequential stopping evidence.',
            'Gemini archived prices are reference repricing only; not current verified Gemini prices, DeepSeek invoice, or TokenHub actual spend.',
            'Pareto costs and accuracy always share the same all-method question-repeat cohort. Historical and new accepted protocols are mixed for BC/MMBC; RQ3 remains V10+ only.',
            'Selected-successful-native-execution metrics exclude preceding failed retries. Historical/all-attempt expense is retained separately, not reset or claimed included.',
            'Observed-only latency/compression/cache means disclose coverage; missing records are not zeros. Client HTTP is not provider-internal inference latency.']}


def fmt(value,scale=1):return 'NA' if value is None else f'{value*scale:.3f}'


def markdown(value):
    lines=['## 完整三次与配对统计','',
           '以下主表使用每个benchmark/harness的**所有方法、同题、三个repeat均完成且已评分**交集。N不足100时是条件完整案例，不是全量100×3。CI按题簇bootstrap；不显著不能解释为等价。','',
           '|Benchmark|Harness|方法|共同题数|mean ± sample std (%)|题簇95%CI (%)|',
           '|---|---|---|---:|---:|---|']
    for r in value['strict_three_repeat_summaries']:
        s=r['all_methods_complete_three_repeats'];lo,hi=s['bootstrap95']
        lines.append(f"|{r['benchmark']}|{r['harness']}|{r['method']}|{s['questions']}|{fmt(s['mean'],100)} ± {fmt(s['sample_std'],100)}|[{fmt(lo,100)}, {fmt(hi,100)}]|")
    lines+=['','配对检验每一对都保留同题全部3次，但不同配对可能有不同题集；不能将其拼成单一方法排名。Holm跨下表全部有效比较校正。中间快照仅供监测，不能用反复查看p值决定停止。','',
            '|Benchmark/Harness|对比|配对题簇|Δ(pp)|95%CI(pp)|p(Holm)|','|---|---|---:|---:|---|---:|']
    for r in value['paired_tests']:
        lo,hi=r['bootstrap95'];lines.append(f"|{r['benchmark']}/{r['harness']}|{r['anchor']} − {r['baseline']}|{r['question_clusters']}|{fmt(r['delta'],100)}|[{fmt(lo,100)}, {fmt(hi,100)}]|{('NA' if r['p_holm'] is None else format(r['p_holm'],'.4g'))}|")
    lines+=['','## 同题成本、缓存与延迟','',
            '仅使用所有方法同时完成、已评分且成功native轨迹usage完整的相同题次，同时计算两个坐标。参考价沿用归档：cached $0.15/M、non-cache $1.50/M、output $9/M；不是实际DeepSeek账单，未重核今日价格。早期失败重试费用保存在原账本，不混入以下成功轨迹效率指标。BC/MMBC接受历史协议混合，结果仅作条件比较。','',
            '|Benchmark/Harness|方法|共同N|cached|non-cache|output|total|参考$/题次|Acc%|token cache%|API客户端秒|render秒|E2E秒|压缩次数|',
            '|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---|---|']
    def cov(m):return f"{fmt(m['mean_observed'])} ({m['observed_trajectories']}/{m['observed_trajectories']+m['missing_trajectories']})"
    for group in value['paired_cost_groups']:
        if not group['available']:lines.append(f"|{group['benchmark']}/{group['harness']}|全部方法|0|NA|NA|NA|NA|NA|NA|NA|NA|NA|NA|NA|");continue
        for p in group['points']:
            t=p['mean_tokens'];lines.append(f"|{group['benchmark']}/{group['harness']}|{p['method']}|{p['n']}|"+'|'.join(fmt(t[k]) for k in TOKEN_KEYS)+f"|{fmt(p['reference_usd_mean'])}|{fmt(p['accuracy'],100)}|{fmt(p['token_weighted_cache_hit_rate'],100)}|{cov(p['client_http_seconds'])}|{cov(p['render_seconds'])}|{cov(p['end_to_end_seconds'])}|{cov(p['compression_count'])}|")
    lines+=['','API/render/E2E/压缩列括号为有可靠埋点的题次覆盖，缺失不补0；这些时间可能重叠，不可相加当作独立分解。请求cache hit仅在明确逐请求缓存字段存在时统计，详见JSON selected_execution_metrics。','',
            '![文本任务：同题参考价Pareto](pareto_text.png)','', '![多模态任务：同题参考价Pareto](pareto_multimodal.png)','',
            '图中每个面板使用其内部所有方法共同题次；不同面板不共用Pareto前沿。没有完整共同成本子集的面板明确显示不可用。','',
            '![RQ3完整三次共同题集置信区间](rq3_complete3_ci.png)','']
    return '\n'.join(lines)


def plots(value,output):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    colors={'none':'#666666','discard':'#0072B2','sliding_window':'#009E73','summarize':'#E69F00','visual':'#CC79A7','vanilla_visual':'#D55E00'}
    for benchmark,name in [('bc100','pareto_text'),('mmbc100','pareto_multimodal')]:
        groups=[g for g in value['paired_cost_groups'] if g['benchmark']==benchmark]
        fig,axes=plt.subplots(1,max(1,len(groups)),figsize=(7*max(1,len(groups)),5),squeeze=False,layout='constrained')
        for ax,g in zip(axes[0],groups):
            ax.set_title(f"{benchmark} / {g['harness']} — shared n={g['common_n']}")
            ax.set_xlabel('Archived Gemini-equivalent USD / successful trajectory')
            ax.set_ylabel('Accuracy on identical complete-cost cohort (%)')
            if not g['available']:ax.text(.5,.5,'Unavailable: no all-method complete-cost intersection',transform=ax.transAxes,ha='center',wrap=True);continue
            for p in g['points']:
                ax.scatter(p['reference_usd_mean'],p['accuracy']*100,s=65,label=p['method'],color=colors.get(p['method']))
            front=sorted((p for p in g['points'] if p['method'] in g['pareto_front_methods']),key=lambda p:p['reference_usd_mean'])
            ax.plot([p['reference_usd_mean'] for p in front],[p['accuracy']*100 for p in front],ls='--',alpha=.5)
            ax.legend(loc='best',fontsize=9,framealpha=.95)
            ax.grid(alpha=.2)
        fig.suptitle('Conditional complete cases; reference repricing, NOT actual DeepSeek spend',fontsize=11)
        for suffix in ('png','pdf'):fig.savefig(output/f'{name}.{suffix}',dpi=150)
        plt.close(fig)
    fig,ax=plt.subplots(figsize=(8,5),layout='constrained')
    scales=[r for r in value['strict_three_repeat_summaries'] if r['benchmark']=='rq3']
    available=False
    for r in scales:
        s=r['all_methods_complete_three_repeats']
        if s['mean'] is None:continue
        available=True;x=float(r['method'].split('_',1)[1]);lo,hi=s['bootstrap95'];mean=s['mean']
        ax.errorbar(x,mean*100,yerr=[[max(0,mean-lo)*100],[max(0,hi-mean)*100]],fmt='o',capsize=4)
    n=scales[0]['all_methods_complete_three_repeats']['questions'] if scales else 0
    if not available:
        ax.text(.5,.5,'Unavailable: no all-resolution complete-three-repeat question cohort',ha='center',transform=ax.transAxes,wrap=True)
        ax.set_axis_off()
    ax.set_title(f'RQ3 seven-page protocol: common questions={n}, three repeats')
    ax.set_xlabel('Resolution scale');ax.set_ylabel('Accuracy (%) / question-cluster bootstrap 95% CI');ax.grid(alpha=.2)
    for suffix in ('png','pdf'):fig.savefig(output/f'rq3_complete3_ci.{suffix}',dpi=150)
    plt.close(fig)
