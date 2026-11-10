#!/usr/bin/env python3
"""Freeze answer-selected BC retries independently of all original attempts."""
import argparse
import json
from pathlib import Path
from lab import ROOT
from prepare_mmbc100_campaign import sha, read, digest, immutable, immutable_json, implementation_hashes
from prepare_rq3_bounded_retry_v1 import scale_config

VERSION = 'bc-bounded-retry-v1'
PROTOCOL = 'bc-bounded-pages-v1'
HARNESSES = ('hermes', 'dsh')
DEFAULT_ROOT = ROOT/'outputs/campaigns'/VERSION
PRIVATE = ROOT/'outputs/grading'/VERSION/'private'
NEW_SOURCES = ('prepare_bc_bounded_retry_v1.py', 'bc_bounded_retry_sources_v1.py',
    'run_bc_bounded_retry_v1.py', 'run_bc_bounded_retry_trial_v1.py',
    'prepare_rq3_bounded_retry_v1.py', 'run_bounded_vera_trial_v1.py', 'run_bc_trial_v3_io.py',
    'hermes_bounded_bc_worker_v1.py', 'hermes_bounded_rq3_worker_v1.py',
    'rq3_bounded_renderer_v2.py', 'bounded_multimodal_renderer_v1.py',
    'bounded_lossless_transport_v1.py', 'bounded_visual_request_guard_v1.py',
    'bootstrap_bc_bounded_retry_v1.py', 'dsh_bounded_bc_worker_v1.py')


def prepare(root=DEFAULT_ROOT):
    from bc_bounded_retry_sources_v1 import source_records
    root = Path(root).resolve()
    if root != DEFAULT_ROOT.resolve(): raise ValueError('Independent fixed BC namespace required')
    records, gold, public = source_records()
    if len(records)!=600 or len(public)!=100: raise ValueError('Expected BC100x3 for two harnesses')
    for h, count in [('hermes',113),('dsh',137)]:
        group=[r for r in records if r['harness']==h]
        if len(group)!=300 or sum(r['selected_for_retry'] for r in group)!=count:
            raise ValueError('Selection differs from reviewed inventory')
    immutable_json(PRIVATE/'selection.json', {'records':records, 'selected_using_answer_correctness':True,
        'original_runs':600, 'new_runs':250, 'old_results_deleted':False,
        'single_attempt_accuracy_valid':False}, private=True)
    immutable_json(PRIVATE/'gold.json',gold,private=True)
    immutable(root/'cohort.jsonl', ''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in public).encode())
    model=read(ROOT/'configs/experiment.json')['model']
    if model!='deepseek-v4.1-flash-1017/huoshan/huoshan': raise ValueError('Unexpected route')
    cfg=scale_config(read(ROOT/'configs/experiment.v3.review.json'),.75,model)
    cfg.pop('rq3',None); cfg.pop('bounded_rq3_protocol',None)
    cfg.update(campaign_version=VERSION,bounded_bc_protocol=PROTOCOL)
    cfg['bc100_campaign'].update(name=VERSION,models={h:model for h in HARNESSES})
    cfg['bounded_retry']={'version':VERSION,'selection_uses_prior_answers':True,
        'maximum_new_attempts_per_selected_job':1,'mixed_protocol_union_is_single_attempt_accuracy':False,
        'retain_all_original_costs_and_failures':True,'automatic_retry_until_correct':False}
    immutable_json(root/'experiment.json',cfg)
    by_id={r['id']:r for r in public}
    jobs=[{'job_id':r['job_id'],'harness':r['harness'],'strategy':'visual',
        'bounded_bc_protocol':PROTOCOL,'scale':.75,'scale_key':'scale_0750',
        'question_id':r['question_id'],'question':by_id[r['question_id']]['question'],
        'repeat':r['repeat'],'model':model,'timeout_seconds':1800,
        'config_path':str(root/'experiment.json'),'config_sha256':sha(root/'experiment.json')}
        for r in records if r['selected_for_retry']]
    sources=implementation_hashes()
    sources.update({'scripts/'+n:sha(ROOT/'scripts'/n) for n in NEW_SOURCES})
    # DSH's process-local helper/preload are explicitly frozen too.
    from dsh_bounded_bc_worker_v1 import BOUNDED_SOURCE_FILES
    sources.update({str(n):sha(ROOT/n) for n in BOUNDED_SOURCE_FILES})
    definition={'execution_version':VERSION,'protocol':PROTOCOL,'harnesses':list(HARNESSES),
        'config_sha256':sha(root/'experiment.json'),'cohort_sha256':sha(root/'cohort.jsonl'),
        'selection_path':str(PRIVATE/'selection.json'),'selection_sha256':sha(PRIVATE/'selection.json'),
        'gold_path':str(PRIVATE/'gold.json'),'gold_sha256':sha(PRIVATE/'gold.json'),
        'jobs_sha256':digest(jobs),'planned_runs':len(jobs),'original_runs':600,
        'per_cell_concurrency_cap':16,'global_prediction_cap':32,'reserved_judge_slots':2,
        'implementation_sha256':sources,'harness_lock':read(ROOT/'harness-lock.json'),
        'selection_uses_prior_answers':True,'single_attempt_accuracy_valid':False,
        'old_failures_and_usage_retained':True,'maximum_new_attempts_per_job':1}
    immutable_json(root/'plan.json',{'definition':definition,'jobs':jobs})
    immutable_json(root/'campaign-manifest.json',{'version':VERSION,'root':str(root),
        'plan_sha256':sha(root/'plan.json'),'planned_runs':len(jobs),
        'per_harness':{h:sum(j['harness']==h for j in jobs) for h in HARNESSES},
        'old_results_deleted':False,'union_is_single_attempt_avg3':False})
    validate_sources(read(root/'plan.json'),root)
    return read(root/'campaign-manifest.json')


