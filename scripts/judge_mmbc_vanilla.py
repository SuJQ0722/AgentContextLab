#!/usr/bin/env python3
"""Independent vanilla MMBC grader. Parent five-arm grades/protocol are read-only."""
import argparse,fcntl,json,os,signal,time
from pathlib import Path
from collections import Counter,deque
from concurrent.futures import ThreadPoolExecutor,wait,FIRST_COMPLETED
import judge_mmbc100 as base
from prepare_mmbc_vanilla import expected_config,PROTOCOL
import report_mmbc_sixmethods as reports
from lab import ROOT,environment

VERSION='mmbc100-vanilla-private-judge-v1'
MODEL=base.MODEL
LABEL='vanilla_visual'
DEFAULT_ROOT=ROOT/'outputs/campaigns/mmbc100-hermes-vanilla-v1'
DEFAULT_OUT=ROOT/'outputs/grading/mmbc100-hermes-vanilla-v1'
sha,read,atomic,immutable=base.sha,base.read,base.atomic,base.immutable

def load_source(root,gold,out,parent=base.DEFAULT_ROOT):
 root,gold,out,parent=[Path(p).resolve() for p in (root,gold,out,parent)]
 if out==base.DEFAULT_OUT.resolve() or root==parent or any(p==root or root in p.parents for p in [gold,out]):raise ValueError('Vanilla grading/gold namespace must be separate from prediction and parent grades')
 plan,cfg,manifest=read(root/'plan.json'),read(root/'experiment.json'),read(root/'campaign-manifest.json');d=plan['definition']
 parent_plan=read(parent/'plan.json');parent_manifest=read(parent/'campaign-manifest.json');lineage=read(root/'vanilla-lineage.json')
 if cfg!=expected_config(read(parent/'experiment.json')) or d['parent_config_sha256']!=sha(parent/'experiment.json') or d['vanilla_lineage_sha256']!=sha(root/'vanilla-lineage.json') or manifest['vanilla_lineage_sha256']!=sha(root/'vanilla-lineage.json') or lineage['protocol']!=PROTOCOL or lineage['parent_plan_sha256']!=sha(parent/'plan.json') or lineage['parent_campaign_manifest_sha256']!=sha(parent/'campaign-manifest.json'):raise ValueError('Vanilla changes exceed the approved text-only intervention')
 if parent_manifest['plan_sha256']!=sha(parent/'plan.json') or d['parent_plan_sha256']!=sha(parent/'plan.json') or manifest['parent_plan_sha256']!=sha(parent/'plan.json') or Path(d['parent_root']).resolve()!=parent or Path(manifest['parent_root']).resolve()!=parent:raise ValueError('Wrong parent plan lineage')
 if d['execution_version']!='mmbc100-hermes-vanilla-v1' or d['planned_runs']!=300 or d['strategies']!=['visual'] or d['method_labels']!=[LABEL] or manifest['method_label']!=LABEL:raise ValueError('Wrong vanilla scope')
 if cfg['model']!=MODEL or cfg['mmbc100_campaign']['judge_model']!=MODEL:raise ValueError('Wrong exact model/route')
 if manifest['plan_sha256']!=sha(root/'plan.json') or d['config_sha256']!=sha(root/'experiment.json'):raise ValueError('Frozen vanilla plan/config changed')
 cohort_sha=sha(root/'cohort.jsonl');images_sha=sha(root/'image-assets/manifest.json')
 if d['cohort_sha256']!=cohort_sha or manifest['cohort_sha256']!=cohort_sha or cohort_sha!=sha(parent/'cohort.jsonl') or d['input_images_sha256']!=images_sha or manifest['input_images_sha256']!=images_sha or images_sha!=sha(parent/'image-assets/manifest.json'):raise ValueError('Initial source cohort/images differ from parent')
 rows=base.jsonlines(root/'cohort.jsonl');cohort={r['question_id']:r for r in rows};private=gold/'private/selected-source.jsonl';secret=base.jsonlines(private);mapping=read(gold/'private/source-map.json');answers={r['question_id']:r['answer'] for r in secret}
 if len(rows)!=100 or len(cohort)!=100 or len(secret)!=100 or set(answers)!=set(cohort) or set(mapping['selected_ids'])!=set(cohort) or mapping['cohort_sha256']!=cohort_sha or mapping['selected_source_sha256']!=sha(private):raise ValueError('Wrong private cohort binding')
 if any(set(r)!={'question_id','question','image'} for r in rows):raise ValueError('Private fields in public cohort')
 for r in secret:
  q=cohort[r['question_id']]
  if r['source_row']['question']!=q['question'] or r['source_row']['image']!=q['image']:raise ValueError('Private/public question differs')
 expected={(q,rep) for q in cohort for rep in [1,2,3]};seen=set();parent_jobs={j['job_id']:j for j in parent_plan['jobs'] if j['strategy']=='visual'}
 for j in plan['jobs']:
  key=(j['question_id'],j['repeat']);original=parent_jobs.get(j['job_id']);rel=Path(j['job_id'])
  if key not in expected or key in seen or original is None or Path(j['config_path']).resolve()!=root/'experiment.json' or j['config_sha256']!=sha(root/'experiment.json') or rel.is_absolute() or '..' in rel.parts or j.get('method_label')!=LABEL or any(j[k]!=original[k] for k in ['job_id','question_id','question','image','repeat','model','harness','strategy']):raise ValueError('Vanilla jobs must be exact parent visual cohort/repeats with new label')
  seen.add(key)
 if seen!=expected or len(plan['jobs'])!=300:raise ValueError('Vanilla requires exactly100x3')
 binding={'root':str(root),'gold_root':str(gold),'parent_root':str(parent),'parent_plan_sha256':sha(parent/'plan.json'),'plan_sha256':sha(root/'plan.json'),'cohort_sha256':cohort_sha,'input_images_sha256':images_sha,'config_sha256':sha(root/'experiment.json'),'private_map_sha256':sha(gold/'private/source-map.json'),'private_source_sha256':sha(private),'method_label':LABEL,'actual_strategy':'visual'}
 immutable(out/'source-binding.json',binding);return plan,cohort,answers,binding

