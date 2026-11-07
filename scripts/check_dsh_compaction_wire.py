#!/usr/bin/env python3
"""Local-only native compaction -> attachment -> actual HTTP image verification."""
import json,threading,time,subprocess
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from lab import ROOT,environment,command

def main():
 out=ROOT/'outputs/preflight'/f'dsh-compaction-wire-{time.time_ns()}';work=out/'workspace';work.mkdir(parents=True)
 observed=[]
 class Fixture(BaseHTTPRequestHandler):
  def log_message(self,*a):pass
  def do_POST(self):
   body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
   if self.path=='/search':
    content=' '.join(f'Record {i}: Warehouse cedar held {i+100} packages. Reference K-{i:04d}.' for i in range(80))
    raw=json.dumps({'organic':[{'title':'Fixture records','link':'https://example.com/fixture','snippet':content}]}).encode()
    self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(raw);return
   images=[p for m in body['messages'] for p in (m.get('content',[]) if isinstance(m.get('content'),list) else []) if p.get('type')=='image_url']
   title=any('Generate the session title from this JSON array of human messages:' in str(m.get('content')) for m in body['messages'])
   observed.append({'images':len(images),'title':title})
   final=bool(images) or title
   delta={'role':'assistant','content':'COMPACTION-WIRE-OK'} if final else {'role':'assistant','tool_calls':[{'index':0,'id':f'call{len(observed)}','type':'function','function':{'name':'web_search','arguments':json.dumps({'queries':[f'fixture records {len(observed)}']})}}]}
   self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
   base={'id':'fixture','object':'chat.completion.chunk','created':1,'model':body['model']}
   for c in [dict(base,choices=[{'index':0,'delta':delta,'finish_reason':None}]),dict(base,choices=[{'index':0,'delta':{},'finish_reason':'stop' if final else 'tool_calls'}],usage={'prompt_tokens':1000,'completion_tokens':10,'total_tokens':1010,'prompt_tokens_details':{'cached_tokens':0}})]:self.wfile.write(('data: '+json.dumps(c)+'\n\n').encode())
   self.wfile.write(b'data: [DONE]\n\n')
 server=ThreadingHTTPServer(('127.0.0.1',0),Fixture);threading.Thread(target=server.serve_forever,daemon=True).start()
 try:
  env,cfg=environment(ROOT,'dsh');url=f'http://127.0.0.1:{server.server_port}'
  env.update(TOKENHUB_BASE_URL=url+'/v1',TOKENHUB_API_KEY='fixture-only',DSH_HOME=str(out/'dsh-home'),ACL_WORKSPACE=str(work),
   ACL_STRATEGY='visual_native',ACL_COMPRESSION_TRIGGER='32768',ACL_POST_COMPRESSION_BUDGET='16384',
   ACL_RAW_CANVAS_AUDIT_DIR=str(out/'raw-canvas'),ACL_IMAGE_WIRE_AUDIT_DIR=str(out/'wire'),ACL_IMAGE_WIRE_EXPECTED=str(out/'expected.json'),
   NODE_OPTIONS=(env.get('NODE_OPTIONS','')+' --import='+str(ROOT/'scripts/dsh_wire_image_guard.mjs')).strip(),
   ACL_WEB_SECRETS=json.dumps({'search':{'url':'127.0.0.1','port':server.server_port,'api_key':'fixture-only'},'fetch':{'base_url':url}}))
  overlay=out/'research.patch.yml';overlay.write_text((ROOT/'configs/research.dsh.patch.yml').read_text().replace('"@ACL_DSH_CONTEXT_PLUGIN@"',json.dumps(str(ROOT/'plugins/dsh-context/index.mjs'))))
  inputs=out/'input.json';inputs.write_text(json.dumps({'question_id':'native-wire-fixture','images':[]}))
  plugins=[{'id':'evaluation','name':str(ROOT/'plugins/dsh-evaluation/index.mjs'),'config':{'inputFile':str(inputs),'metricsDir':str(work/'metrics'),'maxSteps':30,'allowedTools':['web_search'],'expectedStrategy':'visual_native'}},
    {'id':'local-web','name':str(ROOT/'plugins/dsh-local-web/index.mjs'),'config':{'metricsDir':str(work/'metrics')}},
    {'id':'wire-expectations','name':str(ROOT/'scripts/dsh_wire_expectations.mjs'),'config':{'expectedFile':str(out/'expected.json')}}]
  compaction={'strategy':'visual_native','python':env['ACL_PYTHON'],'renderer':str(ROOT/'scripts/render_dsh_history_audited.py'),'metricsDir':str(work/'metrics'),'historyScale':float(env['ACL_VISUAL_HISTORY_SCALE']),'fontSize':int(env['ACL_VISUAL_FONT_SIZE']),'postCompressionBudget':16384,'thresholdRatio':32768/int(env['ACL_CONTEXT_WINDOW']),'headroomTokens':8192,'retainTokens':4096,'maxTokens':4096,'compactionRetries':0,'maxOverflowRetries':0}
  provider={'apiKeyEnv':'TOKENHUB_API_KEY','api':'openai-completions','baseURL':url+'/v1','requestImageMaxBytes':20*1024*1024,'models':[{'id':env['ACL_MODEL'],'input':json.loads(env['ACL_INPUT_MODALITIES']),'contextWindow':int(env['ACL_CONTEXT_WINDOW']),'maxTokens':int(env['ACL_MAX_OUTPUT_TOKENS'])}]}
  patch=out/'observer.json';patch.write_text(json.dumps([{'id':'session-title-llm','disabled':True},{'insert':plugins},{'id':'acl-research-compaction','config':compaction},{'id':'llm-pi-ai','config':{'providers':{'tokenhub':provider}}},{'id':'web','config':{'searchProvider':'acl-serper-cache','fetchProvider':'acl-jina-reader'}}]))
  prompt='Search the fixture inventory repeatedly until you have sufficient historical records. Summarize the result.'
  cmd=command(ROOT,'dsh',prompt,env);cmd[cmd.index(str(ROOT/'.state/dsh-research.patch.yml'))]=str(overlay);cmd[-1:]=['--patch',str(patch),'--json','--approval-policy','never',prompt]
  with (out/'stdout.jsonl').open('w') as so,(out/'stderr.log').open('w') as se:r=subprocess.run(cmd,cwd=work,env=env,stdout=so,stderr=se,timeout=150)
  comps=[json.loads(x) for x in (work/'metrics/compression.jsonl').read_text().splitlines()] if (work/'metrics/compression.jsonl').exists() else []
  wire=[json.loads(x) for x in (out/'wire/requests.jsonl').read_text().splitlines()]
  expected=[json.loads(x) for x in (out/'expected.json.jsonl').read_text().splitlines()]
  report={'paid_requests':0,'exit_code':r.returncode,'fixture_settings':{'trigger':32768,'retainTokens':4096,'requestImageMaxBytes':20*1024*1024},'compression_records':comps,'server_requests':observed,
   'wire_images_after_native_compaction':sum(x['image_count'] for x in wire),'guard_errors':[x['guard_error'] for x in wire if x['guard_error']],
   'native_image_expectations':[x for x in expected if x['wire_sha256']],'scientific_scope':'Real compaction+renderer+adapter; synthetic localhost content and actual configured 32768-token trigger, not benchmark accuracy.'}
  (out/'result.json').write_text(json.dumps(report,indent=2));print(json.dumps({'out':str(out),**{k:report[k] for k in ['exit_code','wire_images_after_native_compaction','guard_errors']}}))
  assert r.returncode==0 and comps and all(x['valid'] for x in comps) and report['wire_images_after_native_compaction']>0 and not report['guard_errors']
 finally:server.shutdown()
if __name__=='__main__':main()
