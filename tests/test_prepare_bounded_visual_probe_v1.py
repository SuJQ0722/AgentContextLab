import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import prepare_bounded_visual_probe_v1 as p

class WindowPreparationTests(unittest.TestCase):
 def test_unicode_byte_boundary_exact_slice_and_words(self):
  for text in ['汉字中文😀é'*500,('ordinary word with digits 2026\n'*100),('x'*2000),('ab '*300), '']:
   for pos in ['early','middle','late']:
    w=p.select_window(text,pos);self.assertEqual(text[w['start_char']:w['end_char']],w['window']);self.assertEqual(text.encode()[w['start_byte']:w['end_byte']].decode(),w['window']);self.assertLessEqual(w['bytes'],512);self.assertLessEqual(w['whitespace_words'],96)
  self.assertTrue(p.select_window('x'*2000,'middle')['ascii_token_cut_start'])
 def test_regular_ascii_window_does_not_cut_word(self):
  text='alpha beta gamma\n'*300
  for pos in ['early','middle','late']:
   w=p.select_window(text,pos);self.assertFalse(w['ascii_token_cut_start']);self.assertFalse(w['ascii_token_cut_end']);self.assertFalse(p.token_interior(text,w['start_char']));self.assertFalse(p.token_interior(text,w['end_char']))
 def test_fact_grounding_and_empty_facts_no_replacement(self):
  source='The count is 17 at https://example.org.';f={'id':'f1','type':'numeral','question':'What count?','answer':'17','quote':'count is 17'}
  self.assertTrue(p.validate_facts({'facts':[f]},source));self.assertTrue(p.validate_facts({'facts':[]},source));self.assertFalse(p.validate_facts({'facts':[dict(f,answer='18')]},source));self.assertFalse(p.validate_facts({'facts':[f,f]},source));self.assertFalse(p.validate_facts({'facts':[dict(f,quote='other source 17')]},source))
 def test_fixed_sources_independent_of_old_outcomes_and_all_templates_incomplete(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);parent=root/'parent';parent.mkdir();cases=[]
   for q in ['q_004','q_009']:
    source=parent/(q+'.txt');source.write_text('[message 0; role=tool]\n'+('The year is 2026; URL https://example.org.\n'*90));history=parent/(q+'.json');history.write_text('[{"role":"tool","content":"original history"}]');cases.append({'id':q,'source_path':str(source),'source_sha256':p.sha(source),'renderer_input_path':str(history),'renderer_input_sha256':p.sha(history)})
   p.save(parent/'manifest.json',{'cases':cases});(parent/'manifest.sha256').write_text(p.sha(parent/'manifest.json'));(parent/'results.json').write_text('INVALID OLD RESULTS MUST NOT BE READ');cfg=root/'config/configs';cfg.mkdir(parents=True);(cfg/'experiment.json').write_text('{"model":"deepseek-v4.1-flash-1017/huoshan/huoshan"}')
   with patch.object(p,'ROOT',root/'config'):
    m=p.prepare(parent,root/'out');self.assertEqual(len(m['windows']),6);self.assertEqual([w['split'] for w in m['windows']],['development']*3+['holdout']*3);self.assertEqual(m['provider_requests_sent'],0)
    for w in m['windows']:
     raw=Path(w['window_path']).read_text();source=Path(w['source_path']).read_text();self.assertEqual(raw,source[w['start_char']:w['end_char']]);self.assertEqual(len({r['facts_reference'] for r in w['representations'].values()}),1)
     folder=Path(w['window_path']).parent;req=p.read(folder/'requests/text_control.reconstruction.json');self.assertEqual(req['max_tokens'],768);self.assertEqual(req['thinking'],{'type':'disabled'});self.assertTrue(req['messages'][0]['content'][0]['text'].endswith(raw));self.assertEqual(w['representations']['summary']['status'],'pending_same_window_summary_generation');self.assertEqual(w['representations']['canvas_0.75']['status'],'pending_unified_renderer')
    original=p.sha(root/'out/manifest.json');p.prepare(parent,root/'out');self.assertEqual(original,p.sha(root/'out/manifest.json'))
    Path(m['windows'][0]['window_path']).write_text('altered')
    with self.assertRaises(ValueError):p.prepare(parent,root/'out')
 def test_no_paid_executor_and_fixed_output_bound(self):
  request=p.make_request('deepseek-v4.1-flash-1017/huoshan/huoshan','test');self.assertEqual(request['max_tokens'],768);self.assertFalse(request['stream']);self.assertEqual(p.METHODS,('text_control','canvas_1','canvas_0.75','canvas_0.5','summary'))
if __name__=='__main__':unittest.main()