def validate_sources(plan,root):
    root=Path(root).resolve();d=plan['definition']
    if d.get('execution_version')!=VERSION or d.get('harnesses')!=list(HARNESSES):raise ValueError('Wrong BC protocol')
    for p,s in [(root/'experiment.json',d['config_sha256']),(root/'cohort.jsonl',d['cohort_sha256']),
                (Path(d['selection_path']),d['selection_sha256']),(Path(d['gold_path']),d['gold_sha256'])]:
        if sha(p)!=s:raise ValueError('Frozen artifact changed: '+str(p))
    records=read(d['selection_path'])['records']
    for r in records:
        if sha(r['result_path'])!=r['result_sha256']:raise ValueError('Original result changed')
        if r.get('grade_sha256') and sha(r['grade_path'])!=r['grade_sha256']:raise ValueError('Original grade changed')
        if r['selected_for_retry']!=(r['score']==0):raise ValueError('Selection changed')
    if digest(plan['jobs'])!=d['jobs_sha256'] or len(plan['jobs'])!=250:raise ValueError('Jobs changed')
    if {j['job_id'] for j in plan['jobs']}!={r['job_id'] for r in records if r['selected_for_retry']}:raise ValueError('Selected jobs differ')
    if any(set(json.loads(line))!={'id','question'} for line in (root/'cohort.jsonl').read_text().splitlines()):raise ValueError('Private fields in prediction cohort')
    for n,s in d['implementation_sha256'].items():
        if sha(ROOT/n)!=s:raise ValueError('Frozen implementation changed: '+n)
    if read(ROOT/'harness-lock.json')!=d['harness_lock']:raise ValueError('Harness pins changed')
    return root


def load_validate(root=DEFAULT_ROOT):
    root=Path(root).resolve();plan=read(root/'plan.json');manifest=read(root/'campaign-manifest.json')
    if manifest['version']!=VERSION or manifest['plan_sha256']!=sha(root/'plan.json'):raise ValueError('Plan binding changed')
    validate_sources(plan,root);return plan,manifest


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=DEFAULT_ROOT)
    p.add_argument('--prepare',action='store_true');p.add_argument('--validate',action='store_true');a=p.parse_args()
    print(json.dumps(prepare(a.root) if a.prepare else load_validate(a.root)[1] if a.validate else {'live':False,'model_calls':0,'planned_runs':250}))

if __name__=='__main__':main()
