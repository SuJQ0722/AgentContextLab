#!/usr/bin/env python3
"""Bounded native Hermes prefix capture. Default dry run; --fixture is localhost only."""
import argparse
import base64
import fcntl
import hashlib
import importlib
import io
import json
import mimetypes
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from urllib.parse import urlsplit
from urllib.request import urlopen

from lab import ROOT, environment, python_for

class PrefixCaptured(BaseException): pass
class AuxiliaryBlocked(BaseException): pass

def write(path,data):
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2));tmp.replace(path)

def image_ledger(messages):
    from PIL import Image
    result=[]
    for mi,m in enumerate(messages):
        for pi,p in enumerate(m.get('content',[]) if isinstance(m.get('content'),list) else []):
            if p.get('type')!='image_url': continue
            obj=p['image_url'];url=obj.get('url','') if isinstance(obj,dict) else obj
            item={'message_index':mi,'part_index':pi,'detail':obj.get('detail') if isinstance(obj,dict) else None,
                  'inline':url.startswith('data:')}
            if item['inline']:
                raw=base64.b64decode(url.split(',',1)[1],validate=True)
                with Image.open(io.BytesIO(raw)) as im: item['dimensions']=list(im.size)
                item.update(sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw))
            else:item['url']=url
            result.append(item)
    return result

def previous_prompt(metrics):
    path=metrics/'calls.jsonl'
    if not path.exists():return None
    for line in reversed(path.read_text().splitlines()):
        row=json.loads(line)
        if row.get('purpose')=='agent':
            return (row.get('raw_provider_usage') or {}).get('prompt_tokens')
    return None

def install_capture(recorder,out,model,threshold):
    from openai.resources.chat.completions import Completions, AsyncCompletions
    async def forbid_async(*a,**kw): raise AuxiliaryBlocked('Async auxiliary completion forbidden')
    AsyncCompletions.create=forbid_async
    measured=Completions.create
    allowed={'model','messages','tools','tool_choice','stream','stream_options','max_tokens','max_completion_tokens',
             'temperature','top_p','parallel_tool_calls','response_format','stop','seed','reasoning_effort'}
    def create(client,*args,**kwargs):
        if kwargs.get('model')!=model:raise AuxiliaryBlocked('Different model forbidden')
        prompt=previous_prompt(recorder.out)
        # Outside Recorder: intercepted call does not create a paid call-start/error.
        if prompt is not None and prompt>=threshold:
            request={k:v for k,v in kwargs.items() if k in allowed}
            raw=json.dumps(request,ensure_ascii=False,sort_keys=True).encode()
            (out/'prefix.json').write_bytes(raw)
            ledger=image_ledger(request['messages'])
            write(out/'prefix-manifest.json',{'status':'captured','previous_measured_prompt_tokens':prompt,
                'trigger_tokens':threshold,'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),
                'native_image_parts':len(ledger),'images':ledger,'next_api_call_sent':False,
                'captured_request_fields':list(request),'excluded_fields':[k for k in kwargs if k not in allowed],
                'token_definition':'Previous actual provider usage; captured request not measured by provider.'})
            os.kill(os.getpid(),signal.SIGUSR1)
            raise PrefixCaptured()
        recorder.archive({'type':'full_request','request':{k:v for k,v in kwargs.items() if k in allowed}})
        return measured(client,*args,**kwargs)
    Completions.create=create

