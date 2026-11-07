#!/usr/bin/env python3
"""Real native DSH adapter wire audit with complete rendered history canvases."""
import argparse,base64,hashlib,json,os,signal,subprocess,threading,time
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from lab import ROOT,environment,command

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--live',action='store_true');p.add_argument('--source',type=Path,default=ROOT/'outputs/preflight/visual-history-pdf-8192-font16-scale1.0');p.add_argument('--max-output-tokens',type=int,default=2048);p.add_argument('--timeout',type=int,default=240);p.add_argument('--preserve-native-bytes',action='store_true');a=p.parse_args()
 source=a.source.resolve();inputs=json.loads((source/'native-input.json').read_text());expected_pages=len(inputs['images']);root=ROOT/'outputs/preflight'/f'dsh-wire-images-{time.time_ns()}';root.mkdir(parents=True)
 server_records=[]
 class Fixture(BaseHTTPRequestHandler):
  def log_message(self,*args):pass
  def do_POST(self):
   data=json.loads(self.rfile.read(int(self.headers['Content-Length'])));hashes=[]
   for m in data['messages']:
    for block in m.get('content',[]) if isinstance(m.get('content'),list) else []:
     if block.get('type')=='image_url':hashes.append(hashlib.sha256(base64.b64decode(block['image_url']['url'].split(',',1)[1])).hexdigest())
   server_records.append({'model':data['model'],'image_sha256':hashes})
   self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
   b={'id':'wire-fixture','object':'chat.completion.chunk','created':1,'model':data['model']}
   for c in [dict(b,choices=[{'index':0,'delta':{'role':'assistant','content':'WIRE-OK'},'finish_reason':None}]),dict(b,choices=[{'index':0,'delta':{},'finish_reason':'stop'}],usage={'prompt_tokens':100,'completion_tokens':4,'total_tokens':104,'prompt_tokens_details':{'cached_tokens':0}})]:self.wfile.write(('data: '+json.dumps(c)+'\n\n').encode())
   self.wfile.write(b'data: [DONE]\n\n')
 server=ThreadingHTTPServer(('127.0.0.1',0),Fixture);threading.Thread(target=server.serve_forever,daemon=True).start()
 try:
  expected=None;results=[]
  for mode in ['fixture-observe','fixture-strict']+(['live-strict'] if a.live else []):
   out=root/mode;workspace=out/'workspace';workspace.mkdir(parents=True)
   env,cfg=environment(ROOT,'dsh');env.pop('ACL_STRATEGY',None)
   env.update(DSH_HOME=str(out/'dsh-home'),ACL_WORKSPACE=str(workspace),ACL_MAX_OUTPUT_TOKENS=str(a.max_output_tokens),
      ACL_IMAGE_WIRE_AUDIT_DIR=str(out/'wire'),NODE_OPTIONS=(env.get('NODE_OPTIONS','')+' --import='+str(ROOT/'scripts/dsh_wire_image_guard.mjs')).strip())
   if mode.startswith('fixture'):env.update(TOKENHUB_BASE_URL=f'http://127.0.0.1:{server.server_port}/v1',TOKENHUB_API_KEY='fixture-only')
   if expected:env['ACL_IMAGE_WIRE_EXPECTED']=str(root/'expected-wire.json')
   patches=[{'id':'session-title-llm','disabled':True},{'insert':[{'id':'wire-evaluation','name':str(ROOT/'plugins/dsh-evaluation/index.mjs'),'config':{'inputFile':str(source/'native-input.json'),'metricsDir':str(out/'metrics'),'maxSteps':1,'allowedTools':[]}}]}]
   if a.preserve_native_bytes:
    provider={'apiKeyEnv':'TOKENHUB_API_KEY','api':'openai-completions','baseURL':env['TOKENHUB_BASE_URL'],'requestImageMaxBytes':20*1024*1024,'models':[{'id':env['ACL_MODEL'],'input':json.loads(env['ACL_INPUT_MODALITIES']),'contextWindow':int(env['ACL_CONTEXT_WINDOW']),'maxTokens':a.max_output_tokens}]}
    env['ACL_IMAGE_WIRE_EXPECTED']=str(out/'native-expected.json')
    patches.extend([{'id':'llm-pi-ai','config':{'providers':{'tokenhub':provider}}},{'insert':[{'id':'wire-expectations','name':str(ROOT/'scripts/dsh_wire_expectations.mjs'),'config':{'expectedFile':str(out/'native-expected.json')}}]}])
   patch=out/'observer.json';patch.write_text(json.dumps(patches))
   prompt='WIRE_CANVAS_AUDIT\n'+(source/'question.txt').read_text()+'\nUse the complete attached history canvases. Return only the requested JSON.'
   cmd=command(ROOT,'dsh',prompt,env);cmd[-1:]=['--patch',str(patch),'--json','--approval-policy','never',prompt]
   start=time.monotonic()
   with (out/'stdout.jsonl').open('w') as stdout,(out/'stderr.log').open('w') as stderr:
    proc=subprocess.Popen(cmd,cwd=workspace,env=env,stdout=stdout,stderr=stderr,start_new_session=True)
    try:code=proc.wait(timeout=a.timeout)
    except subprocess.TimeoutExpired:
     os.killpg(proc.pid,signal.SIGTERM)
     try:proc.wait(timeout=5)
     except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);proc.wait()
     code=124
   records=[json.loads(x) for x in (out/'wire/requests.jsonl').read_text().splitlines()]
   tasks=[r for r in records if r['task_marker_present']]
   assert tasks and not any(r['guard_error'] for r in tasks),f'Wire guard failed: {out}'
   assert all(r['image_count']==expected_pages for r in tasks), 'Complete canvas image set lost'
   if mode=='fixture-observe':
    if a.preserve_native_bytes:
     source_hashes=[hashlib.sha256(Path(im['path']).read_bytes()).hexdigest() for im in inputs['images']]
     assert [im['sha256'] for im in tasks[0]['images']]==source_hashes, 'Preserve mode changed original input image bytes; stop before paid request'
    expected={'wire_sha256':[im['sha256'] for im in tasks[0]['images']]};(root/'expected-wire.json').write_text(json.dumps(expected))
   if mode.startswith('fixture'):
    assert code==0 and server_records[-1]['image_sha256']==expected['wire_sha256'],'Final HTTP server bytes differ from fetch audit'
   events=[]
   for line in (out/'stdout.jsonl').read_text().splitlines():
    try:events.append(json.loads(line))
    except ValueError:pass
   final=next((x for x in reversed(events) if x.get('type')=='final'),{})
   calls_path=out/'metrics/calls.jsonl'
   usage=[json.loads(x) for x in calls_path.read_text().splitlines()] if calls_path.exists() else []
   results.append({'mode':mode,'exit_code':code,'wire_request_count':len(records),'canvas_requests':len(tasks),'images':tasks[0]['images'],
     'final':final,'calls':usage,'client_cli_seconds':time.monotonic()-start})
  from PIL import Image
  provenance=[]
  for src,wire in zip(inputs['images'],results[0]['images']):
   srcpath=Path(src['path']);wirepath=root/'fixture-observe/wire'/(wire['sha256']+'.'+wire['format'])
   with Image.open(srcpath) as im: source_size=list(im.size);source_pixel_sha=hashlib.sha256(im.convert('RGB').tobytes()).hexdigest()
   with Image.open(wirepath) as im: wire_size=list(im.size);wire_pixel_sha=hashlib.sha256(im.convert('RGB').tobytes()).hexdigest()
   sh=hashlib.sha256(srcpath.read_bytes()).hexdigest()
   provenance.append({'source_path':str(srcpath),'source_byte_sha256':sh,'source_dimensions':source_size,'wire_byte_sha256':wire['sha256'],'wire_dimensions':wire_size,'byte_identical':sh==wire['sha256'],'rgb_pixels_identical':source_size==wire_size and source_pixel_sha==wire_pixel_sha,'source_rgb_sha256':source_pixel_sha,'wire_rgb_sha256':wire_pixel_sha})
  report={'provenance':provenance,'source':str(source),'complete_canvas_pages':expected_pages,'paid_requested':a.live,'max_output_tokens':a.max_output_tokens,'timeout_seconds':a.timeout,'preserve_native_bytes':a.preserve_native_bytes,'results':results,'server_fixture_records':server_records}
  (root/'audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps({'out':str(root),'modes':[r['mode'] for r in results],'paid_requested':a.live}))
 finally:server.shutdown()

if __name__=='__main__':main()
