#!/usr/bin/env python3
"""Reconstruct cost/cache/latency analysis from archived runs without inference."""
import argparse
import collections
from concurrent.futures import ThreadPoolExecutor
import csv
import hashlib
import json
from pathlib import Path
import re
import statistics

ROOT = Path(__file__).resolve().parents[1]
METHODS = ['No Compression', 'Discard', 'Sliding Window', 'Summarize', 'VERA']


def number(value):
    return float(value) if value not in (None, '') else None


def mean(values):
    present = [v for v in values if v is not None]
    return statistics.mean(present) if present else None


def labels(group):
    relative = group.split('preds_archive/', 1)[-1]
    parts = relative.split('/')
    benchmark = parts[1] if parts[0] == 'to_upload' else parts[0]
    if benchmark.startswith(('gemini35_', 'qwen35-')):
        benchmark = 'bc'
    text = relative.lower()
    if 'scale' in text: method = re.search(r'scale\w+', text)[0]
    elif 'vis_text' in text or 'vis-text' in text: method = 'VERA text-only'
    elif 'no_cc' in text: method = 'No Compression'
    elif 'discard' in text: method = 'Discard'
    elif '_summarize' in text or text.endswith('-sm'): method = 'Summarize'
    elif '_sw' in text or text.endswith('-sw'): method = 'Sliding Window'
    elif '_vis' in text or text.endswith('-vis'): method = 'VERA'
    else: method = 'unclassified'
    # Keep updated/debug/ablation campaigns in the complete table but do not
    # mix them into the selected publication-style paired comparisons.
    canonical = 'debug' not in text and method in METHODS
    if benchmark == 'bc':
        canonical = canonical and ('gemini35_flash_' in text)
    return benchmark, method, canonical


def extract(source_row, pricing):
    row = dict(source_row)
    path, group = Path(row['path']), Path(row['group'])
    data = json.loads(path.read_text())
    history_path = group / 'history' / path.relative_to(group/'conv')
    history = json.loads(history_path.read_text()) if history_path.exists() else {}
    matched = bool(history and history.get('session_id') == row['session_id'])
    if not matched: history = {}
    benchmark, method, canonical = labels(row['group'])
    question_hash = hashlib.sha256(str(data.get('question', '')).encode()).hexdigest()
    cached, uncached, writes, output = [number(row.get(k)) for k in
                                      ('cached_input','uncached_input','cache_write_input','output')]
    complete_usage = all(v is not None for v in [cached, uncached, writes, output])
    total_input = cached + uncached + writes if complete_usage else None
    total_tokens = total_input + output if complete_usage else None
    cost = None
    if data.get('model') == pricing['recorded_model_alias'] and complete_usage and writes == 0:
        cost = (cached*pricing['cached_input_per_million'] + uncached*pricing['non_cache_input_per_million']
                + output*pricing['output_per_million']) / 1e6
    expected = (history.get('token_usage') or data.get('token_usage') or {}).get('api_call_count')
    calls = {}
    for line in history.get('agent_log_tail','').splitlines():
        m = re.search(r'\[([^\]]+)\].*API call #(\d+):.*?latency=([\d.]+)s', line)
        if m: calls[(m[1], int(m[2]))] = float(m[3])
    # Tail fragments are lower bounds, never mislabeled as total API time.
    full_calls = bool(expected and len(calls) == expected and len({sid for sid,_ in calls}) == 1
                      and {i for _,i in calls} == set(range(1,expected+1)))
    api_sum = sum(calls.values()) if calls else None
    stats = data.get('compression_stats') or history.get('compression_stats') or {}
    per = stats.get('per_compression') or []
    indices = {int(v['index']) for v in per if v.get('index') is not None}
    trace = group / 'compress_trace' / path.relative_to(group/'conv').with_suffix('')
    if trace.exists():
        for f in trace.glob('compress_*_summary.json'):
            match = re.match(r'compress_(\d+)_summary.json',f.name)
            if match: indices.add(int(match[1]))
    recorded = max(data.get('compression_count') or 0, stats.get('compressions') or 0)
    count = max(recorded, max(indices, default=0))
    count_quality = 'recorded_visual_stats' if per and recorded == len(per) else 'trace_lower_bound' if indices else 'positive_export' if count else 'unknown_zero_export'
    if method == 'No Compression': count, count_quality = 0, 'disabled_by_method'
    elif count == 0: count = None
    return dict(group=row['group'], benchmark=benchmark, method=method, canonical=canonical,
        modality='multimodal' if benchmark in ('bc_v3','bc_v3_debug','mmbrowsecomp') else 'text',
        model=data.get('model'), session_id=row['session_id'], question_id=row['question_id'],
        question_hash=question_hash, repeat=row['repeat'], status=row['status'], score=number(row['score']),
        cached_input=cached, non_cache_input=uncached, cache_write_input=writes, output=output,
        total_input=total_input,total_tokens=total_tokens,cache_hit_rate=cached/total_input if total_input else None,
        official_token_usd_estimate=cost,tokenhub_billed_usd=None,
        end_to_end_seconds=history.get('wall_seconds'),
        session_span_seconds=number(row.get('session_span_seconds', row.get('end_to_end_seconds'))),
        api_seconds=api_sum if full_calls else None,api_observed_tail_seconds=api_sum,
        api_observed_calls=len(calls),api_expected_calls=expected,api_timing_complete=full_calls,
        render_seconds=None,compression_count=count,compression_count_quality=count_quality,
        recorded_compression_count=data.get('compression_count'),history_matched=matched,
        retry_attempts=len(history.get('retry_attempts') or []),source_path=str(path),history_path=str(history_path))


