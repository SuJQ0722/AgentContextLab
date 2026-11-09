#!/usr/bin/env python3
"""Independent URL delivery gate; prior local upload failures stay immutable."""
import argparse,base64,fcntl,hashlib,io,json,logging,os,signal,sys,time
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit
import httpx,requests
from PIL import Image
import info_loss_phase4 as study
from local_web import configure_image_upload
from lab import ROOT,environment
from info_loss_eval import save

DEFAULT=ROOT/'outputs/experiment6/paired-repair-phase4-url1'
VERSION='phase4-exact-pixels-imgbb-url1'

def pixel_sha(data):
 with Image.open(io.BytesIO(data)) as image:
  rgba=image.convert('RGBA');return hashlib.sha256(str(rgba.size).encode()+b'\0'+rgba.tobytes()).hexdigest(),list(rgba.size)

def upload_and_verify(item,root,env):
 """Existing authorized Hermes imgBB handler; image download must be byte exact."""
 cache=root/'hosted'/f"{item['sha256']}.json"
 if cache.exists():
  record=study.read(cache)
  if record['source_sha256']!=item['sha256'] or not record.get('byte_identical') or not record.get('pixel_identical'):raise ValueError('Invalid hosted cache')
  return record
 data=Path(item['path']).read_bytes()
 if hashlib.sha256(data).hexdigest()!=item['sha256']:raise ValueError('Frozen source image changed')
 configured=dict(env);configure_image_upload(ROOT,configured)
 if not configured.get('IMAGE_UPLOAD_API_KEY'):raise ValueError('Existing Hermes image upload key unavailable')
 sys.path.insert(0,str(ROOT/'hermes-agent'))
 from tools.image_search_tool import _upload_imgbb
 # Reuse just the authorized upload credential and proxy configuration.
 selected={k:v for k,v in configured.items() if k in ('IMAGE_UPLOAD_API_KEY','http_proxy','https_proxy','HTTP_PROXY','HTTPS_PROXY','NO_PROXY','no_proxy')}
 started=time.monotonic()
 with patch.dict(os.environ,selected):
  logging.getLogger('tools.image_search_tool').disabled=True
  url=_upload_imgbb(Path(item['path']))
 if not url or urlsplit(url).scheme!='https':raise ValueError('Image upload failed; no model call issued')
 proxy=configured.get('https_proxy') or configured.get('HTTPS_PROXY') or configured.get('http_proxy')
 with httpx.Client(proxy=proxy,trust_env=False,timeout=45,follow_redirects=True) as client:
  response=client.get(url);response.raise_for_status();received=response.content
 got=hashlib.sha256(received).hexdigest();source_pixel,dims=pixel_sha(data);remote_pixel,remote_dims=pixel_sha(received)
 if got!=item['sha256'] or source_pixel!=remote_pixel or dims!=remote_dims:raise ValueError('Hosted image changed bytes or pixels; reject before inference')
 record={'provider':'authorized_Hermes_imgbb','url':url,'source_path':item['path'],'source_sha256':item['sha256'],'download_sha256':got,'pixel_sha256':source_pixel,'dimensions':dims,'byte_identical':True,'pixel_identical':True,'checked_at':study.old.now(),'client_upload_download_seconds':time.monotonic()-started,'model_calls':0}
 save(cache,record);return record

