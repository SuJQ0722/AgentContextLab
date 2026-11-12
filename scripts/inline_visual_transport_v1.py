"""Retain the last ten original images and send inline bytes in 64KiB writes.

There is no upload service, hosted URL transformation, image recoding or merging.
The cached Request.content remains available to downstream identity/route guards.
"""
import hashlib,json,time
from pathlib import Path
import httpx
from recent_ten_hosted_selection_v1 import transform as retain
from visual_transport_runtime_v2 import TerminalTransportFailure

VERSION='inline-recent-ten-chunked-v1'
MAX_BODY_BYTES=32*1024*1024
CHUNK_BYTES=64*1024

class ChunkedBytes(httpx.SyncByteStream):
    def __init__(self,raw):self.raw=raw
    def __iter__(self):
        for position in range(0,len(self.raw),CHUNK_BYTES):yield self.raw[position:position+CHUNK_BYTES]
    def close(self):pass

def chunk_request(request,wire):
    headers=httpx.Headers(request.headers);headers.pop('transfer-encoding',None);headers['content-length']=str(len(wire))
    outgoing=httpx.Request(request.method,request.url,headers=headers,content=wire,extensions=dict(request.extensions))
    outgoing.stream=ChunkedBytes(wire)
    if outgoing.content!=wire or outgoing.headers['content-length']!=str(len(wire)):
        raise ValueError('Chunked request cached content identity changed')
    return outgoing

def visual_max_images(config):
    """Resolve the new visual policy; explicit frozen settings take precedence."""
    policy = config.get('visual_image_retention')
    if policy is None:
        root_config = Path(__file__).resolve().parents[1] / 'configs/experiment.json'
        policy = json.loads(root_config.read_text())['visual_image_retention']
    value = policy['max_images_per_request']
    if type(value) is not int or not 1 <= value <= 10:
        raise ValueError('Visual image limit must be an integer from 1 to 10')
    return value

def transport_version(max_images):
    return VERSION if max_images == 10 else f'inline-recent-{max_images}-chunked-v2'

def transform(body,*,rendered_registry,max_images=10):
    wire,selection=retain(body,rendered_registry=rendered_registry,max_images=max_images)
    if len(wire)>MAX_BODY_BYTES:raise ValueError('Inline request exceeds 32MiB body budget')
    selection.pop('final_hosted_body_limit_bytes',None)
    selection.update(version='inline-recent-ten-selection-v1' if max_images == 10 else f'inline-recent-{max_images}-selection-v2',final_inline_body_limit_bytes=MAX_BODY_BYTES,transport_stage='local_image_selection_for_inline_delivery')
    final_guard=selection.get('final_guard',{})
    if final_guard.pop('deferred_to_hosted_wire',None):final_guard['body_limit_revalidated_for_inline']=True
    final_guard.update(max_body_bytes=MAX_BODY_BYTES,body_limit_policy='inline_32_mib')
    return wire,{'version':transport_version(max_images),'max_images':max_images,'selection':selection,'image_count':selection['retained_image_count'],
                 'final_body_bytes':len(wire),'final_body_sha256':hashlib.sha256(wire).hexdigest(),
                 'max_body_bytes':MAX_BODY_BYTES,'chunk_bytes':CHUNK_BYTES,'image_transport':'inline',
                 'pixels_reencoded':False,'pages_merged':False,'hosting_calls':0,
                 'content_length_preserved':True,'transfer_encoding_chunked':False}

def install(out,*,rendered_registry,approved_base_url,max_images=10):
    endpoint=httpx.URL(approved_base_url.rstrip('/')+'/chat/completions');original=httpx.Client._send_single_request
    if getattr(original,'_inline_recent_ten_v1',False):raise RuntimeError('Fresh worker required')
    path=Path(out)/'inline-images-wire-v1.jsonl';path.parent.mkdir(parents=True,exist_ok=True)
    def send(client,request):
        if request.url!=endpoint:return original(client,request)
        began=time.monotonic()
        try:
            wire,row=transform(request.content,rendered_registry=rendered_registry,max_images=max_images)
            outgoing=chunk_request(request,wire)
        except Exception as exc:
            with path.open('a')as f:f.write(json.dumps({'version':transport_version(max_images),'max_images':max_images,'decision':'reject','error_type':type(exc).__name__,'network_send_authorized':False,'at_unix':time.time()})+'\n')
            raise TerminalTransportFailure('inline_image_request_rejected')from None
        row.update(decision='allow',at_unix=time.time(),client_image_preparation_seconds=time.monotonic()-began,
                   network_send_authorized=True,wire_stage=f'after_last{max_images}_before_explicit_route_rotation')
        with path.open('a')as f:f.write(json.dumps(row,separators=(',',':'))+'\n')
        return original(client,outgoing)
    send._inline_recent_ten_v1=True;httpx.Client._send_single_request=send
    return {'version':transport_version(max_images),'max_images':max_images,'ledger':str(path),'uninstall':lambda:setattr(httpx.Client,'_send_single_request',original)}
