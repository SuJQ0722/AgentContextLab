"""Reviewable one-extra visual continuation, pinned to an existing measured target.

Dry/prepare only unless a separate explicit authorization names this exact plan.
No old prediction or calibration result is overwritten or promoted to accuracy.
"""
import argparse,base64,copy,hashlib,io,json,math,sys
from pathlib import Path
from unittest.mock import patch
from lab import ROOT
import controlled_inline_retry_v8 as v8
import controlled_native_worker_bounded_v1 as bounded
from controlled_transport_v5 import DiagnosticRecorder
from inline_visual_transport_v1 import transform
VERSION='controlled-visual-same-target-v13'
REVIEW=ROOT/'outputs/recovery-controlled-info-v13/formal-visual-extra-one-review/manifest.json'
DEST=ROOT/'outputs/campaigns/visual-hosted-failure-retry-v1/cells/transport-v13-formal-visual-extra-one'
def read(p):return json.loads(Path(p).read_text())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(p,value):
 p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(value,indent=2))
def immutable(p,raw):
 p.parent.mkdir(parents=True,exist_ok=True)
 if p.exists() and p.read_bytes()!=raw:raise ValueError('Frozen artifact changed')
 if not p.exists():p.write_bytes(raw)
class TargetGate:
 def __init__(self,target):
  if not v8.valid_target(target):raise ValueError('Uncertified target')
  self.target=target;self.lower=math.ceil(target['first_actual_prompt_tokens']*.98);self.upper=min(16384,math.floor(target['first_actual_prompt_tokens']*1.02));self.raised=False;self.first_agent_observed=False
 def check(self,count,stage):
  if type(count)!=int or not self.lower<=count<=self.upper:raise bounded.v5.BudgetInfeasible('Pinned visual '+stage+' usage absent/outside shared target ±2%')
 def budget(self,record):
  if record.get('method')=='visual':
   if record.get('canvas_scale')!=1:raise bounded.v5.BudgetInfeasible('Pinned visual cannot change reference resolution')
   self.check(record.get('prompt_tokens'),'calibration')
 def annotate(self,value):
  value.update(pinned_visual_target_tokens=self.target['first_actual_prompt_tokens'],pinned_target_lower=self.lower,pinned_target_upper=self.upper,visual_reference_resolution_fixed=True)
  if 'first_actual_prompt_tokens' in value:
   try:self.check(value['first_actual_prompt_tokens'],'actual')
   except bounded.v5.BudgetInfeasible:
    value.update(passed=False,fatal_error='BudgetInfeasible',failure_category='scientific_budget_or_integrity',failure_message='Actual visual prompt outside immutable ±2% target')
    if not self.raised:self.raised=True;raise

def adapter_class(target,representation_path,expected_sha):
 class Replay(bounded.BoundedAdapter):
  def __init__(self,spec,out):
   super().__init__(spec,out)
   # Preserve historical wire bytes, not merely a freshly encoded equivalent.
   if sha(representation_path)!=expected_sha:raise ValueError('Reference representation changed')
   pages=read(representation_path);proofs={}
   journal=representation_path.parent/'bounded-fit-registrations.jsonl'
   for line in journal.read_text().splitlines():
    for proof in json.loads(line).get('encoding_proofs',[]):proofs.setdefault(proof['source_sha256'],proof)
   from PIL import Image
   for part in pages:
    raw=bounded.raw(part);identity=hashlib.sha256(raw).hexdigest()
    if identity not in proofs:raise ValueError('Historical encoding proof missing')
    proof=proofs[identity];path=representation_path.parent/'bounded-transport'/(proof['output_sha256']+'.webp');encoded=path.read_bytes()
    if hashlib.sha256(encoded).hexdigest()!=proof['output_sha256']:raise ValueError('Historical encoded bytes changed')
    with Image.open(io.BytesIO(raw)) as original,Image.open(io.BytesIO(encoded)) as restored:
     if original.size!=restored.size or original.convert('RGBA').tobytes()!=restored.convert('RGBA').tobytes():raise ValueError('Historical encoded pixels differ')
    wire_part=copy.deepcopy(part);wire_part['image_url']['url']='data:image/webp;base64,'+base64.b64encode(encoded).decode()
    self.encoding_cache[identity]=(wire_part,{**proof,'historical_wire_bytes_reused':True,'new_encoding_seconds':0})
  def render_prefix(self,messages,font_size):
   if sha(representation_path)!=expected_sha:raise ValueError('Pinned representation changed')
   pages=read(representation_path)
   if not pages or any(x.get('type')!='image_url' for x in pages):raise ValueError('Expected exact image-only reference representation')
   self.set_pages(pages);return copy.deepcopy(pages),0.0
  def annotate(self,value):
   result=super().annotate(value);result.update(reference_representation_replayed=True,reference_representation_sha256=expected_sha,reference_effective_canvas_linear_scale=target.get('effective_canvas_linear_scale'),effective_canvas_linear_scale=target.get('effective_canvas_linear_scale'),new_render_seconds=0.0)
   return result
 return Replay

