import hashlib,json,sys,tempfile,threading,unittest
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import judge_mmbc100 as m

def fixture(root,n=2):
 cohort={f'q{i}':{'question_id':f'q{i}','question':f'Question {i}?','image':['https://example.invalid/image.png'] if i%2 else []} for i in range(n)}
 jobs=[{'job_id':f'hermes/{method}/{q}_r{rep:02}','question_id':q,'question':row['question'],'image':row['image'],'strategy':method,'harness':'hermes','repeat':rep,'model':m.MODEL} for method in m.METHODS for q,row in cohort.items() for rep in [1,2,3]]
 return {'jobs':jobs},cohort,{q:'GOLD' for q in cohort},{'cohort_sha256':'cohort','plan_sha256':'plan','private_source_sha256':'private'}

def result(root,job,status='completed',clean=True):
 p=root/'jobs'/job['job_id']/'attempts/attempt_001/result.json';m.atomic(p,{**job,'status':status,'final':'Prediction','slot_released':clean,'unconfirmed_child_termination':[] if clean else [{'pid':1}]});return p

class MMBCJudgeTests(unittest.TestCase):
 def test_fixed100_private_hash_and_public_isolation(self):
  with tempfile.TemporaryDirectory() as d:
   base=Path(d);root=base/'campaign';gold=base/'gold';out=base/'grades';root.mkdir();plan,cohort,answers,_=fixture(root,100)
   public=''.join(json.dumps(r)+'\n' for r in cohort.values());(root/'cohort.jsonl').write_text(public)
   m.atomic(root/'experiment.json',{'model':m.MODEL,'mmbc100_campaign':{'judge_model':m.MODEL}})
   plan['definition']={'cohort_sha256':m.sha(root/'cohort.jsonl'),'config_sha256':m.sha(root/'experiment.json')};m.atomic(root/'plan.json',plan);m.atomic(root/'campaign-manifest.json',{'plan_sha256':m.sha(root/'plan.json')})
   private=gold/'private/selected-source.jsonl';private.parent.mkdir(parents=True);private.write_text(''.join(json.dumps({'question_id':q,'answer':'GOLD','source_row':row})+'\n' for q,row in cohort.items()))
   m.atomic(gold/'private/source-map.json',{'selected_source_sha256':m.sha(private),'cohort_sha256':m.sha(root/'cohort.jsonl'),'selected_ids':list(cohort)})
   loaded=m.load_source(root,gold,out);self.assertEqual(len(loaded[0]['jobs']),1500);self.assertNotIn('GOLD',(root/'cohort.jsonl').read_text());private.write_text(private.read_text()+'\n')
   with self.assertRaises(ValueError):m.load_source(root,gold,out)
 def test_operational_zero_cleanup_and_unresolved_judge_missing(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d)/'campaign';out=Path(d)/'grades';plan,cohort,answers,binding=fixture(root)
   result(root,plan['jobs'][0],'failed');result(root,plan['jobs'][1],'timeout',False);result(root,plan['jobs'][2]);directory=m.grade_dir(out,plan['jobs'][2]);m.atomic(directory/'request-started.json',{})
   candidates,rows,info=m.inventory(root,out,plan,cohort,answers,binding)
   self.assertEqual(rows[0]['score'],0);self.assertIsNone(rows[1]['score']);self.assertIsNone(rows[2]['score']);self.assertEqual(rows[2]['score_reason'],'judge_request_unresolved');self.assertEqual(candidates,[]);self.assertFalse(info['all_terminal'])
 def test_complete_clusters_and_missing_subgroup_are_not_filled(self):
  plan,cohort,_,_=fixture(Path('/unused'),4);rows=[]
  for j in plan['jobs']:rows.append({'method':j['strategy'],'question_id':j['question_id'],'repeat':j['repeat'],'question_sha256':j['question'],'score':1. if j['strategy']=='visual' else 0.,'score_reason':'judged_completed'})
  a=m.analyze(rows,cohort,200);self.assertEqual(a['groups']['all100']['paired'][0]['paired_runs'],12);self.assertEqual(a['groups']['initial_images']['summary'][0]['planned'],6);self.assertEqual(a['groups']['all100']['summary'][-1]['sample_std_across_three_repeats'],0)
  rows[-1]['score']=None;a=m.analyze(rows,cohort,200);self.assertFalse(a['groups']['all100']['summary'][-1]['complete']);self.assertIsNone(a['groups']['all100']['summary'][-1]['mean']);self.assertTrue(a['groups']['no_initial_images']['summary'][-1]['complete']);self.assertFalse(a['groups']['all100']['paired'][0]['ready'])
 def test_real_local_http_grade_no_retry_and_result_sha(self):
  received=[]
  class Handler(BaseHTTPRequestHandler):
   def log_message(self,*args):pass
   def do_POST(self):
    body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));received.append(body)
    data=json.dumps({'model':'deepseek-v4-1-flash-261017','choices':[{'finish_reason':'stop','message':{'content':'{"score": 1}'}}],'usage':{'prompt_tokens':11,'completion_tokens':3,'total_tokens':14}}).encode();self.send_response(200);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
  server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  try:
   with tempfile.TemporaryDirectory() as d:
    root=Path(d)/'campaign';out=Path(d)/'grades';plan,cohort,answers,binding=fixture(root);path=result(root,plan['jobs'][0]);candidates,_,_=m.inventory(root,out,plan,cohort,answers,binding);c=candidates[0];cfg={'judge_model':m.MODEL,'max_tokens':8192,'temperature':0,'top_p':1,'timeout_seconds':3};env={'TOKENHUB_BASE_URL':f'http://127.0.0.1:{server.server_port}','TOKENHUB_API_KEY':'local-fixture-not-secret'}
    g=m.judge_one(c,cfg,env);self.assertEqual(g['score'],1);self.assertEqual(g['version'],m.VERSION);self.assertIsNone(g['usage']['cached_input_tokens']);m.judge_one(c,cfg,env);self.assertEqual(len(received),1);self.assertEqual(received[0]['model'],m.MODEL);self.assertIn('GOLD',received[0]['messages'][0]['content']);self.assertFalse((root/'private').exists())
    path.write_text(path.read_text()+'\n')
    with self.assertRaises(ValueError):m.judge_one(c,cfg,env)
  finally:server.shutdown();server.server_close();thread.join()
 def test_accounting_unreturned_start_missing_cache_and_no_judge_double_count(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d)/'campaign';out=Path(d)/'grades';plan,cohort,answers,binding=fixture(root,1);j=plan['jobs'][0];p=result(root,j);metrics=p.parent/'native/metrics';metrics.mkdir(parents=True)
   (metrics/'call-starts.jsonl').write_text('{"call_id":"a","purpose":"agent"}\n{"call_id":"b","purpose":"compaction"}\n');(metrics/'calls.jsonl').write_text(json.dumps({'call_id':'a','purpose':'agent','raw_provider_usage':{'prompt_tokens':10,'completion_tokens':2,'total_tokens':12},'client_stream_seconds':3})+'\n');(metrics/'web.jsonl').write_text('{"kind":"search","cache_header":"true"}\n{"kind":"fetch","cache_header":null}\n')
   _,rows,_=m.inventory(root,out,plan,cohort,answers,binding);a=m.accounting(rows,out);s=a['prediction']['none'];self.assertEqual(s['tokens']['observations'],2);self.assertEqual(s['tokens']['fields']['cached_input']['missing_count'],2);self.assertEqual(s['requests']['sdk_unresolved'],1);self.assertEqual(s['sdk_client_seconds_known'],3);self.assertIsNone(s['provider_api_latency_seconds']);self.assertEqual(s['web_cache_rates']['search']['known_hit_rate'],1);self.assertIsNone(s['web_cache_rates']['fetch']['known_hit_rate']);self.assertEqual(a['judge']['tokens']['observations'],0)
if __name__=='__main__':unittest.main()
