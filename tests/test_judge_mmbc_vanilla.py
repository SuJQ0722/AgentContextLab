import copy,io,json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import judge_mmbc_vanilla as v
import report_mmbc_sixmethods as report
base=v.base

def setup_fixture(folder):
 parent=folder/'parent';root=folder/'vanilla';gold=folder/'gold';out=folder/'vgrades';pout=folder/'pgrades'
 for d in [parent,root,gold/'private']:d.mkdir(parents=True)
 cohort={f'q{i:03}':{'question_id':f'q{i:03}','question':f'Question {i}?','image':['https://example.invalid/a.png'] if i<69 else []} for i in range(100)}
 raw=''.join(json.dumps(r)+'\n' for r in cohort.values())
 for r in [parent,root]:(r/'cohort.jsonl').write_text(raw);base.atomic(r/'image-assets/manifest.json',{'images':{}})
 cfg={'model':v.MODEL,'mmbc100_campaign':{'judge_model':v.MODEL},'shared_policy':{'strategy_configs':{'visual':{'text_only':False}}}};base.atomic(parent/'experiment.json',cfg);base.atomic(root/'experiment.json',v.expected_config(cfg))
 jobs=[{'job_id':f'hermes/{m}/{q}_r{rep:02}','question_id':q,'question':row['question'],'image':row['image'],'harness':'hermes','strategy':m,'model':v.MODEL,'repeat':rep,'config_path':str(parent/'experiment.json'),'config_sha256':base.sha(parent/'experiment.json')} for m in base.METHODS for q,row in cohort.items() for rep in [1,2,3]]
 d={'config_sha256':base.sha(parent/'experiment.json'),'cohort_sha256':base.sha(parent/'cohort.jsonl')};base.atomic(parent/'plan.json',{'definition':d,'jobs':jobs});base.atomic(parent/'campaign-manifest.json',{'plan_sha256':base.sha(parent/'plan.json')})
 lineage={'protocol':v.PROTOCOL,'parent_plan_sha256':base.sha(parent/'plan.json'),'parent_campaign_manifest_sha256':base.sha(parent/'campaign-manifest.json')};base.atomic(root/'vanilla-lineage.json',lineage)
 vjobs=[dict(j,method_label=v.LABEL,config_path=str(root/'experiment.json'),config_sha256=base.sha(root/'experiment.json')) for j in jobs if j['strategy']=='visual']
 definition={'execution_version':'mmbc100-hermes-vanilla-v1','planned_runs':300,'strategies':['visual'],'method_labels':[v.LABEL],'parent_root':str(parent),'parent_plan_sha256':base.sha(parent/'plan.json'),'parent_config_sha256':base.sha(parent/'experiment.json'),'vanilla_lineage_sha256':base.sha(root/'vanilla-lineage.json'),'config_sha256':base.sha(root/'experiment.json'),'cohort_sha256':base.sha(root/'cohort.jsonl'),'input_images_sha256':base.sha(root/'image-assets/manifest.json')};base.atomic(root/'plan.json',{'definition':definition,'jobs':vjobs});base.atomic(root/'campaign-manifest.json',{**definition,'plan_sha256':base.sha(root/'plan.json'),'method_label':v.LABEL})
 private=gold/'private/selected-source.jsonl';private.write_text(''.join(json.dumps({'question_id':q,'answer':'PRIVATE GOLD','source_row':r})+'\n' for q,r in cohort.items()));base.atomic(gold/'private/source-map.json',{'selected_ids':list(cohort),'selected_source_sha256':base.sha(private),'cohort_sha256':base.sha(root/'cohort.jsonl')})
 return root,parent,gold,out,pout

