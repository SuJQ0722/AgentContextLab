"""Read-only, answer-selected BC retry sources; private gold stays out of public rows."""
import hashlib,json
from pathlib import Path
from lab import ROOT
INVENTORY=ROOT/'outputs/preflight/vera-retry-inventory-v1/records.jsonl'
COHORT=ROOT/'outputs/campaigns/bc100-r3-hermes-parity-v3/cohort.jsonl'
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_text())
def check(value,message):
 if not value:raise ValueError(message)

def source_records(inventory=INVENTORY,cohort=COHORT):
 inventory,cohort=Path(inventory),Path(cohort)
 sources=[json.loads(x) for x in cohort.read_text().splitlines() if x.strip()]
 check(len(sources)==100 and len({r['id'] for r in sources})==100,'Expected100 unique BC questions')
 gold={r['id']:{'question':r['question'],'answer':r['answer']} for r in sources}
 public=[{'id':r['id'],'question':r['question']} for r in sources]
 records=[]
 for r in (json.loads(x) for x in inventory.read_text().splitlines() if x.strip()):
  if r['group'] not in ('bc/dsh/visual','bc/hermes/visual'):continue
  check(sha(r['result_path'])==r['result_sha256'],'Original result changed')
  v=read(r['result_path']);check(all(v[k]==r[k] for k in ('job_id','harness','question_id','repeat')),'Result identity mismatch')
  check(v['status']==r['prediction_status'] and v['slot_released'] is True and v['unconfirmed_child_termination']==[],'Original result status/cleanup unresolved')
  check(r['question_id'] in gold,'Unknown question')
  question_sha=hashlib.sha256(gold[r['question_id']]['question'].encode()).hexdigest()
  check(question_sha==r['question_sha256'],'Question differs from source')
  if v['status']=='completed':
   check(r['grade_path'] and sha(r['grade_path'])==r['grade_sha256'],'Original grade changed')
   g=read(r['grade_path']);check(g['status']=='scored' and type(g['score']) in (float,int) and g['score']==r['score'],'Unknown score cannot select a retry')
   check(all(g[k]==r[k] for k in ('job_id','harness','question_id','repeat','result_sha256','question_sha256')),'Grade identity mismatch')
   final=v.get('final');prediction=final if isinstance(final,str) else (final or {}).get('text','')
   check(isinstance(prediction,str) and g['prediction_sha256']==hashlib.sha256(prediction.encode()).hexdigest(),'Grade prediction binding differs')
   check(Path(g['attempt_path']).resolve()==Path(r['attempt_path']).resolve(),'Grade attempt differs')
  else:check(v['status'] in ('timeout','failed') and r['score']==0,'Unresolved original result')
  check(type(r['score']) in (int,float) and r['score'] in (0,1),'Nonbinary original grade')
  records.append({'job_id':r['job_id'],'harness':r['harness'],'question_id':r['question_id'],'repeat':r['repeat'],
   'status':v['status'],'score':r['score'],'selected_for_retry':r['score']==0,'result_path':r['result_path'],'result_sha256':r['result_sha256'],
   'grade_path':r['grade_path'],'grade_sha256':r['grade_sha256'],'previous_selected_attempt':r['attempt_path'],'question_sha256':question_sha,
   'old_route':v.get('model'),'source_inventory_path':str(inventory),'source_inventory_sha256':sha(inventory),'source_cohort_path':str(cohort),'source_cohort_sha256':sha(cohort)})
 check(len(records)==600 and len({r['job_id'] for r in records})==600,'Expected two complete100x3 visual cells')
 for harness in ('hermes','dsh'):
  check({(r['question_id'],r['repeat']) for r in records if r['harness']==harness}=={(q,rep) for q in gold for rep in (1,2,3)},'Incomplete harness cohort')
 return records,gold,public
