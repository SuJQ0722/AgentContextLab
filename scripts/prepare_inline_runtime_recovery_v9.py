"""Rebind stopped DSH/mixed cells to isolated runtime repairs; preserve all attempts."""
import argparse,copy,json
from pathlib import Path
from lab import ROOT
from prepare_mmbc100_campaign import immutable,sha
from bc_route_runtime_v1 import immutable_json
from prepare_inline_retry5_v8 import source_hashes
from prepare_visual_hosted_retry_v1 import load_validate
BASE=ROOT/'outputs/campaigns/visual-hosted-failure-retry-v1/cells'
SOURCE=BASE/'transport-v8-one-hour-retry5'
DEST=BASE/'transport-v9-runtime-recovery'
PROOF=ROOT/'outputs/cloud-runtime/inline-retry5-v8/dsh-frozen-options-repair'
VERSION='inline-runtime-recovery-v9'


def read(path):return json.loads(Path(path).read_text())


def prepare():
    implementations=source_hashes();manifests=[]
    for cell in ('bc_dsh','shared_baselines'):
        old=SOURCE/'cells'/cell;root=DEST/'cells'/cell
        if (root/'plan.json').exists():manifests.append(load_validate(root)[1]);continue
        proof=PROOF/(cell+'-after.json');state=read(proof)
        if state.get('state')!='SUSPENDED' or state.get('ready_replicas')!=0 or not state.get('uid'):
            raise ValueError('Stopped CCI proof required')
        plan,_=load_validate(old);definition=copy.deepcopy(plan['definition'])
        for folder in ('configs','cohorts','image-assets'):
            for p in (old/folder).rglob('*'):
                if p.is_file():immutable(root/p.relative_to(old),p.read_bytes())
        for name in ('cohort.jsonl','experiment.json'):immutable(root/name,(old/name).read_bytes())
        jobs=[];records=[];bindings={str(proof):sha(proof),str(old/'plan.json'):sha(old/'plan.json')}
        for prior in plan['jobs']:
            attempt=old/'jobs'/prior['job_id']/'attempts/attempt_001';result_path=attempt/'result.json'
            result=read(result_path) if result_path.exists() else None
            if result_path.exists():bindings[str(result_path)]=sha(result_path)
            complete=result is not None and result.get('status')=='completed'
            records.append({'job_id':prior['job_id'],'selected':not complete,'reason':'historical_completed_retained' if complete else 'stopped_runtime_recovery',
                            'previous_attempt':str(attempt),'previous_status':result.get('status') if result else 'unfinished_or_pending'})
            if complete:continue
            job=copy.deepcopy(prior);job.update(operational_recovery_version=VERSION,previous_v8_attempt=str(attempt),
                    config_path=str(root/Path(prior['config_path']).relative_to(old)))
            if prior.get('native_cohort_path'):
                job['native_cohort_path']=str(root/Path(prior['native_cohort_path']).relative_to(old))
            if prior.get('controlled_spec_path'):
                spec=read(prior['controlled_spec_path']);spec['config_path']=job['config_path']
                target=root/'controlled-specs'/Path(prior['controlled_spec_path']).name;immutable_json(target,spec)
                job.update(controlled_spec_path=str(target),controlled_spec_sha256=sha(target))
            jobs.append(job)
        definition.update(implementation_sha256=implementations,source_results_sha256={**definition['source_results_sha256'],**bindings},
                          planned_runs=len(jobs),operational_recovery_version=VERSION)
        immutable_json(root/'selection.json',{'records':records,'selection_uses_answers':False,'all_prior_artifacts_preserved':True})
        immutable_json(root/'plan.json',{'definition':definition,'jobs':jobs})
        manifest={'root':str(root),'cell':cell,'harness':'dsh' if cell=='bc_dsh' else 'hermes','planned_runs':len(jobs),
                  'plan_sha256':sha(root/'plan.json'),'version':'visual-hosted-failure-retry-v1','operational_recovery_version':VERSION}
        immutable_json(root/'campaign-manifest.json',manifest);manifests.append(manifest)
    immutable_json(DEST/'inventory.json',{'version':VERSION,'cells':manifests,'concurrency_per_cell':16,'global_cap':None})
    return manifests


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--freeze',action='store_true');args=p.parse_args()
    print(json.dumps(prepare() if args.freeze else {'live':False,'model_calls':0,'cells':['bc_dsh','shared_baselines']}))