class VanillaTests(unittest.TestCase):
 def test300same_gold_parent_and_label_without_writing_parent(self):
  with tempfile.TemporaryDirectory() as d:
   root,parent,gold,out,pout=setup_fixture(Path(d));prior=base.sha(parent/'plan.json');plan,cohort,answers,binding=v.load_source(root,gold,out,parent);candidates,rows,info=v.inventory(root,out,plan,cohort,answers,binding)
   self.assertEqual(len(rows),300);self.assertEqual(set(r['method'] for r in rows),{v.LABEL});self.assertEqual(set(r['actual_strategy'] for r in rows),{'visual'});self.assertEqual(prior,base.sha(parent/'plan.json'));self.assertEqual(candidates,[]);self.assertEqual(sum(bool(r['image']) for r in cohort.values()),69)
   cfg=base.read(root/'experiment.json');cfg['shared_policy']['strategy_configs']['visual']['text_only']=False;base.atomic(root/'experiment.json',cfg)
   with self.assertRaises(ValueError):v.load_source(root,gold,out,parent)
 def test_extra_scientific_difference_rejected_even_same_label(self):
  with tempfile.TemporaryDirectory() as d:
   root,parent,gold,out,pout=setup_fixture(Path(d));cfg=base.read(root/'experiment.json');cfg['max_rounds']=1;base.atomic(root/'experiment.json',cfg)
   with self.assertRaises(ValueError):v.load_source(root,gold,out,parent)
 def test_new_score_same_jobid_is_isolated_and_not_retried(self):
  with tempfile.TemporaryDirectory() as d:
   root,parent,gold,out,pout=setup_fixture(Path(d));plan,cohort,answers,binding=v.load_source(root,gold,out,parent);j=plan['jobs'][0];rp=root/'jobs'/j['job_id']/'attempts/attempt_001/result.json';base.atomic(rp,{**j,'status':'completed','final':'prediction','slot_released':True,'unconfirmed_child_termination':[]});base.atomic(pout/'jobs'/j['job_id']/'grade.json',{'marker':'original parent grade'});parent_sha=base.sha(pout/'jobs'/j['job_id']/'grade.json')
   candidates,_,_=v.inventory(root,out,plan,cohort,answers,binding);sent=[]
   class Response(io.BytesIO):status=200;headers={}
   def opener(request,timeout):sent.append(json.loads(request.data));return Response(json.dumps({'model':'deepseek-v4-1-flash-261017','choices':[{'finish_reason':'stop','message':{'content':'{"score": 1}'}}],'usage':{'prompt_tokens':10,'completion_tokens':2,'total_tokens':12}}).encode())
   cfg={'judge_model':v.MODEL,'max_tokens':8192,'temperature':0,'top_p':1,'timeout_seconds':3};env={'TOKENHUB_BASE_URL':'http://localhost.invalid','TOKENHUB_API_KEY':'test-not-secret'};g=v.judge_one(candidates[0],cfg,env,opener);v.judge_one(candidates[0],cfg,env,opener)
   self.assertEqual(len(sent),1);self.assertEqual(g['method_label'],v.LABEL);self.assertEqual(g['score'],1);self.assertEqual(g['strategy'],'visual');self.assertEqual(parent_sha,base.sha(pout/'jobs'/j['job_id']/'grade.json'));_,rows,_=v.inventory(root,out,plan,cohort,answers,binding);self.assertEqual(rows[0]['score'],1)
 def test_sixmethod_missing_and_pair_clusters_preserve_three_repeats(self):
  cohort={'a':{'image':['x']},'b':{'image':[]}};rows=[{'method':method,'question_id':q,'repeat':rep,'question_sha256':q,'score':float(method=='visual'),'score_reason':'judged_completed'} for method in ['visual',v.LABEL] for q in cohort for rep in [1,2,3]];rng=report.np.random.default_rng(1);p=report.additional_pair(rows,['a','b'],rng,200);self.assertTrue(p['ready']);self.assertEqual(p['question_clusters'],2);self.assertEqual(p['paired_runs'],6);self.assertEqual(p['visual_minus_vanilla'],1)
  rows[-1]['score']=None;s=report.summarize(rows,['a','b'],v.LABEL,rng,200);self.assertFalse(s['complete']);self.assertIsNone(s['mean']);self.assertFalse(report.additional_pair(rows,['a','b'],rng,200)['ready'])
  with self.assertRaises(ValueError):report.additional_pair(rows+[rows[0]],['a','b'],rng,200)
 def test_combined_report_keeps1800rows_and_parent_namespace_untouched(self):
  with tempfile.TemporaryDirectory() as d:
   root,parent,gold,out,pout=setup_fixture(Path(d));pp,pc,pa,pb=base.load_source(parent,gold,pout);_,pr,pi=base.inventory(parent,pout,pp,pc,pa,pb);vp,vc,va,vb=v.load_source(root,gold,out,parent);_,vr,vi=v.inventory(root,out,vp,vc,va,vb)
   for path,rows in [(pout,pr),(out,vr)]:base.atomic(path/'observations.json',rows);base.atomic(path/'protocol.json',{'judge_model':v.MODEL})
   before=base.sha(pout/'observations.json');data=report.combine(pout,out,Path(d)/'combined',200);self.assertEqual(len(data['groups']['all100']['summary']),6);self.assertEqual(sum(r['planned'] for r in data['groups']['all100']['summary']),1800);self.assertEqual(before,base.sha(pout/'observations.json'));self.assertFalse(data['groups']['all100']['additional_visual_vs_vanilla']['ready'])
   with self.assertRaises(ValueError):report.combine(pout,out,pout,200)
if __name__=='__main__':unittest.main()
