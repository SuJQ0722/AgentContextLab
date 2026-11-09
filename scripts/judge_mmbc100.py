#!/usr/bin/env python3
"""Private MMBC-100 judging plus complete-cohort repeated-run statistics. Dry by default."""
import argparse,fcntl,hashlib,json,os,signal,statistics,time
from collections import Counter,defaultdict,deque
from concurrent.futures import ThreadPoolExecutor,wait,FIRST_COMPLETED
from pathlib import Path
import urllib.request
import numpy as np
import judge_bc_v3_completed as bc
from analyze_significance import interval,paired_test,holm
from monitor_bc_campaign_v3 import inspect_attempt,aggregate,numeric,analyze_usage
from lab import ROOT,environment

VERSION='mmbc100-private-judge-v1'
MODEL='deepseek-v4.1-flash-1017/huoshan/huoshan'
METHODS=('none','discard','summarize','sliding_window','visual')
DEFAULT_ROOT=ROOT/'outputs/campaigns/mmbc100-hermes-deepseek-v1'
DEFAULT_OUT=ROOT/'outputs/grading/mmbc100-deepseek-hermes-v1'
DEFAULT_GOLD=ROOT/'outputs/grading/mmbc100-hermes-deepseek-v1'
TERMINAL={'completed','failed','timeout','interrupted','not_started'}
sha,read,atomic,immutable=bc.sha,bc.read,bc.atomic,bc.immutable

def jsonlines(path):return [json.loads(x) for x in Path(path).read_text().splitlines() if x.strip()]
def clean(result):return result.get('slot_released') is True and result.get('unconfirmed_child_termination')==[]
def grade_dir(out,job):return out/'jobs'/job['job_id']

def load_source(root,gold,out):
 root,gold,out=map(lambda p:Path(p).resolve(),(root,gold,out))
 if gold==root or root in gold.parents or out==root or root in out.parents:raise ValueError('Gold and grading must remain outside prediction root')
 paths={n:root/n for n in ['plan.json','experiment.json','cohort.jsonl','campaign-manifest.json']}
 plan,cfg,manifest=read(paths['plan.json']),read(paths['experiment.json']),read(paths['campaign-manifest.json'])
 mapping=read(gold/'private/source-map.json');private=gold/'private/selected-source.jsonl'
 if cfg['model']!=MODEL or cfg['mmbc100_campaign']['judge_model']!=MODEL:raise ValueError('Unapproved prediction/judge route')
 if manifest['plan_sha256']!=sha(paths['plan.json']) or plan['definition']['cohort_sha256']!=sha(paths['cohort.jsonl']) or plan['definition']['config_sha256']!=sha(paths['experiment.json']):raise ValueError('Prediction plan/cohort binding changed')
 if mapping['selected_source_sha256']!=sha(private) or mapping['cohort_sha256']!=sha(paths['cohort.jsonl']):raise ValueError('Private gold/cohort binding changed')
 public=jsonlines(paths['cohort.jsonl']);secret=jsonlines(private)
 cohort={r['question_id']:r for r in public};answers={r['question_id']:r['answer'] for r in secret}
 if len(public)!=100 or len(cohort)!=100 or len(secret)!=100 or len(answers)!=100 or set(answers)!=set(cohort) or set(mapping['selected_ids'])!=set(cohort):raise ValueError('Expected identical unique 100-question cohorts')
 if any(set(r)!={'question_id','question','image'} for r in public):raise ValueError('Public cohort unexpectedly contains private fields')
 for r in secret:
  if r['source_row']['question']!=cohort[r['question_id']]['question'] or r['source_row']['image']!=cohort[r['question_id']]['image']:raise ValueError('Gold source row differs from public question/images')
 expected={(m,q,rep) for m in METHODS for q in cohort for rep in [1,2,3]};seen=set();jobids=set()
 for j in plan['jobs']:
  key=(j['strategy'],j['question_id'],j['repeat']);rel=Path(j['job_id']);q=cohort[j['question_id']]
  if key not in expected or key in seen or j['job_id'] in jobids or j['harness']!='hermes' or j['model']!=MODEL or j['question']!=q['question'] or j['image']!=q['image'] or rel.is_absolute() or '..' in rel.parts:raise ValueError('Job identity/content differs from fixed scope')
  seen.add(key);jobids.add(j['job_id'])
 if seen!=expected:raise ValueError('Incomplete five-method 100x3 plan')
 binding={'root':str(root),'gold_root':str(gold),'plan_sha256':sha(root/'plan.json'),'cohort_sha256':sha(root/'cohort.jsonl'),'config_sha256':sha(root/'experiment.json'),'private_map_sha256':sha(gold/'private/source-map.json'),'private_source_sha256':sha(private)}
 immutable(out/'source-binding.json',binding)
 return plan,cohort,answers,binding

