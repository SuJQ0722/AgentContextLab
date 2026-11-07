#!/usr/bin/env python3
"""Local-only native Hermes RQ3 worker/adapter integration fixture."""
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
import yaml
from lab import ROOT,environment
from check_hermes_policy import Fixture


def main():
    out=ROOT/'outputs/preflight'/f'rq3-worker-{time.time_ns()}';out.mkdir(parents=True)
    server=ThreadingHTTPServer(('127.0.0.1',0),Fixture)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    url=f'http://127.0.0.1:{server.server_port}'
    try:
        cfg=json.loads((ROOT/'configs/experiment.json').read_text());cfg['visual_renderer']['history_scale']=.125
        cfg['web'].update(search_host='127.0.0.1',search_port=server.server_port,fetch_base_url=url)
        config=out/'experiment.json';config.write_text(json.dumps(cfg))
        web=out/'web.yaml';web.write_text(yaml.safe_dump({'web':{'local_web':{'search':{'url':'127.0.0.1','port':server.server_port,'api_key':'fixture'},'fetch':{'fetch_server':{'base_url':url}}}}}))
        spec={'job_id':'hermes/scale_0125/fixture_r01','harness':'hermes','strategy':'visual','model':cfg['model'],'scale':.125,
            'question_id':'fixture','question':'Search for fixture evidence, fetch the result, then answer POLICY-OK.','repeat':1,'timeout_seconds':90,'config_path':str(config)}
        path=out/'spec.json';path.write_text(json.dumps(spec))
        env,_=environment(ROOT,'hermes',config);env.update(TOKENHUB_BASE_URL=url+'/v1',TOKENHUB_API_KEY='fixture',ACL_HERMES_WEB_CONFIG=str(web),SERPER_API_KEY='fixture')
        with (out/'fixture.log').open('w') as log:
            proc=subprocess.run([sys.executable,str(ROOT/'scripts/rq3_trial.py'),'--spec',str(path),'--out',str(out/'attempt'),'--live'],env=env,stdout=log,stderr=subprocess.STDOUT,timeout=100)
        result=json.loads((out/'attempt/result.json').read_text())
        if proc.returncode or result['status']!='completed' or 'POLICY-OK' not in result['final']['text']:raise RuntimeError(f'Local RQ3 fixture failed: {out}')
        native=out/'attempt/native';metadata=json.loads((native/'rq3-render-adapter.json').read_text())
        private=yaml.safe_load((native/'hermes-home/config.yaml').read_text())
        if private['context']['strategy_config']['history_scale']!=.125:raise RuntimeError('Scale override did not reach native policy')
        calls=[json.loads(x) for x in (native/'metrics/calls.jsonl').read_text().splitlines()]
        summary={'passed':True,'paid_api_calls':0,'fixture_calls':len(calls),'scale_reached_native_policy':.125,'adapter':metadata['name']}
        (out/'result.json').write_text(json.dumps(summary,indent=2));print(json.dumps({**summary,'artifact':str(out/'result.json')}))
    finally:server.shutdown()


if __name__=='__main__':main()