def prepare(root,parent=study.DEFAULT):
 parent=Path(parent).resolve();m=study.read(parent/'manifest.json');study.verify(parent,m)
 if (root/'manifest.json').exists():raise ValueError('Existing URL protocol manifest')
 starts=list(parent.glob('calls/*/started.json'))
 if any(not (p.parent/'response.json').exists() for p in starts):raise ValueError('Parent unresolved request prevents cutover')
 if not (parent/'quality-hold.json').exists():raise ValueError('Parent must be explicitly held')
 count=len(starts);prior={str(p.relative_to(parent)):study.sha(p) for pattern in ('calls/*/started.json','calls/*/response.json') for p in parent.glob(pattern)}
 new=json.loads(json.dumps(m));new.update(version=VERSION,prepared_at=study.old.now(),max_requests=190-count,stages=['tiles_high'],implementation_sha256=study.sources(),url_entry_sha256=study.sha(__file__),local_parent_root=str(parent),local_parent_manifest_sha256=study.sha(parent/'manifest.json'),prior_call_evidence=prior,prior_calls=count,combined_paid_cap=190,
  stage_selection='Explicit new URL gate on fixed q004 five arms; original pixels/detail/prompts/model from phase4 tiles_high. Previous transport errors not overwritten or scored. URL gate included in cumulative190 calls; primary analysis excludes q004.')
 new['limitations']+=['URL delivery is a new explicit inference deployment. All local failed/unknown attempts retained; no apparent improvement may be attributed to pixels/thinking without separating transport.',
  'Hosted image downloaded byte-for-byte and decoded-pixel verified before request; provider server-side URL fetch itself is only evidenced by a successful factual gate, not independently intercepted.',
  'Operational image uploads/download checks are not model calls; HTTP cost/latency separate from model client duration.']
 for sub in ('facts','summaries'):
  for path in (parent/sub).glob('*.json'):save(root/sub/path.name,study.read(path))
 # Imported preprocessing remains separately attributed; change copied target references only.
 for item in new['reused']:
  path=root/('facts' if item['kind']=='facts' else 'summaries')/Path(item['target']).name;item['target']=str(path);item['target_sha256']=study.sha(path)
 save(root/'manifest.json',new);(root/'manifest.sha256').write_text(study.sha(root/'manifest.json')+'\n');return new

def verify_parent(m):
 p=Path(m['local_parent_root'])
 if study.sha(p/'manifest.json')!=m['local_parent_manifest_sha256'] or len(list(p.glob('calls/*/started.json')))!=m['prior_calls']:raise ValueError('Parent manifest/request count changed')
 if any(study.sha(p/key)!=digest for key,digest in m['prior_call_evidence'].items()):raise ValueError('Parent call evidence changed')
 if study.sha(__file__)!=m['url_entry_sha256']:raise ValueError('URL implementation changed')

