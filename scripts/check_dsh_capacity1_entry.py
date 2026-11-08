#!/usr/bin/env python3
"""Localhost-only capacity1 CLI replay of complete real second-compression canvases.

Uses retained q039/q048 canvas bytes, not new benchmark model calls. The source
second-compression images are admitted as native inputs for transport replay;
this does not claim to rerun the original trajectory or compression decisions.
"""
import base64
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
from lab import ROOT, environment
from dsh_image_preservation_capacity1 import runtime_record


def rows(path):
    return [json.loads(s) for s in path.read_text().splitlines()] if path.exists() else []


def main():
    root=ROOT/'outputs/preflight'/f'dsh-capacity1-entry-{time.time_ns()}'
    root.mkdir(parents=True)
    report={'paid_model_calls':0,'external_http_calls':0,'runtime':runtime_record(),
            'scope':'Actual capacity1 entry and native adapter, with complete real second-compression canvases admitted as native inputs; local HTTP only. Not a new benchmark trajectory.', 'cases':[]}
    for case,q,multiplier in [('q039-second','q_039',1),('q048-second','q_048',1),('q048-over64','q_048',4)]:
        source=ROOT/f'outputs/campaigns/bc100-r3-hermes-parity-v3/jobs/dsh/visual/{q}_r01/attempts/attempt_001/native/visual_native/{q}'
        expected=json.loads((source/'workspace/metrics/expected-wire.json').read_text())
        folder=root/case;folder.mkdir(); refs=expected['native_attachments']*multiplier
        paths=[]
        for index,ref in enumerate(refs):
            sha=ref['attachmentId'].removeprefix('sha256:')
            path=folder/f'canvas-{index:02d}.png'
            os.link(source/f'dsh-home/attachments/v1/objects/{sha[:2]}/{sha}',path)
            paths.append(str(path))
        cohort=folder/'cohort.jsonl'
        cohort.write_text(json.dumps({'id':q,'question':'Report that the complete historical canvas attachments are present.','image':paths})+'\n')
        output=folder/'runs'; work=output/'visual_native'/q/'workspace'
        observed=[]; errors=[]
        class Fixture(BaseHTTPRequestHandler):
            def log_message(self,*unused): pass
            def do_POST(self):
                if self.path!='/v1/chat/completions':
                    errors.append('Unexpected non-model fixture endpoint');self.send_error(400);return
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                images=[p for m in body['messages'] for p in (m.get('content',[]) if isinstance(m.get('content'),list) else []) if p['type']=='image_url']
                hashes=[hashlib.sha256(base64.b64decode(p['image_url']['url'].split(',',1)[1])).hexdigest() for p in images]
                expectation=json.loads((work/'metrics/expected-wire.json').read_text())
                exact=hashes==expected['wire_sha256']*multiplier==expectation['wire_sha256']
                if not exact: errors.append('Final HTTP image hashes/order/count changed')
                details=[p['image_url'].get('detail') for p in images]
                if not all(want is None or got==want for got,want in zip(details,expectation['details'])): errors.append('Final details changed')
                observed.append({'image_hashes':hashes,'details':details,'all_source_bytes_match':exact,
                    'base64_bytes':sum(len(p['image_url']['url'].split(',',1)[1]) for p in images)})
                self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
                base={'id':'capacity1-local','object':'chat.completion.chunk','created':1,'model':body['model']}
                for chunk in [dict(base,choices=[{'index':0,'delta':{'role':'assistant','content':'CAPACITY-LOCAL-OK'},'finish_reason':None}]),
                              dict(base,choices=[{'index':0,'delta':{},'finish_reason':'stop'}],usage={'prompt_tokens':1000,'completion_tokens':5,'total_tokens':1005,'prompt_tokens_details':{'cached_tokens':0}})]:
                    self.wfile.write(('data: '+json.dumps(chunk)+'\n\n').encode())
                self.wfile.write(b'data: [DONE]\n\n')
        server=ThreadingHTTPServer(('127.0.0.1',0),Fixture)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        try:
            url=f'http://127.0.0.1:{server.server_port}'
            cfg=json.loads((ROOT/'configs/experiment.v3.review.json').read_text())
            cfg['web'].update(search_host='127.0.0.1',search_port=server.server_port,fetch_base_url=url)
            cfg['bc100']['max_rounds']=2
            config=folder/'config.json';config.write_text(json.dumps(cfg))
            private=folder/'web.json';private.write_text(json.dumps({'web':{'local_web':{'search':{'url':'127.0.0.1','port':server.server_port,'api_key':'fixture'},'fetch':{'fetch_server':{'base_url':url,'extract_mode':'text','timeout':5}}}}}))
            env,_=environment(ROOT,'dsh',config)
            env.update(TOKENHUB_BASE_URL=url+'/v1',TOKENHUB_API_KEY='fixture',SERPER_API_KEY='fixture',FETCH_SERVER_URL=url,
                       ACL_HERMES_WEB_CONFIG=str(private),JINA_API_KEY='fixture',NODE_OPTIONS='',
                       NO_PROXY='127.0.0.1,localhost,::1',no_proxy='127.0.0.1,localhost,::1')
            cmd=[sys.executable,str(ROOT/'scripts/run_dsh_eval_v3_capacity1.py'),'--dataset','bc100','--strategies','visual_native',
                 '--question-id',q,'--limit','1','--timeout','120','--config',str(config),'--output-root',str(output),
                 '--cohort-file',str(cohort),'--cohort-sha256',hashlib.sha256(cohort.read_bytes()).hexdigest(),
                 '--web-prevalidated','--offline-fixture','--live']
            with (folder/'stdout.log').open('w') as stdout,(folder/'stderr.log').open('w') as stderr:
                process=subprocess.Popen(cmd,env=env,cwd=ROOT,stdout=stdout,stderr=stderr,start_new_session=True)
                try: process.wait(timeout=150)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid,signal.SIGTERM);process.wait(timeout=15)
            native=output/'visual_native'/q
            result=json.loads((native/'result.json').read_text()) if (native/'result.json').exists() else {}
            calls=rows(work/'metrics/calls.jsonl'); wire=rows(work/'metrics/wire/requests.jsonl')
            patches=json.loads((native/'evaluation.patch.json').read_text())
            assert {'id':'image-offload','disabled':True} in patches
            provider=next(p for p in patches if p.get('id')=='llm-pi-ai')['config']['providers']['tokenhub']
            assert provider['maxRequestImageBytes']==64*1024*1024
            events=[]
            import zstandard
            for path in (native/'dsh-home/sessions').rglob('session.v4.jsonl.zstd'):
                with path.open('rb') as stream:
                    for line in zstandard.ZstdDecompressor().stream_reader(stream).read().splitlines():
                        item=json.loads(line)
                        if item.get('type')=='image/offload':events.append(item)
            item={'case':case,'exit_code':process.returncode,'status':result.get('status'),'actual_http':observed,
                  'calls':[{'finish':r.get('finish'),'usage':r.get('usage')} for r in calls],
                  'wire_guard_errors':[r.get('guard_error') for r in wire if r.get('guard_error')],
                  'image_offload_events':events,'effective_patch_verified':True,'errors':errors}
            report['cases'].append(item);(root/'result.json').write_text(json.dumps(report,indent=2))
            assert not errors and not events
            if multiplier==1:
                assert process.returncode==0 and result.get('status')=='completed'
                assert len(observed)==1 and observed[0]['all_source_bytes_match'] and observed[0]['base64_bytes']>20*1024*1024
                assert not item['wire_guard_errors']
            else:
                assert not observed and not wire, 'Oversized payload reached HTTP or wire guard'
                assert len(calls)==1 and calls[0]['finish']['failure']['code']=='IMAGE_OFFLOAD_REQUIRED'
                assert result.get('status')!='completed'
            print(json.dumps({'case':case,'passed':True,'output':str(root)}),flush=True)
        finally: server.shutdown();server.server_close()
    report['passed']=True;(root/'result.json').write_text(json.dumps(report,indent=2))


if __name__=='__main__':main()
