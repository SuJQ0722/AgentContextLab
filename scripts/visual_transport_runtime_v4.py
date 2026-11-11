"""Explicit gateway-proxy transport, independent of harness NO_PROXY mutations.

Retains the V3 route/usage/deadline protocol and inline byte stream. Only the
approved chat endpoint uses this dedicated proxy pool. Tool traffic is untouched.
"""
import hashlib,json,threading,time,socket
from pathlib import Path
from urllib.parse import urlsplit
import httpx
from visual_transport_runtime_v3 import DEFAULT_POLICY,ALLOWED_MODELS,ROUTE_POLICY,TerminalTransportFailure
from visual_transport_runtime_v3 import install as install_routes

VERSION='visual-transport-runtime-v4'

def install(policy,out,*,approved_base_url,gateway_proxy,route_policy=ROUTE_POLICY,worker_key=None,deadline_seconds=1800):
    parsed=urlsplit(gateway_proxy or '')
    if parsed.scheme not in('http','https')or not parsed.hostname or parsed.query or parsed.fragment:
        raise ValueError('Explicit HTTP(S) gateway proxy required')
    if route_policy!=ROUTE_POLICY:raise ValueError('Explicit four-route policy required')
    endpoint=httpx.URL(approved_base_url.rstrip('/')+'/chat/completions')
    original=httpx.Client._send_single_request
    if getattr(original,'_gateway_proxy_v4',False):raise RuntimeError('Fresh worker required')
    pool=httpx.Client(proxy=gateway_proxy,trust_env=False,follow_redirects=False,
                     limits=httpx.Limits(max_connections=16,max_keepalive_connections=0))
    path=Path(out)/'gateway-proxy-v4.jsonl';path.parent.mkdir(parents=True,exist_ok=True);lock=threading.Lock()
    proxy_sha=hashlib.sha256(gateway_proxy.encode()).hexdigest();worker_deadline=time.monotonic()+deadline_seconds
    def emit(row):
        with lock:
            with path.open('a')as f:
                f.write(json.dumps({'version':VERSION,'at_unix':time.time(),**row},separators=(',',':'))+'\n');f.flush()
    def proxied(client,request):
        if request.url!=endpoint:return original(client,request)
        began=time.monotonic();previous=request.extensions.get('trace');current_method=None
        attempt_deadline=min(worker_deadline,began+policy['stream_seconds']);active_socket=[None];expired=threading.Event()
        def expire():
            expired.set()
            current=active_socket[0]
            if current is not None:
                try:current.shutdown(socket.SHUT_RDWR)
                except OSError:pass
            emit({'event':'http_wall_deadline','body_sha256':hashlib.sha256(request.content).hexdigest(),
                  'client_seconds':time.monotonic()-began,'socket_shutdown_attempted':current is not None})
        timer=threading.Timer(max(.001,attempt_deadline-time.monotonic()),expire);timer.daemon=True
        timeout=dict(request.extensions.get('timeout',{}));timeout['read']=max(.001,attempt_deadline-time.monotonic());request.extensions['timeout']=timeout
        emit({'event':'explicit_gateway_proxy_send','proxy_identity_sha256':proxy_sha,
              'proxy_hostname':parsed.hostname,'proxy_port':parsed.port,'trust_env':False,
              'body_sha256':hashlib.sha256(request.content).hexdigest(),'body_bytes':len(request.content),
              'request_stream_type':type(request.stream).__name__,
              'upload_metric_scope':'client_to_proxy_socket_not_provider_ingress',
              'http_wall_budget_seconds':max(0,attempt_deadline-began),'read_timeout_policy':'remaining_http_wall',
              'keepalive_disabled_for_per_attempt_socket_deadline':True})
        def trace(name,info):
            nonlocal current_method
            if name.endswith(('connect_tcp.complete','start_tls.complete')):
                stream=info.get('return_value')
                if hasattr(stream,'get_extra_info'):
                    current=stream.get_extra_info('socket')
                    if current is not None:
                        active_socket[0]=current
                        if expired.is_set()or time.monotonic()>=attempt_deadline:
                            try:current.shutdown(socket.SHUT_RDWR)
                            except OSError:pass
                            raise httpx.ReadTimeout('HTTP wall deadline before socket became available',request=request)
            if name.endswith(('receive_response_headers.started','receive_response_body.started')):
                timeout['read']=max(.001,attempt_deadline-time.monotonic())
            # httpcore propagates the outer trace into CONNECT. Keep these
            # events separate so a zero-byte tunnel is never a model upload.
            if name.endswith('send_request_headers.started'):
                value=getattr(info.get('request'),'method',None)
                current_method=value.decode('ascii','replace')if isinstance(value,bytes)else value
            if name.startswith(('http11.','http2.'))and current_method=='CONNECT':
                emit({'event':'proxy_tunnel_phase','phase':name,'elapsed_seconds':time.monotonic()-began})
                return
            if previous:previous(name,info)
        request.extensions['trace']=trace
        class DeadlineStream(httpx.SyncByteStream):
            def __init__(self,stream):self.stream=stream
            def __iter__(self):
                try:
                    for chunk in self.stream:
                        if expired.is_set():raise httpx.ReadTimeout('HTTP wall deadline',request=request)
                        yield chunk
                    if expired.is_set()or time.monotonic()>=attempt_deadline:
                        raise httpx.ReadTimeout('HTTP wall deadline at response EOF',request=request)
                finally:self.close()
            def close(self):timer.cancel();self.stream.close()
        timer.start()
        try:
            response=original(pool,request)
            if expired.is_set()or time.monotonic()>=attempt_deadline:
                response.close()
                raise httpx.ReadTimeout('HTTP wall deadline before response delivery',request=request)
            response.stream=DeadlineStream(response.stream)
            return response
        except BaseException:
            timer.cancel();raise
    proxied._gateway_proxy_v4=True;httpx.Client._send_single_request=proxied
    try:
        handle=install_routes(policy,out,approved_base_url=approved_base_url,route_policy=route_policy,
                              worker_key=worker_key,deadline_seconds=deadline_seconds)
    except BaseException:
        httpx.Client._send_single_request=original;pool.close();raise
    emit({'event':'gateway_proxy_configuration','proxy_identity_sha256':proxy_sha,'proxy_hostname':parsed.hostname,
          'proxy_port':parsed.port,'inherited_route_version':handle['version'],
          'environment_proxy_bypass_ignored':True,'provider_internal_latency_measured':False})
    def uninstall():
        handle['uninstall']();httpx.Client._send_single_request=original;pool.close()
    return {**handle,'version':VERSION,'inherited_route_version':handle['version'],
            'gateway_proxy_ledger':str(path),'proxy_identity_sha256':proxy_sha,
            'proxy_mode':'explicit_configured_gateway_proxy',
            'effective_read_timeout_policy':'remaining_http_wall_budget',
            'hard_http_wall_seconds':policy['stream_seconds'],'keepalive_connections':0,
            'uninstall':uninstall}
