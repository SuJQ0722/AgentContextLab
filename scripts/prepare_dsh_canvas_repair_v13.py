"""Partition never-claimed V12 DSH visual jobs without resetting attempt budgets."""
import copy,hashlib,json,shutil,time
from pathlib import Path
from lab import ROOT
from bootstrap_turns500_v12 import load_validate
from bc_route_runtime_v1 import immutable_json
from prepare_mmbc100_campaign import immutable
BASE=ROOT/'outputs/campaigns/visual-hosted-failure-retry-v1/cells/seven-page-turns500-v12'
SOURCE=BASE/'cells/bc_dsh'
DEST=BASE/'cells/bc_dsh_handle_v13'
OUT=ROOT/'outputs/cloud-runtime/dsh-canvas-handle-v13'
FILES=['scripts/'+n for n in ('dsh_canvas_segments_v13.py','dsh_inline_bridge_v13.py','dsh_inline_wire_v13.mjs','dsh_canvas_worker_v13.py','dsh_canvas_trial_v13.py','dsh_canvas_entry_v13.py','prepare_dsh_canvas_repair_v13.py')]
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
 if (DEST/'plan.json').exists():
  load_validate(DEST);print('Existing immutable partition validated; not reselected');return
 plan,manifest=load_validate(SOURCE)
 if list((SOURCE/'controllers').glob('*/*/owner.json'))or list((SOURCE/'leases').glob('*/owner.json')):raise ValueError('Original controller identity requires drain review')
 for j in plan['jobs']:
  d=SOURCE/'jobs'/j['job_id']
  if d.exists()and any(d.iterdir()):raise ValueError('Never-claimed partition only')
  if j['prior_attempts_consumed']!=len(j['prior_attempt_costs'])or j['current_generation_attempt_limit']!=3-j['prior_attempts_consumed']:raise ValueError('Inherited budget mismatch')
  if j['prior_attempts_consumed']>=3:raise ValueError('No cumulative attempt budget remains')
  if j['harness']!='dsh'or j['strategy']!='visual'or j['timeout_seconds']!=3600 or j['max_rounds']!=500:raise ValueError('Unexpected scope')
 OUT.mkdir(parents=True,exist_ok=True)
 immutable_json(SOURCE/'STOP',{'reason':'Never-claimed jobs moved to independent handle-repair partition','destination':str(DEST),'source_plan_sha256':sha(SOURCE/'plan.json'),'at_unix':time.time(),'original_results_untouched':True})
 DEST.mkdir(parents=True,exist_ok=True)
 for name in('experiment.json','cohort.jsonl'):immutable(DEST/name,(SOURCE/name).read_bytes())
 for name in('configs','cohorts','image-assets'):
  if(SOURCE/name).exists():shutil.copytree(SOURCE/name,DEST/name,dirs_exist_ok=True,symlinks=False)
 jobs=copy.deepcopy(plan['jobs'])
 for j in jobs:
  j['config_path']=str(DEST/'configs'/Path(j['config_path']).name)
  j['native_cohort_path']=str(DEST/'cohorts'/Path(j['native_cohort_path']).name)
  if sha(j['config_path'])!=j['config_sha256']or sha(j['native_cohort_path'])!=j['native_cohort_sha256']:raise ValueError('Physical copy changed input bytes')
 definition=copy.deepcopy(plan['definition']);definition.update(cell=DEST.name,dispatch_partition_version='dsh-canvas-handle-v13',dispatch_source_plan_sha256=sha(SOURCE/'plan.json'),bridge_repair_version='dsh-canvas-handle-segments-v13',planned_runs=len(jobs))
 definition['source_results_sha256'][str(SOURCE/'plan.json')]=sha(SOURCE/'plan.json')
 for p in FILES:definition['implementation_sha256'][p]=sha(ROOT/p)
 immutable_json(DEST/'plan.json',{'definition':definition,'jobs':jobs})
 m={**manifest,'root':str(DEST),'cell':DEST.name,'planned_runs':len(jobs),'plan_sha256':sha(DEST/'plan.json'),'harness':'dsh'}
 immutable_json(DEST/'campaign-manifest.json',m);load_validate(DEST)
 immutable_json(OUT/'inventory.json',{'at_unix':time.time(),'cells':[m],'source_root':str(SOURCE),'source_plan_sha256':sha(SOURCE/'plan.json'),'migrated_never_claimed':len(jobs),'attempt_budgets_unchanged':True,'prior_attempts_consumed':{j['job_id']:j['prior_attempts_consumed']for j in jobs},'network_entry_sha256':sha(ROOT/'scripts/network_entry_v13.py'),'concurrency_per_cell':16})
 view=OUT/'grading-source';(view/'cells').mkdir(parents=True,exist_ok=True);(view/'cells'/DEST.name).symlink_to(DEST,target_is_directory=True);immutable_json(view/'inventory.json',{'cells':[m]})
 print(json.dumps({'root':str(DEST),'jobs':len(jobs),'no_model_calls':True}))
if __name__=='__main__':main()