def inventory(root,out,plan,cohort,answers,binding):
 candidates=[];rows=[];terminal=0
 for job in plan['jobs']:
  attempt=root/'jobs'/job['job_id']/'attempts/attempt_001';rp=attempt/'result.json';directory=grade_dir(out,job);result=read(rp) if rp.exists() else {};state=result.get('status','no_terminal_result');cleanup=clean(result)
  row={'job_id':job['job_id'],'method':job['strategy'],'question_id':job['question_id'],'question_sha256':bc.sha_bytes(job['question'].encode()),'repeat':job['repeat'],'initial_images':bool(cohort[job['question_id']]['image']),'attempt':str(attempt),'prediction_status':state,'score':None,'score_reason':'prediction_missing','result_sha256':sha(rp) if rp.exists() else None}
  identity_fields=['job_id']+[k for k in ['harness','strategy','question_id','repeat','model'] if state!='not_started' or k in result]
  if result and any(result.get(k)!=job[k] for k in identity_fields):raise ValueError('Result belongs to another job/model')
  if state in TERMINAL and cleanup:terminal+=1
  if state in {'failed','timeout'} and cleanup:row.update(score=0.,score_reason='confirmed_operational_failure_zero')
  elif state=='completed' and cleanup:
   value=result.get('final');prediction=value if isinstance(value,str) else value.get('text') if isinstance(value,dict) else ''
   if prediction is None:prediction=''
   if not isinstance(prediction,str):raise ValueError('Nontext prediction')
   b={'root':str(root),'job_id':job['job_id'],'harness':'hermes','strategy':job['strategy'],'question_id':job['question_id'],'repeat':job['repeat'],'attempt_path':str(attempt),'result_path':str(rp),'result_sha256':row['result_sha256'],'prediction_sha256':bc.sha_bytes(prediction.encode()),'question_sha256':row['question_sha256'],'cohort_sha256':binding['cohort_sha256'],'plan_sha256':binding['plan_sha256'],'private_source_sha256':binding['private_source_sha256']}
   if (directory/'binding.json').exists() and read(directory/'binding.json')!=b:raise ValueError('Previously bound prediction changed')
   gp=directory/'grade.json';g=read(gp) if gp.exists() else None
   row['score_reason']='ungraded_completed'
   if g:
    if any(g.get(k)!=b[k] for k in ['result_sha256','prediction_sha256','attempt_path','plan_sha256','private_source_sha256']):raise ValueError('Grade/result identity mismatch')
    if g.get('status')=='scored' and type(g.get('score')) in (int,float) and g['score'] in (0,1):row.update(score=float(g['score']),score_reason='judged_completed')
    else:row['score_reason']=g.get('status','judge_missing')
   elif (directory/'request-started.json').exists():row['score_reason']='judge_request_unresolved'
   elif (directory/'local-error.json').exists():row['score_reason']='judge_local_error'
   else:candidates.append({'directory':directory,'binding':b,'question':job['question'],'answer':answers[job['question_id']],'prediction':prediction})
  elif result:row['score_reason']='cleanup_unconfirmed' if not cleanup else state+'_missing'
  rows.append(row)
 return candidates,rows,{'planned':len(rows),'terminal_cleanup_confirmed':terminal,'all_terminal':terminal==len(rows),'ready_to_grade':len(candidates),'prediction_states':dict(Counter(r['prediction_status'] for r in rows)),'score_states':dict(Counter(r['score_reason'] for r in rows))}

def judge_one(candidate,config,env,opener=None):
 # Reuse exact standard answer-equivalence prompt, strict numeric parser and raw ledger.
 result=bc.grade(candidate,config,env,opener=opener or urllib.request.build_opener(urllib.request.ProxyHandler({})).open)
 if result.get('status')=='already_claimed':return result
 if result.get('api_calls')==1 and result.get('status')=='scored' and result.get('finish_reason')!='stop':result.update(status='incomplete_judge_response',score=None)
 result['version']=VERSION;result['inherited_judge_protocol']='Hermes answer-equivalence + numeric JSON score 0/1'
 if result.get('api_calls')==1 and result.get('status')=='scored' and result.get('returned_model') not in (MODEL,'deepseek-v4-1-flash-261017'):
  result.update(status='judge_model_identity_unverified',score=None)
 atomic(candidate['directory']/'grade.json',result)
 return result