def write_csv(path, rows):
    with path.open('w') as f:
        if rows:
            w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)


def databench_records(template):
    """Preserve absent billed-token instrumentation in the separate data benchmark."""
    base=ROOT.parent/'databench/sources/AgenticDataBench'
    strategies={'none':'No Compression','discard':'Discard','sw':'Sliding Window','sm':'Summarize',
                'vis':'VERA','vis-text-only':'VERA text-only','vis-v2':'VERA failed-render variant'}
    result=[]
    for parent in ['output','output_archive_20260810_070633','output_archive_failed_render_20260810_152529']:
        for run in sorted((base/parent).glob('hermes-*')):
            match=re.match(r'hermes-(.+)-(none|discard|sw|sm|vis-text-only|vis-v2|vis)-[0-9a-f]+$',run.name)
            if not match:continue
            model, strategy=match.groups()
            reports=sorted((run/'reports').glob('*_evaluation.json'))
            if model=='minimax-m3' and strategy=='sw' and parent=='output':
                completed=sorted((base/'compressed_intersection_trajectories/sw_completed_evaluation').glob('*_evaluation.json'))
                if len(completed)==1:reports=completed
            scores={}
            if len(reports)==1:
                scores={r['id']:r.get('total_score') for r in json.loads(reports[0].read_text()).get('results',[])}
            for path in sorted(run.glob('*/dabench/result.json')):
                data=json.loads(path.read_text());qid=path.parent.parent.name
                count=max(data.get('compression_count') or 0,(data.get('compression_stats') or {}).get('compressions') or 0,
                          (data.get('result') or '').count('compacting context'))
                quality='stdout_marker_lower_bound' if count else 'disabled_by_method' if strategy=='none' else 'unknown_zero_export'
                row={k:None for k in template}
                row.update(group=str(run),benchmark='AgenticDataBench',method=strategies[strategy],canonical=False,
                    modality='multimodal',model=model,session_id=data.get('session_id'),question_id=qid,
                    question_hash=hashlib.sha256(json.dumps(data.get('task',qid),sort_keys=True).encode()).hexdigest(),repeat='1',
                    status='success' if data.get('finished') else 'failed',score=scores.get(qid),
                    end_to_end_seconds=data.get('wall_seconds'),compression_count=count if count or strategy=='none' else None,
                    compression_count_quality=quality,recorded_compression_count=data.get('compression_count'),
                    source_path=str(path),history_path=None,history_matched=False,api_timing_complete=False,api_observed_calls=0)
                result.append(row)
    return result


