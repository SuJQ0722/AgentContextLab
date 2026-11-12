"""Freeze failure/unfinished recovery from public scientific identities, never grades."""
import argparse
from collections import defaultdict
import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from functools import lru_cache
from lab import ROOT
from bc_route_runtime_v1 import immutable_json
from prepare_mmbc100_campaign import immutable, sha as uncached_sha
from one_hour_timeout_retry_v10 import VERSION
from inline_route_contract_v2 import ROUTES

BASE=ROOT/'outputs/campaigns/visual-hosted-failure-retry-v1/cells'
DEST=BASE/'seven-page-retry3-v10'
V7=BASE/'transport-v7-two-hour/cells'
STOP_PROOF=ROOT/'outputs/cloud-runtime/retry5-stop-20261111/interrupted-native-attempts.json'


# Inputs are frozen for the duration of preparation; avoid rereading the same
# multi-megabyte predecessor plan for every question.
@lru_cache(maxsize=None)
def sha(path):return uncached_sha(path)

@lru_cache(maxsize=None)
def read(path):return json.loads(Path(path).read_text())

@lru_cache(maxsize=None)
def cohort_bytes(path):return Path(path).read_bytes()


def rq3_records():
    source=ROOT/'outputs/campaigns/rq3-deepseek-bc100-r3-scale0750-v1/plan.json'
    plan=read(source)
    allowed={0.,.25,.5,.7,.75,.8,1.}
    records=[]
    for job in plan['jobs']:
        if job['scale'] not in allowed: continue
        cell='rq3_scale_'+format(round(job['scale']*1000),'04d')
        records.append({'benchmark':'rq3','harness':'hermes','strategy':'visual',
            'question_id':job['question_id'],'repeat':job['repeat'],'status':'new_full_rerun',
            'cell':cell,'job_id':job['job_id'],'attempt':str(source.parent/'jobs'/job['job_id']/'attempts/attempt_001'),
            'model':ROUTES[0],'source_job':job,'source_plan_path':str(source),
            'source_config_path':job['config_path'],'selection_reason':'rq3_full_rerun'})
    counts=defaultdict(int)
    for record in records:counts[record['cell']]+=1
    if len(counts)!=7 or set(counts.values())!={300}:raise ValueError('RQ3 must contain exactly seven 100x3 cells')
    return records


def source_hashes():
    # Bind customized harness sources and every local orchestration dependency.
    paths=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0')
    return {name:sha(ROOT/name) for name in paths if name and (ROOT/name).is_file() and
            (name.startswith(('scripts/','plugins/','hermes-agent/')) and Path(name).suffix in ('.py','.mjs','.js','.ts') or name=='harness-lock.json')}


def certified_stopped(attempt):
    if STOP_PROOF.exists():
        for row in read(STOP_PROOF)['records']:
            if Path(row['attempt']).resolve()==Path(attempt).resolve() and row.get('cloud_state')=='SUSPENDED' and row.get('cloud_ready_replicas')==0:
                return STOP_PROOF
    proof=ROOT/'outputs/cloud-runtime/retry5-stop-20261111/additional-orphan-proofs.json'
    if proof.exists():
        for row in read(proof):
            if Path(row.get('result_path','/nonexistent')).parent.resolve()==Path(attempt).resolve() and row.get('all_proven_dead')is True:return proof
    return None


def selected(record):
    if record.get('selection_reason') in ('rq3_full_rerun', 'timeout_no_completed_successor', 'timeout_lineage_user_stopped'):
        proof = None
        if record.get('requires_current_stop_proof'):
            proof=Path(record['stop_proof_path'])
            if not read(proof).get('all_verified'):raise ValueError('Current stop proof is incomplete')
        return True, record['selection_reason'], proof
    return False, 'outside_explicit_restart_scope', None


def configure(source,cell,visual):
    cfg=copy.deepcopy(source)
    if visual:cfg=copy.deepcopy(read(V7/cell/'experiment.json'))
    cfg.update(timeout_seconds=3600,max_timeout_retries=2,one_hour_retry_version=VERSION,
               dsh_buffered_watchdog_version='dsh-buffered-sdk-watchdog-one-hour-v3',
               model=ROUTES[0],approved_model_routes=list(ROUTES),model_route_policy='four-route-rotation-v1',
               transport_runtime_version='visual-transport-runtime-v4',image_transport='inline-recent-ten-chunked-v1',
               transport_delivery_version='inline-direct-v1',gateway_proxy='http://10.120.0.246:7890')
    # Preserve source scientific settings; copy only the established HTTP policy.
    cfg['transport_runtime_policy']=copy.deepcopy(read(V7/'bc_hermes/experiment.json')['transport_runtime_policy'])
    for name in ('bc100','bc100_campaign','mmbc100_campaign','mmbc_vanilla_campaign'):
        if isinstance(cfg.get(name),dict):cfg[name]['timeout_seconds']=3600
    latest=read(ROOT/'configs/experiment.json')
    if visual:
        cfg['visual_page_window']=copy.deepcopy(latest['visual_page_window'])
        scale=float(cell.removeprefix('rq3_scale_'))/1000 if cell.startswith('rq3_scale_') else .75
        cfg['visual_page_window']['history_scale']=scale
        cfg['visual_image_retention']=copy.deepcopy(latest['visual_image_retention'])
    cfg['max_attempts']=3
    cfg['restart_protocol']='seven-page-retry3-v10'
    return cfg