class Client(study.Client):
 def call(self,key,prompt,images=(),purpose='evaluation'):
  folder=self.out/'calls'/key;done=folder/'response.json'
  if done.exists():return study.read(done)
  if (folder/'started.json').exists():return {'status':'interrupted_unknown','content':'','usage':None}
  self.boundary();verify_parent(self.manifest)
  if len(list(self.out.glob('calls/*/started.json')))>=self.manifest['max_requests']:raise study.Hold('combined190_paid_cap')
  while sum(p.name.isdigit() for p in Path('/proc').iterdir())>=100:self.boundary();time.sleep(5)
  content=[{'type':'text','text':prompt}];hosted=[]
  for item in images:
   self.boundary();record=upload_and_verify(item,self.out,self.env);hosted.append(record)
   content.append({'type':'image_url','image_url':{'url':record['url'],'detail':item['detail']}})
  payload={'model':self.manifest['model'],'messages':[{'role':'user','content':content}],'max_tokens':self.manifest['max_output_tokens'],'temperature':0,'stream':False,'thinking':self.manifest['thinking']};body=json.dumps(payload,ensure_ascii=False,separators=(',',':')).encode()
  save(folder/'request-manifest.json',{'purpose':purpose,'prompt':prompt,'images':images,'hosted_images':hosted,'model':payload['model'],'max_tokens':payload['max_tokens'],'thinking':payload['thinking'],'request_sha256':hashlib.sha256(body).hexdigest(),'request_bytes':len(body),'automatic_retries':0,'transport':'direct_exact_imgbb_urls','prior_local_requests':self.manifest['prior_calls'],'cumulative_max_requests':190})
  self.boundary();folder.mkdir(parents=True,exist_ok=True)
  with (folder/'started.json').open('x') as f:json.dump({'time':study.old.now(),'pid':os.getpid(),'purpose':purpose},f)
  study.live_status(self.out,'running');begin=time.monotonic();result={'status':'transport_error','content':'','usage':None,'purpose':purpose,'provider_api_seconds':None,'actual_cost_usd':None}
  before=signal.signal(signal.SIGALRM,lambda *_:(_ for _ in ()).throw(study.old.Deadline()));signal.alarm(self.manifest['max_request_wall_seconds'])
  try:
   with httpx.Client(trust_env=False,timeout=httpx.Timeout(connect=20,write=90,read=180,pool=20)) as client:
    response=client.post(self.env['TOKENHUB_BASE_URL'].rstrip('/')+'/chat/completions',content=body,headers={'Authorization':'Bearer '+self.env['TOKENHUB_API_KEY'],'Content-Type':'application/json'})
   result['http_status']=response.status_code;raw=response.json();safe=json.dumps(raw,ensure_ascii=False).replace(self.env['TOKENHUB_API_KEY'],'<redacted>');save(folder/'raw-response.json',json.loads(safe));result.update(usage=raw.get('usage'),returned_model=raw.get('model'))
   if response.status_code!=200:result.update(status='provider_error',error=raw.get('error'))
   else:
    choice=raw['choices'][0];message=choice['message'];result.update(status='completed',content=message.get('content') or '',finish_reason=choice.get('finish_reason'),reasoning_content_chars=len(message.get('reasoning_content') or ''),reasoning_tokens=(raw.get('usage') or {}).get('completion_tokens_details',{}).get('reasoning_tokens'))
    if raw.get('model') not in (None,'deepseek-v4-1-flash-261017',self.manifest['model']):result['status']='model_identity_mismatch'
  except Exception as exc:result['error_type']=type(exc).__name__
  finally:signal.alarm(0);signal.signal(signal.SIGALRM,before)
  result['client_http_seconds']=time.monotonic()-begin;save(done,result);study.live_status(self.out,'running');self.errors=self.errors+1 if result['status']!='completed' else 0
  print(json.dumps({'call':key,'status':result['status'],'http':result.get('http_status'),'finish':result.get('finish_reason'),'reasoning_tokens':result.get('reasoning_tokens'),'seconds':result['client_http_seconds'],'request_bytes':len(body)}),flush=True)
  if self.errors>=3 or result['status']=='model_identity_mismatch':raise study.Hold('infrastructure_or_model_identity_gate')
  return result

def main():
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,default=DEFAULT);p.add_argument('--prepare',action='store_true');p.add_argument('--upload-check',action='store_true');p.add_argument('--live',action='store_true');a=p.parse_args();root=a.output.resolve();root.mkdir(parents=True,exist_ok=True)
 with (root/'run.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  m=prepare(root) if a.prepare else study.read(root/'manifest.json');study.verify(root,m);verify_parent(m)
  if a.upload_check:
   env,_=environment(ROOT,'dsh');record=upload_and_verify(m['cases'][0]['tiled_representations']['canvas_1']['images'][0],root,env);print(json.dumps({k:v for k,v in record.items() if k!='url'}));return
  if a.live:
   if (root/'quality-hold.json').exists():raise ValueError('Explicit hold; no silent restart')
   with (Path(m['local_parent_root'])/'run.lock').open('a') as parent_lock:
    fcntl.flock(parent_lock,fcntl.LOCK_EX|fcntl.LOCK_NB);verify_parent(m)
    with patch.object(study,'Client',Client):study.run(root,m)
  else:print(json.dumps({'paid_calls':0,'new_cap':m['max_requests'],'prior_calls':m['prior_calls'],'combined_cap':190,'root':str(root)}))
if __name__=='__main__':main()
