"""Worker-scoped transport budgets and client phase telemetry, never provider latency."""
import hashlib
import json
import math
from pathlib import Path
import threading
import time
import uuid
import random
from datetime import timezone
from email.utils import parsedate_to_datetime
import re
from sse_completion import SSECompletion

VERSION = 'visual-transport-runtime-v3'
MAX_RATE_LIMIT_ATTEMPTS = 5
MAX_RATE_LIMIT_WAIT_SECONDS = 300.0
DEFAULT_POLICY = {'connect_seconds':10., 'write_seconds':45., 'read_seconds':120.,
                  'pool_seconds':10., 'stream_seconds':300., 'max_failed_sends':2}

class TerminalTransportFailure(SystemExit):
    """Explicit worker failure; bypass generic SDK/Hermes retry multiplication."""
    def __init__(self, reason):
        self.reason=reason
        super().__init__(78)


def retry_after_seconds(headers, now=None):
    """Parse only recognized formats; never retain arbitrary response header text."""
    now=time.time() if now is None else now
    value=headers.get('retry-after-ms')
    if value is not None:
        try:
            seconds=float(value)/1000
            if math.isfinite(seconds) and seconds>=0:return seconds,'retry-after-ms'
        except (ValueError,TypeError):pass
    value=headers.get('retry-after')
    if value is not None:
        try:
            seconds=float(value)
            if math.isfinite(seconds) and seconds>=0:return seconds,'retry-after'
        except (ValueError,TypeError):pass
        try:
            date=parsedate_to_datetime(value)
            if date.tzinfo is None:date=date.replace(tzinfo=timezone.utc)
            return max(0.,date.timestamp()-now),'retry-after-date'
        except (ValueError,TypeError,OverflowError):pass
    return None,None


def rate_limit_summary(response):
    """Read the explicit refusal, retaining only a constrained code and wait hint."""
    delay,source=retry_after_seconds(response.headers)
    row={'status_code':429,'retry_after_seconds':delay,'retry_after_source':source,
         'retry_after_header_present':any(k in response.headers for k in ('retry-after','retry-after-ms'))}
    try:
        response.read()
        payload=response.json()
        error=payload.get('error',payload) if isinstance(payload,dict) else {}
        code=error.get('code') if isinstance(error,dict) else None
        if isinstance(code,(str,int)) and re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}',str(code)):
            row['provider_code']=str(code)
    except Exception as exc:
        row['error_body_read_error_type']=type(exc).__name__
    return row


