#!/usr/bin/env python3
"""One isolated native Hermes turn with local measurement; no alternate agent loop."""
import argparse
import contextvars
import gzip
import json
import os
from pathlib import Path
import sys
import threading
import time
import uuid
from urllib.parse import urlsplit
from datetime import datetime, timezone
import yaml
from lab import ROOT, environment
from local_web import configure_web


def now():
    return datetime.now(timezone.utc).isoformat()


class Recorder:
    def __init__(self, out):
        self.out=out;out.mkdir(parents=True,exist_ok=True)
        self.lock=threading.Lock();self.invalid=False;self.compacting=False
        self.purpose=contextvars.ContextVar('measurement_purpose',default='agent')

    def write(self, name, record):
        with self.lock:
            with (self.out/name).open('a') as f:f.write(json.dumps(record,ensure_ascii=False,default=str)+'\n')

    def archive(self, record):
        with self.lock:
            with gzip.open(self.out/'requests-responses.jsonl.gz','at') as f:
                f.write(json.dumps(record,ensure_ascii=False,default=str)+'\n')

    def install(self):
        from openai.resources.chat.completions import Completions
        original=Completions.create; recorder=self
        def create(client,*args,**kwargs):
            if recorder.invalid:raise RuntimeError('Invalid visual rendering; refusing further inference')
            started=time.monotonic();cid=str(uuid.uuid4());at=now();purpose='compaction' if recorder.compacting else recorder.purpose.get()
            recorder.write('call-starts.jsonl',{'call_id':cid,'started_at':at,'purpose':purpose})
            recorder.archive({'call_id':cid,'type':'request','model':kwargs.get('model'),
                              'messages':kwargs.get('messages'),'max_tokens':kwargs.get('max_tokens')})
            def finish(response=None,error=None):
                usage=getattr(response,'usage',None)
                raw=usage.model_dump() if hasattr(usage,'model_dump') else usage
                normalized=None
                if raw and raw.get('prompt_tokens_details',{}):
                    cached=(raw.get('prompt_tokens_details') or {}).get('cached_tokens')
                    if cached is not None:
                        normalized={'inputTokens':raw['prompt_tokens']-cached,'cacheReadTokens':cached,
                            'outputTokens':raw['completion_tokens'],'totalTokens':raw['total_tokens']}
                choices=getattr(response,'choices',None) or []
                reason=getattr(choices[0],'finish_reason',None) if choices else None
                recorder.write('calls.jsonl',{'call_id':cid,'started_at':at,'ended_at':now(),
                    'purpose':purpose,'model':kwargs.get('model'),'usage':normalized,'raw_provider_usage':raw,
                    'finish':{'kind':'error' if error else reason or 'unknown'},
                    'error_type':type(error).__name__ if error else None,
                    'client_stream_seconds':time.monotonic()-started,
                    'provider_internal_latency_seconds':None,'timing_definition':'SDK call incl SDK retries; not provider internal'})
                if response is not None and hasattr(response,'model_dump'):
                    recorder.archive({'call_id':cid,'type':'response','response':response.model_dump()})
            try:response=original(client,*args,**kwargs)
            except BaseException as error:finish(error=error);raise
            if kwargs.get('stream'):
                class Stream:
                    def __getattr__(self,k):return getattr(response,k)
                    def __enter__(self):return self
                    def __exit__(self,*a):response.close()
                    def __iter__(self):
                        last=None
                        try:
                            for chunk in response:
                                if getattr(chunk,'usage',None):last=chunk
                                recorder.archive({'call_id':cid,'type':'stream_chunk','chunk':chunk.model_dump()})
                                yield chunk
                        except BaseException as error:finish(last,error);raise
                        else:finish(last)
                return Stream()
            finish(response);return response
        Completions.create=create
        # Native local-web uses httpx. Record only proxy status/cache headers,
        # never authorization, request bodies, or API key-bearing URLs.
        import httpx
        sync_send=httpx.Client.send;async_send=httpx.AsyncClient.send
        def web_record(request,response,start,error=None):
            kind={'/search':'search','/fetch':'fetch'}.get(request.url.path)
            if kind:self.write('web.jsonl',{'timestamp':now(),'kind':kind,
                'success':response is not None and response.status_code<400,
                'proxy_http_status':response.status_code if response is not None else None,
                'cache_header':response.headers.get('X-Cached') if response is not None else None,
                'client_http_seconds':time.monotonic()-start,'origin_http_status':None,
                'error_type':type(error).__name__ if error else None})
        def send(client,request,*args,**kwargs):
            start=time.monotonic()
            try:r=sync_send(client,request,*args,**kwargs)
            except BaseException as e:web_record(request,None,start,e);raise
            web_record(request,r,start);return r
        async def asend(client,request,*args,**kwargs):
            start=time.monotonic()
            try:r=await async_send(client,request,*args,**kwargs)
            except BaseException as e:web_record(request,None,start,e);raise
            web_record(request,r,start);return r
        httpx.Client.send=send;httpx.AsyncClient.send=asend

    def instrument_engine(self,engine):
        original=engine.compress
        def compress(*args,**kwargs):
            before=getattr(engine,'compression_count',0);start=time.monotonic()
            token=self.purpose.set('compaction');self.compacting=True
            try:result=original(*args,**kwargs)
            finally:self.purpose.reset(token);self.compacting=False
            after=getattr(engine,'compression_count',0)
            if after>before:self.write('compression.jsonl',{'timestamp':now(),'strategy':engine.name,
                'count_delta':after-before,'valid':True,'compression_seconds':time.monotonic()-start,
                'post_compression_tokens':None,'budget_validation':'Native Hermes policy; not exact matched image-token budget'})
            return result
        engine.compress=compress
        from plugins.context_engine.visual import render
        original_render=render.render_visual_compression
        def reject(*a,**k):raise RuntimeError('PIL fallback forbidden in campaign')
        render._text_to_images_fallback=reject
        def measured(*args,**kwargs):
            from render_dsh_history import RenderFailures
            failures=RenderFailures();render.logger.addHandler(failures);start=time.monotonic()
            try:
                result=original_render(*args,**kwargs)
                if failures.errors:raise RuntimeError('Visual renderer reported partial failure')
                self.write('render.jsonl',{'timestamp':now(),'render_seconds':time.monotonic()-start,
                    'renderer':'Hermes PDF/Poppler','stats':kwargs.get('stats')})
                return result
            except BaseException:
                self.invalid=True;raise
            finally:render.logger.removeHandler(failures)
        render.render_visual_compression=measured


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--spec',type=Path,required=True);ap.add_argument('--out',type=Path,required=True)
    ap.add_argument('--live',action='store_true');args=ap.parse_args()
    spec=json.loads(args.spec.read_text());out=args.out.resolve()
    if not args.live:print(json.dumps({'live':False,'job_id':spec['job_id']}));return
    cfg_path=Path(spec['config_path']);env,cfg=environment(ROOT,'hermes',cfg_path)
    env.pop('CM',None);env.pop('COMPRESS_STRATEGY',None)
    for key in list(env):
        if key.startswith('HERMES_VISUAL_') or key=='HERMES_DISCARD_KEEP_ROUNDS':env.pop(key)
    home=out/'hermes-home';workspace=out/'workspace';home.mkdir(parents=True,exist_ok=True);workspace.mkdir(exist_ok=True)
    home.chmod(0o700)
    env.update(HERMES_HOME=str(home),HERMES_SESSION_STORAGE_ROOT=str(out/'sessions'))
    configure_web(ROOT,env,cfg_path);web=json.loads(env['ACL_WEB_SECRETS'])
    bypass=[env.get('NO_PROXY',''),'localhost','127.0.0.1','::1',
            urlsplit(env['TOKENHUB_BASE_URL']).hostname or '',str(web['search']['url']),
            urlsplit(web['fetch']['base_url']).hostname or '']
    env['NO_PROXY']=env['no_proxy']=','.join(x for x in bypass if x)
    model=spec['model'];strategy=spec['strategy'];engine='compressor' if strategy=='none' else strategy
    hcfg={'model':{'default':model,'provider':'custom','base_url':env['TOKENHUB_BASE_URL'],
          'context_length':cfg['context_window'],'max_tokens':cfg['max_output_tokens'],'api_mode':'chat_completions'},
        'agent':{'coding_context':'off','api_max_retries':3},
        'compression':{'enabled':strategy!='none','threshold':cfg['pilot']['compression_trigger_tokens']/cfg['context_window']},
        'context':{'engine':engine,'strategy_config':{'save_dir':str(out/'context_images'),
            'keep_rounds':0 if strategy=='discard' else 1,'window_size':5,
            'font_size':cfg['visual_renderer']['font_size'],'history_scale':cfg['visual_renderer']['history_scale']}},
        'memory':{'memory_enabled':False,'user_profile_enabled':False},'curator':{'enabled':False},
        'sessions':{'write_json_snapshots':True},'plugins':{'enabled':['local-web']},
        'tool_output':{'max_bytes':cfg['bc100']['fetch_max_output_chars']},
        'web':{'local_web':{'search':web['search'],'fetch':{'fetch_server':web['fetch']}}}}
    private=home/'config.yaml';private.write_text(yaml.safe_dump(hcfg));private.chmod(0o600)
    os.environ.clear();os.environ.update(env);os.chdir(workspace)
    sys.path.insert(0,str(ROOT/'hermes-agent'))
    from hermes_logging import setup_logging
    setup_logging()
    recorder=Recorder(out/'metrics');recorder.install()
    from run_agent import AIAgent
    from hermes_state import SessionDB
    agent=AIAgent(model=model,provider='custom',base_url=env['TOKENHUB_BASE_URL'],api_key=env['TOKENHUB_API_KEY'],
        api_mode='chat_completions',max_iterations=cfg['bc100_campaign']['max_rounds'],max_tokens=cfg['max_output_tokens'],
        enabled_toolsets=['web'],quiet_mode=True,save_trajectories=True,skip_context_files=True,skip_memory=True,
        session_db=SessionDB(home/'state.db'),session_id='acl-'+uuid.uuid4().hex)
    actual=agent.context_compressor.name
    if strategy!='none' and actual!=engine:raise RuntimeError('Hermes policy mismatch; no inference allowed')
    if strategy=='none' and agent.compression_enabled:raise RuntimeError('No-compression policy not applied')
    tool_names=[t.get('function',{}).get('name') for t in agent.tools]
    if not set(tool_names)<= {'web_search','web_extract'}:raise RuntimeError('Unexpected Hermes tool set')
    recorder.write('policy.jsonl',{'timestamp':now(),'verified':True,'strategy':strategy,'engine':actual,'tools':tool_names})
    recorder.instrument_engine(agent.context_compressor)
    start=time.monotonic()
    result=agent.run_conversation(user_message=spec['question'],task_id=spec['job_id'])
    (out/'conversation.json').write_text(json.dumps(result,ensure_ascii=False,default=str))
    text=(result.get('final_response') or '') if not result.get('error') else ''
    (out/'native-result.json').write_text(json.dumps({'status':'completed' if text and not result.get('error') else 'failed',
        'final':{'text':text},'native_error':bool(result.get('error')),'session_id':agent.session_id,
        'agent_loop_seconds':time.monotonic()-start},indent=2))


if __name__=='__main__':main()
