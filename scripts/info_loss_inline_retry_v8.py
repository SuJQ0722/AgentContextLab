"""Full-content <=10-tile information loss, 16 condition slots, one-hour attempts.

Separate scientific transport version. No image hosting, process-count throttle,
score-based selection, or implicit omission of source pixels.
"""
import argparse,base64,concurrent.futures,copy,fcntl,hashlib,json,os,signal,time
from pathlib import Path
import httpx
from PIL import Image
import info_loss_phase4 as phase
from info_loss_eval import save
from info_loss_report import summarize_usage
from lab import ROOT,environment
from inline_route_contract_v2 import ROUTES
VERSION='info-loss-inline-retry5-v8'
DEFAULT=ROOT/'outputs/experiment6/inline-retry5-v8'
class Deadline(BaseException):pass

def tile_case(case,out):
    result={};proof=[]
    for method in ('canvas_1','canvas_0.75','canvas_0.5'):
        scale=float(method.split('_')[1]);items=[]
        for page,(base,item) in enumerate(zip(case['representations']['canvas_1']['images'],case['representations'][method]['images'])):
            if phase.sha(item['path'])!=item['sha256']:raise ValueError('Frozen canvas changed')
            with Image.open(item['path']) as opened:image=opened.convert('RGBA')
            rebuilt=Image.new('RGBA',image.size)
            for index,start in enumerate(range(0,base['height'],2048)):
                end=min(start+2048,base['height']);a=round(start*scale);b=image.height if end==base['height'] else round(end*scale)
                crop=image.crop((0,a,image.width,b));path=out/'tiles'/case['id']/method/f'p{page}_t{index}.png';path.parent.mkdir(parents=True,exist_ok=True);crop.save(path)
                rebuilt.paste(crop,(0,a));items.append({'path':str(path),'sha256':phase.sha(path),'media_type':'image/png','width':crop.width,'height':crop.height,'detail':'high','source_page':page,'box':[0,a,image.width,b],'source_sha256':item['sha256']})
            if rebuilt.tobytes()!=image.tobytes():raise ValueError('Incomplete source pixels')
            proof.append({'method':method,'page':page,'complete_pixels':True,'source_sha256':item['sha256']})
        if len(items)>10 or any(max(i['width'],i['height'])>2048 for i in items):raise ValueError('Complete evidence exceeds bounded ten-image protocol')
        result[method]={'images':items}
    if len({len(x['images']) for x in result.values()})!=1:raise ValueError('Unpaired scale tiling')
    return result,proof

def prepare(out,parent):
    parent=Path(parent).resolve();source=phase.read(parent/'manifest.json')
    if phase.sha(parent/'manifest.json')!=(parent/'manifest.sha256').read_text().strip():raise ValueError('Parent manifest changed')
    if (out/'manifest.json').exists():raise ValueError('Use --resume for frozen output')
    out.mkdir(parents=True,exist_ok=True);cases=[];proofs=[];reused=[]
    for original in source['cases']:
        case=copy.deepcopy(original);case['tiled_representations'],proof=tile_case(case,out);proofs.extend({'case':case['id'],**p} for p in proof)
        for field in ('source','renderer_input'):
            if phase.sha(case[field+'_path'])!=case[field+'_sha256']:raise ValueError('Source changed')
        for kind in ('facts','summaries'):
            old=parent/kind/(case['id']+'.json')
            if old.exists():
                value=phase.read(old)
                if kind=='facts' and (not value or len(phase.old.grounded_facts({'facts':value},Path(case['source_path']).read_text()))!=len(value)):continue
                if kind=='summaries' and not value.get('text'):continue
                target=out/kind/old.name;save(target,value);reused.append({'path':str(old),'sha256':phase.sha(old),'target':str(target),'target_sha256':phase.sha(target)})
        cases.append(case)
    m={'version':VERSION,'model':phase.old.MODEL,'parent_manifest':str(parent/'manifest.json'),'parent_manifest_sha256':phase.sha(parent/'manifest.json'),
       'cases':cases,'methods':list(phase.METHODS),'max_output_tokens':8192,'thinking':{'type':'disabled'},'concurrency':16,
       'attempt_timeout_seconds':3600,'max_timeout_retries':5,'max_attempts':6,'max_images':10,'max_requests':190*6*4,
       'request_cap_derivation':'190 original logical calls x 6 attempts x 4 gateway routes; all physical requests audited',
       'stage':'tiles_high','tiling':'2048px non-overlapping normalized cuts; full pixel reconstruction checked; separate protocol from older overlapping tiles',
       'proofs':proofs,'reused':reused,'implementation_sha256':{**phase.sources(),'scripts/info_loss_inline_retry_v8.py':phase.sha(__file__)},
       'limitations':['Fixed original 10 text-history cases; not MMBC generalization or avg3.','No answer-based gate or cohort removal.','Different tile protocol; previous image answers reusable only for identical request fingerprints.','All failed attempts charged; provider usage missing remains unknown.']}
    save(out/'manifest.json',m);(out/'manifest.sha256').write_text(phase.sha(out/'manifest.json')+'\n');return m

