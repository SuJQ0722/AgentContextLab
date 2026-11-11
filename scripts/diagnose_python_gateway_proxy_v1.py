"""One explicitly authorized 64KiB inline upload diagnostic, never auto-replayed."""
import argparse,base64,fcntl,hashlib,json,signal,threading,time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
import httpx
from lab import ROOT,environment
from bounded_visual_reading_gate_v1 import save

OUT=ROOT/'outputs/preflight/python-gateway-proxy-v1'
SOURCE=ROOT/'outputs/preflight/visual-transport-engineering-v2/live-diagnostic'
MODEL='deepseek-v4.1-flash-1017/huoshan/huoshan'

class ChunkedBytes(httpx.SyncByteStream):
    def __init__(self,raw,chunk_size=65536):self.raw=raw;self.chunk_size=chunk_size;self.chunks_yielded=0;self.bytes_yielded=0
    def __iter__(self):
        for start in range(0,len(self.raw),self.chunk_size):
            part=self.raw[start:start+self.chunk_size];self.chunks_yielded+=1;self.bytes_yielded+=len(part);yield part
    def close(self):pass

def make_request(url,wire,headers=None):
    req=httpx.Request('POST',url,headers={'content-type':'application/json',**(headers or {})},content=wire)
    stream=ChunkedBytes(wire);req.stream=stream
    assert req.content==wire and req.headers['content-length']==str(len(wire))
    assert 'transfer-encoding'not in req.headers
    return req,stream

def prepare(out):
    from openai import OpenAI
    import recent_ten_images_transport_v1 as retention
    payload=json.loads((SOURCE/'requests/ten_page_reading.json').read_text())
    assert payload['model']==MODEL
    registry=set()
    for message in payload['messages']:
        for part in message['content']if isinstance(message['content'],list)else []:
            if part.get('type')=='image_url':registry.add(hashlib.sha256(base64.b64decode(part['image_url']['url'].split(',',1)[1],validate=True)).hexdigest())
    captured=[]
    def fixture(req):
        wire,row=retention.transform(req.content,rendered_registry=registry);captured.append((wire,row))
        return httpx.Response(200,headers={'content-type':'text/event-stream'},content=b'data: [DONE]\n\n')
    thinking=payload.pop('thinking')
    with OpenAI(api_key='offline-fixture',base_url='http://offline.invalid/v1',max_retries=0,http_client=httpx.Client(transport=httpx.MockTransport(fixture)))as client:
        with client.chat.completions.create(**payload,extra_body={'thinking':thinking})as stream:
            list(stream)
    assert len(captured)==1
    wire,selection=captured[0]
    prior=json.loads((SOURCE/'calls/ten_page_reading/wire.jsonl').read_text().splitlines()[0])
    assert selection['retained_image_count']==10
    assert len(wire)==prior['final_body_bytes']==5280272
    assert hashlib.sha256(wire).hexdigest()==prior['final_body_sha256']
    out.mkdir(parents=True,exist_ok=True)
    p=out/'wire.json'
    if p.exists():assert p.read_bytes()==wire
    else:p.write_bytes(wire);p.chmod(0o600)
    save(out/'prepared.json',{'bytes':len(wire),'sha256':hashlib.sha256(wire).hexdigest(),
        'same_bytes_as_prior_ten_page_attempt':True,'image_count':10,'model':MODEL,'selection':selection,
        'model_calls':0,'chunk_bytes':65536,'content_length_preserved':True,'transfer_encoding_chunked':False})
    return wire

def local_check(out,wire):
    observed={}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            raw=self.rfile.read(int(self.headers['content-length']))
            observed.update(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest(),content_length=self.headers['content-length'],transfer_encoding=self.headers.get('transfer-encoding'))
            self.send_response(200);self.send_header('content-length','2');self.end_headers();self.wfile.write(b'OK')
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        req,stream=make_request(f'http://127.0.0.1:{server.server_port}/fixture',wire)
        with httpx.Client(trust_env=False,timeout=15)as client:response=client.send(req)
        assert response.status_code==200 and observed['sha256']==hashlib.sha256(wire).hexdigest() and observed['bytes']==len(wire)
        assert observed['transfer_encoding']is None and req.content==wire
        observed.update(passed=True,chunks_yielded=stream.chunks_yielded,model_calls=0)
        save(out/'local-http.json',observed)
    finally:server.shutdown();server.server_close();thread.join()

