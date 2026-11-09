#!/usr/bin/env python3
"""Prepare an explicit .75 replacement scope; never starts model or cloud work."""
import argparse,copy,hashlib,json
from pathlib import Path
import run_rq3_parity_v3 as frozen
from bc_route_runtime_v2 import immutable_json
from lab import ROOT
VERSION='rq3-scale0750-scope-v1'
SCALES=(0.,.25,.5,.7,.75,.8,1.)
DEFAULT_ROOT=ROOT/'outputs/campaigns/rq3-deepseek-bc100-r3-scale0750-v1'
GRADING=ROOT/'outputs/grading/rq3-scale0750-v1'
SOURCES=('prepare_rq3_scale0750_v1.py','run_rq3_scale0750_trial.py','rq3_scale0750_worker.py')
MANIFEST='scale0750-scope.json'
def jobs_hash(jobs):return hashlib.sha256(json.dumps(jobs,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def copy_bytes(source,target):
    target.parent.mkdir(parents=True,exist_ok=True);raw=source.read_bytes()
    if target.exists():
        if target.read_bytes()!=raw:raise ValueError('Derived input changed')
    else:
        with target.open('xb') as stream:stream.write(raw)
def prepare(parent,root):
    parent=Path(parent).resolve();root=Path(root).resolve()
    if parent==root:raise ValueError('New scale requires an independent root')
    original=frozen.read(parent/'plan.json');frozen.validate(original,parent)
    if original['definition']['scales']!=list(frozen.SCALES):raise ValueError('Unexpected parent scope')
    root.mkdir(parents=True,exist_ok=True)
    for name in ('experiment.json','cohort.jsonl'):copy_bytes(parent/name,root/name)
    hashes={}
    for scale in SCALES:
        target=root/'configs'/(frozen.label(scale)+'.json')
        if scale==.75:
            cfg=copy.deepcopy(frozen.read(parent/'configs/scale_0700.json'))
            cfg['visual_renderer']['history_scale']=.75;cfg['rq3']['far_history_scale']=.75
            cfg['rq3']['scope_revision']=VERSION
            cfg['rq3']['baseline']='Reuse original-root six unchanged scale cohorts in final analysis; only this new .75 cohort is executable here'
            immutable_json(target,cfg)
        else:copy_bytes(parent/'configs'/(frozen.label(scale)+'.json'),target)
        hashes[str(target.relative_to(root))]=frozen.sha(target)
    jobs=[]
    for old in original['jobs']:
        job=copy.deepcopy(old);scale=.75 if old['scale']==.125 else old['scale'];job['scale']=scale
        job['job_id']=f"hermes/{frozen.label(scale)}/{job['question_id']}_r{job['repeat']:02d}"
        job['config_path']=str(root/'configs'/(frozen.label(scale)+'.json'));jobs.append(job)
    definition=copy.deepcopy(original['definition'])
    definition.update(scales=list(SCALES),scale_config_sha256=hashes,jobs_sha256=jobs_hash(jobs),scope_revision=VERSION,
        executable_scales=[.75],executable_runs=300,placeholder_runs=1800,
        parent_root=str(parent),parent_plan_sha256=frozen.sha(parent/'plan.json'),
        control='Explicit revised final scales replace .125 with .75; only .75 runs here. Six unchanged scales are reused from the original root by separate final analysis.',
        source_compatibility='Original frozen plan/trial validator schema retained; new explicit .75 native authorization replaces the old worker membership check, with the same inherited image guard.')
    definition['implementation_sha256'].update({'scripts/'+n:frozen.sha(ROOT/'scripts'/n) for n in SOURCES})
    plan={'definition':definition,'jobs':jobs};immutable_json(root/'plan.json',plan)
    authorized=[j['job_id'] for j in jobs if j['scale']==.75]
    manifest={'version':VERSION,'parent_root':str(parent),'parent_plan_sha256':frozen.sha(parent/'plan.json'),
        'root':str(root),'plan_sha256':frozen.sha(root/'plan.json'),'cohort_sha256':frozen.sha(root/'cohort.jsonl'),
        'final_scales':list(SCALES),'replaced_scale':.125,'authorized_scale':.75,'authorized_runs':300,
        'authorized_job_ids':authorized,'authorized_job_ids_sha256':jobs_hash(authorized),
        'placeholder_runs':1800,'placeholder_execution_authorized':False,
        'native_entry':'scripts/rq3_scale0750_worker.py','trial_entry':'scripts/run_rq3_scale0750_trial.py',
        'new_sources_sha256':{'scripts/'+n:frozen.sha(ROOT/'scripts'/n) for n in SOURCES},
        'source_policy':'Original source files and original plan unchanged; explicit independent derived scope',
        'scientific_scale_scope_changed':True,'model_image_tools_budgets_changed':False,'scale_change':'Only far-history linear scale for the new .75 cohort; recent/native evidence unchanged'}
    immutable_json(root/MANIFEST,manifest);validate_scope(root);return manifest

def validate_scope(root,full=True):
    root=Path(root).resolve();plan=frozen.read(root/'plan.json');m=frozen.read(root/MANIFEST)
    if full:frozen.validate(plan,root)
    if m.get('version')!=VERSION or Path(m['root']).resolve()!=root or m['plan_sha256']!=frozen.sha(root/'plan.json'):raise ValueError('Derived scope/plan differs')
    d=plan['definition']
    if d.get('scope_revision')!=VERSION or d.get('scales')!=list(SCALES) or d.get('executable_scales')!=[.75] or m.get('final_scales')!=list(SCALES):raise ValueError('Scope scales differ')
    if m.get('authorized_scale')!=.75 or m.get('authorized_runs')!=300 or m.get('placeholder_execution_authorized') is not False:raise ValueError('Wrong execution authorization')
    jobs=[j for j in plan['jobs'] if j['scale']==.75];ids=[j['job_id'] for j in jobs]
    if len(jobs)!=300 or len(set(ids))!=300 or {j['repeat'] for j in jobs}!={1,2,3} or len({j['question_id'] for j in jobs})!=100:raise ValueError('Expected fixed100x3 .75 cohort')
    if ids!=m['authorized_job_ids'] or jobs_hash(ids)!=m['authorized_job_ids_sha256']:raise ValueError('Authorized job list differs')
    if d['parent_plan_sha256']!=m['parent_plan_sha256'] or d['parent_root']!=m['parent_root']:raise ValueError('Parent lineage mismatch')
    if m['cohort_sha256']!=frozen.sha(root/'cohort.jsonl') or m['cohort_sha256']!=d['cohort_sha256']:raise ValueError('Frozen cohort mismatch')
    for path,expected in m['new_sources_sha256'].items():
        if frozen.sha(ROOT/path)!=expected:raise ValueError('New scope implementation changed')
    return plan,m

def validate_authorized_spec(spec):
    root=Path(spec['campaign_root']).resolve();plan,m=validate_scope(root,full=False)
    if spec.get('scale')!=.75 or spec.get('job_id') not in m['authorized_job_ids'] or spec.get('plan_sha256')!=m['plan_sha256']:raise ValueError('Only the new .75 cohort may execute here')
    expected=next(j for j in plan['jobs'] if j['job_id']==spec['job_id'])
    if any(spec.get(k)!=v for k,v in expected.items()):raise ValueError('Authorized spec differs from planned observation')
    path=Path(spec['config_path']);rel=str(path.relative_to(root))
    if frozen.sha(path)!=plan['definition']['scale_config_sha256'][rel]:raise ValueError('Authorized scale config changed')
    return m

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--parent',type=Path,default=frozen.DEFAULT_ROOT);p.add_argument('--root',type=Path,default=DEFAULT_ROOT);a=p.parse_args()
    m=prepare(a.parent,a.root);print(json.dumps({'paid_calls':0,'root':m['root'],'plan_sha256':m['plan_sha256'],'authorized_runs':300,'final_scales':SCALES,'trial':m['trial_entry']}))
if __name__=='__main__':main()