def analyze(rows,cohort,draws=10000):
 rng=np.random.default_rng(20261109);groups={name:[q for q,r in cohort.items() if name=='all100' or bool(r['image'])==(name=='initial_images')] for name in ['all100','initial_images','no_initial_images']};reports={}
 for name,ids in groups.items():
  allowed=set(ids);summaries=[];paired=[];indices={}
  for method in METHODS:
   selected=[r for r in rows if r['method']==method and r['question_id'] in allowed];ix={(r['question_id'],r['repeat']):r for r in selected};expected={(q,rep) for q in ids for rep in [1,2,3]}
   if len(ix)!=len(selected):raise ValueError('Duplicate repeated observation')
   full=bool(ids) and set(ix)==expected and all(r['score'] is not None for r in selected);repmeans=[];perrep=[]
   for rep in [1,2,3]:
    rs=[ix.get((q,rep),{}) for q in ids];scores=[r['score'] for r in rs if r.get('score') is not None];ready=bool(ids) and len(scores)==len(ids);v=statistics.mean(scores) if ready else None;perrep.append({'repeat':rep,'known':len(scores),'planned':len(ids),'mean':v})
    if ready:repmeans.append(v)
   known=[r['score'] for r in selected if r['score'] is not None];n=len(expected);ci=interval([statistics.mean(ix[q,rep]['score'] for rep in [1,2,3]) for q in ids],rng,draws) if full else [None,None]
   summaries.append({'method':method,'questions':len(ids),'planned':n,'known':len(known),'missing':n-len(known),'complete':full,'mean':statistics.mean(repmeans) if full else None,'sample_std_across_three_repeats':statistics.stdev(repmeans) if full else None,'bootstrap95':ci,'per_repeat':perrep,'accuracy_bounds':[sum(known)/n,(sum(known)+n-len(known))/n] if n else None,'score_reasons':dict(Counter(r['score_reason'] for r in selected))});indices[method]=(ix,full)
  visual,vready=indices['visual']
  for method in METHODS[:-1]:
   base,bready=indices[method];ready=vready and bready;pair={'baseline':method,'ready':ready}
   if ready:
    if any(visual[k]['question_sha256']!=base[k]['question_sha256'] for k in visual):raise ValueError('Paired question text mismatch')
    delta=[statistics.mean(visual[q,rep]['score']-base[q,rep]['score'] for rep in [1,2,3]) for q in ids];pair.update(question_clusters=len(ids),paired_runs=len(ids)*3,visual_minus_baseline=statistics.mean(delta),bootstrap95=interval(delta,rng,draws),paired_signflip_p=paired_test(delta,rng,draws))
   paired.append(pair)
  if all(p['ready'] for p in paired):
   for p,adjusted in zip(paired,holm([p['paired_signflip_p'] for p in paired])):p['holm_p_four_comparisons_within_subgroup']=adjusted
  reports[name]={'summary':summaries,'paired':paired}
 return {'groups':reports,'draws':draws,'random_seed':20261109,'method':'Question-cluster bootstrap resamples questions, retaining all three repeats. Sample standard deviation over three complete repeat means. Four visual-vs-baseline sign-flip tests; Holm within each prespecified subgroup, not across all 12 exploratory comparisons. No significance claim from incomplete cohorts.'}

