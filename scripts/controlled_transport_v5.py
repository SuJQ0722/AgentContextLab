"""Bounded native recovery support and secret-free transport diagnostics; no retry loop."""
import hashlib,json,os,traceback,uuid
from urllib.parse import urlsplit
from controlled_native_guard_v4 import ControlledRecorder

class AuxiliaryRequestLimit(BaseException):pass

def fingerprint(kwargs):
    semantic={k:v for k,v in kwargs.items() if k not in ('extra_headers','timeout')}
    return hashlib.sha256(json.dumps(semantic,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()

def is_provider_error(error):
    import openai,httpx
    return isinstance(error,(openai.APIError,httpx.TransportError))

def cause_chain(error):
    """Never serialize exception repr/body/headers or traceback locals."""
    rows=[];seen=set()
    while error is not None and id(error) not in seen and len(rows)<8:
        seen.add(id(error));message=str(error).lower()
        hints=[label for label,needles in {
            'peer_disconnected':('disconnected','connection closed','incomplete chunk','peer closed'),
            'timeout':('timed out','timeout'),'connection_reset':('connection reset',),
            'connection_refused':('connection refused',),'dns':('name or service not known','name resolution'),
            'tls':('certificate verify','ssl','tls')}.items() if any(n in message for n in needles)]
        rows.append({'type':type(error).__name__,'module':type(error).__module__,
            'errno':getattr(error,'errno',None),'status_code':getattr(error,'status_code',None),'hints':hints,
            'frames':[{'file':os.path.basename(f.filename),'line':f.lineno,'function':f.name} for f in traceback.extract_tb(error.__traceback__)[-8:]]})
        error=error.__cause__ or error.__context__
    return rows

class DiagnosticRecorder(ControlledRecorder):
    def install(self):
        super().install()
        import contextvars,httpx
        from openai.resources.chat.completions import Completions
        sdk=Completions.create;send=httpx.Client._send_single_request
        context=contextvars.ContextVar('controlled_transport_request',default=None)
        def log_error(stage,error,meta):
            self.write('transport-diagnostics.jsonl',{'event':stage,'cause_chain':cause_chain(error),**meta,
                'freeform_exception_or_headers_saved':False,'automatic_retry_added_by_observer':False})
        def create(client,*args,**kwargs):
            meta={'sdk_observation_id':uuid.uuid4().hex,'purpose':self.purpose.get(),'request_fingerprint':fingerprint(kwargs),'stream':bool(kwargs.get('stream'))}
            token=context.set(meta)
            try:response=sdk(client,*args,**kwargs)
            except BaseException as error:log_error('sdk_exception',error,meta);raise
            finally:context.reset(token)
            if kwargs.get('stream'):
                class Stream:
                    def __getattr__(self,key):return getattr(response,key)
                    def __enter__(self):return self
                    def __exit__(self,*args):response.close()
                    def __iter__(self):
                        try:yield from response
                        except BaseException as error:log_error('stream_exception',error,meta);raise
                return Stream()
            return response
        def wire(client,request):
            if not request.url.path.rstrip('/').endswith('/chat/completions'):return send(client,request)
            meta={**(context.get() or {}),'endpoint_host':request.url.host,'endpoint_path':request.url.path,
                'request_bytes':len(request.content),'http_body_sha256':hashlib.sha256(request.content).hexdigest()}
            try:response=send(client,request)
            except BaseException as error:log_error('http_exception',error,meta);raise
            self.write('transport-diagnostics.jsonl',{'event':'http_response','http_status':response.status_code,
                'retry_after':response.headers.get('retry-after'),'provider_request_id':response.headers.get('x-request-id'),**meta})
            return response
        Completions.create=create;httpx.Client._send_single_request=wire