def load_images(row,out):
    from PIL import Image
    images=[];ledger=[];directory=out/'input-images';directory.mkdir(exist_ok=True)
    for index,ref in enumerate(row.get('image') or []):
        if ref.startswith(('https://','http://')):
            with urlopen(ref,timeout=60) as r:raw=r.read(30*1024*1024+1)
        else:
            path=Path(ref)
            if not path.exists() and '/hermes-agent/' in ref:
                path=ROOT/'hermes-agent'/ref.split('/hermes-agent/',1)[1]
            raw=path.read_bytes()
        if len(raw)>30*1024*1024:raise ValueError('Image too large')
        with Image.open(io.BytesIO(raw)) as im:
            mime=Image.MIME[im.format];size=list(im.size)
        local=directory/f'{index:02d}{mimetypes.guess_extension(mime) or ".bin"}';local.write_bytes(raw)
        images.append({'type':'image_url','image_url':{'url':f'data:{mime};base64,'+base64.b64encode(raw).decode()}})
        ledger.append({'source':ref,'path':str(local),'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'dimensions':size})
    write(out/'input-images.json',ledger)
    return images,ledger

def worker(spec,out):
    import yaml
    from hermes_bc_worker import Recorder
    from local_web import configure_web
    started=time.monotonic();env,cfg=environment(ROOT,'hermes',spec['config_path'])
    for key in list(env):
        if key.startswith(('HERMES_VISUAL_','AUXILIARY_')) or key in ('CM','COMPRESS_STRATEGY','HERMES_DISCARD_KEEP_ROUNDS'):env.pop(key)
    home=out/'hermes-home';workspace=out/'workspace';home.mkdir(mode=0o700,exist_ok=True);workspace.mkdir(exist_ok=True)
    env.update(HERMES_HOME=str(home),HERMES_SESSION_STORAGE_ROOT=str(out/'sessions'),
               HERMES_IMAGE_ROOT=os.pathsep.join([str(out/'input-images'),str(workspace)]))
    configure_web(ROOT,env,Path(spec['config_path']));web=json.loads(env['ACL_WEB_SECRETS'])
    bypass=[env.get('NO_PROXY',''),'localhost','127.0.0.1','::1',urlsplit(env['TOKENHUB_BASE_URL']).hostname or '',
            str(web['search']['url']),urlsplit(web['fetch']['base_url']).hostname or '']
    env['NO_PROXY']=env['no_proxy']=','.join(x for x in bypass if x)
    model=spec['model']
    hcfg={'model':{'default':model,'provider':'custom','base_url':env['TOKENHUB_BASE_URL'],
         'context_length':cfg['context_window'],'max_tokens':cfg['max_output_tokens'],'api_mode':'chat_completions','supports_vision':True},
         'agent':{'coding_context':'off','api_max_retries':3,'image_input_mode':'native'},'compression':{'enabled':False},'context':{'engine':'compressor'},
         'memory':{'memory_enabled':False,'user_profile_enabled':False},'curator':{'enabled':False},
         'sessions':{'write_json_snapshots':True},'plugins':{'enabled':['local-web']},
         'auxiliary':{'vision':{'provider':'custom','model':model,'base_url':env['TOKENHUB_BASE_URL']}},
         'tool_output':{'max_bytes':cfg['bc100']['fetch_max_output_chars']},
         'web':{'local_web':{'search':web['search'],'fetch':{'fetch_server':web['fetch']}}}}
    private=home/'config.yaml';private.write_text(yaml.safe_dump(hcfg));private.chmod(0o600)
    os.environ.clear();os.environ.update(env);os.chdir(workspace);sys.path.insert(0,str(ROOT/'hermes-agent'))
    from hermes_logging import setup_logging
    setup_logging()
    from run_agent import AIAgent
    from hermes_state import SessionDB
    from tools.vision_tools import _should_use_native_vision_fast_path
    if not _should_use_native_vision_fast_path():raise RuntimeError('Native vision fast path not active')
    import agent.auxiliary_client as auxiliary
    async def blocked(*a,**kw):raise AuxiliaryBlocked('Auxiliary inference forbidden in native-prefix capture')
    auxiliary.async_call_llm=blocked
    import tools.vision_tools as vision
    vision.async_call_llm=blocked
    recorder=Recorder(out/'metrics');recorder.install();install_capture(recorder,out,model,spec['threshold'])
    agent=AIAgent(model=model,provider='custom',base_url=env['TOKENHUB_BASE_URL'],api_key=env['TOKENHUB_API_KEY'],
        api_mode='chat_completions',max_iterations=spec['max_rounds'],max_tokens=cfg['max_output_tokens'],
        enabled_toolsets=['web','vision'],quiet_mode=True,save_trajectories=True,skip_context_files=True,skip_memory=True,
        session_db=SessionDB(home/'state.db'),session_id='capture-'+uuid.uuid4().hex)
    allowed={'web_search','web_extract','vision_analyze','image_search','image_crop','image_zoom_in'}
    agent.tools=[t for t in agent.tools if t.get('function',{}).get('name') in allowed]
    names=[t['function']['name'] for t in agent.tools]
    if agent.compression_enabled or not {'vision_analyze','image_crop','image_zoom_in','web_search','web_extract'}<=set(names):
        raise RuntimeError('Capture policy verification failed')
    recorder.write('policy.jsonl',{'compression_enabled':False,'native_vision':True,'tools':names,'model':model})
    images,ledger=load_images(spec,out)
    content=[{'type':'text','text':spec['question']+'\n\nImage files available for crop/zoom:\n'+'\n'.join(r['path'] for r in ledger)}]+images
    status='not_reached';reason='normal_completion_or_iteration_limit'
    def captured_signal(signum,frame):raise PrefixCaptured()
    signal.signal(signal.SIGUSR1,captured_signal)
    try:
        result=agent.run_conversation(user_message=content,task_id='prefix/'+spec['dataset'])
        write(out/'conversation.json',result)
    except PrefixCaptured:status='captured';reason='measured_previous_prompt_threshold'
    except AuxiliaryBlocked:status='blocked';reason='auxiliary_inference_forbidden'
    write(out/'result.json',{'status':status,'reason':reason,'elapsed_seconds':time.monotonic()-started,
        'model':model,'native_image_inputs':len(images),'threshold':spec['threshold'],'session_id':agent.session_id})

def run(args):
    if args.worker:
        worker(json.loads(args.spec.read_text()),args.out.resolve());return
    cfg=json.loads((ROOT/'configs/experiment.json').read_text())
    cohort=ROOT/'outputs/cohorts'/f'{args.dataset}.jsonl';row=json.loads(cohort.read_text().splitlines()[0])
    out=(args.out or ROOT/'outputs/experiment3/prefix-capture'/args.dataset).resolve()
    if not args.live:
        print(json.dumps({'live':False,'dataset':args.dataset,'question_id':row['id'],'images':len(row.get('image') or []),
            'model':cfg['model'],'trigger':32768,'timeout_seconds':1800,'max_rounds':cfg['bc100_campaign']['max_rounds'],
            'out':str(out),'answer_or_metadata_in_prompt':False}));return
    out.mkdir(parents=True,exist_ok=True)
    lock=(out/'lease.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    if (out/'result.json').exists():print('Terminal capture retained; no repeated calls.');return
    if (out/'started.json').exists():raise SystemExit('Prior incomplete attempt retained; automatic retry forbidden. Choose a new explicit output directory.')
    frozen=out/'experiment.json';frozen.write_text(json.dumps(cfg,indent=2))
    # Deliberate allowlist: do not copy answer, source, metadata, checklist, sub_goals.
    spec={'question':row['question'],'question_id':row['id'],'image':row.get('image') or [],'dataset':args.dataset,
          'model':cfg['model'],'config_path':str(frozen),'threshold':32768,'max_rounds':cfg['bc100_campaign']['max_rounds']}
    write(out/'spec.json',spec);write(out/'started.json',{'pid':os.getpid(),'time':time.time(),'cohort_sha256':hashlib.sha256(cohort.read_bytes()).hexdigest(),'capture_code_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
    with (out/'process.log').open('w') as log:
        proc=subprocess.Popen([python_for(ROOT),str(Path(__file__).resolve()),'--worker','--spec',str(out/'spec.json'),'--out',str(out)],
            stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        def stop(signum,frame):
            os.killpg(proc.pid,signal.SIGTERM)
            try:proc.wait(timeout=10)
            except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);proc.wait()
            write(out/'result.json',{'status':'interrupted','reason':'supervisor_signal','partial_usage_retained':True})
            raise SystemExit(128+signum)
        signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
        try:code=proc.wait(timeout=1800)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid,signal.SIGTERM)
            try:proc.wait(timeout=10)
            except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);proc.wait()
            write(out/'result.json',{'status':'not_reached','reason':'1800s_wall_timeout','partial_usage_retained':True});return
    if not (out/'result.json').exists():write(out/'result.json',{'status':'failed','exit_code':code,'partial_usage_retained':True})
    print((out/'result.json').read_text())

def fixture():
    from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
    import threading
    from PIL import Image
    class Handler(BaseHTTPRequestHandler):
        calls=0
        def log_message(self,*a):pass
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            if self.path=='/search':
                data={'organic':[{'title':'fixture','link':'https://example.com','snippet':'native evidence'}]}
            else:
                Handler.calls+=1
                assert image_ledger(body['messages']), 'Initial native image absent'
                message={'role':'assistant','content':None,'tool_calls':[{'index':0,'id':'search1','type':'function',
                    'function':{'name':'web_search','arguments':'{"query":"fixture","limit":1}'}}]}
                data={'id':'fixture','object':'chat.completion','created':1,'model':body['model'],
                    'choices':[{'index':0,'finish_reason':'tool_calls','message':message}],
                    'usage':{'prompt_tokens':32768,'completion_tokens':10,'total_tokens':32778,'prompt_tokens_details':{'cached_tokens':1024}}}
            if body.get('stream'):
                data['object']='chat.completion.chunk';data['choices'][0]['delta']=data['choices'][0].pop('message')
                raw=('data: '+json.dumps(data)+'\n\ndata: [DONE]\n\n').encode();mime='text/event-stream'
            else:raw=json.dumps(data).encode();mime='application/json'
            self.send_response(200);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(raw)))
            self.end_headers();self.wfile.write(raw)
    out=ROOT/'outputs/preflight'/f'prefix-capture-{time.time_ns()}';out.mkdir(parents=True)
    srv=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=srv.serve_forever,daemon=True).start()
    try:
        import yaml
        url=f'http://127.0.0.1:{srv.server_port}'
        cfg=json.loads((ROOT/'configs/experiment.json').read_text());cfg['web'].update(search_host='127.0.0.1',search_port=srv.server_port,fetch_base_url=url)
        write(out/'experiment.json',cfg);im=out/'input.png';Image.new('RGB',(64,64),'blue').save(im)
        write(out/'spec.json',{'dataset':'fixture','question':'Use web search to check the image.','image':[str(im)],
              'model':cfg['model'],'config_path':str(out/'experiment.json'),'threshold':32768,'max_rounds':3})
        webconfig=out/'web.yaml';webconfig.write_text(yaml.safe_dump({'web':{'local_web':{'search':{'url':'127.0.0.1','port':srv.server_port,'api_key':'fixture-only'},'fetch':{'fetch_server':{'base_url':url}}}}}))
        env=dict(os.environ,TOKENHUB_BASE_URL=url+'/v1',TOKENHUB_API_KEY='fixture-only',ACL_HERMES_WEB_CONFIG=str(webconfig),SERPER_API_KEY='fixture-only')
        with (out/'process.log').open('w') as log:
            p=subprocess.run([python_for(ROOT),str(Path(__file__).resolve()),'--worker','--spec',str(out/'spec.json'),'--out',str(out)],env=env,stdout=log,stderr=subprocess.STDOUT,timeout=120)
        if p.returncode:raise RuntimeError(f'Fixture worker failed; inspect {out}/process.log')
        result=json.loads((out/'result.json').read_text());manifest=json.loads((out/'prefix-manifest.json').read_text())
        calls=[json.loads(s) for s in (out/'metrics/calls.jsonl').read_text().splitlines()]
        assert result['status']=='captured' and Handler.calls==1 and len(calls)==1
        assert manifest['native_image_parts']==1 and calls[0]['usage']['cacheReadTokens']==1024
        assert 'tools' in json.loads((out/'prefix.json').read_text())
        write(out/'fixture-result.json',{'passed':True,'paid_requests':0,'fixture_model_calls':Handler.calls,'captured_images':1})
        print(json.dumps({'passed':True,'paid_requests':0,'out':str(out)}))
    finally:srv.shutdown()

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--dataset',choices=['browsecomp_v3','mmbrowsecomp'],default='browsecomp_v3')
    ap.add_argument('--out',type=Path);ap.add_argument('--spec',type=Path);ap.add_argument('--worker',action='store_true')
    ap.add_argument('--live',action='store_true');ap.add_argument('--fixture',action='store_true');ap.add_argument('--resume',action='store_true',help='Terminal output is skipped; incomplete output never automatically retried')
    a=ap.parse_args()
    if a.fixture:fixture()
    else:run(a)
if __name__=='__main__':main()
