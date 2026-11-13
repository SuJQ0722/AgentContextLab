"""Pending-only grading for the new controlled text recovery; no calibration scores."""
import argparse,fcntl,io,json,os,time,urllib.error
from pathlib import Path
import httpx
from lab import ROOT,environment
import judge_bc_v3_completed as bc
from judge_visual_hosted_retry_v1 import gold_sources,gold_key
from run_controlled_dependency_recovery_v13 import DEFAULT,read,sha,save
OUT=ROOT/'outputs/grading/controlled-dependency-recovery-v13'
def main():
 p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=DEFAULT);p.add_argument('--out',type=Path,default=OUT);p.add_argument('--live',action='store_true');p.add_argument('--watch',action='store_true');a=p.parse_args();root=a.root;out=a.out;out.mkdir(parents=True,exist_ok=True);out.chmod(0o700)
 lease=(out/'run.lock').open('a');fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB);plan=read(root/'plan.json');gold,hashes=gold_sources();env,_=environment(ROOT,'hermes')
 cfg={'judge_model':'deepseek-v4.1-flash-1017/huoshan/huoshan','max_tokens':8192,'temperature':0,'top_p':1,'timeout_seconds':180}
 bc.immutable(out/'protocol.json',{'version':'controlled-dependency-grading-v13','plan_sha256':sha(root/'plan.json'),'source_gold_sha256':hashes,'config':cfg,'retries':0,'new_call_cap':len(plan['jobs']),'missing_usage_is_unknown':True})
 def opener(request,timeout):
  proxy=env.get('HTTPS_PROXY') or env.get('https_proxy')
  with httpx.Client(proxy=proxy,trust_env=False,timeout=timeout) as c:r=c.post(request.full_url,content=request.data,headers=dict(request.header_items()))
  if r.status_code>=400:raise urllib.error.HTTPError(request.full_url,r.status_code,'Provider error',r.headers,io.BytesIO(r.content))
  b=io.BytesIO(r.content);b.status=r.status_code;b.headers=r.headers;return b
 while True:
  rows=[];pending=[]
  for j in plan['jobs']:
   d=root/'jobs'/j['job_id'];attempts=sorted(d.glob('attempt_*'));r={};chosen=None
   for attempt in attempts:
    rp=attempt/'native-result.json';terminal=attempt/'controller-terminal.json'
    if rp.exists() and terminal.exists() and read(terminal).get('status')=='completed':r=read(rp);chosen=attempt;break
   dest=out/'jobs'/j['job_id'];grade=read(dest/'grade.json') if(dest/'grade.json').exists() else {}
   row={'job_id':j['job_id'],'method':j['controlled_method'],'status':r.get('status','no_completed_result'),'grade_status':grade.get('status'),'score':grade.get('score') if grade.get('status')=='scored' else None}
   if chosen and not(dest/'request-started.json').exists():
    secret=gold[gold_key(j)][j['question_id']]
    if secret['question']!=j['question']:raise ValueError('Gold question mismatch')
    control=read(chosen/'compression-control.json');target=read(j['control_target_path'])
    valid=control.get('passed') is True and control.get('native_hashes')==target['native_hashes'] and control.get('prefix_sha256')==target['prefix_sha256'] and abs(control['first_actual_prompt_tokens']-target['first_actual_prompt_tokens'])/target['first_actual_prompt_tokens']<=.02
    row['measured_control_valid']=valid
    if valid:
     binding={'job_id':j['job_id'],'result_path':str(chosen/'native-result.json'),'result_sha256':sha(chosen/'native-result.json'),'control_path':str(chosen/'compression-control.json'),'control_sha256':sha(chosen/'compression-control.json'),'target_path':j['control_target_path'],'target_sha256':sha(j['control_target_path']),'plan_sha256':sha(root/'plan.json'),'gold_source_sha256':hashes}
     pending.append({'directory':dest,'binding':binding,'question':secret['question'],'answer':secret['answer'],'prediction':r['final']['text']})
   rows.append(row)
  save(out/'status.json',{'at':time.time(),'rows':rows,'ready':len(pending),'live':a.live})
  if a.live:
   for candidate in pending:
    bc.grade(candidate,cfg,env,opener=opener)
  if not a.watch:print(json.dumps({'ready':len(pending),'live':a.live}));break
  if(root/'STOP').exists() or(out/'STOP').exists():break
  time.sleep(30)
if __name__=='__main__':main()
