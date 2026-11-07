#!/usr/bin/env python3
"""Exercise all five native Hermes policies against a local API fixture (no paid API)."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
from lab import ROOT, environment, python_for


class Fixture(BaseHTTPRequestHandler):
    count=0
    def log_message(self,*args):pass
    def do_POST(self):
        body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));Fixture.count+=1
        if self.path in ('/search','/fetch'):
            data=({'organic':[{'title':'Example','link':'https://example.com','snippet':'Fixture evidence'}]} if self.path=='/search'
                  else {'status':'success','content':'Fixture evidence: POLICY-OK'})
            b=json.dumps(data).encode();self.send_response(200);self.send_header('Content-Type','application/json')
            self.send_header('X-Cached','true');self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b);return
        tool_count=sum(m.get('role')=='tool' for m in body['messages'])
        message={'role':'assistant','content':'POLICY-OK'};reason='stop'
        if tool_count<2:
            name='web_search' if tool_count==0 else 'web_extract'
            arguments={'query':'fixture query','limit':1} if tool_count==0 else {'urls':['https://example.com']}
            message={'role':'assistant','content':None,'tool_calls':[{'index':0,'id':f'call_{tool_count}',
                'type':'function','function':{'name':name,'arguments':json.dumps(arguments)}}]};reason='tool_calls'
        data={'id':'fixture','object':'chat.completion','created':1,'model':body.get('model'),
              'choices':[{'index':0,'finish_reason':reason,'message':message}],
              'usage':{'prompt_tokens':100,'completion_tokens':3,'total_tokens':103,'prompt_tokens_details':{'cached_tokens':40}}}
        if body.get('stream'):
            self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
            data['object']='chat.completion.chunk';data['choices'][0]['delta']=data['choices'][0].pop('message')
            self.wfile.write(('data: '+json.dumps(data)+'\n\ndata: [DONE]\n\n').encode())
        else:
            b=json.dumps(data).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b)


def main():
    root=ROOT/'outputs/preflight'/f'hermes-policy-{time.time_ns()}';root.mkdir(parents=True)
    server=ThreadingHTTPServer(('127.0.0.1',0),Fixture);threading.Thread(target=server.serve_forever,daemon=True).start()
    try:
        for strategy in ['none','summarize','sliding_window','discard','visual']:
            out=root/strategy;out.mkdir();spec=out/'spec.json'
            env,cfg=environment(ROOT,'hermes');env.update(TOKENHUB_BASE_URL=f'http://127.0.0.1:{server.server_port}/v1',TOKENHUB_API_KEY='fixture-only')
            cfg['web'].update(search_host='127.0.0.1',search_port=server.server_port,fetch_base_url=f'http://127.0.0.1:{server.server_port}')
            config_path=out/'experiment.json';config_path.write_text(json.dumps(cfg))
            spec.write_text(json.dumps({'job_id':'fixture/'+strategy,'harness':'hermes','model':cfg['model'],
                'strategy':strategy,'question':'Search, fetch the result, then return POLICY-OK.','config_path':str(config_path)}))
            with (out/'process.log').open('w') as log:
                r=subprocess.run([python_for(ROOT),str(ROOT/'scripts/hermes_bc_worker.py'),'--spec',str(spec),'--out',str(out/'native'),'--live'],
                    cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=120)
            if r.returncode:raise RuntimeError(f'Hermes fixture failed: {out}/process.log')
            result=json.loads((out/'native/native-result.json').read_text())
            assert result['final']['text']=='POLICY-OK'
            calls=[json.loads(l) for l in (out/'native/metrics/calls.jsonl').read_text().splitlines()]
            assert calls and all(c['usage']['cacheReadTokens']==40 for c in calls)
            web=[json.loads(l) for l in (out/'native/metrics/web.jsonl').read_text().splitlines()]
            assert {w['kind'] for w in web}=={'search','fetch'} and all(w['success'] for w in web)
        (root/'result.json').write_text(json.dumps({'passed':True,'paid_requests':0,'fixture_requests':Fixture.count},indent=2))
        print(json.dumps({'passed':True,'artifacts':str(root),'paid_requests':0}))
    finally:server.shutdown()


if __name__=='__main__':main()
