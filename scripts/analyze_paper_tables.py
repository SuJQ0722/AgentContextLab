#!/usr/bin/env python3
"""Offline reconstruction of archived Table-1 candidate cohort; no model calls."""
import csv,json,statistics,hashlib,shutil
from pathlib import Path
from collections import defaultdict,Counter
import numpy as np
from analyze_significance import interval,paired_test,holm
ROOT=Path(__file__).resolve().parents[1]
ARCHIVE=ROOT.parent/'hermes-agent/preds_archive'
METHODS=['No Compression','Discard','Sliding Window','Summarize','VERA']
BENCHES={'bc':'bc','bc-zh':'bc_zh','xbench':'xbench_deepsearch','seal0':'seal0'}

def csvsave(path,rows):
    if not rows:return
    with path.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]),lineterminator='\n');w.writeheader();w.writerows(rows)

def main():
    out=ROOT/'docs/paper-table1';out.mkdir(parents=True,exist_ok=True)
    ids=list(csv.DictReader((ARCHIVE/'_gemini_4way_success_ids.csv').open()))
    rows=list(csv.DictReader((ROOT/'outputs/experiment1/per_trajectory.csv').open()))
    expected=list(csv.DictReader((ARCHIVE/'_gemini_4way_success_accuracy.csv').open()))
    summaries=[];pairs=[];membership=[];rng=np.random.default_rng(20261107)
    for b,alias in BENCHES.items():
        keys={(r['question_id'],r['repeat_index']) for r in ids if r['benchmark']==b}
        counts=Counter(rep for q,rep in keys);indices={}
        for m in METHODS:
            rs=[r for r in rows if r['benchmark']==alias and r['method']==m and
                ((r['canonical']=='True' and not(b=='bc' and m=='Discard')) or
                 (b=='bc' and m=='Discard' and '/bc/gemini-3.5-flash-thinking-discard' in r['group']))]
            ix={};dups=set()
            for r in rs:
                k=(r['question_id'],r['repeat'])
                if k in ix:dups.add(k)
                ix[k]=r
            if dups:raise RuntimeError('Duplicate source keys: '+str((b,m,len(dups))))
            indices[m]=ix
            scores={k:float(ix[k]['score']) for k in keys if k in ix and ix[k]['score']!=''}
            # Legacy denominator reconstruction ONLY. Unknowns remain explicitly unknown elsewhere.
            reps=[sum(v for k,v in scores.items() if k[1]==s)/counts[s] for s in sorted(counts)]
            correct=sum(scores.values());missing=len(keys)-len(scores)
            summaries.append({'benchmark':b,'method':m,'cohort_trajectories':len(keys),'unique_questions':len({q for q,r in keys}),
                'repeat_denominators':json.dumps(dict(sorted(counts.items()))),'scored':len(scores),
                'missing_records':sum(k not in ix for k in keys),'observed_unscored':sum(k in ix and ix[k]['score']=='' for k in keys),
                'legacy_correct':correct,'legacy_pooled_accuracy_missing_zero':correct/len(keys),
                'legacy_avg3_repeat_mean':statistics.mean(reps),'legacy_repeat_std':statistics.stdev(reps),
                'legacy_repeat_accuracy':json.dumps(reps),'unknown_lower_bound':correct/len(keys),'unknown_upper_bound':(correct+missing)/len(keys),
                'source_groups':json.dumps(sorted({r['group'] for r in rs}))})
            for k in sorted(keys):
                r=ix.get(k,{})
                membership.append({'benchmark':b,'method':m,'question_id':k[0],'repeat':k[1],'question_hash':r.get('question_hash',''),
                   'status':r.get('status','absent'),'score':r.get('score',''),'source_path':r.get('source_path',''),
                   'legacy_missing_zero':k not in scores})
        for m in METHODS[:-1]:
            va=indices['VERA'];base=indices[m];clusters=defaultdict(list);hash_mismatch=0;matched=0
            for k in keys:
                if k not in va or k not in base:continue
                a,c=va[k],base[k]
                if not a['question_hash'] or a['question_hash']!=c['question_hash']:hash_mismatch+=1;continue
                if a['score']=='' or c['score']=='':continue
                clusters[a['question_hash']].append(float(a['score'])-float(c['score']));matched+=1
            d=[statistics.mean(x) for x in clusters.values()];ci=interval(d,rng)
            pairs.append({'benchmark':b,'baseline':m,'matched_scored_trajectories':matched,'matched_question_clusters':len(d),
                'hash_mismatch_excluded':hash_mismatch,'delta_question_weighted':statistics.mean(d) if d else None,
                'bootstrap95_low':ci[0],'bootstrap95_high':ci[1],'paired_cluster_signflip_p':paired_test(d,rng),
                'estimand':'Observed-scored paired subset within fixed archive cohort; no unknown imputation; question-weighted'})
    adjusted=holm([r['paired_cluster_signflip_p'] for r in pairs])
    for row,p in zip(pairs,adjusted):row['holm_p_family16']=p
    csvsave(out/'summary.csv',summaries);csvsave(out/'paired_tests.csv',pairs);csvsave(out/'membership.csv',membership)
    lines=['# Table 1 candidate: archived four-compression-method success cohort','',
      'Offline reconstruction; no new inference or judging. BC-EN No Compression 59.836% exactly matches the reviewer’s 59.8% fingerprint. The full paper mapping remains unverified: the reported overall 69.0% is not reproduced. Do not relabel this as confirmed Table 1.', '',
      'The fixed cohort comes from `_gemini_4way_success_ids.csv`: Discard, Summary, Sliding Window, and VERA all succeeded. No Compression was not part of this selection. This outcome-dependent cohort favors the compression methods and is a limitation of the original selection, not a fair prespecified full-benchmark estimate.', '',
      '| Benchmark | Method | N | Scored | Legacy pooled % | Legacy repeat mean ± std % | Unknown upper % |',
      '|---|---|---:|---:|---:|---:|---:|']
    for r in summaries:lines.append(f"| {r['benchmark']} | {r['method']} | {r['cohort_trajectories']} | {r['scored']} | {100*r['legacy_pooled_accuracy_missing_zero']:.3f} | {100*r['legacy_avg3_repeat_mean']:.3f} ± {100*r['legacy_repeat_std']:.3f} | {100*r['unknown_upper_bound']:.3f} |")
    lines+=['', 'Repeat means use the original per-repeat denominators, which differ. Their std mixes random-run variation with cohort composition. This is not a balanced same-question avg@3 estimate.', '',
      'Legacy reconstruction counts absent/unscored outcomes as zero only to reproduce the old table, not as newly established incorrect answers. BC No Compression has 41 absent records out of 244; neither summary.jsonl nor judge_summary.jsonl contains those 41. They cannot be assigned a failure cause or a true zero score from available evidence. Unknown lower/upper bounds are supplied.', '',
      'Paired tests retain the fixed cohort, then require matching question ID, repeat and exact question content hash plus two observed scores. No five-method complete-case intersection is imposed. Deltas are averaged within question and then across independent question clusters; bootstrap uses 10,000 question-cluster resamples, and paired sign flips use 10,000 draws, with Holm correction over 16 comparisons. These conditional observed-pair estimates have a different estimand from legacy pooled accuracy and do not repair the original outcome-based cohort selection.', '',
      'BC Discard source is `preds_archive/bc/gemini-3.5-flash-thinking-discard`; the other canonical `preds_archive/gemini35_flash_discard` run is a different run and must not be substituted. See `summary.csv` for exact groups and `membership.csv` for per-row paths/hashes.', '',
      'Archive No Compression BC-ZH=79.0%, XBench=71.841%, SEAL-0=56.169%; combined trajectory-weighted=70.046%, four-benchmark macro=66.711%. Neither reproduces overall69.0%. Locate the submitted table/aggregation definition before replacing paper numbers.']
    (out/'audit.md').write_text('\n'.join(lines)+'\n')
    rq=ROOT/'docs/rq3';rq.mkdir(exist_ok=True)
    source=ARCHIVE/'visual_setting_recovered_common_success_7scale_metrics.csv';shutil.copyfile(source,rq/source.name)
    scales=list(csv.DictReader(source.open()))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,ax=plt.subplots(figsize=(7,3.4));ax.plot([r['scale'] for r in scales],[100*float(r['accuracy']) for r in scales],marker='o');ax.set(xlabel='History image scale (original CSV labels)',ylabel='Raw accuracy (%)',title='Archived aggregate: common-success N=187; no CI available');fig.tight_layout()
    fig.savefig(rq/'raw-aggregate-accuracy.png',dpi=180);fig.savefig(rq/'raw-aggregate-accuracy.pdf');plt.close(fig)
    print(json.dumps({'table1_rows':len(summaries),'paired_tests':len(pairs),'new_api_calls':0,'table1_mapping_verified':False,'table5_mapping_verified':False}))
if __name__=='__main__':main()
