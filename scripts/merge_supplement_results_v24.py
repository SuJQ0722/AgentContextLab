"""Full-cohort recovery views retaining old completions and explicit protocol strata."""
import argparse,time
from collections import Counter,defaultdict
from pathlib import Path
from lab import ROOT
from supplement_recovery_v24 import DEFAULT,read,save,sha

OUT=ROOT/'outputs/reports/supplement-timeout-v24'
def summary(rows):
    known=[r['score']for r in rows if r.get('score')is not None];correct=sum(known);n=len(rows)
    repeat=[]
    for k in (1,2,3):
        values=[r['score']for r in rows if r.get('repeat')==k and r.get('score')is not None]
        repeat.append(sum(values)/len(values)if values else None)
    return {'slots':n,'states':dict(Counter(r['status']for r in rows)),'scored':len(known),'known_correct':correct,
        'fixed_denominator_known_correct_rate':correct/n if n else None,
        'valid_accuracy_pooled':correct/len(known)if known else None,
        'valid_accuracy_mean3':sum(repeat)/3 if all(x is not None for x in repeat)else None,
        'unobserved_correctness_bounds':[correct/n,(correct+n-len(known))/n]if n else None,
        'new_200turn_terminal':sum(r.get('selected_protocol')=='200turn/3h/v24'for r in rows),
        'old_retained':sum(r.get('selected_protocol')=='historical'for r in rows)}

def merge():
    snapshot=read(OUT/'latest.json');recovery={r['slot_id']:r for r in snapshot['observations']}
    base=[r for r in read(DEFAULT/'sources/core.json')['observations']if not(r['benchmark']=='mmbc100'and r['method']=='visual')]+read(DEFAULT/'sources/overlay.json')['observations']
    repaired={}
    for p in (ROOT/'outputs/grading/missing-completed-v24/jobs').glob('*/grade.json'):
        grade=read(p)
        if grade.get('status')=='scored':repaired[grade['slot_id']]=grade['score']
    groups=defaultdict(list);observations=[]
    for original in base:
        row=dict(original);new=recovery.get(row['slot_id']);row['selected_protocol']='historical'
        if row['slot_id']in repaired:row.update(score=repaired[row['slot_id']],status='completed_scored')
        if new:
            row['recovery_status']=new['status']
            if new['status']not in ('active','pending'):
                status='completed_scored'if new['score']is not None else 'completed_ungraded'if new['status']=='completed'else'timeout_unresolved'if new['status']=='timeout'else'failed'
                row.update(status=status,score=new['score'],selected_protocol='200turn/3h/v24',recovery_job_id=new['job_id'])
                path=DEFAULT/'jobs'/new['job_id']/'attempts/attempt_001/result.json'
                row.update(historical_latest_result_path=original['latest_terminal_result_path'],
                    latest_terminal_result_path=str(path),latest_terminal_result_sha256=sha(path),
                    latest_terminal_status=new['status'],selected_result_path=str(path),selected_result_sha256=sha(path))
            elif row['status']=='active':row['status']='timeout_unresolved'  # Frozen audited RQ3 temporary terminal.
        row['task_valid_score']=row['score'];observations.append(row)
        groups['/'.join([row['benchmark'],row['harness'],row['method']])].append(row)
    controls=[];paired=defaultdict(dict)
    for old in read(DEFAULT/'sources/controlled.json')['rows']:
        row=dict(old);key='controlled:'+row['job_id'];new=recovery.get(key);row['selected_protocol']='historical'
        if key in repaired:row['score']=repaired[key]
        if new:
            row['recovery_status']=new['status']
            if new['status']not in ('active','pending'):
                row.update(status=new['status'],score=new['score'],control_valid=new.get('control_valid',False),selected_protocol='200turn/3h/v24')
        controls.append(row)
        if row.get('action')=='matched_continuation'and row.get('control_valid')and row.get('score')is not None and row.get('vera_score')is not None:
            paired[(row['question_id'],row['repeat'])][row['method']]=row
    complete=[v for v in paired.values()if set(v)=={'summary','window'}]
    save(OUT/'full-cohort.json',{'at':time.time(),'groups':{k:summary(v)for k,v in groups.items()},'observations':observations,
        'controlled':{'methods':{m:summary([r for r in controls if r['method']==m])for m in ('summary','window')},'rows':controls,
            'strict_three_arm_complete_slots':len(complete),'strict_three_arm_distinct_questions':len({k[0]for k,v in paired.items()if set(v)=={'summary','window'}})},
        'mixed_protocol':True,'interpretation':'Latest terminal recovery selected independently of correctness; old successful500-turn results retained. This is not a uniform200-turn evaluation.',
        'estimated_scores_used':False,'models_called':0})
    return not any(r['status']in ('pending','active')for r in snapshot['observations'])
def main():
    p=argparse.ArgumentParser();p.add_argument('--watch',action='store_true');a=p.parse_args()
    while True:
        done=merge()
        if done or not a.watch:break
        time.sleep(60)
if __name__=='__main__':main()