def summarize(rows, label):
    qs=collections.defaultdict(list)
    for row in rows: qs[row['question_hash']].append(row)
    scored=[r for r in rows if r['score'] is not None]
    total_input=sum(r['total_input'] or 0 for r in rows)
    result=dict(group=label,benchmark=rows[0]['benchmark'],method=rows[0]['method'],model=rows[0]['model'],
        modality=rows[0]['modality'],canonical=rows[0]['canonical'],trajectories=len(rows),questions=len(qs),
        scored_trajectories=len(scored),score_coverage=len(scored)/len(rows),
        mean_score=mean([r['score'] for r in rows]),
        acc_scored=mean([float(r['score']==1) for r in scored]),
        acc_lower_bound=sum(r['score']==1 for r in scored)/len(rows),
        acc_upper_bound=(sum(r['score']==1 for r in scored)+len(rows)-len(scored))/len(rows),
        acc_question_weighted=mean([mean([r['score'] for r in v]) for v in qs.values()]),
        cache_hit_rate=sum(r['cached_input'] or 0 for r in rows)/total_input if total_input else None)
    for key in ('cached_input','non_cache_input','cache_write_input','output','total_tokens',
                'official_token_usd_estimate','end_to_end_seconds','session_span_seconds','api_seconds','render_seconds','compression_count'):
        result[key+'_mean']=mean([r[key] for r in rows])
        result[key+'_available']=sum(r[key] is not None for r in rows)
    result['usd_per_question_mean']=mean([mean([r['official_token_usd_estimate'] for r in v]) for v in qs.values()])
    result['tokenhub_billed_usd']=None
    return result


def paired_tables(rows):
    by_bench=collections.defaultdict(lambda:collections.defaultdict(dict))
    duplicates=[]
    for row in rows:
        if not row['canonical'] or row['official_token_usd_estimate'] is None or row['score'] is None: continue
        key=(row['question_hash'],row['repeat'])
        mapping=by_bench[row['benchmark']][row['method']]
        if key in mapping:
            duplicates.append((row['benchmark'],row['method'],key));continue
        mapping[key]=row
    result=[]
    membership=[]
    for benchmark, methods in by_bench.items():
        if len(methods)<2:continue
        common=set.intersection(*(set(v) for v in methods.values()))
        if not common:continue
        for method, mapping in methods.items():
            selected=[mapping[k] for k in sorted(common)]
            result.append(summarize(selected,benchmark+' paired-scored'))
            membership.extend({'benchmark':benchmark,'method':method,'session_id':r['session_id'],
                'question_hash':r['question_hash'],'repeat':r['repeat']} for r in selected)
    return result,membership,duplicates