def install(policy, out, *, approved_base_url, route_policy=None, worker_key=None, deadline_seconds=1800):
    if route_policy is not None:
        if route_policy != "four-route-rotation-v1":raise ValueError("Unknown explicit route policy")
        return install_four_routes(policy,out,approved_base_url=approved_base_url,worker_key=worker_key,deadline_seconds=deadline_seconds)
    import httpx
    from openai import OpenAI
    from bounded_visual_request_guard_v1 import BoundedVisualRequestError
    endpoint=httpx.URL(approved_base_url.rstrip('/')+'/chat/completions')
    policy=dict(policy)
    if set(policy)!=set(DEFAULT_POLICY) or any(type(v) not in (int,float) or not math.isfinite(v) or v<=0 for v in policy.values()):
        raise ValueError('Explicit positive complete transport policy required')
    if type(policy['max_failed_sends']) is not int:raise ValueError('Integer failed-send limit required')
    path=Path(out)/'transport-phases-v3.jsonl';path.parent.mkdir(parents=True,exist_ok=True)
    original_send=httpx.Client._send_single_request;original_request=OpenAI.request
    if getattr(original_send,'_visual_transport_runtime_v3',False):raise RuntimeError('Fresh worker required')
    lock=threading.Lock();failures={}
    def emit(row):
        row={'version':VERSION,'at_unix':time.time(),'latency_kind':'client_transport_not_provider',**row}
        with lock:
            with path.open('a')as f:f.write(json.dumps(row,separators=(',',':'))+'\n');f.flush()
    def terminal(reason,key,rid):
        emit({'event':'terminal_failure','reason':reason,'request_id':rid,'body_sha256':key,'usage_known':False})
        raise TerminalTransportFailure(reason)
    def sdk(client,cast_to,options,**kwargs):
        if str(client.base_url).rstrip('/')==approved_base_url.rstrip('/'):
            options=options.model_copy(update={'max_retries':0})
        return original_request(client,cast_to,options,**kwargs)
    class ObservedStream(httpx.SyncByteStream):
        def __init__(self,inner,key,rid,start):self.inner,self.key,self.rid,self.start=inner,key,rid,start;self.closed=False;self.done=False;self.failed=False
        def __iter__(self):
            size=0;first=True;framing=SSECompletion()
            try:
                for chunk in self.inner:
                    elapsed=time.monotonic()-self.start
                    if elapsed>policy['stream_seconds']:
                        self.failed=True;failures[self.key]=failures.get(self.key,0)+1
                        terminal('stream_wall_budget',self.key,self.rid)
                    if first:emit({'event':'first_response_bytes','request_id':self.rid,'elapsed_seconds':elapsed});first=False
                    size+=len(chunk)
                    framing.feed(chunk)
                    if framing.done:
                        keep = len(chunk) - (size - framing.done_offset)
                        chunk = chunk[:keep]
                        size = framing.done_offset
                        self.done=True;failures.pop(self.key,None)
                        emit({'event':'stream_complete','request_id':self.rid,'completion_evidence':'sse_done','response_bytes':size,'elapsed_seconds':time.monotonic()-self.start})
                    yield chunk
                    if self.done:break
                if framing.saw_sse and not framing.done:
                    raise httpx.RemoteProtocolError('SSE ended before terminal event')
                if not self.done:
                    self.done=True;failures.pop(self.key,None)
                    emit({'event':'stream_complete','request_id':self.rid,'completion_evidence':'http_eof','response_bytes':size,'elapsed_seconds':time.monotonic()-self.start})
            except Exception as exc:
                self.failed=True;failures[self.key]=failures.get(self.key,0)+1
                emit({'event':'stream_error','request_id':self.rid,'error_type':type(exc).__name__,'response_bytes':size,'elapsed_seconds':time.monotonic()-self.start,'usage_known':False})
                raise
            finally:self.close()
        def close(self):
            if not self.closed:
                self.closed=True
                try:self.inner.close()
                finally:
                    if not self.done and not self.failed:
                        failures[self.key]=failures.get(self.key,0)+1
                        emit({'event':'stream_abandoned','request_id':self.rid,'usage_known':False})
    def send(client,request):
        if request.url != endpoint:return original_send(client,request)
        key=hashlib.sha256(request.content).hexdigest();sdk_request_id=uuid.uuid4().hex
        previous=request.extensions.get('trace');waited=0.
        for http_attempt in range(1,MAX_RATE_LIMIT_ATTEMPTS+1):
            rid=uuid.uuid4().hex;start=time.monotonic();starts={}
            if failures.get(key,0)>=policy['max_failed_sends']:terminal('failed_send_budget',key,rid)
            emit({'event':'request_started','request_id':rid,'sdk_request_id':sdk_request_id,
                  'http_attempt':http_attempt,'body_sha256':key,'body_bytes':len(request.content),
                  'prior_failed_sends':failures.get(key,0)})
            def trace(name,info):
                if name.startswith(('connection.','http11.','http2.')):
                    phase,suffix=name.rsplit('.',1)
                    if suffix=='started':starts[phase]=time.monotonic()
                    row={'event':'transport_phase','request_id':rid,'phase':name,'elapsed_seconds':time.monotonic()-start}
                    if suffix in ('complete','failed') and phase in starts:row['phase_seconds']=time.monotonic()-starts[phase]
                    if suffix=='failed':row['error_type']=type(info.get('exception')).__name__
                    emit(row)
                if previous:previous(name,info)
            request.extensions['trace']=trace
            request.extensions['timeout']={k:policy[k+'_seconds']for k in ('connect','write','read','pool')}
            try:response=original_send(client,request)
            except BoundedVisualRequestError:terminal('deterministic_image_guard_rejection',key,rid)
            except Exception as exc:
                failures[key]=failures.get(key,0)+1
                emit({'event':'send_error','request_id':rid,'error_type':type(exc).__name__,'elapsed_seconds':time.monotonic()-start,'usage_known':False});raise
            emit({'event':'response_headers','request_id':rid,'status_code':response.status_code,'elapsed_seconds':time.monotonic()-start})
            if response.status_code==429:
                details=rate_limit_summary(response)
                base=details['retry_after_seconds']
                if base is None:base=min(60.*(2**(http_attempt-1)),120.)
                delay=base+random.uniform(.1,5.)
                retry=http_attempt<MAX_RATE_LIMIT_ATTEMPTS and waited+delay<=MAX_RATE_LIMIT_WAIT_SECONDS
                emit({'event':'rate_limit_refused','request_id':rid,'sdk_request_id':sdk_request_id,
                      'http_attempt':http_attempt,'max_http_attempts':MAX_RATE_LIMIT_ATTEMPTS,
                      'max_wait_seconds':MAX_RATE_LIMIT_WAIT_SECONDS,'waited_seconds':waited,
                      'proposed_wait_seconds':delay,'retry_authorized':retry,
                      'counts_as_failed_transport':False,'usage_known':False,**details})
                if not retry:
                    # Return the actual HTTP429 so the SDK reports RateLimitError,
                    # never turn quota admission refusal into transport failure.
                    emit({'event':'rate_limit_budget_exhausted','request_id':rid,
                          'reason':'attempt_limit' if http_attempt>=MAX_RATE_LIMIT_ATTEMPTS else 'wait_budget',
                          'waited_seconds':waited,'http_attempts':http_attempt})
                    return response
                response.close()
                began=time.monotonic();time.sleep(delay)
                elapsed=time.monotonic()-began
                # Budget by planned delay even with an injected test clock.
                waited+=max(delay,elapsed)
                emit({'event':'rate_limit_backoff','request_id':rid,'sdk_request_id':sdk_request_id,
                      'planned_wait_seconds':delay,'client_wait_seconds':elapsed,
                      'total_wait_seconds':waited,'wait_excluded_from_provider_latency':True})
                continue
            if response.status_code>=400:
                failures[key]=failures.get(key,0)+1
                return response
            response.stream=ObservedStream(response.stream,key,rid,start)
            return response
        raise AssertionError('Unreachable rate-limit loop')
    send._visual_transport_runtime_v3=True
    httpx.Client._send_single_request=send;OpenAI.request=sdk
    def uninstall():httpx.Client._send_single_request=original_send;OpenAI.request=original_request
    return {'version':VERSION,'policy':policy,'ledger':str(path),'sdk_max_retries':0,'max_rate_limit_attempts':MAX_RATE_LIMIT_ATTEMPTS,'max_rate_limit_wait_seconds':MAX_RATE_LIMIT_WAIT_SECONDS,'uninstall':uninstall}


