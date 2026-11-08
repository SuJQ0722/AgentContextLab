#!/usr/bin/env python3
"""Repaired Hermes entrypoint; separate version, explicit review gate, native images."""
import argparse
import base64
import json
import os
from pathlib import Path
import sys
import time
import uuid
from urllib.parse import urlsplit
import yaml
from lab import ROOT, environment
from local_web import configure_web
from hermes_bc_worker import Recorder, now
from hermes_native_vision_worker_v2 import VisionRecorder
from review_execution import enforce, enforce_resolved_web
from shared_context_policy import context_config, policy_config, configure_engine
from run_dsh_eval import stage_images
from native_image_origins import write_origin_map, install_hermes_origin_resolver

TOOLS = ['web_search', 'web_extract', 'image_search', 'image_crop', 'image_zoom_in']


class ReviewedTextRecorder(Recorder):
    """Account native summaries and reject route changes at the HTTP boundary."""
    def install(self):
        super().install()
        import contextvars
        import httpx
        import requests
        from openai import OpenAI
        from openai.resources.chat.completions import Completions, AsyncCompletions
        from agent import auxiliary_client
        spec=json.loads(Path(sys.argv[sys.argv.index('--spec')+1]).read_text())
        model=spec['model'];base_url=os.environ['TOKENHUB_BASE_URL'].rstrip('/')
        approved_key=os.environ['TOKENHUB_API_KEY']
        endpoint=base_url+'/chat/completions'
        in_inference=contextvars.ContextVar('reviewed_inference',default=False)
        original=Completions.create;aux=auxiliary_client.call_llm
        cached_client=auxiliary_client._get_cached_client
        sync_send=httpx.Client.send;async_send=httpx.AsyncClient.send
        final_send=httpx.Client._send_single_request;final_async_send=httpx.AsyncClient._send_single_request
        requests_send=requests.Session.send
        recorder=self

        def denied(reason):
            recorder.write('route-guard.jsonl',{'timestamp':now(),'action':'blocked','reason':reason})
            raise RuntimeError(reason)

        def is_model_path(url):
            path=urlsplit(str(url)).path.rstrip('/')
            return (path.endswith(('/chat/completions','/responses','/messages','/completions','/generate','/chat'))
                    or ':generateContent' in path or ':streamGenerateContent' in path)

        def check_wire(url, method, body):
            if not (in_inference.get() or is_model_path(url)):
                return
            if not in_inference.get():
                denied('Uninstrumented direct model HTTP request is forbidden')
            # Compare the full endpoint, including path, port and query. A
            # same-model request to another host is still a route violation.
            if str(url).rstrip('/')!=endpoint or method.upper()!='POST':
                denied('Inference endpoint differs from the approved chat-completions route')
            try:payload=json.loads(body)
            except (TypeError,ValueError,UnicodeDecodeError):
                denied('Inference HTTP body is not valid inspectable JSON')
            if payload.get('model')!=model:
                denied('Inference HTTP body selects an unapproved model')

        def guarded(client,*args,**kwargs):
            if kwargs.get('model')!=model:
                denied('Reviewed SDK request selects an unapproved model')
            if str(getattr(client._client,'base_url','')).rstrip('/')!=base_url:
                denied('Reviewed SDK client selects an unapproved endpoint')
            token=in_inference.set(True)
            try:return original(client,*args,**kwargs)
            finally:in_inference.reset(token)

        def same_client(provider,*args,**kwargs):
            if not in_inference.get():
                return cached_client(provider,*args,**kwargs)
            chosen_model=args[0] if args else kwargs.get('model')
            if provider!='custom' or chosen_model!=model or str(kwargs.get('base_url','')).rstrip('/')!=base_url:
                denied('Auxiliary fallback attempted a different provider/model/endpoint')
            client,final_model=cached_client(provider,*args,**kwargs)
            if (client is not None and (not isinstance(client,OpenAI) or final_model!=model
                    or str(client.base_url).rstrip('/')!=base_url)):
                denied('Auxiliary resolved client is outside the approved route')
            return client,final_model

        def summary_only(*args,**kwargs):
            task=kwargs.get('task',args[0] if args else None)
            if task!='compression' or (kwargs.get('main_runtime') or {}).get('model')!=model:
                denied('Only same-model native compression auxiliary calls are allowed')
            # These are explicit call_llm parameters, not forwarded API-body
            # kwargs. Override task/environment routing and disallow fallback.
            kwargs.update(provider='custom',model=model,base_url=base_url,api_key=approved_key,api_mode='chat_completions')
            token=in_inference.set(True)
            try:return aux(*args,**kwargs)
            finally:in_inference.reset(token)

        def send(client,request,*args,**kwargs):
            check_wire(request.url,request.method,request.content)
            return sync_send(client,request,*args,**kwargs)

        async def asend(client,request,*args,**kwargs):
            if in_inference.get() or is_model_path(request.url):
                denied('Uninstrumented asynchronous inference is forbidden')
            return await async_send(client,request,*args,**kwargs)

        def request_send(client,request,*args,**kwargs):
            check_wire(request.url,request.method,request.body)
            return requests_send(client,request,*args,**kwargs)

        def final_wire_send(client,request):
            # Runs after HTTPX request hooks and once per redirect/retry.
            check_wire(request.url,request.method,request.content)
            return final_send(client,request)

        async def final_wire_async_send(client,request):
            if in_inference.get() or is_model_path(request.url):
                denied('Uninstrumented asynchronous inference is forbidden')
            return await final_async_send(client,request)

        async def no_async(*args,**kwargs):
            denied('Uninstrumented asynchronous inference is forbidden')

        Completions.create=guarded;AsyncCompletions.create=no_async
        auxiliary_client.call_llm=summary_only;auxiliary_client.async_call_llm=no_async
        auxiliary_client._get_cached_client=same_client
        httpx.Client.send=send;httpx.AsyncClient.send=asend;requests.Session.send=request_send
        httpx.Client._send_single_request=final_wire_send;httpx.AsyncClient._send_single_request=final_wire_async_send

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--spec',type=Path,required=True);ap.add_argument('--out',type=Path,required=True)
    ap.add_argument('--live',action='store_true');ap.add_argument('--offline-fixture',action='store_true');args=ap.parse_args()
    spec=json.loads(args.spec.read_text());out=args.out.resolve()
    cfg_path=Path(spec['config_path']);env,cfg=environment(ROOT,'hermes',cfg_path)
    if cfg.get('execution_version')!='hermes-parity-v3':
        raise ValueError('Use the new separately versioned configuration, even for dry-run')
    if spec.get('model')!=cfg.get('model'):
        raise ValueError('Job model differs from the reviewed experiment route')
    if not args.live:print(json.dumps({'live':False,'job_id':spec['job_id'],'execution_version':'hermes-parity-v3','tools':TOOLS,'native_images':True}));return
    enforce(cfg,env,out,offline_fixture=args.offline_fixture)
    out.mkdir(parents=True,exist_ok=True)
    if any((out/name).exists() for name in ('native-result.json','conversation.json','metrics/call-starts.jsonl')):
        raise ValueError('Existing repaired attempt must not be overwritten or silently retried')
    with (out/'attempt-started.json').open('x') as claim:
        json.dump({'pid':os.getpid(),'job_id':spec['job_id'],'started_at':now()},claim)
    env.pop('CM',None);env.pop('COMPRESS_STRATEGY',None)
    for key in list(env):
        if key.startswith('HERMES_VISUAL_') or key=='HERMES_DISCARD_KEEP_ROUNDS':env.pop(key)
    home=out/'hermes-home';workspace=out/'workspace';home.mkdir(parents=True,exist_ok=True);workspace.mkdir(exist_ok=True)
    home.chmod(0o700)
    env.update(HERMES_HOME=str(home),HERMES_SESSION_STORAGE_ROOT=str(out/'sessions'),HERMES_IMAGE_ROOT=str(workspace),HERMES_IMAGE_CACHE=str(workspace/'image-cache'))
    configure_web(ROOT,env,cfg_path);web=json.loads(env['ACL_WEB_SECRETS'])
    enforce_resolved_web(env,offline_fixture=args.offline_fixture)
    env['SERPER_API_KEY']=web['search']['api_key']
    bypass=[env.get('NO_PROXY',''),'localhost','127.0.0.1','::1',
            urlsplit(env['TOKENHUB_BASE_URL']).hostname or '',str(web['search']['url']),
            urlsplit(web['fetch']['base_url']).hostname or '']
    env['NO_PROXY']=env['no_proxy']=','.join(x for x in bypass if x)
    model=spec['model'];strategy=spec['strategy'];engine='compressor' if strategy=='none' else strategy
    hcfg={'model':{'default':model,'provider':'custom','base_url':env['TOKENHUB_BASE_URL'],
          'context_length':cfg['context_window'],'max_tokens':cfg['max_output_tokens'],'api_mode':'chat_completions','supports_vision':True},
        'agent':{'coding_context':'off','api_max_retries':3,'image_input_mode':'native'},
        'auxiliary':{'compression':{'provider':'custom','model':model,'base_url':env['TOKENHUB_BASE_URL']}},
        'compression':{'enabled':strategy!='none','threshold':cfg['pilot']['compression_trigger_tokens']/cfg['context_window']},
        'context':context_config(strategy,cfg,out/'context_images'),
        'memory':{'memory_enabled':False,'user_profile_enabled':False},'curator':{'enabled':False},
        'sessions':{'write_json_snapshots':True},'plugins':{'enabled':['local-web']},
        'tool_output':{'max_bytes':cfg['bc100']['fetch_max_output_chars']},
        'web':{'local_web':{'search':web['search'],'fetch':{'fetch_server':web['fetch']}}}}
    private=home/'config.yaml';private.write_text(yaml.safe_dump(hcfg));private.chmod(0o600)
    os.environ.clear();os.environ.update(env);os.chdir(workspace)
    sys.path.insert(0,str(ROOT/'hermes-agent'))
    from hermes_logging import setup_logging
    setup_logging()
    recorder=(VisionRecorder if strategy=='visual' else ReviewedTextRecorder)(out/'metrics');recorder.install()
    from run_agent import AIAgent
    from hermes_state import SessionDB
    agent=AIAgent(model=model,provider='custom',base_url=env['TOKENHUB_BASE_URL'],api_key=env['TOKENHUB_API_KEY'],
        api_mode='chat_completions',max_iterations=cfg['bc100_campaign']['max_rounds'],max_tokens=cfg['max_output_tokens'],
        enabled_toolsets=['web','vision'],quiet_mode=True,save_trajectories=True,skip_context_files=True,skip_memory=True,
        session_db=SessionDB(home/'state.db'),session_id='acl-'+uuid.uuid4().hex)
    actual=agent.context_compressor.name
    configure_engine(agent.context_compressor,strategy,policy_config(strategy,cfg,out/'context_images'))
    if strategy!='none' and actual!=engine:raise RuntimeError('Hermes policy mismatch; no inference allowed')
    if strategy=='none' and agent.compression_enabled:raise RuntimeError('No-compression policy not applied')
    agent.tools=[t for t in agent.tools if t.get('function',{}).get('name') in TOOLS]
    tool_names=[t.get('function',{}).get('name') for t in agent.tools]
    agent.valid_tool_names=set(tool_names)
    if set(tool_names)!=set(TOOLS):raise RuntimeError('Missing required Hermes image/web tool; refusing inference')
    recorder.write('policy.jsonl',{'timestamp':now(),'verified':True,'strategy':strategy,'engine':actual,'tools':tool_names})
    recorder.instrument_engine(agent.context_compressor)
    images=stage_images(spec,workspace)
    os.environ['ACL_IMAGE_ORIGIN_MAP']=write_origin_map(spec,images,out/'input-origins.json')
    install_hermes_origin_resolver()
    recorder.write('input.jsonl',{'question_id':spec.get('question_id'),'images':images})
    user_message=spec['question']
    if images:
        user_message=[{'type':'text','text':spec['question']+'\n\nImage files available for crop/zoom:\n'+'\n'.join(r['path'] for r in images)}]
        user_message += [{'type':'image_url','image_url':{'url':f"data:{r['media_type']};base64,"+base64.b64encode(Path(r['path']).read_bytes()).decode()}} for r in images]
    start=time.monotonic()
    result=agent.run_conversation(user_message=user_message,task_id=spec['job_id'])
    (out/'conversation.json').write_text(json.dumps(result,ensure_ascii=False,default=str))
    text=(result.get('final_response') or '') if not result.get('error') else ''
    (out/'native-result.json').write_text(json.dumps({'status':'completed' if text and not result.get('error') else 'failed',
        'final':{'text':text},'native_error':bool(result.get('error')),'session_id':agent.session_id,
        'agent_loop_seconds':time.monotonic()-start},indent=2))


if __name__=='__main__':main()