def verify(out,m):
    if m['version']!=VERSION or phase.sha(out/'manifest.json')!=(out/'manifest.sha256').read_text().strip():raise ValueError('Manifest changed')
    for p,h in m['implementation_sha256'].items():
        if phase.sha(ROOT/p)!=h:raise ValueError('Implementation changed')
    if phase.sha(m['parent_manifest'])!=m['parent_manifest_sha256']:raise ValueError('Source manifest changed')

def boundary(out):
    if (out/'STOP').exists():raise phase.Hold('dispatch_stopped')

class Client:
    def __init__(self,out,m,attempt):self.out=out;self.manifest=m;self.attempt=attempt;self.env,_=environment(ROOT,'dsh')
    def call(self,key,prompt,images=(),purpose='evaluation'):
        boundary(self.out)
        if len(images)>10:raise ValueError('Never truncate information-loss evidence')
        content=[{'type':'text','text':prompt}]
        for item in images:
            data=Path(item['path']).read_bytes()
            if hashlib.sha256(data).hexdigest()!=item['sha256']:raise ValueError('Frozen image changed')
            content.append({'type':'image_url','image_url':{'url':f"data:{item['media_type']};base64,"+base64.b64encode(data).decode(),'detail':item['detail']}})
        payload={'model':self.manifest['model'],'messages':[{'role':'user','content':content}],'max_tokens':8192,'temperature':0,'stream':False,'thinking':self.manifest['thinking']}
        fingerprint=hashlib.sha256(json.dumps(payload,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
        cache=self.out/'completed-calls'/fingerprint
        if cache.exists():return phase.read(cache)
        for folder in (Path(self.manifest['parent_manifest']).parent/'calls').glob('*'):
            if (folder/'response.json').exists() and (folder/'request-manifest.json').exists():
                old=phase.read(folder/'request-manifest.json');r=phase.read(folder/'response.json')
                if old.get('request_sha256')==fingerprint and r.get('status')=='completed':
                    save(cache,{**r,'reused_source':str(folder/'response.json'),'new_request':False});return phase.read(cache)
        request_number=0
        while True:
            boundary(self.out);route=ROUTES[request_number%4];request_number+=1
            sent={**payload,'model':route}
            if len(json.dumps(sent,ensure_ascii=False,separators=(',',':')).encode())>32*1024*1024:raise phase.Hold('inline_body_exceeds_32MiB_no_request_sent')
            folder=self.attempt/'calls'/f'{key}_{request_number:03d}'
            folder.mkdir(parents=True,exist_ok=True)
            with (self.out/'request-counter.lock').open('a') as lock:
                fcntl.flock(lock,fcntl.LOCK_EX)
                counter=self.out/'request-counter.json';n=phase.read(counter)['count'] if counter.exists() else 0
                if n>=self.manifest['max_requests']:raise phase.Hold('audited_request_cap')
                save(counter,{'count':n+1});save(folder/'started.json',{'at':time.time(),'request_number':n+1,'route':route,'purpose':purpose,'image_count':len(images),'request_fingerprint':fingerprint,'hosting_calls':0})
            begin=time.monotonic();r={'status':'transport_error','content':'','usage':None,'purpose':purpose,'provider_api_seconds':None}
            try:
                proxy=self.env.get('HTTPS_PROXY') or self.env.get('https_proxy') or self.env.get('http_proxy')
                if not proxy:raise ValueError('Explicit proxy required')
                with httpx.Client(proxy=proxy,trust_env=False,timeout=httpx.Timeout(connect=20,write=90,read=300,pool=20)) as client:
                    response=client.post(self.env['TOKENHUB_BASE_URL'].rstrip('/')+'/chat/completions',json=sent,headers={'Authorization':'Bearer '+self.env['TOKENHUB_API_KEY']})
                raw=response.json();r.update(http_status=response.status_code,usage=raw.get('usage'),returned_model=raw.get('model'))
                save(folder/'raw-response.json',json.loads(json.dumps(raw).replace(self.env['TOKENHUB_API_KEY'],'<redacted>')))
                if response.status_code==200:
                    choice=raw['choices'][0];message=choice['message'];r.update(status='completed',content=message.get('content') or '',finish_reason=choice.get('finish_reason'))
                    if raw.get('model') not in (None,'deepseek-v4-1-flash-261017',self.manifest['model'],*ROUTES):r['status']='model_identity_mismatch'
                else:r['status']='provider_error'
            except (httpx.HTTPError,ValueError,KeyError,IndexError) as exc:r['error_type']=type(exc).__name__
            finally:
                r['client_http_seconds']=time.monotonic()-begin;save(folder/'response.json',r)
            if r['status']=='completed':save(cache,r);return r
            if r['status']=='model_identity_mismatch' or r.get('http_status')==401:return r
            status=r.get('http_status')
            if status is not None and status<500 and status not in (400,403,404,408,429,200):return r
            if request_number%4==0:time.sleep(60)

def run_condition(args):
    out,case_id,method=args;out=Path(out);m=phase.read(out/'manifest.json');case=next(c for c in m['cases'] if c['id']==case_id)
    task=out/'conditions'/case_id/method;task.mkdir(parents=True,exist_ok=True)
    with (task/'run.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if (task/'result.json').exists():return phase.read(task/'result.json')
        for number in range(1,7):
            attempt=task/'attempts'/f'attempt_{number:03d}';result=attempt/'result.json'
            if result.exists():
                r=phase.read(result)
                if r['status']!='timeout':save(task/'result.json',r);return r
                continue
            boundary(out)
            if attempt.exists():raise phase.Hold('unknown_prior_attempt_requires_audit')
            attempt.mkdir(parents=True);save(attempt/'started.json',{'at':time.time(),'pid':os.getpid(),'attempt':number});start=time.monotonic()
            previous=signal.signal(signal.SIGALRM,lambda *_:(_ for _ in ()).throw(Deadline()));signal.alarm(3600)
            try:
                client=Client(out,m,attempt)
                with (out/('prepare-'+case_id+'.lock')).open('a') as prep_lock:
                    fcntl.flock(prep_lock,fcntl.LOCK_EX);facts,base=phase.prepare_case(client,case)
                if not facts:raise phase.Hold('grounded_facts_unavailable')
                value=phase.condition(client,case,base,facts,'tiles_high',method);r={'status':'completed' if value['qa_status']=='completed' and value['reconstruction_status']=='completed' else 'failed','row':value}
            except Deadline:r={'status':'timeout','row':None}
            except phase.Hold as exc:r={'status':'blocked','reason':str(exc),'row':None}
            except Exception as exc:r={'status':'failed','error_type':type(exc).__name__,'row':None}
            finally:signal.alarm(0);signal.signal(signal.SIGALRM,previous)
            r.update(attempt=number,end_to_end_seconds=time.monotonic()-start,case=case_id,method=method);save(result,r)
            if r['status']!='timeout':save(task/'result.json',r);return r
        save(task/'result.json',r);return r

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,default=DEFAULT);p.add_argument('--parent',type=Path,default=phase.DEFAULT);p.add_argument('--prepare',action='store_true');p.add_argument('--resume',action='store_true');p.add_argument('--live',action='store_true');a=p.parse_args();out=a.output.resolve();out.mkdir(parents=True,exist_ok=True)
    with (out/'run.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);m=prepare(out,a.parent) if a.prepare else phase.read(out/'manifest.json');verify(out,m)
        if not a.live:print(json.dumps({'paid_calls':0,'cases':len(m['cases']),'max_images':max(len(r['images']) for c in m['cases'] for r in c['tiled_representations'].values()),'concurrency':16,'max_timeout_retries':5}));return
        rows=[]
        with concurrent.futures.ProcessPoolExecutor(max_workers=16) as pool:
            futures=[pool.submit(run_condition,(str(out),c['id'],method)) for c in m['cases'] for method in m['methods']]
            for future in concurrent.futures.as_completed(futures):
                r=future.result();rows.append(r);save(out/'condition-results.json',rows)
                responses=list(out.glob('conditions/*/*/attempts/*/calls/*/response.json'));starts=list(out.glob('conditions/*/*/attempts/*/calls/*/started.json'))
                save(out/'usage-summary.json',summarize_usage([phase.read(p) for p in responses],len(starts)))
                save(out/'live-status.json',{'at':time.time(),'conditions_finished':len(rows),'conditions_total':len(futures),'statuses':{s:sum(r['status']==s for r in rows) for s in ('completed','timeout','blocked','failed')},'calls_started':len(starts),'calls_returned':len(responses)})

if __name__=='__main__':main()
