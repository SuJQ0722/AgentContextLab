#!/usr/bin/env python3
"""Wait for both harnesses, then grade once per terminal job with separate usage."""
import argparse
import concurrent.futures
import fcntl
import json
from pathlib import Path
import sys
import time
import urllib.request
from lab import ROOT,environment
from run_bc_campaign import attempt_state
from run_bc_trial import atomic
sys.path.insert(0,str(ROOT/'hermes-agent/Browsecomp_eval'))
from browsecomp_eval.judge import build_judge_prompt,analyse_judgemodel_res


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True)
    p.add_argument('--live',action='store_true');p.add_argument('--watch',action='store_true');a=p.parse_args()
    if not a.live:print('Dry run: no judging calls');return
    lock=(a.root/'judge.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    plan=json.loads((a.root/'plan.json').read_text());env,cfg=environment(ROOT,'dsh',a.root/'experiment.json')
    rows={r['id']:r for r in (json.loads(l) for l in (ROOT/'outputs/cohorts/bc100.jsonl').read_text().splitlines())}
    def grade(job):
        directory=a.root/'jobs'/job['job_id'];marker=directory/'judge-started.json';out=directory/'judge.json'
        if out.exists() or marker.exists():return
        state,attempt=attempt_state(directory)
        if state!='terminal':return
        result=json.loads((attempt/'result.json').read_text());prediction=(result.get('final') or {}).get('text') or ''
        record={'job_id':job['job_id'],'model':cfg['bc100_campaign']['judge_model'],'score':None,'usage':None}
        with marker.open('x') as f:json.dump(record,f)
        if not prediction.strip():record.update(status='scored',score=0.,api_calls=0,rule='no_final_answer_within_budget')
        else:
            row=rows[job['question_id']];prompt=build_judge_prompt(row['question'],prediction,row['answer'])
            request=urllib.request.Request(env['TOKENHUB_BASE_URL'].rstrip('/')+'/chat/completions',
                data=json.dumps({'model':record['model'],'messages':[{'role':'user','content':prompt}],
                                 'max_tokens':cfg['max_output_tokens']}).encode(),
                headers={'Authorization':'Bearer '+env['TOKENHUB_API_KEY'],'Content-Type':'application/json'})
            start=time.monotonic();record['api_calls']=1
            try:
                with urllib.request.urlopen(request,timeout=180) as response:data=json.load(response)
                record['response']=data;record['usage']=data.get('usage')
                score=analyse_judgemodel_res(data['choices'][0]['message'].get('content') or '')
                record.update(status='scored' if score is not None else 'invalid_judge_response',score=score)
            except Exception as e:record.update(status='judge_error',error_type=type(e).__name__)
            record['client_http_seconds']=time.monotonic()-start
        atomic(out,record)
    while True:
        terminal=sum(attempt_state(a.root/'jobs'/j['job_id'])[0]=='terminal' for j in plan['jobs'])
        if terminal==len(plan['jobs']):break
        if not a.watch:raise SystemExit('Predictions not finished; use --watch to keep judging out of prediction timing')
        time.sleep(30)
    with concurrent.futures.ThreadPoolExecutor(max_workers=cfg['bc100_campaign']['concurrency']) as pool:list(pool.map(grade,plan['jobs']))


if __name__=='__main__':main()
