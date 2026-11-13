"""Read-only V14/V15 scoring and cost report; never invokes a model."""
import argparse
import collections
import csv
import fcntl
import json
import time
from pathlib import Path
import info_loss_single_pass_v14 as base
from info_loss_report import summarize_usage
from lab import ROOT

DEFAULT = ROOT / 'outputs/experiment6/single-pass-inline-lossless-v15'


def matched_facts(rows, metric, methods):
    groups = collections.defaultdict(dict)
    for row in rows:
        if row['split'] != 'holdout': continue
        if metric == 'qa' and row.get('qa_answers') is None: continue
        if metric == 'recall' and (row.get('judgment') is None or row.get('judge_version') != 'fixed-output-span-support-v14'): continue
        for fact in row['facts']:
            value = base.phase.exact_score({fact['id']: row['qa_answers'][fact['id']]}, [fact]) if metric == 'qa' else int(row['judgment'][fact['id']]['supported'])
            groups[(row['case'], fact['id'])][row['method']] = value
    return {key: values for key, values in groups.items() if set(methods) <= set(values)}


def report(root):
    plan = base.read(root / 'plan.json'); rows = [base.read(p) for p in root.glob('conditions/*/*/result.json')]
    directory = root / 'analysis'; directory.mkdir(exist_ok=True)
    old = plan.get('prior_stage_ledger', {})
    old_rows = [base.bound_read(x['response']) for x in old.values() if x.get('response')]
    new_rows = [base.read(p) for p in root.glob('calls/*/*/*/response.json')]
    starts = list(root.glob('calls/*/*/*/started.json'))
    # Child launch with no HTTP start is operationally consumed, but not an
    # invented provider call. Keep launch/physical-start counts separate.
    launches = list(root.glob('calls/*/*/*/launch-started.json'))
    costs = {'old_v14': summarize_usage(old_rows, len(old)), 'new_v15': summarize_usage(new_rows, len(starts)),
             'new_child_launches': len(launches), 'child_launches_without_http_start': len(launches) - len(starts),
             'combined_physical_starts': len(old) + len(starts), 'combined_cap': plan.get('combined_v14_v15_call_cap'),
             'older_than_v14_costs_retained_in_original_ledgers': True}
    methods = list(base.phase.METHODS)
    matched = {metric: matched_facts(rows, metric, methods) for metric in ['qa', 'recall']}
    summary = []
    for method in methods:
        own = [r for r in rows if r['split'] == 'holdout' and r['method'] == method]
        qa = [r for r in own if r.get('qa_answers') is not None]; judged = [r for r in own if r.get('judgment') is not None]
        item = {'method': method, 'holdout_conditions': len(own), 'expected_conditions': 9,
            'qa_correct': sum(r['qa_exact_correct'] for r in qa), 'qa_valid_facts': sum(len(r['facts']) for r in qa),
            'recall_supported': sum(r['supported_facts'] for r in judged), 'recall_valid_facts': sum(len(r['facts']) for r in judged),
            'reconstruction_complete': sum(r['reconstruction_complete'] for r in own)}
        for metric, values in matched.items():
            item[metric + '_matched_correct'] = sum(v[method] for v in values.values())
            item[metric + '_matched_facts'] = len(values)
        summary.append(item)
    base.save(directory / 'report.json', {'at': time.time(), 'summary': summary, 'costs': costs,
        'matched_qa_case_facts': [list(k) for k in matched['qa']], 'matched_recall_case_facts': [list(k) for k in matched['recall']],
        'dev_excluded': True, 'partial_output_recall_is_not_completion': True, 'same_uniform_judge_only': True})
    with (directory / 'summary.csv').open('w') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(summary[0])); writer.writeheader(); writer.writerows(summary)
    lines = ['# Information loss: current single-pass observations', '',
        'Nine fixed holdout trajectories; q004 excluded. Available-fact denominators differ across methods. '
        'Semantic recall measures actual generated text, including incomplete length-limited output; it does not imply complete reconstruction.', '',
        '|Method|QA correct/valid facts|Supported/valid reconstruction facts|Complete reconstruction/observed conditions|',
        '|---|---:|---:|---:|']
    for row in summary:
        lines.append(f"|{row['method']}|{row['qa_correct']}/{row['qa_valid_facts']}|{row['recall_supported']}/{row['recall_valid_facts']}|{row['reconstruction_complete']}/{row['holdout_conditions']}|")
    lines += ['', f"Five-method common facts: QA {len(matched['qa'])}; uniform span-judge recall {len(matched['recall'])}. Missing denominators are NA, not 0%.", '',
        f"New-round physical starts: {costs['combined_physical_starts']}/{costs['combined_cap']}; old V14 and new V15 usage remain disjoint. Unknown usage is retained. Client elapsed time is not provider latency.", '',
        'Age curves are descriptive source-position associations, not causal temporal decay; facts within a trajectory are correlated.']
    (directory / 'report.md').write_text('\n'.join(lines) + '\n')
    if not rows: return
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    for axis, metric in zip(axes, ['qa', 'recall']):
        values = matched[metric]
        if values:
            scale_methods = [('canvas_0.5', .5), ('canvas_0.75', .75), ('canvas_1', 1.)]
            axis.plot([scale for _, scale in scale_methods], [sum(v[m] for v in values.values()) / len(values) for m, _ in scale_methods], marker='o', label='Canvas')
            for method, color, style in [('text_control', 'tab:orange', ':'), ('summary', 'tab:green', '--')]:
                axis.axhline(sum(v[method] for v in values.values()) / len(values), color=color, linestyle=style, label=method)
            axis.legend(fontsize=8)
        else: axis.text(.5, .5, 'No complete five-arm fact set yet', transform=axis.transAxes, ha='center')
        axis.set(xlabel='Linear canvas scale', ylabel='Exact QA' if metric == 'qa' else 'Generated-output fact support', ylim=(-.05, 1.05),
                 title=f'Matched holdout facts: n={len(values)}')
    fig.tight_layout(); fig.savefig(directory / 'matched-resolution.png', dpi=180); plt.close(fig)
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    age_rows = []
    for axis, metric in zip(axes, ['qa', 'recall']):
        for method in methods:
            by_age = collections.defaultdict(list)
            for row in rows:
                if row['split'] != 'holdout' or row['method'] != method: continue
                if metric == 'qa' and row.get('qa_answers') is None: continue
                if metric == 'recall' and row.get('judgment') is None: continue
                for fact in row['facts']:
                    age = fact.get('distance_rounds')
                    if age is None: continue
                    value = base.phase.exact_score({fact['id']: row['qa_answers'][fact['id']]}, [fact]) if metric == 'qa' else int(row['judgment'][fact['id']]['supported'])
                    by_age[age].append(value)
            if by_age:
                ages = sorted(by_age); axis.plot(ages, [sum(by_age[a])/len(by_age[a]) for a in ages], marker='o', label=method)
                age_rows.extend({'method': method, 'metric': metric, 'distance_rounds': age,
                    'correct_or_supported': sum(by_age[age]), 'valid_facts': len(by_age[age])} for age in ages)
        if axis.get_legend_handles_labels()[0]: axis.legend(fontsize=7)
        axis.set(xlabel='Observed distance in original rounds', ylabel=metric, ylim=(-.05, 1.05), title='Available facts; unequal coverage, descriptive only')
    fig.tight_layout(); fig.savefig(directory / 'observed-age.png', dpi=180); plt.close(fig)
    if age_rows:
        with (directory / 'observed-age.csv').open('w') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(age_rows[0])); writer.writeheader(); writer.writerows(age_rows)


def main():
    p = argparse.ArgumentParser(); p.add_argument('--root', type=Path, default=DEFAULT); p.add_argument('--watch', action='store_true')
    args = p.parse_args(); root = args.root.resolve()
    if args.watch:
        directory = root / 'analysis'; directory.mkdir(exist_ok=True)
        lease = (directory / 'watch.lock').open('a'); fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
    while True:
        report(root)
        status = base.read(root / 'status.json') if (root / 'status.json').exists() else {}
        if not args.watch or status.get('finished') is True or (root / 'ANALYSIS_STOP').exists(): return
        time.sleep(60)


if __name__ == '__main__': main()
