"""Freeze per-cell continuation after V10 drains, retaining every completed job."""
import argparse,copy,hashlib,json,shutil,subprocess
from pathlib import Path
from lab import ROOT
from prepare_mmbc100_campaign import immutable,immutable_json
from hermes_canvas_budget_worker_v11 import VERSION
BASE=ROOT/'outputs/campaigns/visual-hosted-failure-retry-v1/cells'
SOURCE=BASE/'seven-page-retry3-v10';DEST=BASE/'seven-page-runtime-v11'

def read(path):return json.loads(Path(path).read_text())
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def drained(root):
    controllers=list((root/'controllers').glob('*/*/maintenance.json'))
    for p in controllers:
        e=p.with_name('exit.json')
        if not e.exists() or read(e).get('drained') is not True:return False
    for p in (root/'jobs').glob('**/attempts/attempt_001/controller-dispatched.json'):
        result=p.with_name('result.json')
        if not result.exists():return False
        row=read(result)
        if row.get('slot_released') is not True or row.get('unconfirmed_child_termination')!=[]:return False
    return True

def attempt_has_model_or_unknown(attempt):
    native=Path(attempt['native_artifact_root']);observed=False;rejected=False
    for name in ('transport-phases-v3.jsonl','inline-images-wire-dsh-v1.jsonl','inline-images-wire-v1.jsonl'):
        for p in native.rglob(name):
            for line in p.read_text().splitlines():
                try:r=json.loads(line)
                except ValueError:continue
                if r.get('event') in ('request_started','final_inline_request','stream_complete','request_body_sent'):observed=True
                if r.get('decision')=='allow':observed=True
                if r.get('decision')=='reject' and r.get('network_send_authorized') is False:rejected=True
    if observed:return True,'observed_or_authorized_model_request'
    log=Path(attempt['result_path']).parent/'worker.log'
    text=log.read_text(errors='replace') if log.exists() else ''
    if any(v in text for v in ('Explicit one-hour retry version required','One-hour baseline config required')):
        return False,'verified_pre_model_contract_rejection'
    if rejected:return False,'verified_pre_network_image_guard_rejection'
    return True,'conservative_unknown_acceptance'

def prepare(cell):
    old=SOURCE/'cells'/cell;new=DEST/'cells'/cell
    if (new/'campaign-manifest.json').exists():return read(new/'campaign-manifest.json')
    if not drained(old):return {'cell':cell,'state':'waiting_for_v10_drain'}
    plan=read(old/'plan.json');new.mkdir(parents=True,exist_ok=True)
    # Input bytes are copied unchanged; frozen config paths are rewritten only in new generation.
    for name in ('cohort.jsonl','cohorts','image-assets'):
        source=old/name
        if source.is_file():immutable(new/name,source.read_bytes())
        elif source.exists():
            for p in source.rglob('*'):
                if p.is_file():immutable(new/name/p.relative_to(source),p.read_bytes())
    jobs=[];selection=[];bindings={str(old/'plan.json'):sha(old/'plan.json')};configs={}
    for proof in (old/'controllers').glob('*/*/exit.json'):
        bindings[str(proof)]=sha(proof)
    for original in plan['jobs']:
        result_path=old/'jobs'/original['job_id']/'attempts/attempt_001/result.json'
        result=read(result_path) if result_path.exists() else None
        if result:bindings[str(result_path)]=sha(result_path)
        if result and result.get('status')=='completed':
            selection.append({'job_id':original['job_id'],'retained_completed':True,'result_path':str(result_path)});continue
        consumed=0;costs=[];operational=[]
        for attempt in (result or {}).get('attempts',[]):
            used,reason=attempt_has_model_or_unknown(attempt)
            record={**attempt,'classification':reason};costs.append(record)
            if used:consumed+=1
            else:operational.append(record)
        if consumed>=3:
            selection.append({'job_id':original['job_id'],'retained_exhausted':True,'prior_attempts_consumed':consumed});continue
        cfg=copy.deepcopy(read(original['config_path']));cfg['runtime_recovery_version']=VERSION
        if original['strategy']=='visual':cfg['visual_image_retention']['max_request_bytes']=32*1024*1024
        raw=(json.dumps(cfg,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode();digest=hashlib.sha256(raw).hexdigest();path=new/'configs'/f'{digest}.json';immutable(path,raw);configs[digest]=raw
        job=copy.deepcopy(original)
        job.update(config_path=str(path),config_sha256=digest,runtime_recovery_version=VERSION,
                   prior_attempts_consumed=consumed,prior_attempt_costs=costs,prior_operational_attempts=operational,
                   predecessor_plan_path=str(old/'plan.json'),predecessor_result_path=str(result_path) if result else None)
        if job.get('native_cohort_path'):job['native_cohort_path']=str(new/Path(job['native_cohort_path']).relative_to(old))
        jobs.append(job);selection.append({'job_id':job['job_id'],'selected':True,'prior_attempts_consumed':consumed,'operational_failures':len(operational)})
    if not configs:
        cfg=read(old/'experiment.json');cfg['runtime_recovery_version']=VERSION;raw=(json.dumps(cfg,indent=2)+'\n').encode()
    else:raw=next(iter(configs.values()))
    immutable(new/'experiment.json',raw)
    names=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0')
    hashes={n:sha(ROOT/n) for n in names if n and (ROOT/n).is_file() and (n.startswith(('scripts/','plugins/','hermes-agent/')) and Path(n).suffix in ('.py','.mjs','.js','.ts') or n=='harness-lock.json')}
    definition={**plan['definition'],'runtime_recovery_version':VERSION,'planned_runs':len(jobs),
                'config_sha256':sha(new/'experiment.json'),'cohort_sha256':sha(new/'cohort.jsonl'),
                'implementation_sha256':hashes,'source_results_sha256':bindings,
                'predecessor_planned_runs':len(plan['jobs']),'attempt_budget_includes_predecessor_real_or_unknown_model_attempts':True}
    if (new/'image-assets/manifest.json').exists():definition['input_images_sha256']=sha(new/'image-assets/manifest.json')
    immutable_json(new/'plan.json',{'definition':definition,'jobs':jobs})
    manifest={'root':str(new),'cell':cell,'harness':read(old/'campaign-manifest.json')['harness'],'planned_runs':len(jobs),'retained_completed':sum(r.get('retained_completed',False) for r in selection),'plan_sha256':sha(new/'plan.json'),'version':'visual-hosted-failure-retry-v1','one_hour_retry_version':definition['one_hour_retry_version'],'runtime_recovery_version':VERSION}
    immutable_json(new/'campaign-manifest.json',manifest);immutable_json(new/'selection.json',{'records':selection,'selection_uses_answers':False})
    return manifest

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--cell',required=True);a=p.parse_args();print(json.dumps(prepare(a.cell)))
