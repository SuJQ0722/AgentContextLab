import hashlib,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import info_loss_inline_retry_v8 as worker

class InfoLossInlineTests(unittest.TestCase):
 def test_tiling_preserves_all_pixels_scales_and_bounded_ten(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);case={'id':'fixture','representations':{}}
   for method,scale in [('canvas_1',1),('canvas_0.75',.75),('canvas_0.5',.5)]:
    images=[]
    for i,h in enumerate([6126,4526,6358]):
     p=root/f'{method}-{i}.png';im=Image.new('RGBA',(round(40*scale),round(h*scale)),(i*30,70,90,255));im.save(p)
     images.append({'path':str(p),'sha256':worker.phase.sha(p),'width':im.width,'height':im.height,'detail':'high'})
    case['representations'][method]={'images':images}
   reps,proof=worker.tile_case(case,root/'out')
   self.assertTrue(all(x['complete_pixels'] for x in proof))
   self.assertEqual({len(x['images']) for x in reps.values()},{10})
   self.assertLessEqual(max(i['height'] for r in reps.values() for i in r['images']),2048)
 def test_tiling_rejects_over_ten_instead_of_omitting(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);case={'id':'large','representations':{}}
   for method,scale in [('canvas_1',1),('canvas_0.75',.75),('canvas_0.5',.5)]:
    p=root/(method+'.png');Image.new('RGB',(20,round(23000*scale))).save(p)
    case['representations'][method]={'images':[{'path':str(p),'sha256':worker.phase.sha(p),'width':20,'height':round(23000*scale),'detail':'high'}]}
   with self.assertRaisesRegex(ValueError,'ten-image'):worker.tile_case(case,root/'out')
 def test_completed_call_reuses_without_network_or_process_limit(self):
  with tempfile.TemporaryDirectory() as d:
   out=Path(d);m={'model':worker.phase.old.MODEL,'thinking':{'type':'disabled'},'parent_manifest':str(out/'old/manifest.json')}
   payload={'model':m['model'],'messages':[{'role':'user','content':[{'type':'text','text':'hello'}]}],'max_tokens':8192,'temperature':0,'stream':False,'thinking':m['thinking']}
   key=hashlib.sha256(json.dumps(payload,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
   worker.save(out/'completed-calls'/key,{'status':'completed','content':'wrong answer','usage':{'total_tokens':3}})
   with patch.object(worker,'environment',return_value=({},{})),patch.object(worker.httpx,'Client',side_effect=AssertionError('must not send')):
    c=worker.Client(out,m,out/'attempt');r=c.call('qa','hello');self.assertEqual(r['content'],'wrong answer')
 def test_six_sequential_timeout_attempts_and_terminal_resume(self):
  with tempfile.TemporaryDirectory() as d:
   out=Path(d);worker.save(out/'manifest.json',{'cases':[{'id':'q'}]})
   with patch.object(worker,'environment',return_value=({},{})),patch.object(worker.phase,'prepare_case',return_value=([{'id':'f'}],{})),patch.object(worker.phase,'condition',side_effect=worker.Deadline()) as cond:
    r=worker.run_condition((str(out),'q','canvas_1'));self.assertEqual(r['status'],'timeout');self.assertEqual(r['attempt'],6);self.assertEqual(cond.call_count,6)
    worker.run_condition((str(out),'q','canvas_1'));self.assertEqual(cond.call_count,6)
   self.assertEqual(len(list((out/'conditions/q/canvas_1/attempts').glob('*/result.json'))),6)
 def test_completed_wrong_condition_never_retries(self):
  with tempfile.TemporaryDirectory() as d:
   out=Path(d);worker.save(out/'manifest.json',{'cases':[{'id':'q'}]})
   with patch.object(worker,'environment',return_value=({},{})),patch.object(worker.phase,'prepare_case',return_value=([{'id':'f'}],{})),patch.object(worker.phase,'condition',return_value={'qa_status':'completed','reconstruction_status':'completed','qa_exact_correct':0}) as cond:
    r=worker.run_condition((str(out),'q','canvas_1'));self.assertEqual(r['status'],'completed');self.assertEqual(r['attempt'],1);self.assertEqual(cond.call_count,1)
