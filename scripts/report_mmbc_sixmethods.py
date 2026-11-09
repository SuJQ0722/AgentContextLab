#!/usr/bin/env python3
"""Read-only six-method MMBC report; parent grades remain untouched."""
import argparse,hashlib,json,statistics,time
from collections import Counter
from pathlib import Path
import numpy as np
import judge_mmbc100 as base
from analyze_significance import interval,paired_test

LABEL='vanilla_visual'
DEFAULT_VANILLA=base.ROOT/'outputs/grading/mmbc100-hermes-vanilla-v1'
DEFAULT_OUTPUT=base.ROOT/'outputs/grading/mmbc100-sixmethod-report-v1'
GROUPS=('all100','initial_images','no_initial_images')

def group_ids(cohort,name):return sorted(q for q,r in cohort.items() if name=='all100' or bool(r['image'])==(name=='initial_images'))
def summarize(rows,ids,method,rng,draws):
 chosen=[r for r in rows if r['question_id'] in ids and r['method']==method];ix={(r['question_id'],r['repeat']):r for r in chosen};expected={(q,rep) for q in ids for rep in [1,2,3]}
 if len(ix)!=len(chosen):raise ValueError('Duplicate repeated outcome')
 complete=bool(ids) and set(ix)==expected and all(r['score'] is not None for r in chosen);known=[r['score'] for r in chosen if r['score'] is not None];n=len(expected);means=[];per=[]
 for rep in [1,2,3]:
  scores=[ix[q,rep]['score'] for q in ids if (q,rep) in ix and ix[q,rep]['score'] is not None];v=statistics.mean(scores) if ids and len(scores)==len(ids) else None;per.append({'repeat':rep,'known':len(scores),'planned':len(ids),'mean':v})
  if v is not None:means.append(v)
 return {'method':method,'questions':len(ids),'planned':n,'known':len(known),'missing':n-len(known),'complete':complete,'mean':statistics.mean(means) if complete else None,'sample_std_across_three_repeats':statistics.stdev(means) if complete else None,'bootstrap95':interval([statistics.mean(ix[q,rep]['score'] for rep in [1,2,3]) for q in ids],rng,draws) if complete else [None,None],'per_repeat':per,'accuracy_bounds':[sum(known)/n,(sum(known)+n-len(known))/n] if n else None,'score_reasons':dict(Counter(r['score_reason'] for r in chosen))}

def additional_pair(rows,ids,rng,draws):
 ix={m:{(r['question_id'],r['repeat']):r for r in rows if r['method']==m and r['question_id'] in ids} for m in ['visual',LABEL]};expected={(q,rep) for q in ids for rep in [1,2,3]}
 if any(len(ix[m])!=sum(r['method']==m and r['question_id'] in ids for r in rows) for m in ix):raise ValueError('Duplicate paired trajectory')
 ready=bool(ids) and all(set(v)==expected and all(r['score'] is not None for r in v.values()) for v in ix.values());p={'baseline':LABEL,'ready':ready,'comparison_family':'One additional visual-vs-vanilla comparison; input-image subgroups are descriptive/exploratory, not an all-comparison multiplicity claim'}
 if ready:
  if any(ix['visual'][k]['question_sha256']!=ix[LABEL][k]['question_sha256'] for k in expected):raise ValueError('Paired source text mismatch')
  delta=[statistics.mean(ix['visual'][q,rep]['score']-ix[LABEL][q,rep]['score'] for rep in [1,2,3]) for q in ids];p.update(question_clusters=len(ids),paired_runs=len(ids)*3,visual_minus_vanilla=statistics.mean(delta),bootstrap95=interval(delta,rng,draws),paired_signflip_p=paired_test(delta,rng,draws))
 return p

def validate_observations(rows,binding,labels):
 root=Path(binding['root']);plan=base.read(root/'plan.json')
 if base.sha(root/'plan.json')!=binding['plan_sha256'] or base.sha(root/'cohort.jsonl')!=binding['cohort_sha256']:raise ValueError('Observation source changed')
 jobs={j['job_id']:j for j in plan['jobs']};seen=set()
 for r in rows:
  if r['job_id'] not in jobs or r['job_id'] in seen:raise ValueError('Duplicate/unplanned observation')
  seen.add(r['job_id']);j=jobs[r['job_id']];label=j.get('method_label') or j['strategy'];expected=root/'jobs'/j['job_id']/'attempts/attempt_001'
  if label not in labels or r['method']!=label or r['question_id']!=j['question_id'] or r['repeat']!=j['repeat'] or r['question_sha256']!=hashlib.sha256(j['question'].encode()).hexdigest() or Path(r['attempt']).resolve()!=expected.resolve():raise ValueError('Observation job/method/text identity mismatch')
  if r.get('result_sha256') is not None and base.sha(expected/'result.json')!=r['result_sha256']:raise ValueError('Bound result changed')
  if r.get('score') is not None and r.get('result_sha256') is None:raise ValueError('Scored observation lacks bound result')
  if r.get('score') is not None and (type(r['score']) not in (float,int) or r['score'] not in (0,1)):raise ValueError('Nonbinary score')
 if seen!=set(jobs):raise ValueError('Incomplete observation table; do not replace fixed cohort by available intersection')

