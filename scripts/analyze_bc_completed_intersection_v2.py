"""Offline BC completion intersections with execution-only visual recovery overlays."""
import collections
import hashlib
import json
import statistics
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'outputs/analysis/bc-completion-intersection-v2'
BASE=ROOT/'outputs/grading/bc100-v3-deepseek-sfb-v1/analysis'
METHODS=('none','discard','summarize','sliding_window','visual')
NAMES=('visual-hosted-failure-retry-v1','visual-hosted-transport-v4','visual-inline-failure-retry-v5','dsh-cli-separator-v1','visual-inline-canary-v6')
SOURCES={}

def read(path):
 p=Path(path);raw=p.read_bytes();SOURCES[str(p.relative_to(ROOT))]=hashlib.sha256(raw).hexdigest()
 return [json.loads(l)for l in raw.decode().splitlines()if l.strip()]if p.suffix=='.jsonl'else json.loads(raw)

def digest(text):return hashlib.sha256(text.encode()).hexdigest()

def result_check(row):
 p=Path(row['attempt'])/'result.json';r=read(p)
 if r.get('status')!=row['prediction_status']:raise ValueError('Prediction state mismatch '+str(p))
 if r.get('job_id')!=row['job_id']:raise ValueError('Job identity mismatch '+str(p))
 row['result_path']=str(p);row['result_sha256']=SOURCES[str(p.relative_to(ROOT))]
 row['clean_completed']=(r['status']=='completed'and not r.get('failure_category')and not r.get('error_type')and r.get('exit_code')in(0,None)and r.get('slot_released')is not False and not r.get('unconfirmed_child_termination'))
 gp=row.get('judge_path')
 if row['prediction_status']=='completed'and gp and Path(gp).exists():
  g=read(gp)
  if g.get('result_sha256')!=row['result_sha256']or g.get('question_sha256')!=row['question_hash']or g.get('job_id')!=row['job_id']:raise ValueError('Grade binding mismatch '+gp)
  if g.get('status')=='scored'and g.get('score')in(0,1):
   if row.get('score')!=g['score']:raise ValueError('Grade score mismatch '+gp)
   row['grade_sha256']=SOURCES[str(Path(gp).relative_to(ROOT))]
  else:row['score']=None;row['score_reason']='unscored_bound_grade'
 elif row['prediction_status']=='completed':row['score']=None;row['score_reason']='missing_bound_grade'
 return row

def summary(index,keys):
 keys=sorted(keys);qs=sorted({q for q,r in keys});balanced=[q for q in qs if all((q,r)in keys for r in(1,2,3))]
 values={}
 for m,ix in index.items():
  correct=sum(ix[k]['score']for k in keys);byrep={str(r):{'correct':sum(ix[k]['score']for k in keys if k[1]==r),'denominator':sum(k[1]==r for k in keys)}for r in(1,2,3)}
  counts=[sum(ix[(q,r)]['score']for q in balanced)for r in(1,2,3)];rates=[v/len(balanced)for v in counts]if balanced else[]
  values[m]={'correct':correct,'denominator':len(keys),'accuracy':correct/len(keys)if keys else None,'per_repeat':byrep,
   'balanced_avg3':{'questions':len(balanced),'per_repeat_correct':counts,'per_repeat_accuracy':rates,'mean':statistics.mean(rates)if rates else None,'sample_std_ddof1':statistics.stdev(rates)if rates else None}}
 return {'slots':len(keys),'independent_questions':len(qs),'per_repeat_counts':dict(collections.Counter(r for q,r in keys)),'slot_keys':keys,'balanced_questions':balanced,'methods':values}

