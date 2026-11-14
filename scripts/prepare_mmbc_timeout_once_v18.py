"""Freeze explicitly authorized MMBC VERA timeout-only slots into 2 x 59 one-pass shards.

Retains the V15 physical staging design and actual historical cost lineage.
V18 has a new explicit cutoff and authorization; no old frozen file is changed.
"""
import argparse,copy,hashlib,json,shutil,sys,tempfile
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
R=Path('/mnt/afs_agents/sujiaqi/workspace/projects/AgentContextLab');sys.path.insert(0,str(R/'scripts'))
from bc_route_runtime_v1 import immutable_json
from prepare_mmbc100_campaign import immutable
from prepare_visual_hosted_retry_v1 import load_validate
from prepare_seven_retry3_v10 import configure as configure_pages
from prepare_seven_turns500_v12 import configure as configure_turns
from recovery_once_contract_v18 import VERSION,CUTOFF,DEADLINE,digest,validate_turns,validate_authorization
from mmbc_input_images import stage_images
B=R/'outputs/campaigns/visual-hosted-failure-retry-v1/cells/seven-page-turns500-v12/cells';DEST=R/'outputs/campaigns/mmbc-timeout-once-v18';OPS=R/'outputs/cloud-runtime/mmbc-timeout-once-v18'
NEW=('recovery_once_contract_v18.py','recovery_once_entry_v18.py','run_recovery_once_trial_v18.py','run_recovery_once_v18.py','bootstrap_recovery_once_v18.py','dsh_canvas_worker_v13.py','dsh_inline_wire_v13.mjs','dsh_inline_bridge_v13.py','dsh_canvas_segments_v13.py','network_entry_v13.py')
@lru_cache(None)
def read(p):return json.loads(Path(p).read_text())
@lru_cache(None)
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def raw(v):return (json.dumps(v,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode()
def refcell(row):
 if row['benchmark']=='rq3':return 'rq3_scale_'+f"{round(float(row['method'].split('_')[1])*1000):04d}"
 if row['method']in('visual','vanilla_visual'):
  return ('mmbc_vanilla'if row['method']=='vanilla_visual'else'mmbc_vera')if row['benchmark']=='mmbc100'else'bc_'+row['harness']
 return 'shared_baselines'
def configuration(row):
 source=row['source_job'];cell=refcell(row);plan=read(B/cell/'plan.json');candidates=[j for j in plan['jobs']if j['harness']==row['harness']and j['strategy']==source['strategy']and j['benchmark']==row['benchmark']]
 if candidates:
  cfg=copy.deepcopy(read(candidates[0]['config_path']));template_path=candidates[0]['config_path']
 else:
  # Completed-only old BC baseline groups have no V12 jobs. Reapply the exact
  # existing nonvisual V10->V11->V12 transforms without changing its method.
  cfg=configure_pages(read(source['config_path']),'shared_baselines',False);cfg['runtime_recovery_version']='seven-page-canvas-budget-recovery-v11';cfg=configure_turns(cfg);template_path=source['config_path']
 cfg.update(one_pass_version=VERSION,max_attempts=1,max_timeout_retries=0,max_rounds=500,timeout_seconds=3600,max_output_tokens=8192,turn_limit_version='seven-page-turns500-v12',runtime_recovery_version='seven-page-canvas-budget-recovery-v11',one_hour_retry_version='visual-inline-seven-page-retry3-v10')
 cfg.pop('max_total_model_attempts',None)
 if source['strategy']=='visual':
  assert cfg['visual_page_window']['pages']-cfg['visual_page_window']['recent_pages']==5 and cfg['visual_page_window']['recent_pages']==2
  cfg['visual_image_retention']['max_request_bytes']=32*1024*1024
 return cfg,cell,template_path

def fresh_record(row):
 assert row['benchmark']=='mmbc100' and row['harness']=='hermes' and row['method']=='visual';assert row['state']=='eligible_once' and row.get('selected_completed')is None and not row.get('reservation_evidence')
 assert sha(row['source_plan_path'])==row['source_plan_sha256']
 for e in row.get('result_evidence',[]):
  assert sha(e['path'])==e['sha256'],'Historical result changed since audit'
  if read(e['path']).get('status')=='completed' and (row['benchmark']!='rq3' or '/seven-page-'in e['path'] or '/deepseek-once24h-'in e['path']):raise ValueError('Completed slot must be retained')
 # Old claims may remain after cleanup. Only a new post-cutoff dispatch can make
 # this snapshot invalid; all managed old dispatchers have STOP before freezing.
 for c in row.get('historical_claims',[]):
  owner=c.get('owner',{});claimed=owner.get('claimed_at')
  assert not c.get('active_at_cutoff',False)
 return True

def build(name,rows,manifest_path,cleanup_path=None,freeze=True):
 assert 1<=len(rows)<=59;root=DEST/'cells'/name;bindings={str(manifest_path):sha(manifest_path)};jobs=[];cohort={};configs={};templates=[];authjobs={};all_costs={};ref=refcell(rows[0]);sourceplan=read(B/ref/'plan.json')
 for row in rows:
  fresh_record(row);source=row['source_job'];cfg,cell,template=configuration(row);assert cell==ref
  cfgdata=raw(cfg);cfgsha=hashlib.sha256(cfgdata).hexdigest();cfgpath=root/'configs'/(cfgsha+'.json');immutable(cfgpath,cfgdata);configs[cfgsha]=cfgdata;templates.append(template);bindings[template]=sha(template);bindings[row['source_plan_path']]=row['source_plan_sha256']
  j=copy.deepcopy(source)
  for k in ('one_pass_authorization_path','one_pass_authorization_sha256','additional_attempt_authorization_path','additional_attempt_authorization_sha256','additional_attempt_source_cell','additional_attempt_protocol','authorized_total_model_attempts','max_total_model_attempts','previous_v8_attempt'):j.pop(k,None)
  costs=copy.deepcopy([x for x in row['cost_records']if x['consumed']]);operational=copy.deepcopy([x for x in row['cost_records']if not x['consumed']]);assert len(costs)==row['prior_attempts_consumed_conservative'];all_costs[row['slot_id']]=row['cost_records']
  for cost in costs+operational:
   if cost.get('result_path'):assert sha(cost['result_path'])==cost['result_sha256'];bindings[cost['result_path']]=cost['result_sha256']
  clean=all(c.get('cleanup_confirmed')for c in costs)
  if not clean:
   if cleanup_path:
    proofs={p['attempt_path']:p for p in read(cleanup_path)['records']if p['slot_id']==row['slot_id']}
    clean=all(c.get('cleanup_confirmed') or (proofs.get(c['attempt_path'],{}).get('cleanup_confirmed')is True)for c in costs);bindings[str(cleanup_path)]=sha(cleanup_path)
    aliases=read(OPS/'audit/cleanup-path-aliases.json');bindings[str(OPS/'audit/cleanup-path-aliases.json')]=sha(OPS/'audit/cleanup-path-aliases.json')
    for p,h in read(cleanup_path)['source_sha256'].items():
     shared=aliases.get(p,{}).get('shared_path',p);assert sha(shared)==h;bindings[shared]=h
   if not clean:raise ValueError('Historical cleanup proof missing: '+row['slot_id'])
  cohortsource=Path(source.get('native_cohort_path')or Path(row['source_plan_path']).parent/'cohort.jsonl');cohortdata=cohortsource.read_bytes();cohortsha=hashlib.sha256(cohortdata).hexdigest();nativecohort=root/'cohorts'/(cohortsha+'.jsonl');immutable(nativecohort,cohortdata);bindings[str(cohortsource)]=cohortsha
  j.update(slot_id=row['slot_id'],cell=name,config_path=str(cfgpath),config_sha256=cfgsha,native_cohort_path=str(nativecohort),native_cohort_sha256=cohortsha,one_pass_version=VERSION,prior_attempts_consumed=len(costs),prior_attempt_costs=costs,prior_operational_attempts=operational,new_authorized_ordinal=len(costs)+1,current_generation_attempt_limit=1,max_attempts=1,max_timeout_retries=0,timeout_seconds=3600,max_rounds=500,one_hour_retry_version=cfg['one_hour_retry_version'],turn_limit_version=cfg['turn_limit_version'],runtime_recovery_version=cfg['runtime_recovery_version'],visual_hosted_retry_version='visual-hosted-failure-retry-v1')
  for k in ('dsh_buffered_watchdog_version','approved_model_routes','model_route_policy','image_transport','transport_runtime_version','transport_delivery_version','gateway_proxy'):j[k]=copy.deepcopy(cfg[k])
  if j['strategy']=='visual':
   scale=float(row['method'].split('_')[1])if row['benchmark']=='rq3'else .75
   j.update(scale=scale,scale_key=f'scale_{round(scale*1000):04d}',bounded_max_images=10,bounded_request_protocol='bounded-multimodal-recent-ten-v1',bounded_image_retention='last_10_in_message_order',bounded_benchmark='mmbc100'if row['benchmark']=='mmbc100'else'bc100')
   key='bounded_rq3_protocol'if row['benchmark']=='rq3'else'bounded_visual_protocol'if row['benchmark']=='mmbc100'else'bounded_bc_protocol';j[key]=cfg[key]
  validate_turns(j,cfg)
  cohort[j['question_id']]={'id':j['question_id'],'question_id':j['question_id'],'question':j['question'],**({'image':j['image']}if j.get('image')else{})}
  authjobs[j['slot_id']]={**{k:j[k]for k in ('job_id','model','harness','strategy','question_id','repeat','config_sha256')},'destination_root':str(root),'dispatch_allowed':True,'active_at_cutoff':False,'completed_retained':False,'prior_attempts_consumed':len(costs),'prior_cost_ledger_sha256':digest(costs),'cleanup_confirmed':True,'latest_result_path':row['latest_result_path'],'latest_result_sha256':row['latest_result_sha256']}
  jobs.append(j)
 immutable(root/'experiment.json',configs[jobs[0]['config_sha256']]);cohortdata=''.join(json.dumps(cohort[k],ensure_ascii=False,sort_keys=True)+'\n'for k in sorted(cohort)).encode();immutable(root/'cohort.jsonl',cohortdata)
 if rows[0]['benchmark']=='mmbc100':
  assets=read(B/'mmbc_vera/image-assets/manifest.json');selected={}
  for url in sorted({u for j in jobs for u in j.get('image',[])}):
   rec=assets['images'][url];src=B/'mmbc_vera'/rec['relative_path'];assert sha(src)==rec['sha256'];dst=root/rec['relative_path'];immutable(dst,src.read_bytes());selected[url]=rec
  immutable_json(root/'image-assets/manifest.json',{'version':assets['version'],'cohort_sha256':sha(root/'cohort.jsonl'),'images':selected})
 authpath=root/'one-pass-authorization.json';immutable_json(authpath,{'version':VERSION,'user_authorized':True,'cutoff_utc':CUTOFF,'deadline_utc':DEADLINE,'additional_attempts_per_slot':1,'source_audit_sha256':sha(manifest_path),'selection_report_path':read(manifest_path)['selection_report_path'],'selection_report_sha256':read(manifest_path)['selection_report_sha256'],'jobs':authjobs});bindings[str(authpath)]=sha(authpath)
 for j in jobs:j.update(one_pass_authorization_path=str(authpath),one_pass_authorization_sha256=sha(authpath));validate_authorization({**j,'campaign_root':str(root)})
 implementation=copy.deepcopy(sourceplan['definition']['implementation_sha256'])
 for file in NEW:
  p=R/'scripts'/file
  if p.exists():implementation[str(p.relative_to(R))]=sha(p)
 implementation[str(Path(__file__).resolve().relative_to(R))]=sha(Path(__file__).resolve())
 definition={'execution_version':'visual-hosted-failure-retry-v1','one_hour_retry_version':'visual-inline-seven-page-retry3-v10','one_pass_version':VERSION,'turn_limit_version':'seven-page-turns500-v12','runtime_recovery_version':'seven-page-canvas-budget-recovery-v11','cell':name,'harnesses':sorted({j['harness']for j in jobs}),'per_cell_concurrency_cap':16,'planned_runs':len(jobs),'cohort_sha256':sha(root/'cohort.jsonl'),'config_sha256':sha(root/'experiment.json'),'implementation_sha256':implementation,'source_results_sha256':bindings,'selection_uses_answers':False,'any_completed_retained':True,'max_new_attempts':1,'maximum_new_attempts':1,'timeout_seconds':3600,'max_rounds':500,'max_attempts':1,'max_timeout_retries':0,'deadline_utc':DEADLINE,'cutoff_utc':CUTOFF}
 if rows[0]['benchmark']=='mmbc100':definition['input_images_sha256']=sha(root/'image-assets/manifest.json')
 if not freeze:return {'root':str(root),'planned_runs':len(jobs),'prepared_inputs_only':True}
 immutable_json(root/'plan.json',{'definition':definition,'jobs':jobs});m={'version':'visual-hosted-failure-retry-v1','one_pass_version':VERSION,'root':str(root),'cell':name,'harness':jobs[0]['harness'],'planned_runs':len(jobs),'plan_sha256':sha(root/'plan.json')};immutable_json(root/'campaign-manifest.json',m);load_validate(root)
 if rows[0]['benchmark']=='mmbc100':
  with tempfile.TemporaryDirectory(prefix='once24h-stage-')as tmp:stage_images({'campaign_root':str(root),'image':sorted({u for j in jobs for u in j.get('image',[])})},tmp)
 immutable_json(root/'audit-cost-records.json',{'historical_costs':all_costs,'template_paths':sorted(set(templates)),'new_attempts_per_slot':1});return m

def main():
 p=argparse.ArgumentParser();p.add_argument('--manifest',type=Path,required=True);p.add_argument('--cleanup',type=Path);p.add_argument('--samples',action='store_true');p.add_argument('--freeze',action='store_true');a=p.parse_args();v=read(a.manifest);assert v['eligible_count']==len(v['jobs']);groups=defaultdict(list)
 if a.samples:
  for label,predicate in [('sample_hermes_visual',lambda j:j['harness']=='hermes'and j['method']=='visual'),('sample_dsh_visual',lambda j:j['harness']=='dsh'and j['method']=='visual'),('sample_dsh_baseline',lambda j:j['harness']=='dsh'and j['method']=='discard')]:
   groups[label]=[next(j for j in v['jobs']if predicate(j)and all(c['cleanup_confirmed']for c in j['cost_records']if c['consumed']))]
 else:
  for j in v['jobs']:groups[j['shard_id']].append(j)
 rows=[]
 for name,items in sorted(groups.items()):
  m=build(name,items,a.manifest,a.cleanup,a.freeze);rows.append(m);print(json.dumps(m),flush=True)
 if a.freeze and not a.samples:immutable_json(DEST/'inventory.json',{'version':'visual-hosted-failure-retry-v1','one_pass_version':VERSION,'cells':rows,'concurrency_per_cell':16,'global_cap':None,'deadline_utc':DEADLINE})
if __name__=='__main__':main()