def prepare():
 review=read(REVIEW);jobs=[];root0=ROOT/'outputs/campaigns/visual-hosted-failure-retry-v1/cells/transport-v8-one-hour-retry5/cells'
 for item in review['jobs']:
  if not item['current_target_available']:continue
  cell='controlled_bc' if item['dataset']=='browsecomp_v3' else 'controlled_mmbc';old=next(j for j in read(root0/cell/'plan.json')['jobs'] if j['job_id']==item['job_id']);root=DEST/'cells'/cell;target=Path(item['target_source']);value=read(target);representation=target.parent/'representation.json';spec=read(old['controlled_spec_path'])
  if sha(target)!=item['target_sha256'] or not v8.valid_target(value):raise ValueError('Target proof changed')
  if not representation.exists():raise ValueError('Reference representation missing')
  new=copy.deepcopy(old);new.update(campaign_root=str(root),controlled_target_root=str(root),control_target_path=str(v8.target_path(root,item['job_id'].rsplit('/',1)[0])),max_timeout_retries=0,timeout_seconds=3600)
  immutable(Path(new['control_target_path']),target.read_bytes());sp=root/'controlled-specs'/Path(old['controlled_spec_path']).name;immutable(sp,(json.dumps(spec,sort_keys=True,indent=2)+'\n').encode());new.update(controlled_spec_path=str(sp),controlled_spec_sha256=sha(sp))
  new['same_target_v13']={'target_source':str(target),'target_sha256':sha(target),'representation_path':str(representation),'representation_sha256':sha(representation),'prior_v8_attempts':6,'additional_attempts':1,'max_iterations':500,'calibration_not_scored':False}
  # Actual image pipeline replay, not a fabricated blank-canvas fixture.
  out=DEST/'offline-preflight'/cell/old['job_id'];cls=adapter_class(value,representation,sha(representation));adapter=cls(spec,out);pages,_=adapter.render_prefix([],16);original=adapter.original_compose;adapter.original_compose=lambda current,q,n,r:v8.native_last_compose(original,out,current,q,n,r)
  messages=adapter.compose([{'role':'user','content':old['question']}],old['question'],adapter.native,pages)
  wire,audit=transform(json.dumps({'model':old['model'],'messages':messages}).encode(),rendered_registry=adapter.registry)
  actual=[(x['sha256'],x.get('detail'),x['origin']) for x in audit['selection']['retained']]
  previous=[]
  for line in (target.parent/'metrics/inline-images-wire-v1.jsonl').read_text().splitlines():
   r=json.loads(line)
   if r.get('decision')=='allow' and any(x.get('origin')=='canvas' for x in r.get('selection',{}).get('retained',[])):
    previous.append([(x['sha256'],x.get('detail'),x['origin']) for x in r['selection']['retained']])
  if actual not in previous:raise ValueError('Replay image order/bytes/detail differ from historical final HTTP evidence')
  write(out/'image-parity.json',{'passed':True,'source_target_sha256':sha(target),'image_sequence_exact':True,'final_image_count':len(actual),'body_bytes_test_envelope':len(wire),'calibration_model_calls':0,'model_calls':0,'request_image_ledger':actual,'native_preserved':True,'not_full_original_http_text_equality':True})
  v8.validate(new,root/'jobs'/new['job_id']/'extra_001');jobs.append(new)
 plan={'version':VERSION,'jobs':jobs,'review_path':str(REVIEW),'review_sha256':sha(REVIEW),'model_calls':0,'launch_ready_offline':True,'launch_authorized':False,'additional_attempt_cap':len(jobs),'missing_target_jobs_excluded':5,'implementation_sha256':{n:sha(ROOT/'scripts'/n) for n in ['controlled_visual_same_target_v13.py','network_entry_v13.py']}}
 immutable(DEST/'plan.json',(json.dumps(plan,sort_keys=True,indent=2)+'\n').encode());print(json.dumps({'offline_passed':len(jobs),'paid_calls':0,'plan_sha256':sha(DEST/'plan.json'),'launch_authorized':False}))

