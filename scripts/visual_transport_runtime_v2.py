"""Worker-scoped transport budgets and client phase telemetry, never provider latency."""
import hashlib
import json
import math
from pathlib import Path
import threading
import time
import uuid

VERSION = 'visual-transport-runtime-v2'
DEFAULT_POLICY = {'connect_seconds':10., 'write_seconds':45., 'read_seconds':120.,
                  'pool_seconds':10., 'stream_seconds':300., 'max_failed_sends':2}

class TerminalTransportFailure(SystemExit):
    """Explicit worker failure; bypass generic SDK/Hermes retry multiplication."""
    def __init__(self, reason):
        self.reason=reason
        super().__init__(78)


def install(policy, out, *, approved_base_url):
    import httpx
    from openai import OpenAI
    from bounded_visual_request_guard_v1 import BoundedVisualRequestError
    endpoint=httpx.URL(approved_base_url.rstrip('/')+'/chat/completions')
    policy=dict(policy)
    if set(policy)!=set(DEFAULT_POLICY) or any(type(v) not in (int,float) or not math.isfinite(v) or v<=0 for v in policy.values()):
        raise ValueError('Explicit positive complete transport policy required')
    if type(policy['max_failed_sends']) is not int:raise ValueError('Integer failed-send limit required')
    path=Path(out)/'transport-phases-v2.jsonl';path.parent.mkdir(parents=True,exist_ok=True)
    original_send=httpx.Client._send_single_request;original_request=OpenAI.request
    if getattr(original_send,'_visual_transport_runtime_v2',False):raise RuntimeError('Fresh worker required')
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
            size=0;first=True;tail=b''
            try:
                for chunk in self.inner:
                    elapsed=time.monotonic()-self.start
                    if elapsed>policy['stream_seconds']:
                        self.failed=True;failures[self.key]=failures.get(self.key,0)+1
                        terminal('stream_wall_budget',self.key,self.rid)
                    if first:emit({'event':'first_response_bytes','request_id':self.rid,'elapsed_seconds':elapsed});first=False
                    size+=len(chunk)
                    framed=tail+chunk
                    if not self.done and any(line.strip()==b'data: [DONE]' for line in framed.split(b'\n')[:-1]):
                        self.done=True;failures.pop(self.key,None)
                        emit({'event':'stream_complete','request_id':self.rid,'completion_evidence':'sse_done','response_bytes':size,'elapsed_seconds':time.monotonic()-self.start})
                    tail=framed[-256:]
                    yield chunk
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
        rid=uuid.uuid4().hex;key=hashlib.sha256(request.content).hexdigest();start=time.monotonic();starts={}
        if failures.get(key,0)>=policy['max_failed_sends']:terminal('failed_send_budget',key,rid)
        emit({'event':'request_started','request_id':rid,'body_sha256':key,'body_bytes':len(request.content),'prior_failed_sends':failures.get(key,0)})
        previous=request.extensions.get('trace')
        def trace(name,info):
            # No arbitrary info values: may contain URLs, authorization or bodies.
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
        if response.status_code>=400:
            failures[key]=failures.get(key,0)+1
            # SDK owns error response decoding. Do not reset failures on its EOF.
            return response
        response.stream=ObservedStream(response.stream,key,rid,start)
        return response
    send._visual_transport_runtime_v2=True
    httpx.Client._send_single_request=send;OpenAI.request=sdk
    def uninstall():httpx.Client._send_single_request=original_send;OpenAI.request=original_request
    return {'version':VERSION,'policy':policy,'ledger':str(path),'sdk_max_retries':0,'uninstall':uninstall}
