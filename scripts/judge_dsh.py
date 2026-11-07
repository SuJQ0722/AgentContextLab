#!/usr/bin/env python3
"""Grade completed BC-100 attempts with DeepSeek and persist separate judge usage."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time
import urllib.request
from lab import ROOT, environment
sys.path.insert(0, str(ROOT / 'hermes-agent/Browsecomp_eval'))
from browsecomp_eval.judge import build_judge_prompt, analyse_judgemodel_res


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true');parser.add_argument('--watch',action='store_true')
    args=parser.parse_args()
    if not args.live:
        print('Dry run: uses the configured DeepSeek route and existing Hermes judgment prompt; no API calls.')
        return
    env,cfg=environment(ROOT,'dsh')
    if not cfg['model'].startswith('deepseek-'):
        raise SystemExit('This campaign permits only DeepSeek for new inference and grading.')
    rows={r['id']:r for r in (json.loads(line) for line in (ROOT/'outputs/cohorts/bc100.jsonl').read_text().splitlines())}
    root=ROOT/'outputs/pilot/bc100'
    while True:
        campaign=json.loads((root/'campaign.json').read_text())
        # Keep grading out of prediction latency/cache measurements. The watch
        # service waits for the complete frozen prediction campaign first.
        if args.watch and len(list(root.glob('*/*/result.json')))<campaign['planned_runs']:
            time.sleep(30)
            continue
        for result_path in sorted(root.glob('*/*/result.json')):
            out=result_path.with_name('judge.json')
            if out.exists() or result_path.with_name('judge-started.json').exists():continue
            try:result=json.loads(result_path.read_text())
            except ValueError:continue
            reason=((result.get('final') or {}).get('reason') or {}).get('kind')
            if reason not in ('completed','max-tokens') and result.get('failure_category') not in ('step_limit','timeout'):continue
            qid=result_path.parent.name;row=rows[qid]
            pred=(result.get('final') or {}).get('text') or ''
            record={'question_id':qid,'timestamp':datetime.now(timezone.utc).isoformat(),
                'judge_model':cfg['model'],'score':None,'usage':None,'status':'pending'}
            result_path.with_name('judge-started.json').write_text(json.dumps(record))
            if not pred.strip():
                record.update(score=0.0,status='scored',rule='empty_response',api_calls=0)
            else:
                prompt=build_judge_prompt(row['question'],pred,row['answer'])
                record['prompt_sha256']=hashlib.sha256(prompt.encode()).hexdigest()
                request=urllib.request.Request(env['TOKENHUB_BASE_URL'].rstrip('/')+'/chat/completions',
                    data=json.dumps({'model':cfg['model'],'messages':[{'role':'user','content':prompt}],
                                     'max_tokens':cfg['max_output_tokens']}).encode(),
                    headers={'Authorization':'Bearer '+env['TOKENHUB_API_KEY'],'Content-Type':'application/json'})
                start=time.monotonic()
                try:
                    with urllib.request.urlopen(request,timeout=180) as stream:
                        response=json.load(stream);record['provider_request_id']=stream.headers.get('x-request-id')
                    record['response']=response;record['usage']=response.get('usage')
                    content=response['choices'][0]['message'].get('content') or ''
                    score=analyse_judgemodel_res(content)
                    record.update(score=score,status='scored' if score is not None else 'invalid_judge_response',api_calls=1)
                except Exception as error:
                    record.update(status='transport_error',error_type=type(error).__name__,api_calls=1)
                record['client_http_seconds']=time.monotonic()-start
            temp=out.with_suffix('.tmp');temp.write_text(json.dumps(record,indent=2));temp.replace(out)
            print(json.dumps({'question':qid,'strategy':result_path.parent.parent.name,'status':record['status'],'score':record['score']}),flush=True)
        campaign=json.loads((root/'campaign.json').read_text())
        if not args.watch or len(list(root.glob('*/*/result.json')))>=campaign['planned_runs']:break
        time.sleep(30)


if __name__=='__main__':main()
