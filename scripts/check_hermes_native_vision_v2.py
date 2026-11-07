#!/usr/bin/env python3
"""Exercise real Hermes compression and normal image routing using localhost only."""
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json,threading,subprocess,time,sys
from pathlib import Path
from lab import ROOT,environment,python_for

class Fixture(BaseHTTPRequestHandler):
    calls=0;searches=0;actual=[]
    def log_message(self,*args):pass
    def do_POST(self):
        body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        if self.path=='/api/show':
            self.send_response(404);self.end_headers();return
        if self.path=='/fetch':data={'status':'success','content':'Archived source facts.'}
        elif self.path=='/search':
            Fixture.searches+=1;n=Fixture.searches
            snippet=f'Archived record R{n}: instrument copper harp; catalog number {81460+n}.\n'+'\n'.join(f'Evidence row {i}: source Cedar study measurement {300+n+i}; this is archival text.' for i in range(70))
            data={'organic':[{'title':f'Source R{n}','link':f'https://example.org/{n}','snippet':snippet}]}
        else:
            Fixture.calls+=1;Fixture.actual.append(body)
            images=[p for m in body['messages'] for p in m.get('content',[]) if isinstance(p,dict) and p.get('type')=='image_url']
            if images:message={'role':'assistant','content':'NATIVE-CANVAS-OK'};reason='stop'
            else:
                assert Fixture.calls<=9,'No actual routed image after compression'
                message={'role':'assistant','content':None,'tool_calls':[{'index':0,'id':f's{Fixture.calls}','type':'function','function':{'name':'web_search','arguments':json.dumps({'query':f'record {Fixture.calls}','limit':1})}}]};reason='tool_calls'
            data={'id':'fixture','object':'chat.completion','created':1,'model':body['model'],
                'choices':[{'index':0,'finish_reason':reason,'message':message}],
                'usage':{'prompt_tokens':1000 if images else 40000,'completion_tokens':10,'total_tokens':1010 if images else 40010,'prompt_tokens_details':{'cached_tokens':0}}}
        if body.get('stream'):
            data['object']='chat.completion.chunk';data['choices'][0]['delta']=data['choices'][0].pop('message')
            raw=('data: '+json.dumps(data)+'\n\ndata: [DONE]\n\n').encode();mime='text/event-stream'
        else:raw=json.dumps(data).encode();mime='application/json'
        self.send_response(200);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)

def main():
    out=ROOT/'outputs/preflight'/f'hermes-native-vision-v2-{time.time_ns()}';out.mkdir(parents=True)
    server=ThreadingHTTPServer(('127.0.0.1',0),Fixture);threading.Thread(target=server.serve_forever,daemon=True).start()
    try:
        env,cfg=environment(ROOT,'hermes');url=f'http://127.0.0.1:{server.server_port}'
        env.update(TOKENHUB_BASE_URL=url+'/v1',TOKENHUB_API_KEY='fixture-only')
        cfg['web'].update(search_host='127.0.0.1',search_port=server.server_port,fetch_base_url=url)
        cfg['bc100_campaign']['max_rounds']=10
        (out/'experiment.json').write_text(json.dumps(cfg));spec={'job_id':'native-routing-fixture','strategy':'visual','model':cfg['model'],
            'question':'Search archival records sequentially. Preserve the evidence and finish after inspecting the compressed history.', 'config_path':str(out/'experiment.json')}
        (out/'spec.json').write_text(json.dumps(spec))
        with (out/'process.log').open('w') as log:
            p=subprocess.run([python_for(ROOT),str(ROOT/'scripts/hermes_native_vision_worker_v2.py'),'--spec',str(out/'spec.json'),'--out',str(out/'native'),'--live','--rq3-pdf'],env=env,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,timeout=180)
        if p.returncode:raise RuntimeError(f'Native routing failed; inspect {out}/process.log')
        result=json.loads((out/'native/native-result.json').read_text());assert result['final']['text']=='NATIVE-CANVAS-OK'
        audit=[json.loads(l) for l in (out/'native/metrics/vision-route.jsonl').read_text().splitlines()]
        compressions=[r for r in audit if r['event']=='engine_compressed_messages'];post=[r for r in audit if r['event']=='actual_sdk_request' and r['compression_count']]
        assert compressions and post and all(r['matching_rendered_pixels'] for r in post)
        assert not any(r['event']=='blocked_auxiliary' for r in audit)
        wire=[json.loads(l) for l in (out/'native/metrics/vision-wire.jsonl').read_text().splitlines()]
        assert any(r['compression_count'] and r['matching_rendered_pixels'] for r in wire)
        (out/'actual-post-compression-request.json').write_text(json.dumps(Fixture.actual[-1]))
        (out/'result.json').write_text(json.dumps({'passed':True,'paid_calls':0,'real_native_compressions':len(compressions),
            'post_compression_requests':len(post),'matching_pixels':True,'no_sdk_image_injection':True,'actual_image_count':len(post[-1]['images'])},indent=2))
        print(json.dumps({'passed':True,'paid_calls':0,'artifact':str(out/'result.json')}))
    finally:server.shutdown()
if __name__=='__main__':main()