def accounting(rows,out):
 data={};judge_rows=[];judge_started=0;judge_pending=0;judge_seconds=[]
 for method in METHODS:
  selected=[r for r in rows if r['method']==method];usage=[];sdk_known=render_known=0.;sdk_missing=render_missing=0;requests=Counter();web=Counter();compress=0;comp_present=0;e2e=[];details=[]
  for r in selected:
   a=Path(r['attempt'])
   if not a.exists():continue
   info,raw=inspect_attempt(a,'hermes');usage.extend(raw);requests.update(info['requests']);web.update(info['web_cache']);sdk_known+=info['sdk_client_seconds_known_subtotal'];sdk_missing+=info['sdk_client_seconds_missing_count'];render_known+=info['render_seconds_known_subtotal'];render_missing+=info['render_seconds_missing_count'];compress+=info['compression_count_known_subtotal'];comp_present+=int(info['compression_metrics_present']);e2e.append(info['end_to_end_seconds'])
   details.append({'job_id':r['job_id'],'compression_count_known':info['compression_count_known_subtotal'],'compression_metrics_present':info['compression_metrics_present'],'render_metrics_present':info['render_metrics_present'],'issues':info['issues']})
  cache_pairs=[analyze_usage(r.get('raw_provider_usage'))[0] for r in usage if not r.get('_incomplete')];cache_pairs=[v for v in cache_pairs if v['prompt'] is not None and v['cached_input'] is not None];cache_prompt=sum(v['prompt'] for v in cache_pairs);cache_count=sum(v['cached_input'] for v in cache_pairs)
  web_rates={kind:{'known_hits':web[kind+'_hits'],'known_misses':web[kind+'_misses'],'unknown':web[kind+'_unknown'],'known_hit_rate':web[kind+'_hits']/(web[kind+'_hits']+web[kind+'_misses']) if web[kind+'_hits']+web[kind+'_misses'] else None} for kind in ['search','fetch']}
  data[method]={'planned_runs':len(selected),'observed_attempts':len(details),'attempts_with_render_metrics':sum(x['render_metrics_present'] for x in details),'cache_rate_observed_calls':len(cache_pairs),'cached_token_fraction_observed_calls':cache_count/cache_prompt if cache_prompt else None,'web_cache_rates':web_rates,'tokens':aggregate(usage),'requests':dict(requests),'sdk_client_seconds_known':sdk_known,'sdk_seconds_missing_calls':sdk_missing,'provider_api_latency_seconds':None,'end_to_end_seconds_known':sum(x for x in e2e if numeric(x)),'end_to_end_missing_attempts':sum(not numeric(x) for x in e2e),'render_seconds_known':render_known,'render_seconds_missing_records':render_missing,'compression_count_known':compress,'attempts_with_compression_metrics':comp_present,'attempt_details':details,'web_cache':dict(web),'usd':None}
 for r in rows:
  directory=out/'jobs'/r['job_id'];started=directory/'request-started.json';gp=directory/'grade.json'
  if started.exists():
   judge_started+=1
   if gp.exists():
    g=read(gp)
    if g.get('api_calls')!=0:judge_rows.append({'raw_provider_usage':g.get('raw_provider_usage')});judge_seconds.append(g.get('client_http_seconds'))
   else:judge_rows.append({'raw_provider_usage':None,'_incomplete':True});judge_pending+=1
 return {'prediction':data,'judge':{'request_claims':judge_started,'unresolved':judge_pending,'tokens':aggregate(judge_rows),'client_http_seconds_known':sum(v for v in judge_seconds if numeric(v)),'client_http_seconds_missing':sum(not numeric(v) for v in judge_seconds),'provider_api_latency_seconds':None,'usd':None},'interpretation':'Known token subtotals are not complete totals if any call or field is missing. Unreturned starts remain unknown. Prediction SDK duration may include SDK retries; it is not provider latency. Renderer and API intervals may nest; do not blindly sum. No validated route price: USD unknown.'}

