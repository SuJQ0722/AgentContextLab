"""Apply explicit image/page budgets and send inline bytes in 64KiB writes.

There is no upload service, hosted URL transformation, image recoding or merging.
The cached Request.content remains available to downstream identity/route guards.
"""
import base64,copy,hashlib,json,re,time
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

def visual_policy(config):
    policy = config.get('visual_image_retention')
    if policy is None:
        root_config = Path(__file__).resolve().parents[1] / 'configs/experiment.json'
        policy = json.loads(root_config.read_text())['visual_image_retention']
    return policy

def visual_max_images(config):
    value = visual_policy(config)['max_images_per_request']
    if type(value) is not int or not 1 <= value <= 10:
        raise ValueError('Visual image limit must be an integer from 1 to 10')
    return value

def visual_page_budget(config):
    return visual_policy(config).get('page_budget')

def select_canvas_pages(body, registry, budget):
    """Bound labeled, verified canvas pages; preserve native images and exact bytes."""
    if set(budget) != {'history', 'recent'} or any(type(v) is not int or v < 1 for v in budget.values()):
        raise ValueError('Positive history/recent page budgets required')
    payload = json.loads(body)
    pages = []
    native_count = 0
    for mi, message in enumerate(payload['messages']):
        content = message.get('content')
        if not isinstance(content, list): continue
        label = None
        for pi, part in enumerate(content):
            if part.get('type') == 'text':
                match = re.search(r'\[(History|Recent) page (\d+)/(\d+) — linear scale [^,]+, high detail\]\s*$', part.get('text', ''))
                label = (match.group(1).lower(), pi, part.get('text', '')[:match.start()]) if match else None
            elif part.get('type') == 'image_url':
                value = part['image_url']; url = value.get('url') if isinstance(value, dict) else value
                if not url.startswith('data:image/'): raise ValueError('Inline images required')
                raw = base64.b64decode(url.split(',', 1)[1], validate=True)
                digest = hashlib.sha256(raw).hexdigest()
                if digest in registry:
                    if label is None: raise ValueError('Canvas lacks a verified segment label')
                    pages.append({'segment': label[0], 'message_index': mi, 'label_index': label[1], 'label_prefix': label[2], 'part_index': pi, 'sha256': digest})
                else:
                    native_count += 1
                label = None
    if native_count > 10:
        raise ValueError('Native images exceed 10; refusing native evidence deletion')
    available = 10 - native_count
    effective = {'recent': min(budget['recent'], available, sum(p['segment'] == 'recent' for p in pages))}
    effective['history'] = min(budget['history'], available - effective['recent'])
    removed = []
    for segment, limit in effective.items():
        selected = [p for p in pages if p['segment'] == segment]
        removed.extend(selected[:-limit] if limit else selected)
    positions = {(p['message_index'], i) for p in removed for i in (p['part_index'], p['label_index'])}
    result = copy.deepcopy(payload)
    for page in removed:
        if page['label_prefix']:
            result['messages'][page['message_index']]['content'][page['label_index']]['text'] = page['label_prefix']
            positions.discard((page['message_index'], page['label_index']))
    for mi, message in enumerate(result['messages']):
        if isinstance(message.get('content'), list):
            message['content'] = [part for pi, part in enumerate(message['content']) if (mi, pi) not in positions]
    count = sum(part.get('type') == 'image_url' for message in result['messages'] if isinstance(message.get('content'), list) for part in message['content'])
    if count > 10:
        raise ValueError('Canvas budget plus native images exceeds 10; refusing native evidence deletion')
    audit = {'version': 'canvas-history5-recent2-v1', 'budget': dict(budget), 'effective_budget': effective, 'native_count': native_count,
             'generated_counts': {k: sum(p['segment'] == k for p in pages) for k in budget},
             'retained_counts': {k: min(effective[k], sum(p['segment'] == k for p in pages)) for k in budget},
             'removed': [{k: v for k, v in p.items() if k != 'label_prefix'} for p in removed], 'native_images_preserved': True,
             'policy': 'last_pages_per_segment_no_merge_no_rescale', 'evidence_complete': not removed}
    return (json.dumps(result, ensure_ascii=False, separators=(',', ':')).encode() if removed else body), audit

