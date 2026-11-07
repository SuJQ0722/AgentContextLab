#!/usr/bin/env python3
"""Localhost-only real Hermes search-loop validation of all controlled methods."""
import base64,io,json,os,subprocess,sys,threading,time
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from lab import ROOT,environment,python_for

def main():
    from PIL import Image
    import yaml
    output=ROOT/'outputs/preflight'/f'controlled-native-v2-{time.time_ns()}';output.mkdir(parents=True)
    counts={};agents={}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            if self.path=='/search':body={'organic':[{'title':'Fixture','link':'https://example.org','snippet':'The exact answer is 42.'}]}
            else:
                tag=payload.get('model','');counts[tag]=counts.get(tag,0)+1
                if payload.get('stream'):
                    agents[tag]=agents.get(tag,0)+1
                    if agents[tag]%2==1:message={'role':'assistant','content':None,'tool_calls':[{'index':0,'id':'search1','type':'function','function':{'name':'web_search','arguments':'{"query":"fixture","limit":1}'}}]};finish='tool_calls'
                    else:
                        assert any(m.get('role')=='tool' and '42' in str(m.get('content')) for m in payload['messages']), 'Second native call lost tool result'
                        message={'role':'assistant','content':'Final answer: 42'};finish='stop'
                else:message={'role':'assistant','content':'Archived source: exact answer 42.'};finish='stop'
                body={'id':'fixture','object':'chat.completion','created':1,'model':tag,'choices':[{'index':0,'message':message,'finish_reason':finish}],
                      'usage':{'prompt_tokens':1500,'completion_tokens':10,'total_tokens':1510,'prompt_tokens_details':{'cached_tokens':0}}}
            if payload.get('stream'):
                body['object']='chat.completion.chunk';body['choices'][0]['delta']=body['choices'][0].pop('message')
                raw=('data: '+json.dumps(body)+'\n\ndata: [DONE]\n\n').encode();mime='text/event-stream'
            else:raw=json.dumps(body).encode();mime='application/json'
            self.send_response(200);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
    try:
        url=f'http://127.0.0.1:{server.server_port}';cfg=json.loads((ROOT/'configs/experiment.json').read_text())
        cfg['web'].update(search_host='127.0.0.1',search_port=server.server_port,fetch_base_url=url)
        (output/'experiment.json').write_text(json.dumps(cfg));image=output/'image.png';Image.new('RGB',(16,16),'blue').save(image)
        native={'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(image.read_bytes()).decode()}}
        (output/'prefix.json').write_text(json.dumps({'model':cfg['model'],'messages':[{'role':'user','content':[{'type':'text','text':'Find the exact number using web search.'},native]},{'role':'assistant','content':'Inspect archived evidence','tool_calls':[{'id':'old','type':'function','function':{'name':'web_search','arguments':'{"query":"archived"}'}}]},{'role':'tool','tool_call_id':'old','content':'Archived source says exact number 42; verify using search.'}]}))
        web=output/'web.yaml';web.write_text(yaml.safe_dump({'web':{'local_web':{'search':{'url':'127.0.0.1','port':server.server_port,'api_key':'fixture-only'},'fetch':{'fetch_server':{'base_url':url}}}}}))
        env,_=environment(ROOT,'hermes');env.update(TOKENHUB_BASE_URL=url+'/v1',TOKENHUB_API_KEY='fixture-only',ACL_HERMES_WEB_CONFIG=str(web),SERPER_API_KEY='fixture-only')
        results=[]
        for method in ['visual','summary','window']:
            out=output/method;out.mkdir();spec={'question':'Find answer using web search.','question_id':'fixture','dataset':'fixture','image':[str(image)],'model':cfg['model'],
                'config_path':str(output/'experiment.json'),'threshold':16384,'max_rounds':4,'prefix_path':str(output/'prefix.json'),'method':method}
            path=out/'spec.json';path.write_text(json.dumps(spec))
            with (out/'process.log').open('w') as log:
                child=subprocess.run([python_for(ROOT),str(ROOT/'scripts/controlled_native_worker_v2.py'),'--spec',str(path),'--out',str(out)],env=env,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,timeout=120)
            result=json.loads((out/'result.json').read_text())
            assert child.returncode==0 and result['status']=='completed' and result['control_gate']['passed'],(method,result)
            conversation=json.loads((out/'conversation.json').read_text());assert '42' in str(conversation)
            calls=[json.loads(l) for l in (out/'metrics/calls.jsonl').read_text().splitlines()];assert sum(r['purpose']=='agent' for r in calls)==2
            assert (out/'metrics/web.jsonl').exists()
            results.append({'method':method,'passed':True,'agent_calls':2,'total_fixture_calls':len(calls)})
        (output/'result.json').write_text(json.dumps({'passed':True,'paid_calls':0,'results':results},indent=2));print(json.dumps({'passed':True,'paid_calls':0,'artifact':str(output/'result.json')}))
    finally:server.shutdown()
if __name__=='__main__':main()