def worker(specpath,out,authorization):
 plan=read(DEST/'plan.json');job=read(specpath);auth=read(authorization)
 if out.resolve()!=(Path(job['campaign_root'])/'jobs'/job['job_id']/'extra_001').resolve():raise ValueError('One canonical extra attempt directory required')
 if auth.get('additional_attempts_per_job')!=1:raise ValueError('Exactly one extra attempt must be explicitly authorized')
 if job not in plan['jobs'] or auth.get('plan_sha256')!=sha(DEST/'plan.json') or auth.get('authorized') is not True or job['job_id'] not in auth.get('job_ids',[]):raise ValueError('Explicit additional-attempt authorization absent')
 for name,digest in plan['implementation_sha256'].items():
  if sha(ROOT/'scripts'/name)!=digest:raise ValueError('Frozen worker changed')
 if(out/'attempt-started.json').exists():raise ValueError('Only one explicitly additional native launch')
 proof=job['same_target_v13'];target=read(proof['target_source']);gate=TargetGate(target);original_validate=v8.validate;original_write=DiagnosticRecorder.write;original_annotate=v8.parent.annotate
 def validate(j,d):
  spec,cfg=original_validate(j,d);return {**spec,'max_rounds':500},cfg
 def recorder_write(self,name,value,*args,**kwargs):
  result=original_write(self,name,value,*args,**kwargs)
  if name=='budget-attempts.jsonl':gate.budget(value)
  if name=='calls.jsonl' and value.get('purpose')=='agent' and not gate.first_agent_observed:
   gate.first_agent_observed=True;gate.check((value.get('raw_provider_usage') or {}).get('prompt_tokens'),'first actual ledger including failed stream')
  return result
 def annotate(value,d):
  result=original_annotate(value,d)
  try:gate.annotate(result)
  except bounded.v5.BudgetInfeasible:
   value.update(result);write(d/'pinned-target-failure.json',result);raise
  return result
 sys.argv=[v8.__file__,'--spec',str(specpath),'--out',str(out),'--live']
 with patch.object(v8,'validate',validate),patch.object(bounded,'BoundedAdapter',adapter_class(target,Path(proof['representation_path']),proof['representation_sha256'])),patch.object(DiagnosticRecorder,'write',recorder_write),patch.object(v8.parent,'annotate',annotate):v8.main()

def main():
 p=argparse.ArgumentParser();p.add_argument('--prepare',action='store_true');p.add_argument('--spec',type=Path);p.add_argument('--out',type=Path);p.add_argument('--authorization',type=Path);p.add_argument('--live',action='store_true');a=p.parse_args()
 if a.prepare:prepare();return
 if not a.live:print(json.dumps({'live':False,'requires_explicit_extra_attempt_authorization':True}));return
 if not(a.spec and a.out and a.authorization):p.error('Explicit spec/output/authorization required')
 worker(a.spec,a.out,a.authorization)
if __name__=='__main__':main()
