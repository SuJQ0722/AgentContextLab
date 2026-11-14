"""Recompute the same-completion MMBC cost comparison after all selected retries finish."""
import argparse,time
from collections import defaultdict
from pathlib import Path
from lab import ROOT
from supplement_recovery_v24 import DEFAULT,read,save,sha
from visual_inline_route_accounting_v5 import inspect_attempt
from monitor_bc_campaign_v3 import aggregate,FIELDS

OUT=ROOT/'outputs/reports/supplement-timeout-v24/final-mmbc-cost'
def compute():
    plan=read(DEFAULT/'plan.json');jobs={j['slot_id']:j for j in plan['jobs']if j.get('experiment_kind')=='mmbc'}
    pending=sum(not(DEFAULT/'jobs'/j['job_id']/'attempts/attempt_001/result.json').exists()for j in jobs.values())
    if pending:save(OUT/'status.json',{'at':time.time(),'state':'waiting_for_timeout_recovery','remaining':pending,'model_calls':0});return False
    rows=[r for r in read(DEFAULT/'sources/core.json')['observations']if r['benchmark']=='mmbc100'and r['method']!='visual']+read(DEFAULT/'sources/overlay.json')['observations']
    repaired={}
    for p in (ROOT/'outputs/grading/missing-completed-v24/jobs').glob('*/grade.json'):
        g=read(p)
        if g.get('status')=='scored':repaired[g['slot_id']]=g['score']
    per_slot=defaultdict(dict);details=[]
    for row in rows:
        rp=Path(row['latest_terminal_result_path']);score=row.get('score');job=jobs.get(row['slot_id'])
        if job:
            rp=DEFAULT/'jobs'/job['job_id']/'attempts/attempt_001/result.json'
            result=read(rp)
            if result.get('supplement_version')!=plan['version']:return False
            if result.get('status')=='completed':
                gp=ROOT/'outputs/grading/supplement-timeout-v24/jobs'/job['job_id']/'grade.json'
                if not gp.exists():return False
                g=read(gp);score=g.get('score')if g.get('status')=='scored'else None
            else:score=None
        else:
            result=read(rp);score=repaired.get(row['slot_id'],score)
        item={'slot_id':row['slot_id'],'method':row['method'],'question_id':row['question_id'],'repeat':row['repeat'],
              'status':result.get('status'),'score':score,'cost_source_result':str(rp),'cost_source_sha256':sha(rp)}
        native=result.get('native_artifact_root')
        if result.get('status')=='completed'and score is not None and native and Path(native).is_dir():
            attempt=Path(native).parent;cache=OUT/'attempts'/(sha(rp)+'.json')
            if cache.exists():account=read(cache)
            else:
                requests,coverage=inspect_attempt(attempt,'hermes');account={'usage':aggregate(requests),'coverage':coverage};save(cache,account)
            item['usage']=account['usage'];item['complete_cost']=all(account['usage']['fields'][f]['complete_total']is not None for f in FIELDS)
        else:item['complete_cost']=False
        details.append(item);per_slot[(row['question_id'],row['repeat'])][row['method']]=item
    methods=sorted({r['method']for r in rows});common=[r for r in per_slot.values()if set(r)==set(methods)and all(x['complete_cost']for x in r.values())]
    summary={}
    for method in methods:
        usage={f:sum(row[method]['usage']['fields'][f]['complete_total']for row in common)/len(common)if common else None for f in FIELDS}
        # Frozen historical reference prices, explicitly not a current provider bill.
        reference=(usage['cached_input']*.15+usage['noncache_input']*1.5+usage['output']*9)/1e6 if common else None
        summary[method]={'common_slots':len(common),'mean_tokens':usage,'archived_reference_usd_per_slot':reference,
             'accuracy_on_identical_slots':sum(r[method]['score']for r in common)/len(common)if common else None}
    save(OUT/'latest.json',{'at':time.time(),'methods':summary,'observations':details,'model_calls':0,
        'fixed_method_denominator':300,'actual_usd':None,'pricing':'Historical reference only: cache0.15/noncache1.50/output9 USD per million; not current price or actual bill.',
        'scope':'Successful selected native trajectory only, matching historical efficiency table; failed/recovery expenditure separately in ../costs/latest.json.',
        'limitations':['Common completed/scored/full-usage subset; survivor bias persists.','Old500/new200 mixed recovery protocol.','Missing usage is not zero.']})
    save(OUT/'status.json',{'at':time.time(),'state':'computed','common_slots':len(common),'model_calls':0});return True
def main():
    p=argparse.ArgumentParser();p.add_argument('--watch',action='store_true');a=p.parse_args()
    while True:
        done=compute()
        if done or not a.watch:break
        time.sleep(60)
if __name__=='__main__':main()