def inventory(root,out,plan,cohort,answers,binding):
 candidates,rows,info=base.inventory(root,out,plan,cohort,answers,binding)
 for r in rows:r.update(actual_strategy='visual',method=LABEL)
 info.update(method_label=LABEL,actual_strategy='visual');return candidates,rows,info

def judge_one(candidate,cfg,env,opener=None):
 record=base.judge_one(candidate,cfg,env,opener)
 if record.get('status')!='already_claimed':
  record.update(version=VERSION,method_label=LABEL);atomic(candidate['directory']/'grade.json',record)
 return record

def report(rows,cohort,out,info,draws,parent_grading,combined_output):
 reports.write_vanilla(rows,cohort,out,info,draws)
 if (parent_grading/'observations.json').exists():reports.combine(parent_grading,out,combined_output,draws)

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=DEFAULT_ROOT);p.add_argument('--parent-root',type=Path,default=base.DEFAULT_ROOT);p.add_argument('--output',type=Path,default=DEFAULT_OUT);p.add_argument('--gold-root',type=Path,default=base.DEFAULT_GOLD);p.add_argument('--parent-grading',type=Path,default=base.DEFAULT_OUT);p.add_argument('--combined-output',type=Path,default=reports.DEFAULT_OUTPUT);p.add_argument('--concurrency',type=int,default=2);p.add_argument('--timeout',type=int,default=180);p.add_argument('--max-tokens',type=int,default=8192);p.add_argument('--draws',type=int,default=10000);p.add_argument('--watch',action='store_true');p.add_argument('--live',action='store_true');a=p.parse_args()
 if not 1<=a.concurrency<=2 or a.max_tokens!=8192 or a.timeout<=0 or a.draws<100:p.error('concurrency1–2, max_tokens8192, positive timeout, draws>=100')
 for key in ['root','parent_root','output','gold_root','parent_grading','combined_output']:setattr(a,key,getattr(a,key).resolve())
 if a.output==a.parent_grading:raise ValueError('Do not overwrite parent grading namespace')
 a.output.mkdir(parents=True,exist_ok=True);a.output.chmod(0o700);plan,cohort,answers,binding=load_source(a.root,a.gold_root,a.output,a.parent_root)
 cfg={'version':VERSION,'judge_model':MODEL,'max_tokens':a.max_tokens,'temperature':0,'top_p':1,'timeout_seconds':a.timeout,'source_binding':binding,'sources_sha256':{p:sha(ROOT/'scripts'/p) for p in ['judge_mmbc_vanilla.py','prepare_mmbc_vanilla.py','report_mmbc_sixmethods.py','judge_mmbc100.py','judge_bc_v3_completed.py','analyze_significance.py','monitor_bc_campaign_v3.py']},'hermes_judge_sha256':sha(ROOT/'hermes-agent/Browsecomp_eval/browsecomp_eval/judge.py'),'api_retries':0,'concurrency_cap':2,'usd':None}
 immutable(a.output/'protocol.json',cfg)
 if not a.live:
  candidates,rows,info=inventory(a.root,a.output,plan,cohort,answers,binding);report(rows,cohort,a.output,info,a.draws,a.parent_grading,a.combined_output);print(json.dumps({'live':False,'maximum_new_requests':len(candidates),'model':MODEL,'inventory':info}));return
 lease=(a.output/'controller.lock').open('a');fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB);env,_=environment(ROOT,'hermes',a.root/'experiment.json');stopped=False
 def stop(*unused):
  nonlocal stopped
  stopped=True
 signal.signal(signal.SIGINT,stop);signal.signal(signal.SIGTERM,stop);pending=deque();futures={};next_scan=0;last_report=0;submitted=0;counts=Counter();info={};rows=[]
 with ThreadPoolExecutor(max_workers=a.concurrency) as pool:
  while True:
   if not stopped and not pending and time.time()>=next_scan:
    plan,cohort,answers,binding=load_source(a.root,a.gold_root,a.output,a.parent_root);candidates,rows,info=inventory(a.root,a.output,plan,cohort,answers,binding);pending.extend(c for c in candidates if str(c['directory']) not in futures.values());next_scan=time.time()+60
    if time.time()-last_report>=300 or info['all_terminal']:report(rows,cohort,a.output,info,a.draws,a.parent_grading,a.combined_output);last_report=time.time()
   while not stopped and pending and len(futures)<a.concurrency:
    c=pending.popleft();f=pool.submit(judge_one,c,cfg,env);futures[f]=str(c['directory']);submitted+=1
   if futures:
    finished,_=wait(futures,timeout=1,return_when=FIRST_COMPLETED)
    for f in finished:
     directory=Path(futures.pop(f))
     try:counts[f.result()['status']]+=1
     except Exception as exc:atomic(directory/'local-error.json',{'at':base.bc.now(),'error_type':type(exc).__name__,'automatic_retry':False});counts['local_error']+=1
   atomic(a.output/'status.json',{'at':base.bc.now(),'pid':os.getpid(),'stopping':stopped,'active':len(futures),'pending_snapshot':len(pending),'submitted':submitted,'outcomes':dict(counts),'inventory':info})
   if not futures and not pending and (stopped or not a.watch or info.get('all_terminal')):break
   if stopped and not futures:break
   if not futures:time.sleep(1)
 candidates,rows,info=inventory(a.root,a.output,plan,cohort,answers,binding);report(rows,cohort,a.output,info,a.draws,a.parent_grading,a.combined_output)
if __name__=='__main__':main()