def live(out,wire):
    import visual_transport_runtime_v3 as runtime
    env,_=environment(ROOT,'hermes');proxy=env.get('https_proxy')or env.get('HTTPS_PROXY');assert proxy;endpoint=env['TOKENHUB_BASE_URL'].rstrip('/')+'/chat/completions'
    with (out/'run.lock').open('a')as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if (out/'started.json').exists():raise RuntimeError('Already attempted; no automatic replay')
        result={'status':'failed','usage':None,'raw_provider_usage':None,'provider_api_seconds':None,'actual_usd':None,
                'maximum_model_attempts':1,'automatic_retries':0,'network_path':'explicit_configured_https_proxy','body_sha256':hashlib.sha256(wire).hexdigest(),'body_bytes':len(wire)}
        save(out/'started.json',{'at_unix':time.time(),'max_model_attempts':1,'max_process_seconds':300,'model':MODEL})
        req,stream=make_request(endpoint,wire,{'authorization':'Bearer '+env['TOKENHUB_API_KEY']})
        previous=signal.getsignal(signal.SIGALRM)
        def alarm(signum,frame):raise TimeoutError('Diagnostic process wall budget')
        signal.signal(signal.SIGALRM,alarm);signal.alarm(300)
        started=time.monotonic();handle=None;rawresponse=out/'response.bin';content='';finishes=[];events=0;rawusage=None
        try:
            with patch.object(runtime,'MAX_RATE_LIMIT_ATTEMPTS',1):
                handle=runtime.install({**runtime.DEFAULT_POLICY,'max_failed_sends':1},out,approved_base_url=env['TOKENHUB_BASE_URL'])
                with httpx.Client(proxy=proxy,trust_env=False,follow_redirects=False)as client:
                    response=client.send(req,stream=True);result['status_code']=response.status_code
                    rawresponse.touch(mode=0o600,exist_ok=False)
                    with rawresponse.open('wb')as output:
                        for chunk in response.iter_bytes():output.write(chunk);output.flush()
                    response.close()
                raw=rawresponse.read_bytes()
                if result['status_code']>=400:
                    try:
                        error=json.loads(raw);save(out/'provider-error.json',error)
                        result['provider_error_code']=error.get('error',error).get('code')
                    except (ValueError,AttributeError):pass
                    result['error_type']='HTTP'+str(result['status_code'])
                else:
                    for line in raw.splitlines():
                        if not line.startswith(b'data: ')or line==b'data: [DONE]':continue
                        event=json.loads(line[6:]);events+=1
                        if event.get('usage')is not None:rawusage=event['usage']
                        for choice in event.get('choices',[]):
                            content+=choice.get('delta',{}).get('content')or''
                            if choice.get('finish_reason'):finishes.append(choice['finish_reason'])
                    save(out/'response.json',{'content':content,'finish_reasons':finishes,'raw_provider_usage':rawusage,'sse_events':events})
                    result.update(status='completed'if content and'stop'in finishes else'incomplete',usage=rawusage,raw_provider_usage=rawusage,finish_reasons=finishes)
                    expected=json.loads((SOURCE/'manifest.json').read_text())['expected_fields']
                    try:
                        parsed=json.loads(content.strip().removeprefix('```json').removesuffix('```'))
                        result['reading_matches']={k:str(parsed.get(k,'')).lower()==str(v).lower()for k,v in expected.items()}
                    except ValueError:result['reading_matches']=None
        except (Exception,SystemExit)as exc:
            result['error_type']=type(exc).__name__
        finally:
            signal.alarm(0);signal.signal(signal.SIGALRM,previous)
            if handle:handle['uninstall']()
            result.update(client_wall_seconds=time.monotonic()-started,chunks_yielded=stream.chunks_yielded,bytes_yielded=stream.bytes_yielded,
                          yielded_bytes_are_not_confirmed_network_bytes=True,request_content_unchanged=req.content==wire)
            path=out/'transport-phases-v3.jsonl'
            rows=[json.loads(x)for x in path.read_text().splitlines()]if path.exists()else[]
            result['actual_model_http_attempts']=sum(x.get('event')=='request_started'for x in rows)
            result['request_body_send_complete']=any(x.get('phase')=='http11.send_request_body.complete'for x in rows)
            result['request_body_phase_seconds']=[x.get('phase_seconds')for x in rows if x.get('phase')in('http11.send_request_body.complete','http11.send_request_body.failed')]
            save(out/'result.json',result)
        print(json.dumps(result,ensure_ascii=False),flush=True)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--live',action='store_true');args=p.parse_args()
    prior=ROOT/'outputs/preflight/inline-chunked-transport-v1'
    wire=(prior/'wire.json').read_bytes();old=json.loads((prior/'result.json').read_text())
    assert hashlib.sha256(wire).hexdigest()==old['body_sha256'] and len(wire)==5280272
    OUT.mkdir(parents=True,exist_ok=True)
    save(OUT/'comparison.json',{'prior_result':str(prior/'result.json'),'same_body_sha256':old['body_sha256'],
         'prior_direct_body_send_seconds':old['request_body_phase_seconds'],'prior_direct_wall_seconds':old['client_wall_seconds'],
         'single_new_attempt':True,'same_route':MODEL})
    if args.live:live(OUT,wire)
    else:print(json.dumps({'prepared':True,'model_calls':0}))
if __name__=='__main__':main()
