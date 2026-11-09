#!/usr/bin/env python3
"""Read-only descriptive resolution/age analysis; no model or worker operations."""
import argparse,fcntl,json,time
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from info_loss_phase3 import DEFAULT_OUT,METHODS,save

def aggregate(root):
    data=json.loads((root/'results.json').read_text());facts={p.stem:json.loads(p.read_text()) for p in (root/'facts').glob('*.json')}
    points=[]
    paired=set(data['paired_complete_cases'])
    for row in data['records']:
        for fact in facts.get(row['case'],[]):
            qa=(row.get('qa_by_fact') or {}).get(fact['id'])
            semantic=(row.get('semantic_judge') or {}).get(fact['id'],{}).get('supported')
            points.append({'case':row['case'],'method':row['method'],'fact_id':fact['id'],'fact_type':fact['type'],
                'position':fact['position'],'distance_rounds':fact['distance_rounds'],'qa_exact':qa,'semantic_supported':semantic,
                'complete_five_condition_case':row['case'] in paired})
    grouped=[]
    for method in METHODS:
        for bucket in ['all','0','1-5','6-15','16+']:
            selected=[p for p in points if p['method']==method and (bucket=='all' or agebin(p['distance_rounds'])==bucket)]
            if not selected:continue
            row={'method':method,'distance_bucket':bucket,'source_facts':len(selected),'source_questions':len({p['case'] for p in selected})}
            for key in ['qa_exact','semantic_supported']:
                known=[p for p in selected if p[key] is not None]
                row[key]={'numerator':sum(p[key] for p in known),'observed_facts':len(known),'observed_questions':len({p['case'] for p in known}),
                    'accuracy':sum(p[key] for p in known)/len(known) if known else None}
            grouped.append(row)
    return {'study_status':data['status'],'updated_at':data['updated_at'],'paired_question_ids':sorted(paired),'points':points,'groups':grouped,
        'limitations':['Observed denominators differ when requests fail; see main report missing-response bounds.',
          'Facts within a question are correlated. Descriptive only; no independence claim or fabricated CI.',
          'Original round age is observational, confounded by fact content/position; not causal temporal decay.',
          'Same-model semantic judge exploratory; substring coverage is not used as semantic recall.',
          'Downsampling changes all full canvases, not the historical far-only policy parameter.']}

def agebin(age):return '0' if age==0 else '1-5' if age<=5 else '6-15' if age<=15 else '16+'

def plot(result,out):
    fig,axes=plt.subplots(1,2,figsize=(12,4),layout='constrained')
    for metric,label in [('qa_exact','Probe exact match'),('semantic_supported','Semantic supported fact')]:
        xs=[];ys=[]
        for scale in [.5,.75,1]:
            method='canvas_'+str(scale)
            if scale==1:method='canvas_1'
            found=next((g for g in result['groups'] if g['method']==method and g['distance_bucket']=='all'),None)
            if found and found[metric]['accuracy'] is not None:xs.append(scale);ys.append(found[metric]['accuracy'])
        if xs:axes[0].plot(xs,ys,'o-',label=label)
    axes[0].set(xlabel='Full canvas linear dimension scale',ylabel='Observed fact score',ylim=(-.03,1.03),title='Resolution (available observations)')
    if axes[0].lines:axes[0].legend()
    buckets=['0','1-5','6-15','16+']
    for method in METHODS:
        x=[];y=[]
        for i,bucket in enumerate(buckets):
            g=next((g for g in result['groups'] if g['method']==method and g['distance_bucket']==bucket),None)
            if g and g['qa_exact']['accuracy'] is not None:x.append(i);y.append(g['qa_exact']['accuracy'])
        if x:axes[1].plot(x,y,'o-',label=method)
    axes[1].set(xticks=range(4),xticklabels=buckets,xlabel='Original tool rounds after fact',ylabel='Observed QA exact match',ylim=(-.03,1.03),title='Age association (not causal decay)')
    if axes[1].lines:axes[1].legend(fontsize=8)
    fig.suptitle('Exploratory real-canvas study; missing responses excluded here, bounds in main report',fontsize=10)
    fig.savefig(out/'resolution-age.png',dpi=160);fig.savefig(out/'resolution-age.pdf');plt.close(fig)

def render(root):
    result=aggregate(root);out=root/'analysis';out.mkdir(exist_ok=True);save(out/'descriptive.json',result)
    if result['points']:plot(result,out)
    lines=['# Phase3 descriptive resolution and age analysis','',f"Study status: {result['study_status']}; complete five-condition questions: {len(result['paired_question_ids'])}.",'',
      '|Method|Original round-distance bucket|QA correct/observed|QA questions|Semantic support/observed|','|---|---|---:|---:|---:|']
    for g in result['groups']:
        q=g['qa_exact'];s=g['semantic_supported'];lines.append(f"|{g['method']}|{g['distance_bucket']}|{q['numerator']}/{q['observed_facts']}|{q['observed_questions']}|{s['numerator']}/{s['observed_facts']}|")
    lines+=['']+['- '+x for x in result['limitations']]
    if result['points']:lines+=['','![Resolution and original age](resolution-age.png)']
    (out/'README.md').write_text('\n'.join(lines)+'\n');print(json.dumps({'status':result['study_status'],'fact_observations':len(result['points']),'output':str(out)}))
def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,default=DEFAULT_OUT);p.add_argument('--watch',action='store_true');a=p.parse_args();root=a.output
    if not a.watch:render(root);return
    with (root/'analysis-watch.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);last=None
        while True:
            try:
                source=root/'results.json';stamp=source.stat().st_mtime_ns
                if stamp!=last:
                    render(root);last=stamp
                    if json.loads(source.read_text()).get('status') in ('completed','infrastructure_hold'):return
            except (OSError,ValueError,KeyError) as exc:print(json.dumps({'report_error':type(exc).__name__}),flush=True)
            time.sleep(60)
if __name__=='__main__':main()