def transport_version(max_images, page_budget=None):
    if page_budget is not None: return 'inline-history5-recent2-v1'
    return VERSION if max_images == 10 else f'inline-recent-{max_images}-chunked-v2'

def transform(body,*,rendered_registry,max_images=10,page_budget=None):
    segment_audit = None
    original_body = body
    if page_budget is not None:
        if max_images != 10: raise ValueError('Segment budgets require the 10-image safety envelope')
        registry = set(rendered_registry() if callable(rendered_registry) else rendered_registry)
        body, segment_audit = select_canvas_pages(body, registry, page_budget)
        rendered_registry = registry
    wire,selection=retain(body,rendered_registry=rendered_registry,max_images=max_images)
    if segment_audit is not None:
        selection['canvas_page_selection'] = segment_audit
        selection['pre_segment_body_sha256'] = hashlib.sha256(original_body).hexdigest()
        selection['retention_policy'] = 'history5_recent2_preserve_native'

    if len(wire)>MAX_BODY_BYTES:raise ValueError('Inline request exceeds 32MiB body budget')
    selection.pop('final_hosted_body_limit_bytes',None)
    selection.update(version='inline-recent-ten-selection-v1' if max_images == 10 else f'inline-recent-{max_images}-selection-v2',final_inline_body_limit_bytes=MAX_BODY_BYTES,transport_stage='local_image_selection_for_inline_delivery')
    final_guard=selection.get('final_guard',{})
    if final_guard.pop('deferred_to_hosted_wire',None):final_guard['body_limit_revalidated_for_inline']=True
    final_guard.update(max_body_bytes=MAX_BODY_BYTES,body_limit_policy='inline_32_mib')
    return wire,{'version':transport_version(max_images, page_budget),'max_images':max_images,'selection':selection,'image_count':selection['retained_image_count'],
                 'final_body_bytes':len(wire),'final_body_sha256':hashlib.sha256(wire).hexdigest(),
                 'max_body_bytes':MAX_BODY_BYTES,'chunk_bytes':CHUNK_BYTES,'image_transport':'inline',
                 'pixels_reencoded':False,'pages_merged':False,'hosting_calls':0,
                 'content_length_preserved':True,'transfer_encoding_chunked':False}

def install(out,*,rendered_registry,approved_base_url,max_images=10,page_budget=None):
    endpoint=httpx.URL(approved_base_url.rstrip('/')+'/chat/completions');original=httpx.Client._send_single_request
    if getattr(original,'_inline_recent_ten_v1',False):raise RuntimeError('Fresh worker required')
    path=Path(out)/'inline-images-wire-v1.jsonl';path.parent.mkdir(parents=True,exist_ok=True)
    def send(client,request):
        if request.url!=endpoint:return original(client,request)
        began=time.monotonic()
        try:
            wire,row=transform(request.content,rendered_registry=rendered_registry,max_images=max_images,page_budget=page_budget)
            outgoing=chunk_request(request,wire)
        except Exception as exc:
            with path.open('a')as f:f.write(json.dumps({'version':transport_version(max_images, page_budget),'max_images':max_images,'decision':'reject','error_type':type(exc).__name__,'network_send_authorized':False,'at_unix':time.time()})+'\n')
            raise TerminalTransportFailure('inline_image_request_rejected')from None
        row.update(decision='allow',at_unix=time.time(),client_image_preparation_seconds=time.monotonic()-began,
                   network_send_authorized=True,wire_stage='after_segment_budget_before_route_rotation' if page_budget is not None else f'after_last{max_images}_before_explicit_route_rotation')
        with path.open('a')as f:f.write(json.dumps(row,separators=(',',':'))+'\n')
        return original(client,outgoing)
    send._inline_recent_ten_v1=True;httpx.Client._send_single_request=send
    return {'version':transport_version(max_images, page_budget),'max_images':max_images,'ledger':str(path),'uninstall':lambda:setattr(httpx.Client,'_send_single_request',original)}
