#!/usr/bin/env python3
"""Zero-paid, real-Hermes loopback disconnect/recovery and budget-failclosed fixture."""
import argparse,concurrent.futures,hashlib,json,os,socket,subprocess,sys,threading,time
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from lab import ROOT,environment,python_for

def reference_fixture(explicit=None):
    required=('prefix.json','reference/compression-control.json','summary/spec.json','experiment.json','result.json')
    def valid(path):
        if not all((path/name).exists() for name in required):return False
        result=json.loads((path/'result.json').read_text())
        return result.get('passed') is True and result.get('paid_calls')==0
    if explicit is not None:
        path=Path(explicit).resolve()
        if not valid(path):raise ValueError('Reference must be a completed zero-paid controlled v4 localhost fixture')
        return path
    options=sorted((ROOT/'outputs/preflight').glob('controlled-native-v4-*'),reverse=True)
    for path in options:
        if valid(path):return path
    # Fresh checkout: build the real PDF/native-loop reference using localhost
    # only. This prerequisite makes no paid calls and enforces loopback URLs.
    import check_controlled_native_v4
    check_controlled_native_v4.main()
    return reference_fixture()


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--reference',type=Path);args=parser.parse_args()
    reference=reference_fixture(args.reference)
    import yaml
    output=ROOT/'outputs/preflight'/f'controlled-transport-v5-{time.time_ns()}';output.mkdir(parents=True)
    counts={};lock=threading.Lock()
    original=json.loads((reference/'prefix.json').read_text());native=original['messages'][0]['content'][1]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def disconnect(self):
            self.connection.shutdown(socket.SHUT_RDWR);self.connection.close();self.close_connection=True
        def do_POST(self):
            payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            if self.path=='/search':body={'organic':[{'title':'Fixture','link':'https://example.org','snippet':'The exact answer is 42.'}]};stream=False
            else:
                scenario=self.path.split('/')[1];stream=bool(payload.get('stream'))
                summary=not stream and payload.get('max_tokens')==8192
                kind='agent' if stream else 'summary' if summary else 'calibration'
                with lock:
                    state=counts.setdefault(scenario,{'agent':0,'summary':0,'calibration':0,'agent_body_sha':[]});state[kind]+=1;n=state[kind]
                    if stream:state['agent_body_sha'].append(hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest())
                if payload.get('tools'):
                    assert {t['function']['name'] for t in payload['tools']}=={'web_search','web_extract','image_search','image_crop','image_zoom_in'}
                    assert payload['messages'][1]['content'][1]==native,'Native bytes/detail lost'
                if scenario=='recover' and summary and n==1:self.disconnect();return
                if scenario=='exhaust' and stream:self.disconnect();return
                if stream:
                    if scenario=='recover' and n==1:
                        partial={'id':'partial','object':'chat.completion.chunk','created':1,'model':payload['model'],'choices':[{'index':0,'delta':{'role':'assistant','content':'Searching source','tool_calls':[{'index':0,'id':'search1','type':'function','function':{'name':'web_search','arguments':'{\"query\":'}}]},'finish_reason':None}]}
                        raw=('data: '+json.dumps(partial)+'\n\n').encode()
                        self.send_response(200);self.send_header('Content-Type','text/event-stream');self.send_header('Content-Length',str(len(raw)+2000));self.end_headers();self.wfile.write(raw);self.wfile.flush();self.disconnect();return
                    if scenario=='recover' and n==2:message={'role':'assistant','tool_calls':[{'index':0,'id':'search1','type':'function','function':{'name':'web_search','arguments':'{"query":"fixture","limit":1}'}}]};finish='tool_calls'
                    else:
                        if scenario=='recover':assert any(m.get('role')=='tool' and '42' in str(m.get('content')) for m in payload['messages'])
                        message={'role':'assistant','content':'Final answer: 42'};finish='stop'
                else:message={'role':'assistant','content':json.dumps({'summary':'Archived source states the exact number 42; verify using web search.'})};finish='stop'
                tokens=17000 if scenario=='overbudget' and stream else 1500
                body={'id':'fixture','object':'chat.completion','created':1,'model':payload['model'],'choices':[{'index':0,'message':message,'finish_reason':finish}],
                      'usage':{'prompt_tokens':tokens,'completion_tokens':1 if kind=='calibration' else 10,'total_tokens':tokens+(1 if kind=='calibration' else 10),'prompt_tokens_details':{'cached_tokens':0}}}
            if stream:
                body['object']='chat.completion.chunk';body['choices'][0]['delta']=body['choices'][0].pop('message')
                raw=('data: '+json.dumps(body)+'\n\ndata: [DONE]\n\n').encode();mime='text/event-stream'
            else:raw=json.dumps(body).encode();mime='application/json'
            self.send_response(200);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
    try:
        url=f'http://127.0.0.1:{server.server_port}';cfg=json.loads((reference/'experiment.json').read_text());cfg['web'].update(search_host='127.0.0.1',search_port=server.server_port,fetch_base_url=url)
        (output/'experiment.json').write_text(json.dumps(cfg));web=output/'web.yaml';web.write_text(yaml.safe_dump({'web':{'local_web':{'search':{'url':'127.0.0.1','port':server.server_port,'api_key':'fixture'},'fetch':{'fetch_server':{'base_url':url,'extract_mode':'text'}}}}}))
        results=[]
        def run(scenario):
            out=output/scenario;out.mkdir();spec=json.loads((reference/'summary/spec.json').read_text())
            spec.update(config_path=str(output/'experiment.json'),prefix_path=str(reference/'prefix.json'),target_reference_path=str(reference/'reference/compression-control.json'),max_rounds=4,offline_fixture=True)
            (out/'spec.json').write_text(json.dumps(spec))
            env,_=environment(ROOT,'hermes',output/'experiment.json');env.update(TOKENHUB_BASE_URL=url+'/'+scenario+'/v1',TOKENHUB_API_KEY='fixture-only',ACL_HERMES_WEB_CONFIG=str(web),SERPER_API_KEY='fixture-only',FETCH_SERVER_URL=url)
            with (out/'process.log').open('w') as log:
                child=subprocess.run([python_for(ROOT),str(ROOT/'scripts/controlled_native_worker_v5.py'),'--spec',str(out/'spec.json'),'--out',str(out),'--offline-fixture'],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=240)
            result=json.loads((out/'result.json').read_text());calls=[json.loads(l) for l in (out/'metrics/calls.jsonl').read_text().splitlines()]
            diagnostics=[json.loads(l) for l in (out/'metrics/transport-diagnostics.jsonl').read_text().splitlines()]
            unknown=sum(r.get('raw_provider_usage') is None for r in calls);actual=[r for r in calls if r['purpose']=='agent']
            if scenario=='recover':
                assert result['status']=='completed' and result['control_gate']['passed'],result
                assert counts[scenario]['summary']==2 and counts[scenario]['calibration']==2,counts[scenario]
                assert len(actual)==3 and unknown==2,(len(actual),unknown)
                assert result['control_gate']['prior_actual_usage_unknown']==1
                assert counts[scenario]['agent_body_sha'][0]==counts[scenario]['agent_body_sha'][1]
                assert any(r.get('event')=='stream_exception' for r in diagnostics)
                assert any(len(r.get('cause_chain',[]))>1 for r in diagnostics)
            elif scenario=='exhaust':
                assert result['status']=='failed' and not result['control_gate']['passed'],result
                assert counts[scenario]['agent']==6 and unknown==counts[scenario]['agent'],(counts[scenario],unknown)
                assert counts[scenario]['summary']==1 and counts[scenario]['calibration']==2
                assert not result['control_gate'].get('fatal_error'),result
            else:
                assert not result['control_gate']['passed'] and result['control_gate'].get('fatal_error')=='BudgetInfeasible',result
                assert counts[scenario]['agent']==1,counts[scenario]
            return {'scenario':scenario,'passed':True,'calls':len(calls),'unknown_usage_calls':unknown,'http_counts':counts[scenario],'status':result['status']}
        # Two fixture workers at most; all endpoints are loopback-enforced.
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            for value in pool.map(run,['recover','exhaust','overbudget']):results.append(value)
        (output/'result.json').write_text(json.dumps({'passed':True,'paid_calls':0,'reference_fixture':str(reference),'results':results,'runtime_sources_sha256':{name:hashlib.sha256((ROOT/'scripts'/name).read_bytes()).hexdigest() for name in ('controlled_native_worker_v5.py','capture_multimodal_prefix_v5.py','controlled_transport_v5.py')}},indent=2));print(json.dumps({'passed':True,'paid_calls':0,'artifact':str(output/'result.json')}))
    finally:server.shutdown()
if __name__=='__main__':main()