def plot_pareto(rows, out, modality):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    selected=[r for r in rows if r['modality']==modality]
    benches=sorted({r['benchmark'] for r in selected})
    if not benches:return
    cols=min(3,len(benches)); nrows=(len(benches)+cols-1)//cols
    fig,axes=plt.subplots(nrows,cols,figsize=(5*cols,4*nrows),squeeze=False,layout='constrained')
    colors={m:plt.get_cmap('tab10')(i) for i,m in enumerate(METHODS)}
    for ax,benchmark in zip(axes.flat,benches):
        data=[r for r in selected if r['benchmark']==benchmark]
        points=[(r['official_token_usd_estimate_mean'],100*r['acc_scored'],r['method']) for r in data]
        frontier=sorted((x,y) for x,y,_ in points if not any(a<=x and b>=y and (a<x or b>y) for a,b,_ in points))
        if len(frontier)>1:ax.plot(*zip(*frontier),'--',color='0.55',zorder=1)
        for x,y,m in points:ax.scatter(x,y,s=65,color=colors.get(m,'black'),label=m,zorder=2)
        ax.set_title(f"{benchmark} (paired scored n={data[0]['trajectories']})")
        ax.set_xlabel('Estimated official token cost / trajectory (USD)')
        ax.set_ylabel('Accuracy on matched scored subset (%)');ax.grid(alpha=.2)
        ax.legend(fontsize=8)
    for ax in list(axes.flat)[len(benches):]:ax.set_visible(False)
    fig.suptitle('Historical Gemini 3.5 Flash — standardized repricing, not actual bills',fontsize=12)
    fig.savefig(out/f'pareto_{modality}.png',dpi=180);fig.savefig(out/f'pareto_{modality}.pdf');plt.close(fig)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--audit',type=Path,default=ROOT/'outputs/audit/archive/records.csv')
    p.add_argument('--output',type=Path,default=ROOT/'outputs/experiment1')
    p.add_argument('--reuse',action='store_true')
    args=p.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    pricing=json.loads((ROOT/'configs/gemini-pricing-2026-11-07.json').read_text())
    cache=args.output/'reconstructed.jsonl'
    if args.reuse:rows=[json.loads(x) for x in cache.read_text().splitlines()]
    else:
        with args.audit.open() as f:sources=list(csv.DictReader(f))
        rows=[]
        with cache.open('w') as f,ThreadPoolExecutor(max_workers=4) as pool:
            for i,r in enumerate(pool.map(lambda x:extract(x,pricing),sources),1):
                rows.append(r);f.write(json.dumps(r)+'\n')
                if i%1000==0:print(json.dumps({'reconstructed':i,'total':len(sources)}),flush=True)
    rows.extend(databench_records(rows[0]))
    write_csv(args.output/'per_trajectory.csv',rows)
    groups=collections.defaultdict(list)
    for r in rows:groups[r['group']].append(r)
    table=[summarize(v,k) for k,v in groups.items()]
    write_csv(args.output/'method_benchmark_table.csv',table)
    paired,membership,duplicates=paired_tables(rows)
    write_csv(args.output/'paired_scored_table.csv',paired);write_csv(args.output/'paired_membership.csv',membership)
    report=dict(trajectories=len(rows),groups=len(groups),priced=sum(r['official_token_usd_estimate'] is not None for r in rows),
        wall_clock_recovered=sum(r['end_to_end_seconds'] is not None for r in rows),
        complete_api_times=sum(r['api_timing_complete'] for r in rows),
        partial_api_times=sum(r['api_observed_tail_seconds'] is not None and not r['api_timing_complete'] for r in rows),
        compression_counts_with_evidence=sum(r['compression_count'] is not None for r in rows),
        compression_count_quality=dict(collections.Counter(r['compression_count_quality'] for r in rows)),
        duplicate_paired_keys=duplicates,pricing=pricing,
        limitations=['Scored-only paired figures condition on available judge labels; inspect coverage and full-table accuracy bounds.',
        'Canonical cohorts selected by archive naming, not outcomes; debug/updated/ablation campaigns remain separate in full table.',
        'API tail sums are incomplete unless all expected numbered calls are present; rounded client latency, not provider latency.',
        'session_span_seconds is not CLI wall_seconds. Render latency was not instrumented in the examined exports.',
        'Compression trace counts may be lower bounds. Unknown zero exports are not asserted to mean no compression.',
        'Official prices are a dated current Standard Global counterfactual; gateway bills and tool charges are unknown.',
        'No Gemini inference or judging requests were issued.'])
    (args.output/'audit.json').write_text(json.dumps(report,indent=2))
    plot_pareto(paired,args.output,'text');plot_pareto(paired,args.output,'multimodal')
    print(json.dumps({k:v for k,v in report.items() if k not in ('pricing','limitations','duplicate_paired_keys')}),flush=True)


if __name__=='__main__':main()
