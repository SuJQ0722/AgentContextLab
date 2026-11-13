"""Resume exact information-loss requests, cumulative <=3 physical sends.

Independent output; original scientific functions and records remain unchanged.
Run through network_entry_v13.py for the approved operational proxy. Dry default.
"""
import argparse,base64,collections,fcntl,hashlib,json,os,time
from pathlib import Path
import httpx
import info_loss_phase4 as phase
from info_loss_inline_retry_v8 import ROUTES
from lab import ROOT,environment
PARENT=ROOT/'outputs/experiment6/model-alias-v10'
DEFAULT=ROOT/'outputs/experiment6/request-quota-recovery-v13'
def read(p):return json.loads(Path(p).read_text())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,value):
 p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2));tmp.replace(p)
class Client:
 def __init__(self,out,manifest,index,live):
  self.out=out;self.manifest=manifest;self.index=index;self.live=live;self.observed=[];self.sent=0;self.env,_=environment(ROOT,'dsh');self.cache={}
 def call(self,key,prompt,images=(),purpose='evaluation'):
  if(self.out/'STOP').exists():raise RuntimeError('Stopped before next request')
  content=[{'type':'text','text':prompt}]
  for item in images:
   p=Path(item['path']);data=p.read_bytes()
   if hashlib.sha256(data).hexdigest()!=item['sha256']:raise ValueError('Frozen image changed')
   content.append({'type':'image_url','image_url':{'url':f"data:{item['media_type']};base64,"+base64.b64encode(data).decode(),'detail':item['detail']}})
  payload={'model':self.manifest['model'],'messages':[{'role':'user','content':content}],'max_tokens':8192,'temperature':0,'stream':False,'thinking':self.manifest['thinking']}
  fingerprint=hashlib.sha256(json.dumps(payload,ensure_ascii=False,separators=(',',':')).encode()).hexdigest();old=self.index.get(fingerprint,{'physical_starts':0,'evidence':[]})
  history_cache=PARENT/'completed-calls'/fingerprint
  if fingerprint in self.cache:return self.cache[fingerprint]
  sources=[]
  if history_cache.exists():sources.append(history_cache)
  for e in old['evidence']:
   if e['status']=='completed' and e['response']:sources.append(Path(e['response']))
  local=self.out/'requests'/fingerprint
  for p in sorted(local.glob('attempt_*/response.json')):
   if read(p).get('status')=='completed':sources.append(p)
  for p in sources:
   response=read(p)
   if response.get('status')=='completed':
    self.cache[fingerprint]=response;self.observed.append({'key':key,'fingerprint':fingerprint,'status':'reused_success','source':str(p),'source_sha256':sha(p),'finish':response.get('finish_reason')});return response
  starts=list(local.glob('attempt_*/started.json'));count=old['physical_starts']+len(starts)
  unknown=any(e['response'] is None for e in old['evidence']) or any(not(p.parent/'response.json').exists() for p in starts)
  blocked='unknown_acceptance' if unknown else 'cumulative_three_request_cap' if count>=3 else None
  record={'key':key,'fingerprint':fingerprint,'purpose':purpose,'prior_physical_starts':count,'remaining':max(0,3-count),'status':blocked or 'eligible_new_request'};self.observed.append(record)
  if blocked or not self.live:return {'status':blocked or 'dry_pending','content':''}
  data=json.dumps(payload,ensure_ascii=False,separators=(',',':')).encode()
  if len(images)>10 or len(data)>32*1024*1024:raise ValueError('Frozen image/body ceiling exceeded')
  folder=local/f'attempt_{count+1:03d}';folder.mkdir(parents=True,exist_ok=False)
  route=ROUTES[count%len(ROUTES)];sent={**payload,'model':route};save(folder/'started.json',{'at':time.time(),'request_fingerprint':fingerprint,'key':key,'purpose':purpose,'cumulative_attempt':count+1,'prior_physical_starts':count,'route':route,'image_count':len(images),'request_sha256':hashlib.sha256(json.dumps(sent,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()});self.sent+=1
  started=time.monotonic();r={'status':'transport_error','content':'','usage':None,'purpose':purpose,'provider_api_seconds':None}
  try:
   proxy=self.env.get('HTTPS_PROXY') or self.env.get('https_proxy');assert proxy
   with httpx.Client(proxy=proxy,trust_env=False,timeout=httpx.Timeout(connect=20,write=90,read=300,pool=20)) as client:
    response=client.post(self.env['TOKENHUB_BASE_URL'].rstrip('/')+'/chat/completions',json=sent,headers={'Authorization':'Bearer '+self.env['TOKENHUB_API_KEY']})
   value=response.json();save(folder/'raw-response.json',value);r.update(http_status=response.status_code,usage=value.get('usage'),returned_model=value.get('model'))
   if response.status_code==200:
    ch=value['choices'][0];r.update(status='completed',content=ch['message'].get('content') or '',finish_reason=ch.get('finish_reason'))
    if value.get('model') not in (None,'deepseek-v4.1-flash-1017','deepseek-v4-1-flash-261017',self.manifest['model'],*ROUTES):r['status']='model_identity_mismatch'
   else:r['status']='provider_error'
  except (httpx.HTTPError,ValueError,KeyError,IndexError) as exc:r['error_type']=type(exc).__name__
  finally:
   r['client_http_seconds']=time.monotonic()-started;save(folder/'response.json',r);save(self.out/'live-status.json',{'at':time.time(),'calls_started_this_process':self.sent,'last_key':key,'last_status':r['status'],'usage_known':r.get('usage') is not None})
  if r['status']=='completed':self.cache[fingerprint]=r
  return r

def main():
 p=argparse.ArgumentParser();p.add_argument('--out',type=Path,default=DEFAULT);p.add_argument('--audit',type=Path,default=ROOT/'outputs/recovery-controlled-info-v13/audit.json');p.add_argument('--live',action='store_true');a=p.parse_args();out=a.out.resolve();out.mkdir(parents=True,exist_ok=True)
 if out==PARENT:raise ValueError('Independent namespace required')
 lease=(out/'run.lock').open('a');fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
 manifest=read(PARENT/'manifest.json');audit=read(a.audit);index={x['fingerprint']:x for x in audit['information_loss_requests']};client=Client(out,manifest,index,a.live)
 binding={'version':'info-loss-request-quota-recovery-v13','parent':str(PARENT),'parent_manifest_sha256':sha(PARENT/'manifest.json'),'audit_sha256':sha(a.audit),'cumulative_physical_request_limit':3,'concurrency':1,'http_retry':0,'unknown_acceptance_retry':False,'unchanged_scientific_prompts_images_and_output_budget':True,'old_completed_condition_not_rerun':True}
 if(out/'manifest.json').exists() and read(out/'manifest.json')!=binding:raise ValueError('Resume binding changed')
 save(out/'manifest.json',binding);rows=[]
 for case in manifest['cases']:
  cid=case['id'];facts=read(PARENT/'facts'/f'{cid}.json');base={'text_control':{'text':Path(case['source_path']).read_text()},'summary':read(PARENT/'summaries'/f'{cid}.json')}
  if sha(case['source_path'])!=case['source_sha256']:raise ValueError('Original text changed')
  for method in manifest['methods']:
   prior=PARENT/'conditions'/cid/method/'result.json';r=read(prior) if prior.exists() else {}
   if r.get('status')=='completed':rows.append({'case':cid,'method':method,'status':'reused_completed_condition','source':str(prior),'source_sha256':sha(prior),'row':r.get('row')});continue
   row=phase.condition(client,case,base,facts,'tiles_high',method);rows.append({'case':cid,'method':method,'status':'observed','row':row});save(out/'condition-results.json',rows);save(out/'request-disposition.json',client.observed)
 save(out/'condition-results.json',rows);save(out/'request-disposition.json',client.observed)
 counts=dict(collections.Counter(x['status'] for x in client.observed));save(out/'status.json',{'at':time.time(),'live':a.live,'conditions':len(rows),'request_dispositions':counts,'new_calls':client.sent,'finished':True});print(json.dumps({'live':a.live,'conditions':len(rows),'dispositions':counts,'new_calls':client.sent}))
if __name__=='__main__':main()
