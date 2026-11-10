"""Freeze execution-only retries; any completed lineage is retained without judging."""
import argparse,copy,json
from pathlib import Path
from lab import ROOT
from prepare_mmbc100_campaign import sha,read,digest,immutable,immutable_json
VERSION='visual-hosted-failure-retry-v1'
DEFAULT=ROOT/'outputs/campaigns'/VERSION
NEW=['prepare_visual_hosted_retry_v1.py','run_visual_hosted_retry_v1.py','run_visual_hosted_retry_trial_v1.py','hermes_visual_hosted_retry_worker_v1.py','verified_hosted_images_v3.py','visual_transport_runtime_v2.py','verified_canvas_registry_cache.py','recent_ten_images_transport_v1.py','hermes_mmbc_hosted_worker_v3.py','hermes_mmbc_transport_worker_v2.py','hermes_bounded_mmbc_recent_ten_worker_v1.py','hermes_bounded_mmbc_ten_image_worker_v1.py','bounded_ten_image_guard_v1.py','bootstrap_visual_hosted_retry_v1.py']
def observations(name):
 p=ROOT/'outputs/grading'/name
 return [json.loads(s)for s in p.read_text().splitlines()]if p.suffix=='.jsonl'else read(p)
def select(attempts):
 records=[]
 for a in dict.fromkeys(map(str,attempts)):
  p=Path(a)/'result.json';r=read(p)
  if r.get('slot_released')is not True or r.get('unconfirmed_child_termination')!=[]:raise ValueError('Unconfirmed source cleanup')
  records.append({'path':str(p),'sha256':sha(p),'status':r['status']})
 completed=next((r for r in records if r['status']=='completed'),None)
 if completed:return False,records
 if not records or records[-1]['status']not in ('failed','timeout'):raise ValueError('Unresolved latest execution')
 return True,records

