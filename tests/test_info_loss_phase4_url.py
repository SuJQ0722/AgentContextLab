import io,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import info_loss_phase4_url as url
class URLTests(unittest.TestCase):
 def test_remote_reencode_or_pixel_change_rejected(self):
  # PNG metadata change is pixel-identical but still disallowed by byte-exact contract.
  im=Image.new('RGB',(8,8),'red');a=io.BytesIO();b=io.BytesIO();im.save(a,format='PNG');im.save(b,format='PNG',compress_level=0)
  self.assertEqual(url.pixel_sha(a.getvalue()),url.pixel_sha(b.getvalue()));self.assertNotEqual(url.hashlib.sha256(a.getvalue()).hexdigest(),url.hashlib.sha256(b.getvalue()).hexdigest())
 def test_upload_function_rejects_remote_byte_mutation_before_model(self):
  from types import ModuleType
  fake=ModuleType('tools.image_search_tool');fake._upload_imgbb=lambda p:'https://i.ibb.co/fixture/image.png'
  class HTTP:
   def __init__(self,**kw):pass
   def __enter__(self):return self
   def __exit__(self,*a):pass
   def get(self,u):return type('Response',(),{'content':remote,'raise_for_status':lambda self:None})()
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);p=root/'source.png';im=Image.new('RGB',(8,8),'red');im.save(p);buf=io.BytesIO();im.save(buf,format='PNG',compress_level=0);remote=buf.getvalue()
   item={'path':str(p),'sha256':url.study.sha(p)}
   with patch.dict(sys.modules,{'tools.image_search_tool':fake}),patch.object(url,'configure_image_upload'),patch.object(url.httpx,'Client',HTTP):
    with self.assertRaises(ValueError):url.upload_and_verify(item,root,{'IMAGE_UPLOAD_API_KEY':'fixture'})
   self.assertFalse(list(root.glob('hosted/*.json')))
 def test_url_payload_preserves_text_and_detail_and_cap_includes_old_calls(self):
  sent=[]
  class HTTP:
   def __init__(self,**kw):self.options=kw
   def __enter__(self):return self
   def __exit__(self,*a):pass
   def post(self,endpoint,**kw):
    d=json.loads(kw['content']);sent.append(d)
    return type('Response',(),{'status_code':200,'json':lambda self:{'model':url.study.old.MODEL,'usage':{'prompt_tokens':100,'completion_tokens':2,'total_tokens':102},'choices':[{'message':{'content':'{"f1":"71"}'},'finish_reason':'stop'}]}})()
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);m={'model':url.study.old.MODEL,'max_requests':1,'max_output_tokens':8192,'max_request_wall_seconds':30,'thinking':{'type':'disabled'},'prior_calls':189}
   with patch.object(url.study,'environment',return_value=({'TOKENHUB_BASE_URL':'http://fixture','TOKENHUB_API_KEY':'fixture'},{})),patch.object(url,'verify_parent'),patch.object(url,'upload_and_verify',return_value={'url':'https://i.ibb.co/fixture/image.png','byte_identical':True,'pixel_identical':True}),patch.object(url.httpx,'Client',HTTP):
    client=url.Client(root,m);image={'sha256':'abc','path':'unused','detail':'high'};r=client.call('one','same prompt',[image]);self.assertEqual(r['status'],'completed')
    self.assertEqual(sent[0]['messages'][0]['content'],[{'type':'text','text':'same prompt'},{'type':'image_url','image_url':{'url':'https://i.ibb.co/fixture/image.png','detail':'high'}}]);self.assertEqual(sent[0]['thinking'],{'type':'disabled'})
    self.assertEqual(client.call('one','same prompt',[image]),r);self.assertEqual(len(sent),1)
    with self.assertRaises(url.study.Hold):client.call('two','never sent')
    self.assertEqual(len(sent),1)
if __name__=='__main__':unittest.main()
