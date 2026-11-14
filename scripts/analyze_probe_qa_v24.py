"""Provisional fixed-denominator Probe QA summaries; no model calls or human labels."""
import argparse,json,time,random
from collections import Counter
from probe_qa_v24 import OUT,METHODS,parse_json
from supplement_recovery_v24 import read,save

def analyze(out=OUT):
    manifest=read(out/'manifest.json');scores={m:{}for m in METHODS};exact={m:[]for m in METHODS};states=Counter();budget=Counter();judged=Counter();abstentions=Counter()
    for case in manifest['cases']:
        root=out/'jobs'/case['id'];path=root/'result.json'
        if not path.exists():states['active_or_pending']+=1;continue
        result=read(path);states[result['status']]+=1
        if not(root/'facts.json').exists():continue
        facts=read(root/'facts.json')
        for method,record in result.get('methods',{}).items():
            if method.startswith('summary_') and record.get('budget_matched') is not True:budget[method]+=1;continue
            answers=record.get('answers');j=record.get('independent_judge',{})
            if isinstance(answers,dict):
                for fact in facts:
                    if fact['id']not in answers:continue
                    answer=answers[fact['id']]
                    if answer is None:abstentions[method]+=1
                    if answer is not None and not isinstance(answer,str):continue
                    exact[method].append(int(' '.join(str(answer or '').split()).casefold()==' '.join(fact['answer'].split()).casefold()))
            if j.get('status')!='completed':continue
            try:values=parse_json(j['content'])['facts']
            except (ValueError,KeyError,TypeError):continue
            if not isinstance(values,dict):continue
            parsed={}
            for fact in facts:
                value=(values.get(fact['id'])or{}).get('score') if isinstance(values.get(fact['id']),dict)else None
                if type(value)in(int,float) and value in (0,1):parsed[fact['id']]=value;judged[method]+=1
            if len(parsed)==6:scores[method][case['id']]=sum(parsed.values())/6
    methods={}
    for method in METHODS:
        # Complete six-fact history blocks are used for semantic cluster comparisons.
        values=list(scores[method].values());correct=sum(values)*6;observed=len(values)*6
        methods[method]={'fixed_fact_denominator':240,'semantic_complete_histories':len(values),'semantic_observed_facts':observed,
            'semantic_correct':correct,'observed_accuracy':correct/observed if observed else None,
            'fixed_denominator_bounds':[correct/240,(correct+240-observed)/240],
            'exact_observed_facts':len(exact[method]),'exact_correct':sum(exact[method]),
            'budget_unmatched_or_missing_histories':budget[method],'abstentions':abstentions[method],
            'semantic_individually_valid_fact_scores':judged[method]}
    paired=[]
    for scale in ['1','0.75','0.5']:
        left='canvas_'+scale;right='summary_'+scale;common=sorted(scores[left].keys()&scores[right].keys())
        diffs=[scores[left][key]-scores[right][key]for key in common];ci=None
        if len(diffs)>=2:
            rng=random.Random(20261114);draws=sorted(sum(rng.choices(diffs,k=len(diffs)))/len(diffs)for _ in range(10000));ci=[draws[249],draws[9749]]
        paired.append({'left':left,'right':right,'complete_paired_histories':len(common),'mean_difference':sum(diffs)/len(diffs)if diffs else None,'history_cluster_bootstrap_95pct':ci})
    result={'at':time.time(),'states':dict(states),'methods':methods,'paired':paired,
        'human_review_status':'pending','provisional_until_ground_truth_and_random_audit_reviewed':True,
        'pair_selection':'Complete six-fact independently judged histories with measured budget parity; fixed240 bounds also reported.',
        'causal_temporal_decay_claimed':False,'model_calls':0}
    save(out/'analysis/latest.json',result);return states.get('active_or_pending',0)==0

def main():
    p=argparse.ArgumentParser();p.add_argument('--watch',action='store_true');a=p.parse_args()
    while True:
        done=analyze()
        if done or not a.watch:break
        time.sleep(60)
if __name__=='__main__':main()
