"""One recovery judge per explicitly connection-failed historical grade; preserve history."""
import sys,json,time,hashlib,os,argparse,fcntl
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
R=Path('/mnt/afs_agents/sujiaqi/workspace/projects/AgentContextLab');sys.path.insert(0,str(R/'scripts'))
import judge_seven_runtime_v11 as j
from lab import environment
base=j.base
OUT=R/'outputs/grading/connection-failure-recovery-v13'
def read(p):return json.loads(Path(p).read_text())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--live',action='store_true');a=ap.parse_args();OUT.mkdir(parents=True,exist_ok=True);OUT.chmod(0o700)
 lock=(OUT/'controller.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 gold,gold_hashes=base.gold_sources();candidates=[];records=[];plan_cache={}
 for name in ['seven-page-runtime-v11','seven-page-turns500-v12']:
  old=R/'outputs/grading'/name;cfg=read(old/'protocol.json');obs=read(old/'observations.json')
  for ob in obs:
   if ob.get('score_reason')!='judge_error':continue
   directory=old/'cells'/ob['cell']/'jobs'/ob['job_id'];gp=directory/'grade.json';g=read(gp)
   if g.get('error_type')!='ConnectError':continue
   assert g['status']=='judge_error'and g.get('score')is None and g.get('raw_provider_usage')is None
   terminals=list((directory/'http-attempts').glob('attempt_*/terminal.json'))
   assert terminals and all(read(p).get('error_type')=='ConnectError'for p in terminals)
   binding=read(directory/'binding.json');assert all(g.get(k)==v for k,v in binding.items());assert binding['gold_sources_sha256']==gold_hashes
   plan=Path(binding['root'])/'plan.json';pk=str(plan)
   if pk not in plan_cache:
    assert sha(plan)==binding['plan_sha256'];pd=read(plan);plan_cache[pk]={x['job_id']:x for x in pd['jobs']}
   job=plan_cache[pk][ob['job_id']];assert not job.get('calibration_not_scored')
   result=read(binding['result_path']);assert sha(binding['result_path'])==binding['result_sha256'];assert result['status']=='completed'
   final=result['final'];prediction=final if isinstance(final,str)else final['text'];secret=gold[base.gold_key(job)][job['question_id']]
   assert secret['question']==job['question'];assert hashlib.sha256(prediction.encode()).hexdigest()==binding['prediction_sha256']
   dst=OUT/name/'cells'/ob['cell']/'jobs'/ob['job_id'];dst.mkdir(parents=True,exist_ok=True)
   rec={'source_namespace':name,'cell':ob['cell'],'job_id':ob['job_id'],'prior_grade':str(gp),'prior_grade_sha256':sha(gp),'prior_error_type':'ConnectError','prior_cost_not_assumed_zero':True,'new_grade':str(dst/'grade.json'),'result_sha256':binding['result_sha256'],'new_judge_invocation_limit':1}
   base.immutable(dst/'prior-attempt.json',rec);records.append(rec)
   if not(dst/'grade.json').exists()and not(dst/'request-started.json').exists()and not(dst/'local-error.json').exists():candidates.append(({'directory':dst,'binding':binding,'question':job['question'],'answer':secret['answer'],'prediction':prediction},cfg))
 manifest={'at':time.time(),'eligible':len(records),'fresh_candidates':len(candidates),'live':a.live,'gold_sources_sha256':gold_hashes,'records':records,'science_protocol':'Unchanged Hermes answer-equivalence judge/model/prompt; new network transport only','previous_successes_and_unknown_acceptance_not_reissued':True,'source_sha256':sha(__file__)}
 base.atomic(OUT/'manifest.json',manifest);print(json.dumps({'eligible':len(records),'fresh_candidates':len(candidates),'live':a.live}),flush=True)
 if not a.live:return
 env,_=environment(R,'hermes');done=0
 def status():
  rows=[]
  for r in records:
   p=Path(r['new_grade']);d=read(p)if p.exists()else{};rows.append({**r,'status':d.get('status','pending'),'score':d.get('score'),'error_type':d.get('error_type'),'raw_provider_usage':d.get('raw_provider_usage')})
  base.atomic(OUT/'summary.json',{'at':time.time(),'pid':os.getpid(),'total':len(records),'finished':done,'rows':rows,'concurrency':4,'old_failed_cost_retained_in_prior_roots':True})
 with ThreadPoolExecutor(max_workers=4)as pool:
  futures={pool.submit(j.previous.grade_bound,c,cfg,env):c for c,cfg in candidates}
  status()
  for future in as_completed(futures):
   c=futures[future]
   try:future.result()
   except Exception as e:base.atomic(c['directory']/'local-error.json',{'error_type':type(e).__name__,'automatic_retry':False})
   done+=1;status();print('finished',done,flush=True)
 status()
if __name__=='__main__':main()