def prepare(root=DEFAULT):
 root=Path(root).resolve();cells={}
 bc=observations('bc100-v3-deepseek-sfb-v1/analysis/selected-observations.jsonl')
 rq=observations('rq3-final-seven-v3/observations.jsonl')
 mm=observations('mmbc100-deepseek-hermes-v1/observations.json')
 vanilla=observations('mmbc100-hermes-vanilla-v1/observations.json')
 for h in ('hermes','dsh'):cells['bc_'+h]=('bc',[r for r in bc if r['harness']==h and r['method']=='visual'],'bc-bounded-retry-v1')
 for s in (0,.25,.5,.7,.75,.8,1):cells[f'rq3_scale_{round(s*1000):04d}']=('rq3',[r for r in rq if r['scale']==s],'rq3-bounded-failure-retry-v1')
 cells['mmbc_vera']=('mmbc',[r for r in mm if r['method']=='visual'],'mmbc-vera-bounded-retry-v1')
 cells['mmbc_vanilla']=('mmbc',vanilla,None)
 inventory=[]
 for cell,(kind,rows,bounded)in cells.items():
  dest=root/'cells'/cell;jobs=[];records=[];source_hashes={};base=None;cohort=None;assets_parent=None
  for row in rows:
   original=Path(row['attempt']);source_spec=read(original.parents[1]/'spec.json');attempts=[original]
   # First-pass execution is also retained if an intermediate fixed retry exists.
   if kind=='bc':
    first=ROOT/'outputs/campaigns/bc100-r3-hermes-parity-v3/jobs'/row['job_id']/'attempts/attempt_001'
    if (first/'result.json').exists()and first!=original:attempts.insert(0,first)
   latest=source_spec
   if bounded:
    p=ROOT/'outputs/campaigns'/bounded/'jobs'/row['job_id']
    if (p/'attempts/attempt_001/result.json').exists():attempts.append(p/'attempts/attempt_001');latest=read(p/'spec.json')
   selected,lineage=select(attempts);records.append({'job_id':row['job_id'],'selected':selected,'lineage':lineage})
   for r in lineage:source_hashes[r['path']]=r['sha256']
   if base is None:
    base=read(latest['config_path']);parent=Path(source_spec['campaign_root']);cohort=parent/'cohort.jsonl';assets_parent=parent
   if not selected:continue
   allowed=('job_id','harness','question_id','question','repeat','strategy','model','timeout_seconds','image','scale','scale_key','method_label')
   j={k:latest[k]for k in allowed if k in latest};j.update(visual_hosted_retry_version=VERSION,experiment_kind=kind,cell=cell,model='deepseek-v4.1-flash-1017/huoshan/huoshan',config_path=str(dest/'experiment.json'),image_transport='verified-imgbb-url-v1',transport_runtime_version='visual-transport-runtime-v2',bounded_request_protocol='bounded-multimodal-recent-ten-v1',bounded_max_images=10,bounded_image_retention='last_10_in_message_order',bounded_benchmark='mmbc100'if kind=='mmbc'else'bc100')
   if kind=='bc':j.update(scale=.75,scale_key='scale_0750',bounded_bc_protocol='bc-bounded-pages-v1')
   elif kind=='rq3':j.update(scale=row['scale'],scale_key=f"scale_{round(row['scale']*1000):04d}",bounded_rq3_protocol='rq3-bounded-pages-v1')
   else:j.update(scale=.75,bounded_visual_protocol='bounded-multimodal-pages-v1')
   jobs.append(j)
  cfg=copy.deepcopy(base);template=read(ROOT/'configs/experiment.mmbc-hosted-v3.json')
  for k in ('image_transport','transport_runtime_version','transport_runtime_policy','bounded_request_protocol','bounded_max_images','bounded_image_retention','bounded_transport_encoding'):cfg[k]=template[k]
  scale=rows[0].get('scale')if kind=='rq3'else .75
  cfg.update(campaign_version=VERSION,review_approved=True,execution_version='hermes-parity-v3',model=template['model'],bounded_benchmark='mmbc100'if kind=='mmbc'else'bc100')
  cfg['visual_renderer'].update(history_scale=scale,font_size=16)
  cfg['shared_policy']['strategy_configs']['visual'].update(history_scale=scale,font_size=16,image_width=1024,max_image_height=2048,history_max_image_height=2048,keep_rounds=1,recent_rounds=5,text_only=cell=='mmbc_vanilla')
  cfg['bounded_visual_protocol'if kind=='mmbc'else'bounded_bc_protocol'if kind=='bc'else'bounded_rq3_protocol']='bounded-multimodal-pages-v1'if kind=='mmbc'else'bc-bounded-pages-v1'if kind=='bc'else'rq3-bounded-pages-v1'
  immutable_json(dest/'experiment.json',cfg)
  public=[]
  for r in map(json.loads,cohort.read_text().splitlines()):public.append({k:v for k,v in r.items()if k in ('id','question_id','question','image')})
  immutable(dest/'cohort.jsonl',(''.join(json.dumps(r,ensure_ascii=False)+'\n'for r in public)).encode())
  if kind=='mmbc':
   for p in (assets_parent/'image-assets').rglob('*'):
    if p.is_file() and p.name!='manifest.json':immutable(dest/p.relative_to(assets_parent),p.read_bytes())
   asset=read(assets_parent/'image-assets/manifest.json');asset['cohort_sha256']=sha(dest/'cohort.jsonl');immutable_json(dest/'image-assets/manifest.json',asset)
  for j in jobs:j['config_sha256']=sha(dest/'experiment.json')
  hashes={}
  for parent in [ROOT/'outputs/campaigns'/bounded]if bounded else[assets_parent]:hashes.update(read(parent/'plan.json')['definition']['implementation_sha256'])
  for n in NEW:hashes['scripts/'+n]=sha(ROOT/'scripts'/n)
  if cell=='bc_dsh':
   import dsh_hosted_bc_worker_v1 as dw
   for n in ['scripts/dsh_hosted_bc_worker_v1.py',*dw.BOUNDED_SOURCE_FILES]:hashes[n]=sha(ROOT/n)
  definition={'execution_version':VERSION,'cell':cell,'harnesses':['hermes','dsh'],'per_cell_concurrency_cap':16,'planned_runs':len(jobs),'cohort_sha256':sha(dest/'cohort.jsonl'),'config_sha256':sha(dest/'experiment.json'),'implementation_sha256':hashes,'source_results_sha256':source_hashes,'selection_uses_answers':False,'any_completed_retained':True,'maximum_new_attempts':1}
  if kind=='mmbc':definition['input_images_sha256']=sha(dest/'image-assets/manifest.json')
  immutable_json(dest/'selection.json',{'records':records,'no_answer_fields_read_for_selection':True})
  immutable_json(dest/'plan.json',{'definition':definition,'jobs':jobs})
  m={'root':str(dest),'cell':cell,'harness':rows[0].get('harness','hermes'),'planned_runs':len(jobs),'retained_completed':len(rows)-len(jobs),'plan_sha256':sha(dest/'plan.json'),'version':VERSION}
  immutable_json(dest/'campaign-manifest.json',m);inventory.append(m)
 inventory.extend(prepare_controlled(root))
 immutable_json(root/'inventory.json',{'version':VERSION,'cells':inventory,'concurrency_per_cell':16,'global_cap':None})
 return inventory

