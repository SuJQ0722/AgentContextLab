"""Incremental paired old-timeout/new-attempt stage profiles; no extra evaluations."""
import argparse,time
from collections import defaultdict
from pathlib import Path
from lab import ROOT
from supplement_recovery_v24 import DEFAULT,read,save,sha
from profile_experiment_stages import profile,describe,summarize

OUT=ROOT/'outputs/reports/supplement-timeout-v24/stage-profile'
def collect():
    plan=read(DEFAULT/'plan.json');new=[];old=[];terminal=0
    for job in plan['jobs']:
        path=DEFAULT/'jobs'/job['job_id']/'attempts/attempt_001/result.json'
        if not path.exists():continue
        result=read(path)
        if result.get('supplement_version')!=plan['version']:continue
        terminal+=1;cache=OUT/'episodes'/(job['job_id']+'.json')
        if cache.exists():pair=read(cache)
        else:
            observation={k:job.get(k)for k in ('slot_id','harness','method','question_id','repeat')}
            observation.update(benchmark={'bc':'bc100','mmbc':'mmbc100','rq3':'rq3'}.get(job.get('experiment_kind'),'controlled_mmbc'),
                status='timeout_unresolved'if result['status']=='timeout'else result['status'],score=None,selected_result_path=str(path))
            fresh=profile(observation);fresh.update(configured_concurrency=8,configured_max_rounds=200,configured_timeout_seconds=10800)
            for directory in fresh.get('metric_dirs',[]):
                binding=Path(directory)/'turn-limit-v24.json'
                if binding.exists():
                    value=read(binding);fresh['turn_limit_measured']=value.get('actual_max_iterations',value.get('actual_maxSteps'))
            historical=None
            if job['scope']=='core':
                historical=profile({**observation,'status':'timeout_unresolved','selected_result_path':job['recovery_source_path']})
                historical['historical_concurrency_reference']=16
            pair={'job_id':job['job_id'],'result_sha256':sha(path),'old':historical,'new':fresh};save(cache,pair)
        new.append(pair['new'])
        if pair['old']:old.append(pair['old'])
    groups=defaultdict(list);oldmap={r['slot_id']:r for r in old}
    for row in new:
        if row['slot_id']in oldmap:groups[(row['benchmark'],row['harness'],row['method'])].append((oldmap[row['slot_id']],row))
    compared=[]
    for key,pairs in groups.items():
        metrics={}
        for name in ('decisions_observed','e2e_seconds','sdk_union_seconds','sdk_plus_censored_union_seconds','initialization_to_first_sdk_seconds'):
            metrics[name]={'historical16':describe([a.get(name)for a,b in pairs]),'recovery8':describe([b.get(name)for a,b in pairs])}
        compared.append({'benchmark':key[0],'harness':key[1],'method':key[2],'same_slots':len(pairs),'metrics':metrics})
    save(OUT/'latest.json',{'at':time.time(),'terminal_profiles':len(new),'selected':len(plan['jobs']),'new_groups':summarize(new),'historical_groups':summarize(old),
        'paired_descriptive_comparison':compared,'model_calls':0,'new_concurrency_experiments':0,
        'notes':['Old timeout rounds are right-censored progress, not the rounds required for eventual completion.',
            '200 turns/3h/three-send protocol and calendar period changed along with16→8; no causal concurrency claim.',
            'HTTP headers, upload and SDK times are client observations, not provider internal computation.',
            'Missing instrumentation remains null. Node CPU/memory counters are in runtime/*/*/telemetry.jsonl.']})
    return terminal==len(plan['jobs'])
def main():
    p=argparse.ArgumentParser();p.add_argument('--watch',action='store_true');a=p.parse_args()
    while True:
        done=collect()
        if done or not a.watch:break
        time.sleep(60)
if __name__=='__main__':main()