ALLOWED_MODELS=tuple('deepseek-v4.1-flash-1017/'+route for route in
                     ('huoshan/huoshan','zijian/sfb','huoshan/sfc','zijian/sfc'))
ROUTE_POLICY='four-route-rotation-v1'

def initial_route_index(worker_key):
    if not isinstance(worker_key,str)or not worker_key:raise ValueError('Stable worker key required')
    return int(hashlib.sha256(worker_key.encode()).hexdigest()[:16],16)%len(ALLOWED_MODELS)

def _usage_from_buffer(raw):
    usage=None
    for line in raw.splitlines():
        if not line.startswith(b'data: '):continue
        try:
            event=json.loads(line[6:])
            if isinstance(event,dict)and isinstance(event.get('usage'),dict):usage=event['usage']
        except (ValueError,UnicodeDecodeError):pass
    if usage is None:
        try:
            body=json.loads(raw)
            if isinstance(body,dict)and isinstance(body.get('usage'),dict):usage=body['usage']
        except (ValueError,UnicodeDecodeError):pass
    return usage

def route_error_summary(raw):
    row={}
    try:
        body=json.loads(raw);error=body.get('error',body)if isinstance(body,dict)else {}
        code=error.get('code')if isinstance(error,dict)else None
        message=error.get('message','')if isinstance(error,dict)else ''
        if isinstance(code,(str,int))and re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}',str(code)):row['provider_code']=str(code)
        text=(str(code)+' '+str(message)).lower().replace('_',' ')
        row['model_or_image_unsupported']=any(x in text for x in('model','image','vision','multimodal','visual'))and any(x in text for x in('unsupported','not supported','does not support','不支持','not found','invalid model'))
    except (ValueError,UnicodeDecodeError,TypeError):pass
    return row