def prepare_controlled(root):
 rows=read(ROOT/'outputs/preflight/visual-hosted-retry-inventory/controlled.json');source=ROOT/'outputs/experiment3/controlled-native-bounded-v1';plan=read(source/'plan.json');byid={j['job_id']:j for j in plan['jobs']};items=[]
 for cell,dataset in [('controlled_bc','browsecomp_v3'),('controlled_mmbc','mmbrowsecomp')]:
  dest=root/'cells'/cell;cfg=read(source/'experiment.json');template=read(ROOT/'configs/experiment.mmbc-hosted-v3.json')
  for k in ('image_transport','transport_runtime_version','transport_runtime_policy','bounded_request_protocol','bounded_max_images','bounded_image_retention'):cfg[k]=template[k]
  cfg.update(execution_version='hermes-parity-v3',review_approved=True,campaign_version=VERSION)
  immutable_json(dest/'experiment.json',cfg);immutable(dest/'cohort.jsonl',b'')
  jobs=[];bindings={}
  for r in rows:
   if r['dataset']!=dataset or not r['eligible_retry']:continue
   sourcejob=byid[r['job_id']];sp=Path(sourcejob['spec_path']);spec=read(sp)
   jobs.append({'job_id':r['job_id'],'harness':'hermes','strategy':'visual','question_id':spec['question_id'],'question':spec['question'],'repeat':spec['repeat'],'model':spec['model'],'timeout_seconds':3600,'controlled_spec_path':str(sp),'controlled_spec_sha256':sha(sp),'visual_hosted_retry_version':VERSION,'experiment_kind':'controlled','cell':cell,'config_path':str(dest/'experiment.json'),'config_sha256':sha(dest/'experiment.json')})
   trial=Path(sourcejob['out'])/'trial-status.json'
   state=read(trial)
   if state.get('worker_reaped') is not True or state.get('status') not in ('failed','timeout'):
    raise ValueError('Controlled retry requires a confirmed failed/timeout trial')
   old=ROOT/r['old_result_path']
   if read(old).get('status')=='completed':raise ValueError('Never retry historical completed controlled arm')
   paths=[sp,trial,old,Path(spec['prefix_path'])]
   result=Path(sourcejob['out'])/'result.json'
   if result.exists():paths.append(result)
   for path in paths:bindings[str(path)]=sha(path)
  hashes=dict(plan['definition']['implementation_sha256']);hashes.update({n:sha(ROOT/n)for n in ['scripts/'+n for n in NEW]+['scripts/controlled_hosted_visual_worker_v1.py']})
  definition={'execution_version':VERSION,'cell':cell,'harnesses':['hermes','dsh'],'per_cell_concurrency_cap':16,'planned_runs':len(jobs),'cohort_sha256':sha(dest/'cohort.jsonl'),'config_sha256':sha(dest/'experiment.json'),'implementation_sha256':hashes,'source_results_sha256':bindings,'selection_uses_answers':False,'any_completed_retained':True,'maximum_new_attempts':1}
  immutable_json(dest/'plan.json',{'definition':definition,'jobs':jobs});m={'root':str(dest),'cell':cell,'harness':'hermes','planned_runs':len(jobs),'plan_sha256':sha(dest/'plan.json'),'version':VERSION};immutable_json(dest/'campaign-manifest.json',m);items.append(m)
 return items

def validate_sources(plan,root):
 root=Path(root);d=plan['definition']
 if d.get('execution_version')!=VERSION or d.get('per_cell_concurrency_cap')!=16:raise ValueError('Unexpected retry version')
 for key,name in [('config_sha256','experiment.json'),('cohort_sha256','cohort.jsonl')]:
  if sha(root/name)!=d[key]:raise ValueError('Frozen input changed '+name)
 for p,h in d['implementation_sha256'].items():
  if sha(ROOT/p)!=h:raise ValueError('Frozen implementation changed '+p)
 for p,h in d['source_results_sha256'].items():
  if sha(p)!=h:raise ValueError('Source result changed')
def load_validate(root):
 root=Path(root);plan=read(root/'plan.json');validate_sources(plan,root);m=read(root/'campaign-manifest.json')
 if sha(root/'plan.json')!=m['plan_sha256']:raise ValueError('Plan changed')
 return plan,m
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=DEFAULT);a=p.parse_args();print(json.dumps(prepare(a.root)))