def prepare(inventory_path, controlled_path=None):
    inventory=read(inventory_path);records=inventory['records'];groups=defaultdict(list);decisions=[]
    for record in records:
        if not record['model'].startswith('deepseek-v4.1-flash-1017/'):
            continue
        use,reason,proof=selected(record)
        decisions.append({k:record[k] for k in ('benchmark','harness','strategy','question_id','repeat','status')}|{'selected':use,'reason':reason})
        if use:
            cell='shared_baselines' if record['cell']=='other_strategies' else record['cell']
            groups[cell].append((record,proof))
    controls=read(controlled_path) if controlled_path else {'records':[],'blocked':[]}
    control_references={}
    for record in controls['records']:
        if record['strategy']=='visual':control_references[(record['group'],record['controlled_prefix_key'])]=record['job_id']
        cell=record['group'] if record['strategy']=='visual' else 'shared_baselines'
        groups[cell].append((record,None))
    implementation=source_hashes();manifests=[]
    for cell,entries in sorted(groups.items()):
        root=DEST/'cells'/cell
        if (root/'plan.json').exists():
            from prepare_visual_hosted_retry_v1 import load_validate
            manifests.append(load_validate(root)[1]);continue
        root.mkdir(parents=True,exist_ok=True)
        bindings={str(Path(inventory_path).resolve()):sha(inventory_path)};jobs=[];cohort={};assets={};config_bytes={}
        for record,proof in entries:
            old=copy.deepcopy(record['source_job']);visual=record['strategy'] in ('visual','vanilla_visual')
            plan_path=Path(record['source_plan_path']);source_root=plan_path.parent
            for p in (plan_path,Path(record['source_config_path']),source_root/'cohort.jsonl'):
                if p.exists():bindings[str(p)]=sha(p)
            result_path=Path(record['attempt'])/'result.json'
            if result_path.exists():bindings[str(result_path)]=sha(result_path)
            if proof:bindings[str(proof)]=sha(proof)
            is_controlled=record['benchmark']=='controlled'
            config_cell=record['group'] if is_controlled else cell
            cfg=configure(read(record['source_config_path']),config_cell,visual or is_controlled)
            cfg_raw=(json.dumps(cfg,sort_keys=True,ensure_ascii=False,indent=2)+'\n').encode()
            config_id=hashlib.sha256(cfg_raw).hexdigest();config_path=root/'configs'/(config_id+'.json')
            immutable(config_path,cfg_raw);config_bytes[config_id]=cfg_raw
            cohort_source=(V7/config_cell/'cohort.jsonl') if visual or is_controlled else source_root/'cohort.jsonl'
            cohort_data=cohort_bytes(cohort_source);cohort_sha=hashlib.sha256(cohort_data).hexdigest()
            native_cohort=root/'cohorts'/(cohort_sha+'.jsonl');immutable(native_cohort,cohort_data)
            for row in map(json.loads,cohort_data.decode().splitlines()):
                clean={k:v for k,v in row.items() if k in ('id','question_id','question','image')}
                cohort[(record['benchmark'],str(row.get('id',row.get('question_id'))))]=clean
            old.update(job_id=(record['job_id'] if record['job_id'].startswith(record['benchmark']+'/') else record['benchmark']+'/'+record['job_id']) if cell=='shared_baselines' else record['job_id'],
                       original_job_id=record['job_id'],harness=record['harness'],strategy='visual' if visual else {'summary':'summarize','window':'sliding_window'}.get(record['strategy'],record['strategy']),
                       question_id=record['question_id'],repeat=record['repeat'],model=ROUTES[0],
                       config_path=str(config_path),config_sha256=sha(config_path),timeout_seconds=3600,max_timeout_retries=2,max_attempts=3,
                       one_hour_retry_version=VERSION,dsh_buffered_watchdog_version=cfg['dsh_buffered_watchdog_version'],
                       approved_model_routes=list(ROUTES),model_route_policy=cfg['model_route_policy'],
                       image_transport='inline-recent-ten-chunked-v1',transport_runtime_version=cfg['transport_runtime_version'],
                       transport_delivery_version='inline-direct-v1',gateway_proxy=cfg['gateway_proxy'],
                       visual_hosted_retry_version='visual-hosted-failure-retry-v1',
                       benchmark=record['benchmark'],experiment_kind='controlled' if is_controlled else 'rq3' if record['benchmark']=='rq3' else 'mmbc' if record['benchmark']=='mmbc100' else 'bc',
                       cell=cell,source_result_path=str(result_path) if result_path.exists() else None,
                       source_attempt_path=record['attempt'],native_cohort_path=str(native_cohort),native_cohort_sha256=cohort_sha)
            if visual and not is_controlled:
                scale=float(cell.removeprefix('rq3_scale_'))/1000 if cell.startswith('rq3_scale_') else .75
                old.update(scale=scale,scale_key=f'scale_{round(scale*1000):04d}',bounded_max_images=10,
                           bounded_request_protocol='bounded-multimodal-recent-ten-v1',bounded_image_retention='last_10_in_message_order',
                           bounded_benchmark='mmbc100' if record['benchmark']=='mmbc100' else 'bc100')
                key='bounded_rq3_protocol' if record['benchmark']=='rq3' else 'bounded_visual_protocol' if record['benchmark']=='mmbc100' else 'bounded_bc_protocol'
                old[key]=cfg[key]
            if is_controlled:
                from controlled_inline_retry_v8 import prepare_spec
                prepared=prepare_spec(record,root,config_path,ROUTES[0],target_root=DEST/'cells'/record['group'])
                original_spec=read(prepared['controlled_spec_path'])
                old.update({key:original_spec[key] for key in ('question','question_id','repeat')})
                old.update(prepared,calibration_not_scored=record.get('calibration_not_scored',False))
                reference_id=control_references[(record['group'],record['controlled_prefix_key'])]
                old['controlled_reference_job_path']=str(DEST/'cells'/record['group']/'jobs'/reference_id)
                for path in (Path(original_spec['prefix_path']),Path(record['bounded_candidate']['spec_path'])):
                    bindings[str(path)]=sha(path)
                if controlled_path:bindings[str(Path(controlled_path).resolve())]=sha(controlled_path)
            jobs.append(old)
            image_root=(V7/cell) if visual and record['benchmark']=='mmbc100' else source_root
            manifest_path=image_root/'image-assets/manifest.json'
            if record['benchmark']=='mmbc100' and manifest_path.exists():
                for url,item in read(manifest_path)['images'].items():
                    if url in assets:
                        if assets[url]['sha256']!=item['sha256']:raise ValueError('Original MMBC image identity changed')
                        continue
                    data=(image_root/item['relative_path']).read_bytes()
                    if hashlib.sha256(data).hexdigest()!=item['sha256']:raise ValueError('Input bytes corrupted')
                    immutable(root/item['relative_path'],data);assets[url]=item
        if cell=='shared_baselines':
            from collections import deque
            queues=defaultdict(deque)
            for job in jobs:queues[(job['benchmark'],job.get('dataset',''),job['harness'],job['strategy'])].append(job)
            jobs=[]
            while any(queues.values()):
                for key in sorted(queues):
                    if queues[key]:jobs.append(queues[key].popleft())
        public=(''.join(json.dumps(r,ensure_ascii=False)+'\n' for _,r in sorted(cohort.items()))).encode()
        immutable(root/'cohort.jsonl',public);immutable(root/'experiment.json',next(iter(config_bytes.values())))
        definition={'execution_version':'visual-hosted-failure-retry-v1','one_hour_retry_version':VERSION,
                    'cell':cell,'container_group':'shared_baselines' if cell=='shared_baselines' else 'visual',
                    'harnesses':['hermes','dsh'],'per_cell_concurrency_cap':16,'planned_runs':len(jobs),
                    'config_sha256':sha(root/'experiment.json'),'cohort_sha256':sha(root/'cohort.jsonl'),
                    'implementation_sha256':implementation,'source_results_sha256':bindings,
                    'selection_uses_answers':False,'any_completed_retained':not cell.startswith('rq3_'),'rq3_full_rerun':cell.startswith('rq3_'),'maximum_new_attempts':3,
                    'timeout_seconds':3600,'max_timeout_retries':2}
        if assets:
            immutable_json(root/'image-assets/manifest.json',{'version':'mmbc-original-input-images-v1','cohort_sha256':definition['cohort_sha256'],'images':assets})
            definition['input_images_sha256']=sha(root/'image-assets/manifest.json')
        immutable_json(root/'plan.json',{'definition':definition,'jobs':jobs})
        manifest={'root':str(root),'cell':cell,'harness':'dsh' if cell=='bc_dsh' else 'hermes','planned_runs':len(jobs),
                  'plan_sha256':sha(root/'plan.json'),'version':'visual-hosted-failure-retry-v1','one_hour_retry_version':VERSION}
        immutable_json(root/'campaign-manifest.json',manifest);manifests.append(manifest)
    immutable_json(DEST/'selection.json',{'decisions':decisions,'controlled_blocked':controls['blocked'],'controlled_tasks':len(controls['records']),'selection_uses_answers':False})
    immutable_json(DEST/'inventory.json',{'version':VERSION,'cells':manifests,'concurrency_per_cell':16,'global_cap':None,
                                        'timeout_seconds':3600,'max_timeout_retries':2,'excluded_benchmarks':['agenticdatabench']})
    return manifests


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--inventory',type=Path,required=True);p.add_argument('--freeze',action='store_true');p.add_argument('--controlled',type=Path);args=p.parse_args()
    if not args.freeze:
        print(json.dumps({'live':False,'model_calls':0,'records':len(read(args.inventory)['records']),'timeout_seconds':3600,'max_timeout_retries':2}))
    else:print(json.dumps(prepare(args.inventory,args.controlled)))