def report(rows,cohort,out,info,draws=10000,include_accounting=True):
 stats=analyze(rows,cohort,draws);value={'at':bc.now(),'inventory':info,'statistics':stats,'missing_policy':'Confirmed failed/timeout with cleanup=operational zero; interrupted/not_started/unknown and grading errors stay missing. No complete-case intersection substitutes for the fixed cohort.'}
 if include_accounting:value['accounting']=accounting(rows,out)
 atomic(out/'statistics.json',value);atomic(out/'observations.json',rows)
 lines=['# MMBC-100: five Hermes methods, three repeats','',value['missing_policy'],'','|Subgroup|Method|Known / planned|Mean ± sample std|95% question-cluster CI|','|---|---|---:|---:|---|']
 for name,g in stats['groups'].items():
  for s in g['summary']:
   mean=f"{100*s['mean']:.2f} ± {100*s['sample_std_across_three_repeats']:.2f}%" if s['complete'] else 'NA — incomplete';ci=str([round(v*100,2) for v in s['bootstrap95']]) if s['complete'] else 'NA';lines.append(f"|{name}|{s['method']}|{s['known']}/{s['planned']}|{mean}|{ci}|")
 lines+=['',stats['method'],'','Initial-image presence is fixed from the public input cohort, not inferred from eventual success or tool use. The no-initial-image subgroup may still retrieve images during the run. Accuracy confidence intervals are not equivalence tests. No USD estimate without validated gateway pricing.']
 if include_accounting:
  lines+=['','Known resource subtotals; parentheses count missing token fields/requests. These are not complete totals.','','|Method|Cached input|Noncache input|Output|Total|SDK seconds|Render seconds|End-to-end seconds|USD|','|---|---:|---:|---:|---:|---:|---:|---:|---|']
  for method,resource in value['accounting']['prediction'].items():
   fields=resource['tokens']['fields'];tokens=[f"{fields[k]['known_subtotal']} ({fields[k]['missing_count']} missing)" if resource['tokens']['observations'] else 'No calls observed' for k in ['cached_input','noncache_input','output','total']]
   lines.append('|'+method+'|'+'|'.join(tokens)+f"|{resource['sdk_client_seconds_known']:.2f}|{resource['render_seconds_known']:.2f}|{resource['end_to_end_seconds_known']:.2f}|Unknown|")
  lines+=['',value['accounting']['interpretation'],'Render/compression coverage flags and web cache hit/miss/unknown counts are in statistics.json. Zero subtotal with absent instrumentation is not a measured zero.']
 (out/'summary.md').write_text('\n'.join(lines)+'\n');return value

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=DEFAULT_ROOT);p.add_argument('--output',type=Path,default=DEFAULT_OUT);p.add_argument('--gold-root',type=Path,default=DEFAULT_GOLD);p.add_argument('--concurrency',type=int,default=2);p.add_argument('--timeout',type=int,default=180);p.add_argument('--max-tokens',type=int,default=8192);p.add_argument('--draws',type=int,default=10000);p.add_argument('--watch',action='store_true');p.add_argument('--live',action='store_true');a=p.parse_args()
 if not 1<=a.concurrency<=4 or a.max_tokens!=8192 or a.timeout<=0 or a.draws<100:p.error('concurrency1–4, max_tokens8192, positive timeout, draws>=100')
 a.root=a.root.resolve();a.output=a.output.resolve();a.gold_root=a.gold_root.resolve();a.output.mkdir(parents=True,exist_ok=True);a.output.chmod(0o700)
 plan,cohort,answers,binding=load_source(a.root,a.gold_root,a.output)
 cfg={'version':VERSION,'judge_model':MODEL,'max_tokens':a.max_tokens,'temperature':0,'top_p':1,'timeout_seconds':a.timeout,'source_binding':binding,'sources_sha256':{p:sha(ROOT/'scripts'/p) for p in ['judge_mmbc100.py','judge_bc_v3_completed.py','analyze_significance.py','monitor_bc_campaign_v3.py']},'hermes_judge_sha256':sha(ROOT/'hermes-agent/Browsecomp_eval/browsecomp_eval/judge.py'),'api_retries':0,'concurrency_cap':4,'usd':None}
 immutable(a.output/'protocol.json',cfg)
 if not a.live:
  candidates,rows,info=inventory(a.root,a.output,plan,cohort,answers,binding);report(rows,cohort,a.output,info,a.draws);print(json.dumps({'live':False,'maximum_new_requests':len(candidates),'model':MODEL,'inventory':info}));return
 lease=(a.output/'controller.lock').open('a');fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB);env,_=environment(ROOT,'hermes',a.root/'experiment.json');stopped=False
 def stop(*unused):
  nonlocal stopped
  stopped=True
 signal.signal(signal.SIGINT,stop);signal.signal(signal.SIGTERM,stop)
 pending=deque();futures={};next_scan=0;last_report=0;submitted=0;counts=Counter();info={};rows=[]
 with ThreadPoolExecutor(max_workers=a.concurrency) as pool:
  while True:
   if not stopped and not pending and time.time()>=next_scan:
    # Freeze checks are cheap input hashes, not repeated whole source-tree scans.
    current_plan,current_cohort,current_answers,current_binding=load_source(a.root,a.gold_root,a.output)
    candidates,rows,info=inventory(a.root,a.output,current_plan,current_cohort,current_answers,current_binding)
    pending.extend(c for c in candidates if str(c['directory']) not in futures.values());next_scan=time.time()+60
    if time.time()-last_report>=300 or info['all_terminal']:report(rows,cohort,a.output,info,a.draws);last_report=time.time()
   while not stopped and pending and len(futures)<a.concurrency:
    c=pending.popleft();f=pool.submit(judge_one,c,cfg,env);futures[f]=str(c['directory']);submitted+=1
   if futures:
    finished,_=wait(futures,timeout=1,return_when=FIRST_COMPLETED)
    for f in finished:
     directory=Path(futures.pop(f))
     try:counts[f.result()['status']]+=1
     except Exception as exc:atomic(directory/'local-error.json',{'at':bc.now(),'error_type':type(exc).__name__,'automatic_retry':False});counts['local_error']+=1
   atomic(a.output/'status.json',{'at':bc.now(),'pid':os.getpid(),'stopping':stopped,'active':len(futures),'pending_snapshot':len(pending),'submitted':submitted,'outcomes':dict(counts),'inventory':info})
   if not futures and not pending and (stopped or not a.watch or info.get('all_terminal')):break
   if stopped and not futures:break
   if not futures:time.sleep(1)
 candidates,rows,info=inventory(a.root,a.output,plan,cohort,answers,binding);report(rows,cohort,a.output,info,a.draws)
if __name__=='__main__':main()
