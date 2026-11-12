"""Hosted-delivery staging: retain ten image identities before URL substitution."""
import base64
import copy
import hashlib
import json
from pathlib import Path
import threading
import time
import uuid
import bounded_ten_image_guard_v1 as guard

VERSION = 'hosted-recent-ten-selection-v1'
RETENTION = 'last_10_in_message_order'
MAX_IMAGES = 10

class RecentImageTransportError(guard.TenImageRequestError):
    pass

def _digest(raw):return hashlib.sha256(raw).hexdigest()

def transform(body, *, rendered_registry, max_images=MAX_IMAGES):
    """Return new bytes and provenance; input bytes/messages are never mutated."""
    if type(max_images) is not int or not 1 <= max_images <= MAX_IMAGES:
        raise ValueError('Image limit must be an integer from 1 to 10')
    record={'version':VERSION,'retention_policy':f'last_{max_images}_in_message_order','max_images':max_images,
            'original_body_bytes':None,'original_body_sha256':None,'original_image_count':None,
            'retained':[],'removed':[],'text_and_tool_semantics_unchanged':True,
            'pixels_reencoded':False,'pages_merged':False,'resolution_changed':False}
    try:
        if not isinstance(body,(bytes,bytearray,memoryview)):
            raise ValueError('Exact body bytes required')
        body=bytes(body);record.update(original_body_bytes=len(body),original_body_sha256=_digest(body))
        payload=json.loads(body)
        if not isinstance(payload,dict)or not isinstance(payload.get('messages'),list):
            raise ValueError('Invalid chat messages')
        registry=rendered_registry()if callable(rendered_registry)else rendered_registry
        if registry is None:raise ValueError('Explicit rendered registry required')
        registry=set(registry)
        occurrences=[]
        for mi,message in enumerate(payload['messages']):
            if not isinstance(message,dict):raise ValueError('Invalid message')
            content=message.get('content')
            if not isinstance(content,list):continue
            for pi,part in enumerate(content):
                if not isinstance(part,dict):raise ValueError('Invalid content block')
                if part.get('type')!='image_url':continue
                value=part.get('image_url');url=value.get('url')if isinstance(value,dict)else value
                if not isinstance(url,str)or not url.startswith('data:image/'):
                    raise ValueError('Unverifiable image identity')
                header,encoded=url.split(',',1)
                if not header.endswith(';base64'):raise ValueError('Invalid image encoding')
                raw=base64.b64decode(encoded,validate=True)
                if not raw:raise ValueError('Empty image')
                digest=_digest(raw)
                occurrences.append({'original_image_ordinal':len(occurrences),'message_index':mi,
                    'original_part_index':pi,'sha256':digest,'bytes':len(raw),
                    'origin':'canvas'if digest in registry else'native',
                    'detail':value.get('detail','auto')if isinstance(value,dict)else'auto'})
        record['original_image_count']=len(occurrences)
        cutoff=max(0,len(occurrences)-max_images)
        removed=occurrences[:cutoff];retained=occurrences[cutoff:]
        dropped={(x['message_index'],x['original_part_index'])for x in removed}
        modified=copy.deepcopy(payload)
        kept_positions={};empty=[]
        for mi,message in enumerate(modified['messages']):
            content=message.get('content')
            if not isinstance(content,list):continue
            kept=[]
            for pi,part in enumerate(content):
                if(mi,pi)in dropped:continue
                if part.get('type')=='image_url':kept_positions[(mi,pi)]=len(kept)
                kept.append(part)
            message['content']=kept
            if content and not kept:empty.append(mi)
        for item in retained:
            item['wire_part_index']=kept_positions[(item['message_index'],item['original_part_index'])]
        # Preserve the exact original serialization when retention changes nothing.
        wire=json.dumps(modified,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode('utf-8')if removed else body
        record.update(removed=removed,retained=retained,removed_image_count=len(removed),
            retained_image_count=len(retained),empty_content_message_indices=empty,
            final_body_bytes=len(wire),final_body_sha256=_digest(wire),
            request_body_modified=bool(removed),image_payload_bytes_unchanged=True,
            wire_serialization='utf8-json-ensure_ascii_false-compact'if removed else'original_verbatim_bytes',
            reconstruction='Remove listed original message/part positions; preserve every other JSON value; serialize as specified')
    except Exception as exc:
        record.update(violations=['retention_input_or_registry_unverifiable'],error_type=type(exc).__name__,
                      network_send_authorized=False)
        raise RecentImageTransportError(record)from None
    try:
        final_guard=guard.inspect_payload(wire,rendered_registry=registry,strict_all_images=False)
    except guard.TenImageRequestError as exc:
        final_guard=dict(exc.ledger)
        remaining=[v for v in final_guard['violations'] if v != 'body_exceeds_8_mib']
        if remaining:
            record.update(final_guard=final_guard,violations=remaining,network_send_authorized=False)
            raise RecentImageTransportError(record)from None
        final_guard.update(violations=[], deferred_to_hosted_wire=['body_exceeds_8_mib'])
    record.update(final_guard=final_guard,violations=[],network_send_authorized=False,
                  staging_only=True, final_hosted_body_limit_bytes=8*1024*1024)
    return wire,record