def write_vanilla(rows,cohort,out,info,draws=10000):
 rng=np.random.default_rng(20261109);groups={g:{'summary':[summarize(rows,group_ids(cohort,g),LABEL,rng,draws)]} for g in GROUPS}
 # Reuse validated raw usage accounting; only display label changes, strategy remains visual.
 mapped=[dict(r,method='visual') for r in rows];cost=base.accounting(mapped,out);cost['prediction']={LABEL:cost['prediction']['visual']}
 value={'at':base.bc.now(),'inventory':info,'groups':groups,'accounting':cost,'label':LABEL,'actual_strategy':'visual','interpretation':'Text-only history rendering; full cohort and initial native inputs unchanged. Missing grades/unknown outcomes are not zeros.'}
 base.atomic(out/'statistics.json',value);base.atomic(out/'observations.json',rows);write_markdown(out/'summary.md',groups,'MMBC vanilla: 100 questions × 3 repeats',value['interpretation']);return value

def write_markdown(path,groups,title,note):
 lines=['# '+title,'',note,'','|Subgroup|Method|Known / planned|Mean ± sample std|95% question-cluster CI|','|---|---|---:|---:|---|']
 for name,g in groups.items():
  for s in g['summary']:
   avg=f"{s['mean']*100:.2f} ± {s['sample_std_across_three_repeats']*100:.2f}%" if s['complete'] else 'NA — incomplete';ci=str([round(x*100,2) for x in s['bootstrap95']]) if s['complete'] else 'NA';lines.append(f"|{name}|{s['method']}|{s['known']}/{s['planned']}|{avg}|{ci}|")
 lines+=['','Intervals resample whole questions with all three repeats retained. Vanilla is an additional fixed cohort run, not a replacement of parent visual runs. Costs from the two namespaces are disjoint; no fabricated USD pricing.']
 path.write_text('\n'.join(lines)+'\n')

def combine(parent,vanilla,out,draws=10000):
 parent,vanilla,out=map(Path,(parent,vanilla,out));pb=base.read(parent/'source-binding.json');vb=base.read(vanilla/'source-binding.json')
 if pb['cohort_sha256']!=vb['cohort_sha256'] or pb['private_source_sha256']!=vb['private_source_sha256'] or pb['plan_sha256']!=vb['parent_plan_sha256'] or str(Path(pb['root']).resolve())!=vb['parent_root']:raise ValueError('Different question/gold/parent plan lineage')
 if parent.resolve()==vanilla.resolve():raise ValueError('Separate grader namespaces required')
 for destination in [Path(pb['root']).resolve(),Path(vb['root']).resolve(),parent.resolve(),vanilla.resolve()]:
  if out.resolve()==destination or out.resolve() in destination.parents or destination in out.resolve().parents:raise ValueError('Combined output cannot overwrite source namespace')
 prows=base.read(parent/'observations.json');vrows=base.read(vanilla/'observations.json');validate_observations(prows,pb,set(base.METHODS));validate_observations(vrows,vb,{LABEL})
 cohort={r['question_id']:r for r in base.jsonlines(Path(pb['root'])/'cohort.jsonl')};combined=prows+vrows;original=base.analyze(prows,cohort,draws);rng=np.random.default_rng(20261109);groups={}
 for g in GROUPS:
  ids=group_ids(cohort,g);groups[g]={'summary':original['groups'][g]['summary']+[summarize(vrows,ids,LABEL,rng,draws)],'parent_four_paired_tests':original['groups'][g]['paired'],'additional_visual_vs_vanilla':additional_pair(combined,ids,rng,draws)}
 sources={}
 for name,root in [('parent',parent),('vanilla',vanilla)]:sources[name]={'grading_root':str(root.resolve()),'observations_sha256':base.sha(root/'observations.json'),'binding_sha256':base.sha(root/'source-binding.json'),'protocol_sha256':base.sha(root/'protocol.json')}
 cost={}
 for name,root in [('parent',parent),('vanilla',vanilla)]:
  p=root/'statistics.json'
  if p.exists():d=base.read(p);cost[name]={'at':d.get('at'),'accounting':d.get('accounting'),'note':'Separate source snapshot may lag newest grades; no double counting across namespaces'}
 value={'at':base.bc.now(),'groups':groups,'sources':sources,'draws':draws,'random_seed':20261109,'resources_by_namespace':cost,'inference':'Original four-comparison Holm families remain unchanged. One additional predeclared visual-vs-vanilla comparison is reported separately; no claim of simultaneous control across all five or all image subgroups.'}
 out.mkdir(parents=True,exist_ok=True);base.atomic(out/'statistics.json',value);write_markdown(out/'summary.md',groups,'MMBC-100: six methods, three repeats',value['inference']);return value

def main():
 p=argparse.ArgumentParser();p.add_argument('--parent',type=Path,default=base.DEFAULT_OUT);p.add_argument('--vanilla',type=Path,default=DEFAULT_VANILLA);p.add_argument('--output',type=Path,default=DEFAULT_OUTPUT);p.add_argument('--draws',type=int,default=10000);p.add_argument('--watch',action='store_true');a=p.parse_args()
 while True:
  try:combine(a.parent,a.vanilla,a.output,a.draws)
  except (FileNotFoundError,OSError) as exc:
   if not a.watch:raise
   print(json.dumps({'status':'awaiting_source','error_type':type(exc).__name__}),flush=True)
  if not a.watch:return
  time.sleep(60)
if __name__=='__main__':main()
