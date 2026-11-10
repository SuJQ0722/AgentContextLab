"""Explicit byte-verified hosted delivery after last-ten selection; no inline fallback."""
import base64
import fcntl
import hashlib
import json
from pathlib import Path
import threading
import time
from urllib.parse import urlsplit
from recent_ten_images_transport_v1 import transform as retain
from visual_transport_runtime_v2 import TerminalTransportFailure

VERSION='verified-imgbb-url-v1'
_UPLOAD_LOCK=threading.Lock()  # Existing Hermes upload adapter temporarily patches env.

def digest(raw):return hashlib.sha256(raw).hexdigest()

class VerifiedImageHost:
    def __init__(self, root, env):self.root=Path(root);self.env=dict(env)
    def __call__(self,raw):return self.ensure(raw)
    def ensure(self,raw,mime=None):
        import os,sys,logging
        import httpx,requests
        from unittest.mock import patch
        from info_loss_phase4_url import pixel_sha
        from local_web import configure_image_upload
        from lab import ROOT
        key=digest(raw);directory=self.root/'sources';directory.mkdir(parents=True,exist_ok=True)
        hosted=self.root/'hosted';hosted.mkdir(exist_ok=True)
        suffix='.webp'if raw[:4]==b'RIFF' else '.png'if raw[:8]==b'\x89PNG\r\n\x1a\n'else'.jpg'
        path=directory/(key+suffix);cache=hosted/(key+'.json');receipt=hosted/(key+'.upload.json');started=hosted/(key+'.upload-started.json');checked=hosted/(key+'.verify-started.json')
        def save(p,row):
            tmp=p.with_suffix(p.suffix+'.tmp');tmp.write_text(json.dumps(row,indent=2));tmp.chmod(0o600);tmp.replace(p)
        with (directory/(key+'.lock')).open('a')as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            if path.exists():
                if digest(path.read_bytes())!=key:raise ValueError('Hosted source identity mismatch')
            else:
                with path.open('xb')as f:f.write(raw)
            if cache.exists():return json.loads(cache.read_text())
            configured=dict(self.env);configure_image_upload(ROOT,configured)
            if not configured.get('IMAGE_UPLOAD_API_KEY'):raise ValueError('Existing upload credential unavailable')
            if receipt.exists():
                r=json.loads(receipt.read_text())
                if r.get('source_sha256')!=key:raise ValueError('Receipt identity changed')
                url=r['url']
            else:
                if started.exists():raise ValueError('Unresolved prior upload; explicit recovery required')
                save(started,{'source_sha256':key,'at_unix':time.time(),'automatic_retries':0})
                sys.path.insert(0,str(ROOT/'hermes-agent'))
                from tools import image_search_tool
                with _UPLOAD_LOCK,requests.Session()as session:
                    session.trust_env=False
                    logger=logging.getLogger('tools.image_search_tool');disabled=logger.disabled;logger.disabled=True
                    try:
                        with patch.dict(os.environ,{'IMAGE_UPLOAD_API_KEY':configured['IMAGE_UPLOAD_API_KEY']}),patch.object(image_search_tool.requests,'post',session.post):
                            url=image_search_tool._upload_imgbb(path)
                    finally:logger.disabled=disabled
                if not url or urlsplit(url).scheme!='https':raise ValueError('Single image upload failed')
                save(receipt,{'source_sha256':key,'url':url,'at_unix':time.time(),'transport':'direct_trust_env_false','automatic_retries':0})
            if checked.exists():raise ValueError('Prior verification failed or interrupted; no automatic retry')
            save(checked,{'source_sha256':key,'at_unix':time.time(),'automatic_retries':0})
            proxy=configured.get('https_proxy')or configured.get('HTTPS_PROXY')or configured.get('http_proxy')
            begin=time.monotonic()
            with httpx.Client(proxy=proxy,trust_env=False,timeout=45,follow_redirects=True)as client:
                response=client.get(url);response.raise_for_status();received=response.content
            got=digest(received);pixel,dims=pixel_sha(raw);other,otherdims=pixel_sha(received)
            if got!=key or other!=pixel or dims!=otherdims:raise ValueError('Hosted bytes/pixels changed')
            record={'provider':'authorized_Hermes_imgbb','url':url,'source_path':str(path),'source_sha256':key,'download_sha256':got,'pixel_sha256':pixel,'dimensions':dims,'byte_identical':True,'pixel_identical':True,'checked_at':time.time(),'client_download_seconds':time.monotonic()-begin,'model_calls':0}
            save(cache,record);return record

