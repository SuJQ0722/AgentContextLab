#!/usr/bin/env python3
"""Read-only phase4 holdout accounting: exclude protocol-development q004."""
import argparse,json,time
from pathlib import Path
from datetime import datetime,timezone
from collections import defaultdict
from info_loss_phase4 import DEFAULT,METHODS,read,save
from info_loss_report import summarize_usage

def aggregate(root):
 m=read(root/'manifest.json');data=read(root/'results.json');gate_id=m['cases'][0]['id'];facts={p.stem:read(p) for p in (root/'facts').glob('*.json')}
 rows=[r for r in data['records'] if r['case']!=gate_id];cohort=[c['id'] for c in m['cases'] if c['id']!=gate_id]
 pairs=[qid for qid in cohort if all(any(r['case']==qid and r['method']==method and r.get('qa_exact_correct') is not None for r in rows) for method in METHODS)]
 total_facts=sum(len(facts.get(q,[])) for q in cohort);tables=[];points=[]
 for method in METHODS:
  selected=[r for r in rows if r['method']==method];known=[r for r in selected if r.get('qa_exact_correct') is not None];correct=sum(r['qa_exact_correct'] for r in known);den=sum(r['fact_count'] for r in known)
  tables.append({'method':method,'qa_known_cases':len(known),'qa_correct':correct,'qa_observed_facts':den,'shared_fact_denominator_available_so_far':total_facts,'missing_bounds':[correct/total_facts,(correct+total_facts-den)/total_facts] if total_facts else None,'paired_complete_cases':len(pairs)})
 for r in rows:
  for f in facts.get(r['case'],[]):points.append({'case':r['case'],'method':r['method'],'fact_id':f['id'],'fact_type':f['type'],'distance_rounds':f['distance_rounds'],'qa_exact':(r.get('qa_by_fact') or {}).get(f['id']),'semantic_supported':(r.get('semantic_judge') or {}).get(f['id'],{}).get('supported')})
 started=list((root/'calls').glob('*/started.json'));responses=[read(p) for p in (root/'calls').glob('*/response.json')];usage=summarize_usage(responses,len(started))
 return {'updated_at':datetime.now(timezone.utc).isoformat(),'status':data['status'],'protocol':read(root/'selected-protocol.json') if (root/'selected-protocol.json').exists() else None,'gate_case_excluded_from_primary':gate_id,'primary_cohort':cohort,'primary_available_fact_cases':sum(bool(facts.get(q)) for q in cohort),'paired_complete_question_ids':pairs,'table':tables,'points':points,'all_new_usage_including_failed_gates':usage,'limitations':['Nine fixed holdout questions; gate q004 shown separately in campaign report, not an independent validation question.','Fact denominators are available facts so far, not assumed54; unavailable conditions remain missing.','Different facts within a question are correlated; descriptive curves, no fabricated confidence intervals.','Age is observational distance, not causal time decay. Same-model judge bias remains.']}

def render(root):
 d=aggregate(root);out=root/'holdout-analysis';out.mkdir(exist_ok=True);save(out/'report.json',d)
 lines=['# Phase4: nine held-out source questions','',f"Status: {d['status']}; protocol: {(d['protocol'] or {}).get('stage')}; complete five-arm QA pairs: {len(d['paired_complete_question_ids'])}/9.",'','q004 is the fixed protocol-development gate and is excluded from this primary descriptive table. All of its calls remain in the cost ledger and full campaign report.','','|Method|QA cases|Correct / observed facts|Shared facts currently available|Missing-response accuracy bounds|','|---|---:|---:|---:|---|']
 for r in d['table']:lines.append(f"|{r['method']}|{r['qa_known_cases']}/9|{r['qa_correct']}/{r['qa_observed_facts']}|{r['shared_fact_denominator_available_so_far']}|{r['missing_bounds']}|")
 lines+=['']+['- '+x for x in d['limitations']]
 if any(p['qa_exact'] is not None for p in d['points']):
  import matplotlib;matplotlib.use('Agg');import matplotlib.pyplot as plt
  fig,axes=plt.subplots(1,2,figsize=(11,4),layout='constrained')
  values=[]
  for scale in [.5,.75,1]:
   method='canvas_'+str(scale);known=[p['qa_exact'] for p in d['points'] if p['method']==method and p['qa_exact'] is not None]
   if known:values.append((scale,sum(known)/len(known)))
  if values:axes[0].plot(*zip(*values),'o-')
  for method in METHODS:
   groups=defaultdict(list)
   for p in d['points']:
    if p['method']==method and p['qa_exact'] is not None:groups[p['distance_rounds']].append(p['qa_exact'])
   if groups:axes[1].plot(sorted(groups),[sum(groups[x])/len(groups[x]) for x in sorted(groups)],'o-',label=method)
  axes[0].set(xlabel='Full canvas scale',ylabel='Observed QA exact match',ylim=(-.05,1.05));axes[1].set(xlabel='Original tool-round distance',ylabel='Observed QA exact match',ylim=(-.05,1.05))
  if axes[1].lines:axes[1].legend(fontsize=7)
  fig.suptitle('Nine holdout questions; descriptive available observations, age not causal');fig.savefig(out/'resolution-age.png',dpi=160);fig.savefig(out/'resolution-age.pdf');plt.close(fig);lines+=['','![Descriptive resolution/age](resolution-age.png)']
 (out/'README.md').write_text('\n'.join(lines)+'\n');return d

def main():
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,default=DEFAULT);p.add_argument('--watch',action='store_true');a=p.parse_args();last=None
 while True:
  try:
   source=a.output/'results.json';stamp=source.stat().st_mtime_ns
   if stamp!=last:d=render(a.output);last=stamp
   if not a.watch or read(source)['status'] in ('completed','quality_hold'):return
  except (OSError,ValueError,KeyError) as exc:
   if not a.watch:raise
   print(json.dumps({'observer_error':type(exc).__name__}),flush=True)
  time.sleep(30)
if __name__=='__main__':main()
