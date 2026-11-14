"""Offline accounting of every new recovery attempt, including unsuccessful ones."""
import argparse,time
from collections import defaultdict
from lab import ROOT
from supplement_recovery_v24 import DEFAULT,read,save,sha
from visual_inline_route_accounting_v5 import inspect_attempt
from monitor_bc_campaign_v3 import aggregate

OUT=ROOT/'outputs/reports/supplement-timeout-v24/costs'
def collect():
    plan=read(DEFAULT/'plan.json');groups=defaultdict(list);coverage=[];terminal=0
    for job in plan['jobs']:
        attempt=DEFAULT/'jobs'/job['job_id']/'attempts/attempt_001';rp=attempt/'result.json'
        if not rp.exists():continue
        result=read(rp)
        if result.get('supplement_version')!=plan['version'] and result.get('failure_category')!='launcher_error':continue
        terminal+=1;cache=OUT/'attempts'/(job['job_id']+'.json')
        if cache.exists() and read(cache).get('result_sha256')==sha(rp):value=read(cache)
        else:
            rows,summary=inspect_attempt(attempt,job['harness']);value={'job_id':job['job_id'],'result_sha256':sha(rp),'requests':rows,'coverage':summary};save(cache,value)
        group='/'.join(str(job.get(k)) for k in ('scope','experiment_kind','harness','method','scale'))
        groups[group]+=value['requests'];coverage.append({'job_id':job['job_id'],**value['coverage']})
    save(OUT/'latest.json',{'at':time.time(),'terminal_attempts':terminal,'selected_attempts':len(plan['jobs']),
        'groups':{k:aggregate(v)for k,v in groups.items()},'coverage':coverage,'actual_usd':None,
        'known_subtotals_are_not_complete_costs':True,'failed_requests_included':True,
        'sdk_and_transport_not_double_counted':True,'historical_spend_not_overwritten':True,
        'analysis_status':'Collecting recovery expenditure; final paired fixed-cohort comparison awaits completion.',
        'provider_internal_latency_measured':False})
    return terminal==len(plan['jobs'])
def main():
    p=argparse.ArgumentParser();p.add_argument('--watch',action='store_true');a=p.parse_args()
    while True:
        done=collect()
        if done or not a.watch:break
        time.sleep(60)
if __name__=='__main__':main()
