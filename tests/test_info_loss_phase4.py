import base64,io,json,signal,sys,tempfile,threading,unittest
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import info_loss_phase4 as s

class Phase4Tests(unittest.TestCase):
 def setUp(self):
  # Local HTTP tests are independent of production host-load throttling.
  original=Path.iterdir
  patcher=patch.object(Path,'iterdir',lambda path:iter(()) if str(path)=='/proc' else original(path))
  patcher.start();self.addCleanup(patcher.stop)
 def image_case(self,root):
  reps={}
  for scale in [1,.75,.5]:
   image=Image.new('RGB',(round(40*scale),round(3100*scale)));pixels=image.load()
   for y in range(image.height):
    for x in range(image.width):pixels[x,y]=(x%256,y%256,(x+y)%256)
   p=root/f'{scale}.png';image.save(p);reps['canvas_'+str(scale)]={'images':[{'path':str(p),'sha256':s.sha(p),'width':image.width,'height':image.height,'media_type':'image/png','detail':'low'}]}
  return {'id':'q1','representations':reps}
 def test_tiling_same_boundaries_all_pixels_and_scales(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);case=self.image_case(root);reps,proof=s.tiled(case,root/'out')
   self.assertTrue(all(p['pixel_reconstruction_identical'] for p in proof));self.assertEqual({len(r['images']) for r in reps.values()},{3})
   for method,rep in reps.items():
    source=case['representations'][method]['images'][0]
    with Image.open(source['path']) as image:
     rebuilt=Image.new('RGBA',image.size)
     for tile in rep['images']:
      self.assertEqual(tile['detail'],'high')
      with Image.open(tile['path']) as crop:rebuilt.paste(crop,(tile['box'][0],tile['box'][1]))
     self.assertEqual(rebuilt.tobytes(),image.convert('RGBA').tobytes())
 def test_null_valid_but_refusal_cannot_pass_readability_gate(self):
  facts=[{'id':'f1','answer':'71','question':'How many passengers?'}]
  class Fake:
   def __init__(self,out):self.out=out
   def call(self,*args):return {'status':'completed','finish_reason':'stop','content':'{"f1":null}'}
  with tempfile.TemporaryDirectory() as d:
   out=Path(d);case={'id':'q1','representations':{m:{'images':[]} for m in s.METHODS if m.startswith('canvas')}};base={'text_control':{'text':'71'},'summary':{'text':'71'}}
   result=s.gate(Fake(out),case,base,facts,'original');self.assertFalse(result['passed']);self.assertTrue(all(r['valid_final_json'] for r in result['rows']))
  self.assertIsNone(s.qa_parse({'status':'completed','finish_reason':'length','content':'{"f1":"71"}'},facts))
  self.assertIsNone(s.qa_parse({'status':'completed','finish_reason':'stop','content':'{"f1":{"answer":"71"}}'},facts))
 def test_low_scale_null_does_not_select_easier_case_or_require_accuracy(self):
  facts=[{'id':'f1','answer':'71','question':'How many passengers?'}]
  class Fake:
   def __init__(self,out):self.out=out;self.calls=[]
   def call(self,key,prompt,*args):
    self.calls.append((key,prompt));answer=None if 'canvas_0.' in key else '71'
    return {'status':'completed','finish_reason':'stop','content':json.dumps({'f1':answer})}
  with tempfile.TemporaryDirectory() as d:
   client=Fake(Path(d));case={'id':'q1','representations':{m:{'images':[]} for m in s.METHODS if m.startswith('canvas')}};base={'text_control':{'text':'original'},'summary':{'text':'summary'}}
   facts[0]['question']='How many passengers?';result=s.gate(client,case,base,facts,'original');self.assertTrue(result['passed']);self.assertEqual(len(client.calls),5)
   self.assertTrue(all('71' not in prompt for key,prompt in client.calls))
 def test_real_local_http_disabled_thinking_exact_images_and_resume_no_second_request(self):
  requests=[]
  class Handler(BaseHTTPRequestHandler):
   def log_message(self,*args):pass
   def do_POST(self):
    body=self.rfile.read(int(self.headers['Content-Length']));data=json.loads(body);requests.append(data)
    raw={'model':s.old.MODEL,'choices':[{'message':{'content':'{"f1":"71"}'},'finish_reason':'stop'}],'usage':{'prompt_tokens':20,'completion_tokens':4,'total_tokens':24}}
    encoded=json.dumps(raw).encode();self.send_response(200);self.send_header('Content-Length',str(len(encoded)));self.end_headers();self.wfile.write(encoded)
  server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  try:
   with tempfile.TemporaryDirectory() as d:
    root=Path(d);case=self.image_case(root);item=case['representations']['canvas_1']['images'][0];m={'model':s.old.MODEL,'max_requests':1,'max_output_tokens':8192,'max_request_wall_seconds':30,'thinking':{'type':'disabled'}}
    env={'TOKENHUB_BASE_URL':f'http://127.0.0.1:{server.server_port}/v1','TOKENHUB_API_KEY':'localfixture','https_proxy':f'http://127.0.0.1:{server.server_port}'}
    # The local HTTP server accepts absolute-form proxy requests. No external endpoint.
    with patch.object(s,'environment',return_value=(env,{})):
     client=s.Client(root,m);result=client.call('fixture','Question?', [item]);again=client.call('fixture','Question?', [item])
     self.assertEqual(result,again);self.assertEqual(len(requests),1);self.assertEqual(requests[0]['thinking'],{'type':'disabled'});self.assertEqual(requests[0]['max_tokens'],8192)
     img=requests[0]['messages'][0]['content'][1]['image_url'];self.assertEqual(img['detail'],'low');self.assertEqual(base64.b64decode(img['url'].split(',')[1]),Path(item['path']).read_bytes())
     usage=json.loads((root/'usage-summary.json').read_text());self.assertIsNone(usage['full_cached_input_tokens']);self.assertEqual(usage['cached_unknown'],1)
     with self.assertRaises(s.Hold):client.call('overcap','Question?')
  finally:server.shutdown();server.server_close()
 def test_stop_and_unknown_never_send_or_rewrite_original_response(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);env={'TOKENHUB_BASE_URL':'http://invalid','TOKENHUB_API_KEY':'fixture'}
   with patch.object(s,'environment',return_value=(env,{})),patch.object(s.httpx,'Client',side_effect=AssertionError('must not send')):
    client=s.Client(root,{'max_requests':190});(root/'STOP').touch()
    with self.assertRaises(s.Hold):client.call('new','q')
    self.assertFalse((root/'calls/new/started.json').exists());(root/'STOP').unlink()
    s.save(root/'calls/unknown/started.json',{'pid':999});r=client.call('unknown','q');self.assertEqual(r['status'],'interrupted_unknown');self.assertFalse((root/'calls/unknown/response.json').exists())
if __name__=='__main__':unittest.main()
