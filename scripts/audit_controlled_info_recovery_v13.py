"""Read-only cumulative quota and scientific-target recovery audit. No API calls."""
import argparse,collections,hashlib,json
from pathlib import Path
from lab import ROOT
from controlled_inline_retry_v8 import valid_target
from controlled_native_worker_v5 import native_parts,image_ids

def read(p):return json.loads(Path(p).read_text())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def audit(out):
 out.mkdir(parents=True,exist_ok=True);base=ROOT/'outputs/campaigns/visual-hosted-failure-retry-v1/cells';v8=base/'transport-v8-one-hour-retry5/cells';v9=base/'transport-v9-runtime-recovery/cells/shared_baselines';targets=[];visual=[];text=[]
 for cell in ['controlled_bc','controlled_mmbc']:
  root=v8/cell
  for j in read(root/'plan.json')['jobs']:
   d=root/'jobs'/j['job_id']/'attempts/attempt_001';r=read(d/'result.json') if(d/'result.json').exists() else {};spec=read(j['controlled_spec_path']);prefix=read(spec['prefix_path']);expected=image_ids(native_parts(prefix['messages']));candidates=[]
   for a in sorted(r.get('attempts',[]),key=lambda a:a['attempt_number']):
    p=Path(a['native_artifact_root'])/'compression-control.json'
    if not p.exists():continue
    c=read(p)
    if valid_target(c) and c.get('prefix_sha256')==sha(spec['prefix_path']) and c.get('native_hashes')==expected:
     candidates.append({'source':str(p),'sha256':sha(p),'attempt':a['attempt_number'],'value':c})
   if candidates:
    chosen=candidates[0];targets.append({'prefix_key':j['controlled_prefix_key'],'source_job':j['job_id'],'calibration':j.get('calibration_not_scored',False),'selection':'earliest valid existing subattempt, independent of accuracy','source':chosen['source'],'sha256':chosen['sha256'],'first_actual_prompt_tokens':chosen['value']['first_actual_prompt_tokens'],'native_and_prefix_validated':True,'attempt':chosen['attempt']})
   visual.append({'job_id':j['job_id'],'calibration':j.get('calibration_not_scored',False),'status':r.get('status'),'v8_attempts':r.get('attempt_count',0),'new_attempts_permitted':max(0,3-r.get('attempt_count',0)) if r.get('status')!='completed' else 0})
 targetkeys={x['prefix_key'] for x in targets}
 historical_plans=[]
 for plan in base.glob('*/cells/*/plan.json'):
  try:historical_plans.append((plan,read(plan)['jobs']))
  except (KeyError,ValueError):pass
 for j in read(v9/'plan.json')['jobs']:
  if j.get('experiment_kind')!='controlled':continue
  spec=read(j['controlled_spec_path']);jid=j['controlled_prefix_key']+'/'+j['controlled_method'];previous=[]
  for parent in [ROOT/'outputs/experiment3/controlled-native-v4/jobs'/jid,ROOT/'outputs/experiment3/controlled-native-bounded-v1/jobs'/jid]:
   if (parent/'worker-started.json').exists():previous.append(str(parent/'worker-started.json'))
   for p in parent.glob('attempt_*/worker-started.json'):previous.append(str(p))
  # All historical hosted generations, not only the latest failed wrapper.
  for plan,jobs in historical_plans:
   for old in jobs:
    if old.get('experiment_kind')!='controlled' or old.get('controlled_prefix_key')!=j['controlled_prefix_key'] or old.get('controlled_method')!=j['controlled_method']:continue
    d=plan.parent/'jobs'/old['job_id']/'attempts/attempt_001'
    for p in d.glob('runs/*/native/attempt-started.json'):previous.append(str(p))
    if (d/'native/attempt-started.json').exists():previous.append(str(d/'native/attempt-started.json'))
  previous=sorted(set(previous));text.append({'job_id':j['job_id'],'prefix_key':j['controlled_prefix_key'],'method':j['controlled_method'],'prior_native_attempts_lower_bound':len(previous),'prior_attempt_proofs':previous,'target_recoverable':j['controlled_prefix_key'] in targetkeys,'remaining_attempts_upper_bound':max(0,3-len(previous)),'previous_source_completed':False})
 roots=[ROOT/'outputs/experiment6'/x for x in ['inline-retry5-v8','inline-runtime-v9','model-alias-v10']];calls=collections.defaultdict(list)
 for root in roots:
  for p in root.glob('conditions/*/*/attempts/*/calls/*/started.json'):
   s=read(p);fp=s.get('request_fingerprint');rp=p.parent/'response.json';r=read(rp) if rp.exists() else {};calls[fp].append({'started':str(p),'started_sha256':sha(p),'response':str(rp) if rp.exists() else None,'response_sha256':sha(rp) if rp.exists() else None,'status':r.get('status','unknown'),'finish':r.get('finish_reason'),'at':s.get('at',0),'http_status':r.get('http_status')})
 info=[{'fingerprint':fp,'physical_starts':len(cs),'completed_response_count':sum(c['status']=='completed' for c in cs),'remaining_calls':max(0,3-len(cs)),'evidence':sorted(cs,key=lambda c:c['at'])} for fp,cs in calls.items()]
 result={'version':'controlled-info-quota-audit-v13','created_targets':False,'new_api_calls':0,'visual':visual,'target_candidates':targets,'text':text,'information_loss_requests':info,'warning':'Text prior count is a conservative lower bound; under-cap entries require full predecessor lineage check before launch. No missing target fabricated.'}
 (out/'audit.json').write_text(json.dumps(result,indent=2));print(json.dumps({'visual':len(visual),'recoverable_targets':len(targets),'text':len(text),'text_under_cap_and_target':sum(t['remaining_attempts_upper_bound']>0 and t['target_recoverable'] for t in text),'info_fingerprints':len(info),'info_uncompleted_with_remaining':sum(x['completed_response_count']==0 and x['remaining_calls']>0 for x in info)}))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--out',type=Path,default=ROOT/'outputs/recovery-controlled-info-v13');audit(p.parse_args().out)