def install_four_routes(policy,out,*,approved_base_url,worker_key,deadline_seconds=1800):
    """Explicit authorized route rotation; retry accepted/unknown work is audited.

    Buffer response bytes before exposing them to the SDK: a partial streamed
    answer from a timed-out route must never be concatenated with a later route.
    All intermediate unknown usage is retained, even when a later route succeeds.
    """
    import httpx
    from openai import OpenAI
    from inline_visual_transport_v1 import chunk_request,MAX_BODY_BYTES
    policy=dict(policy)
    if set(policy)!=set(DEFAULT_POLICY)or any(type(x)not in(int,float)or not math.isfinite(x)or x<=0 for x in policy.values()):
        raise ValueError('Explicit positive complete transport policy required')
    if not math.isfinite(deadline_seconds)or deadline_seconds<=0:raise ValueError('Positive route deadline required')
    cursor=initial_route_index(worker_key);deadline=time.monotonic()+deadline_seconds
    endpoint=httpx.URL(approved_base_url.rstrip('/')+'/chat/completions')
    original=httpx.Client._send_single_request;original_request=OpenAI.request
    if getattr(original,'_visual_transport_runtime_v3',False):raise RuntimeError('Fresh worker required')
    path=Path(out)/'transport-phases-v3.jsonl';path.parent.mkdir(parents=True,exist_ok=True);lock=threading.Lock()
    def emit(row):
        row={'version':VERSION,'route_policy':ROUTE_POLICY,'at_unix':time.time(),
             'latency_kind':'client_transport_not_provider',**row}
        with lock:
            with path.open('a')as f:f.write(json.dumps(row,separators=(',',':'))+'\n');f.flush()
    def sdk(client,cast_to,options,**kwargs):
        if str(client.base_url).rstrip('/')==approved_base_url.rstrip('/'):
            options=options.model_copy(update={'max_retries':0})
        return original_request(client,cast_to,options,**kwargs)
    def exhausted(meta,reason):
        emit({**meta,'event':'route_deadline_exhausted','reason':reason,'usage_known':False})
        raise TerminalTransportFailure(reason)
    def send(client,request):
        nonlocal cursor
        if request.url!=endpoint:return original(client,request)
        if request.method!='POST':raise ValueError('Only explicit chat POST route permitted')
        incoming=request.content;payload=json.loads(incoming)
        if not isinstance(payload,dict)or payload.get('model')not in ALLOWED_MODELS:
            raise ValueError('Unapproved version or model route')
        if len(incoming)>MAX_BODY_BYTES:raise ValueError('Inline request exceeds 32MiB body budget')
        sdk_id=uuid.uuid4().hex;index=cursor;attempt=0;cycle=0;cycle_hints=[];total_wait=0.
        previous=request.extensions.get('trace')
        while True:
            route=ALLOWED_MODELS[index];rid=uuid.uuid4().hex
            meta={'request_id':rid,'sdk_request_id':sdk_id,'route':route,'http_attempt':attempt+1,'route_cycle':cycle}
            if time.monotonic()>=deadline:exhausted(meta,'worker_route_deadline')
            chosen=dict(payload);chosen['model']=route
            wire=incoming if route==payload['model']else json.dumps(chosen,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()
            if len(wire)>MAX_BODY_BYTES:raise ValueError('Routed inline request exceeds 32MiB body budget')
            outgoing=chunk_request(request,wire)
            assert outgoing.content==wire
            start=time.monotonic();phase_starts={};headers_at=None;buffer=bytearray();response=None
            emit({**meta,'event':'request_started','body_sha256':hashlib.sha256(wire).hexdigest(),
                  'original_body_sha256':hashlib.sha256(incoming).hexdigest(),'body_bytes':len(wire),
                  'model_only_json_change':route!=payload['model'],'inline_chunk_bytes':65536,
                  'explicit_route_allowlist':list(ALLOWED_MODELS),'prior_failed_sends':None})
            def trace(name,info):
                if name.startswith(('connection.','http11.','http2.')):
                    phase,suffix=name.rsplit('.',1)
                    if suffix=='started':phase_starts[phase]=time.monotonic()
                    row={**meta,'event':'transport_phase','phase':name,'elapsed_seconds':time.monotonic()-start}
                    if suffix in('complete','failed')and phase in phase_starts:row['phase_seconds']=time.monotonic()-phase_starts[phase]
                    if suffix=='failed':row['error_type']=type(info.get('exception')).__name__
                    emit(row)
                if previous:previous(name,info)
            outgoing.extensions['trace']=trace
            outgoing.extensions['timeout']={k:min(policy[k+'_seconds'],max(.001,deadline-time.monotonic()))for k in('connect','write','read','pool')}
            retry=False;failure=None
            try:
                response=original(client,outgoing);headers_at=time.monotonic()
                emit({**meta,'event':'response_headers','status_code':response.status_code,'elapsed_seconds':headers_at-start})
                first=True; framing=SSECompletion()
                for chunk in response.iter_bytes():
                    if first:
                        emit({**meta,'event':'first_response_bytes','elapsed_seconds':time.monotonic()-start,
                              'since_response_headers_seconds':time.monotonic()-headers_at});first=False
                    buffer.extend(chunk)
                    if time.monotonic()>=deadline:raise httpx.ReadTimeout('Worker route deadline',request=outgoing)
                    if time.monotonic()-start>policy['stream_seconds']:raise httpx.ReadTimeout('Route stream wall budget',request=outgoing)
                    if response.is_success:
                        framing.feed(chunk)
                        if framing.done:
                            del buffer[framing.done_offset:]
                            break
                if response.is_success and not framing.done and (framing.saw_sse or 'text/event-stream' in response.headers.get('content-type','')):
                    raise httpx.RemoteProtocolError('SSE ended before terminal event',request=outgoing)
                raw=bytes(buffer);usage=_usage_from_buffer(raw)
                emit({**meta,'event':'stream_complete','completion_evidence':'sse_done' if framing.done else 'http_eof','response_bytes':len(raw),
                      'elapsed_seconds':time.monotonic()-start,'client_stream_seconds':time.monotonic()-headers_at,
                      'usage_known':usage is not None,'raw_provider_usage':usage})
                # iter_bytes produced decoded bytes. Avoid double content decoding.
                headers=httpx.Headers(response.headers);headers.pop('content-encoding',None);headers['content-length']=str(len(raw))
                delivered=httpx.Response(response.status_code,headers=headers,content=raw,request=outgoing,extensions=dict(response.extensions))
                error_details=route_error_summary(raw)if response.status_code>=400 else {}
                if response.status_code==401:
                    emit({**meta,'event':'route_failed','failure_kind':'global_authentication_rejected','status_code':401,
                          'usage_known':usage is not None,'raw_provider_usage':usage,**error_details})
                    raise TerminalTransportFailure('global_authentication_rejected')
                retry=response.status_code in(403,404,408,429) or 500<=response.status_code<=599 or (response.status_code==400 and error_details.get('model_or_image_unsupported')is True)
                if response.status_code==429:
                    details=rate_limit_summary(delivered)
                    if details['retry_after_seconds']is not None:cycle_hints.append(details['retry_after_seconds'])
                    failure={**meta,'event':'route_failed','failure_kind':'rate_limit','usage_known':usage is not None,'raw_provider_usage':usage,**details}
                elif retry:
                    failure={**meta,'event':'route_failed','failure_kind':'server_error'if response.status_code>=500 else'route_unavailable','status_code':response.status_code,
                             'usage_known':usage is not None,'raw_provider_usage':usage,**error_details}
                else:
                    cursor=index
                    emit({**meta,'event':'route_returned','status_code':response.status_code,
                          'usage_known':usage is not None,'raw_provider_usage':usage,'total_wait_seconds':total_wait})
                    return delivered
            except httpx.TransportError as exc:
                retry=True;usage=_usage_from_buffer(bytes(buffer))
                failure={**meta,'event':'route_failed','failure_kind':'transport_unknown_acceptance','error_type':type(exc).__name__,
                         'response_bytes_received':len(buffer),'usage_known':usage is not None,'raw_provider_usage':usage,
                         'elapsed_seconds':time.monotonic()-start}
            finally:
                if response is not None:response.close()
            if not retry:raise AssertionError('Unclassified route outcome')
            emit(failure);attempt+=1;index=(index+1)%len(ALLOWED_MODELS);cursor=index
            if attempt%len(ALLOWED_MODELS)==0:
                cycle+=1;base=min(60.*(2**min(cycle-1,8)),120.)
                delay=max([base,*cycle_hints])+random.uniform(.1,5.)
                cycle_hints=[]
                if time.monotonic()+delay>=deadline:exhausted(meta,'insufficient_deadline_for_route_backoff')
                begin=time.monotonic();time.sleep(delay);elapsed=time.monotonic()-begin;total_wait+=max(delay,elapsed)
                emit({**meta,'event':'route_backoff','route_cycle_completed':cycle,'planned_wait_seconds':delay,
                      'client_wait_seconds':elapsed,'total_wait_seconds':total_wait,'wait_excluded_from_provider_latency':True,
                      'worker_count_unchanged':True})
    send._visual_transport_runtime_v3=True;httpx.Client._send_single_request=send;OpenAI.request=sdk
    def uninstall():httpx.Client._send_single_request=original;OpenAI.request=original_request
    return {'version':VERSION,'route_policy':ROUTE_POLICY,'allowed_models':list(ALLOWED_MODELS),
            'initial_route_index':cursor,'success_route_affinity':True,'worker_deadline_seconds':deadline_seconds,'policy':policy,
            'ledger':str(path),'sdk_max_retries':0,'uninstall':uninstall}