def transform(body,*,rendered_registry,host):
    selected,selection=retain(body,rendered_registry=rendered_registry)
    payload=json.loads(selected);images=[]
    for mi,message in enumerate(payload['messages']):
        if not isinstance(message.get('content'),list):continue
        for pi,part in enumerate(message['content']):
            if part.get('type')!='image_url':continue
            value=part['image_url'];url=value['url']if isinstance(value,dict)else value
            raw=base64.b64decode(url.split(',',1)[1],validate=True);key=digest(raw);record=host(raw)
            if (record.get('source_sha256')!=key or record.get('download_sha256')!=key
                or record.get('byte_identical')is not True or record.get('pixel_identical')is not True
                or not record.get('pixel_sha256') or not record.get('dimensions')):
                raise ValueError('Hosted image lacks verified byte/pixel identity')
            hosted=record.get('url');parsed=urlsplit(hosted or '')
            if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password:raise ValueError('Verified HTTPS image URL required')
            if isinstance(value,dict):value['url']=hosted
            else:part['image_url']=hosted
            images.append({'message_index':mi,'part_index':pi,'source_sha256':key,'download_sha256':key,
                'hosted_url_sha256':digest(hosted.encode()),'byte_identical':True,'pixel_identical':True,
                'detail':value.get('detail','auto')if isinstance(value,dict)else'auto','verified_at':record.get('checked_at')})
    wire=json.dumps(payload,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()if images else selected
    if len(wire)>8*1024*1024:raise ValueError('Hosted request exceeds body budget')
    return wire,{'version':VERSION,'selection':selection,'hosted_images':images,'image_count':len(images),
        'inline_body_bytes':len(selected),'inline_body_sha256':digest(selected),'final_body_bytes':len(wire),
        'final_body_sha256':digest(wire),'provider_fetch_verified':False,'text_tools_and_retained_pixels_unchanged':True}

def install(out,*,rendered_registry,host,approved_base_url):
    import httpx
    original=httpx.Client._send_single_request;endpoint=httpx.URL(approved_base_url.rstrip('/')+'/chat/completions')
    if getattr(original,'_verified_hosted_images_v3',False):raise RuntimeError('Fresh worker required')
    path=Path(out)/'hosted-images-wire-v3.jsonl';path.parent.mkdir(parents=True,exist_ok=True)
    def send(client,request):
        if request.url!=endpoint:return original(client,request)
        start=time.monotonic()
        try:
            wire,row=transform(request.content,rendered_registry=rendered_registry,host=host)
            headers=httpx.Headers(request.headers);headers.pop('transfer-encoding',None);headers['content-length']=str(len(wire))
            outgoing=httpx.Request(request.method,request.url,headers=headers,content=wire,extensions=dict(request.extensions))
        except Exception as exc:
            with path.open('a')as f:f.write(json.dumps({'version':VERSION,'decision':'reject','error_type':type(exc).__name__,'network_send_authorized':False,'at_unix':time.time()})+'\n')
            raise TerminalTransportFailure('verified_hosted_image_delivery_rejected')from None
        row.update(decision='allow',network_send_authorized=True,at_unix=time.time(),client_image_preparation_seconds=time.monotonic()-start)
        with path.open('a')as f:f.write(json.dumps(row,separators=(',',':'))+'\n')
        return original(client,outgoing)
    send._verified_hosted_images_v3=True;httpx.Client._send_single_request=send
    return {'version':VERSION,'ledger':str(path),'uninstall':lambda:setattr(httpx.Client,'_send_single_request',original)}