def main():
 base=read(BASE/'selected-observations.jsonl');first={r['job_id']:r for r in read(BASE/'first-pass-observations.jsonl')};ix={r['job_id']:dict(r,selected_campaign='baseline_selected_fixed_failure_retry')for r in base};audit=[]
 if len(ix)!=3000:raise ValueError('Expected two harnesses, five methods, 100 questions, three repeats')
 for r in base:
  if r['selection']not in ('retained_original_completed','fixed_retry_regardless_of_outcome'):raise ValueError('Unapproved base selection')
  if r['selection']=='fixed_retry_regardless_of_outcome'and first[r['job_id']]['prediction_status']=='completed':raise ValueError('Completed original was retried')
 roots={}
 for h in('hermes','dsh'):
  for campaign in ('bc100-r3-hermes-parity-v3','bc100-r3-hermes-parity-v3-retry1'):
   p=ROOT/'outputs/campaigns'/campaign/'plan.json';plan=read(p);roots[campaign]=plan
 for r in ix.values():
  campaign=Path(r['attempt']).relative_to(ROOT/'outputs/campaigns').parts[0]
  plan=roots[campaign];row=next(j for j in plan['jobs']if j['job_id']==r['job_id'])
  if digest(row['question'])!=r['question_hash']:raise ValueError('Base question mismatch')
  r['plan_path']=str(ROOT/'outputs/campaigns'/campaign/'plan.json')
 for name in NAMES:
  grade_root=ROOT/'outputs/grading'/name;obs_path=grade_root/'observations.json'
  if name=='visual-inline-failure-retry-v5':obs_path=ROOT/'outputs/grading/visual-inline-judge-recovery-v1/observations-merged.json'
  for cell in ('bc_hermes','bc_dsh'):
   binding_path=grade_root/'cells'/cell/'source-binding.json'
   if not binding_path.exists():continue
   binding=read(binding_path);root=Path(binding['root']);plan_path=root/'plan.json';plan=read(plan_path)
   if SOURCES[str(plan_path.relative_to(ROOT))]!=binding['plan_sha256']:raise ValueError('Frozen grading plan mismatch')
   definition=plan['definition']
   if definition.get('selection_uses_answers')is not False:raise ValueError('Unproven answer-independent overlay')
   jobs={j['job_id']:j for j in plan['jobs']}
   observations=[o for o in read(obs_path)if o['cell']==cell]
   for o in observations:
    old=ix[o['job_id']];j=jobs[o['job_id']];decision={'campaign':name,'cell':cell,'job_id':o['job_id'],'candidate_status':o['prediction_status'],'prior_status':old['prediction_status'],'plan_path':str(plan_path)}
    if digest(j['question'])!=old['question_hash']:raise ValueError('Overlay question mismatch')
    if old['prediction_status']=='completed':decision['decision']='retain_existing_completed_without_reading_score'
    elif o['prediction_status']not in ('completed','failed','timeout','not_started'):decision['decision']='ignore_nonterminal'
    else:
     attempt=root/'jobs'/o['job_id']/'attempts/attempt_001';result=attempt/'result.json'
     if not result.exists():decision['decision']='ignore_missing_result'
     else:
      actual=read(result)
      if actual.get('status')!=o['prediction_status']:raise ValueError('Overlay result status mismatch')
      if actual.get('slot_released')is not True or actual.get('unconfirmed_child_termination'):raise ValueError('Overlay cleanup not confirmed')
      gp=o.get('recovery_grade')or str(grade_root/'cells'/cell/'jobs'/o['job_id']/'grade.json')
      ix[o['job_id']]={**old,**o,'attempt':str(attempt),'judge_path':gp,'selected_campaign':name,'plan_path':str(plan_path),'selection':'execution_only_recovery_preserve_any_completed'}
      decision.update(decision='selected_latest_terminal_if_prior_not_completed',result_path=str(result),result_sha256=SOURCES[str(result.relative_to(ROOT))])
    audit.append(decision)
 # This explicit exclusion applies to all bounded retry predictions, irrespective of score.
 rows=list(ix.values())
 with ThreadPoolExecutor(max_workers=8)as pool:rows=list(pool.map(result_check,rows))
 report={'at':datetime.now(timezone.utc).isoformat(),'paid_calls':0,'excluded_campaigns':['bc-bounded-retry-v1'],'overlay_order':list(NAMES),'selection_rule':'Keep any completed result regardless of correctness; otherwise use latest terminal from approved execution-only recovery. Never include bounded answer-selected campaign results.','interpretation':'Conditional successful-completion subset; not full-cohort accuracy. Recovered transient API errors may occur. Mixed engineering protocols and judge routes remain disclosed.','scopes':{}}
 included=[]
 for h in ('hermes','dsh'):
  index={m:{(r['question_id'],r['repeat']):r for r in rows if r['harness']==h and r['method']==m}for m in METHODS}
  common=set.intersection(*(set(v)for v in index.values()));completed={k for k in common if all(index[m][k]['clean_completed']for m in METHODS)}
  graded={k for k in completed if all(type(index[m][k].get('score'))in(int,float)and index[m][k]['score']in(0,1)for m in METHODS)}
  report['scopes'][h]={'completed_slots':len(completed),'missing_any_grade_slots':len(completed-graded),**summary(index,graded)}
  for m in METHODS:
   for k in sorted(graded):included.append(index[m][k])
 report['selected_campaign_counts']=dict(collections.Counter(r['selected_campaign']for r in rows));report['source_sha256']=SOURCES;report['script_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
 OUT.mkdir(parents=True,exist_ok=True)
 for name,data in [('report.json',report),('overlay-decisions.json',audit)]: (OUT/name).write_text(json.dumps(data,indent=2)+'\n')
 for name,data in [('selected-observations.jsonl',rows),('intersection-rows.jsonl',included)]: (OUT/name).write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n'for r in data))
 print(json.dumps({k:{'slots':v['slots'],'independent_questions':v['independent_questions'],'repeat_counts':v['per_repeat_counts'],'balanced_questions':len(v['balanced_questions']),'methods':v['methods']}for k,v in report['scopes'].items()}))
if __name__=='__main__':main()
