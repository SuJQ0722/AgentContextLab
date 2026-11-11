"""Offline RQ3 completed intersections, retaining all historical completed outcomes."""
import hashlib,json,statistics,itertools
import numpy as np
from analyze_significance import interval,paired_test,holm
from pathlib import Path
from collections import Counter
from analyze_success_intersection_v1 import analyze
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'outputs/analysis/all-success-intersections-20261111/rq3'
SCALES=(0.,.25,.5,.7,.75,.8,1.)

def read(p):return json.loads(Path(p).read_text())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def scale_label(s):return f'{s:g}x'
def run():
 sources={};audit=[]
 def load(p):
  p=Path(p);raw=p.read_bytes();sources[str(p)]=hashlib.sha256(raw).hexdigest()
  return [json.loads(x)for x in raw.decode().splitlines()if x] if p.suffix=='.jsonl' else json.loads(raw)
 base=load(ROOT/'outputs/grading/rq3-final-seven-v3/observations.jsonl')
 assert len(base)==2100
 ix={r['job_id']:dict(r)for r in base};original=[dict(r)for r in base]
 def overlay(row,attempt,question=None):
  old=ix[row['job_id']]
  if old['prediction_status']=='completed':return
  if question is not None and hashlib.sha256(question.encode()).hexdigest()!=old['question_hash']:raise ValueError('Question mismatch')
  rp=Path(attempt)/'result.json'
  if not rp.exists():return
  result=load(rp)
  if result.get('job_id')!=row['job_id']:raise ValueError('Job mismatch')
  if result['status'] not in ('completed','failed','timeout'):return
  if result.get('slot_released')is not True or result.get('unconfirmed_child_termination')!=[]:return
  if row['prediction_status']!=result['status']:raise ValueError('Stale observation state')
  if row.get('result_sha256') and row['result_sha256']!=sha(rp):raise ValueError('Result binding changed')
  new={**old,**row,'attempt':str(attempt),'question_hash':old['question_hash'],'scale':old['scale']}
  ix[row['job_id']]=new;audit.append({'job_id':row['job_id'],'old_attempt':old['attempt'],'new_attempt':str(attempt),'status':result['status'],'result_sha256':sha(rp)})
 boundedroot=ROOT/'outputs/campaigns/rq3-bounded-failure-retry-v1'
 plan=load(boundedroot/'plan.json');assert plan['definition']['selection_uses_prior_answers']is False
 jobs={j['job_id']:j for j in plan['jobs']}
 for row in load(ROOT/'outputs/grading/rq3-bounded-failure-retry-v1/observations.json'):
  overlay(row,Path(row['attempt']),jobs[row['job_id']]['question'])
 waves=[('outputs/campaigns/visual-hosted-failure-retry-v1','outputs/grading/visual-hosted-failure-retry-v1','observations.json'),
 ('outputs/campaigns/visual-hosted-failure-retry-v1/cells/transport-v4','outputs/grading/visual-hosted-transport-v4','observations.json'),
 ('outputs/campaigns/visual-hosted-failure-retry-v1/cells/transport-v5','outputs/grading/visual-inline-judge-recovery-v1','observations-merged.json'),
 ('outputs/campaigns/visual-hosted-failure-retry-v1/cells/transport-v6-canary','outputs/grading/visual-inline-canary-v6','observations.json')]
 for root,grading,filename in waves:
  root=ROOT/root;grading=ROOT/grading
  rows=load(grading/filename);plans={}
  for row in rows:
   if not row['cell'].startswith('rq3_scale_'):continue
   cell=root/'cells'/row['cell']
   if row['cell']not in plans:plans[row['cell']]={j['job_id']:j for j in load(cell/'plan.json')['jobs']}
   j=plans[row['cell']][row['job_id']];attempt=cell/'jobs'/row['job_id']/'attempts/attempt_001'
   if row['prediction_status']=='completed':
    if 'recovery_grade'in row:gp=Path(row['recovery_grade'])
    else:gp=grading/'cells'/row['cell']/'jobs'/row['job_id']/'grade.json'
    # V5 merged observations point into the original grade tree unless recovered.
    if not gp.exists() and filename=='observations-merged.json':gp=ROOT/'outputs/grading/visual-inline-failure-retry-v5/cells'/row['cell']/'jobs'/row['job_id']/'grade.json'
    if gp.exists():
     g=load(gp)
     if g.get('result_sha256')!=sha(attempt/'result.json'):raise ValueError('Grade mismatch')
     row={**row,'score':g.get('score') if g.get('status')=='scored' else None,'judge_path':str(gp)}
   overlay(row,attempt,j['question'])
 def summarize(rows):
  normalized=[{**r,'method':scale_label(r['scale'])}for r in rows]
  stats=analyze(normalized,[scale_label(s)for s in SCALES],audit=False)
  keys=stats['completed_and_scored']['slot_keys'];questions=sorted({q for q,rep in keys if all([q,r]in keys for r in (1,2,3))})
  idx={(r['method'],r['question_id'],r['repeat']):r for r in normalized};balanced={}
  for method in [scale_label(s)for s in SCALES]:
   means=[statistics.mean(idx[method,q,rep]['score']for q in questions)for rep in (1,2,3)]if questions else []
   balanced[method]={'questions':len(questions),'correct':sum(idx[method,q,rep]['score']for q in questions for rep in (1,2,3)), 'mean':statistics.mean(means)if means else None,'std':statistics.stdev(means)if means else None,'repeat_means':means}
  stats['balanced_avg3']={'questions':questions,'methods':balanced}
  rng=np.random.default_rng(20261111);pairs=[]
  if questions:
   for left,right in itertools.combinations(balanced,2):
    deltas=[statistics.mean(idx[left,q,rep]['score']-idx[right,q,rep]['score']for rep in (1,2,3))for q in questions]
    pairs.append({'left':left,'right':right,'question_clusters':len(questions),'delta':statistics.mean(deltas),'bootstrap95':interval(deltas,rng),'p':paired_test(deltas,rng)})
   for pair,adjusted in zip(pairs,holm([v['p']for v in pairs])):pair['holm_p_21_pairs']=adjusted
  stats['descriptive_balanced_pairs']=pairs
  stats['coverage']={scale_label(s):dict(Counter(r['prediction_status']for r in rows if r['scale']==s))for s in SCALES}
  return stats
 for row in ix.values():
  rp=Path(row['attempt'])/'result.json'
  if not rp.exists():raise ValueError('Selected result missing')
  value=load(rp)
  if value.get('status')!=row['prediction_status']:raise ValueError('Selected outcome changed')
  if row['prediction_status']=='completed':
   if value.get('slot_released')is not True or value.get('unconfirmed_child_termination')!=[]:raise ValueError('Completed cleanup missing')
   gp=row.get('judge_path')
   if gp and Path(gp).exists():
    grade=load(gp)
    if grade.get('status')=='scored' and grade.get('score')!=row.get('score'):raise ValueError('Score changed')
 report={'source_sha256':sources,'model_calls':0,'selection':'Operational completion only; all completed retained regardless of correctness; missing grade excludes entire paired slot.',
         'original_protocol':summarize(original),'latest_operational_overlay':summarize(list(ix.values())),
         'scientific_limit':'Latest overlay mixes renderer/route/transport versions; not a clean resolution-only ablation. Same question/repeat is matched, no success-subset superiority claim.', 'overlay_audit':audit}
 OUT.mkdir(parents=True,exist_ok=True);(OUT/'report.json').write_text(json.dumps(report,indent=2)+'\n');(OUT/'selected-observations.json').write_text(json.dumps(list(ix.values()),indent=2)+'\n')
 for name in ('original_protocol','latest_operational_overlay'):
  print(name,report[name]['completed_and_scored']['slots'], 'balanced',len(report[name]['balanced_avg3']['questions']))
if __name__=='__main__':run()
