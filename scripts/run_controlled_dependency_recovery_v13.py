"""Recover certified V8 targets and resume only under-quota text controls.

Independent namespace; no visual rerun, calibration never becomes accuracy.
"""
import argparse,copy,fcntl,hashlib,json,os,signal,subprocess,sys,time
from pathlib import Path
from unittest.mock import patch
from lab import ROOT,python_for,environment
import controlled_inline_retry_v8 as frozen
from controlled_native_worker_v5 import native_parts,image_ids
BASE=ROOT/'outputs/campaigns/visual-hosted-failure-retry-v1/cells'
SOURCE=BASE/'transport-v9-runtime-recovery/cells/shared_baselines'
DEFAULT=BASE/'transport-v13-controlled-dependencies/cells/shared_baselines'
def read(p):return json.loads(Path(p).read_text())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,value):
 p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps(value,indent=2));tmp.replace(p)
def immutable(p,data):
 p.parent.mkdir(parents=True,exist_ok=True)
 if p.exists():
  if p.read_bytes()!=data:raise ValueError('Existing binding changed')
 else:
  with p.open('xb') as f:f.write(data)
def prepared(root,auditpath):
 audit=read(auditpath);source=read(SOURCE/'plan.json');lookup={j['job_id']:j for j in source['jobs']};targets={t['prefix_key']:t for t in audit['target_candidates']};jobs=[];blocked=[]
 for q in audit['text']:
  j=copy.deepcopy(lookup[q['job_id']]);jid=j['controlled_prefix_key']+'/'+j['controlled_method']
  # Successful scientific units are never resubmitted, even if recovery plans
  # are stale. Every native launch marker conservatively consumes an attempt.
  completed=[]
  for gen in ['controlled-native-v4','controlled-native-bounded-v1']:
   d=ROOT/'outputs/experiment3'/gen/'jobs'/jid
   for p in [d/'result.json',*d.glob('attempt_*/result.json')]:
    if p.exists() and read(p).get('status')=='completed':completed.append(str(p))
  if completed or not q['target_recoverable'] or q['remaining_attempts_upper_bound']<=0:
   blocked.append({'job_id':j['job_id'],'reason':'prior_success' if completed else 'missing_valid_target' if not q['target_recoverable'] else 'quota_exhausted','prior_success':completed});continue
  t=targets[q['prefix_key']];p=Path(t['source']);value=read(p)
  if sha(p)!=t['sha256'] or not frozen.valid_target(value):raise ValueError('Control target evidence changed')
  spec=read(j['controlled_spec_path']);prefix=Path(spec['prefix_path'])
  if sha(prefix)!=value['prefix_sha256'] or image_ids(native_parts(read(prefix)['messages']))!=value['native_hashes']:raise ValueError('Target native/prefix mismatch')
  if value['actual_route']!=spec['model']:raise ValueError('Target route mismatch')
  target=frozen.target_path(root,q['prefix_key']);immutable(target,p.read_bytes())
  spec['target_reference_path']=str(target);sp=root/'controlled-specs'/Path(j['controlled_spec_path']).name;immutable(sp,(json.dumps(spec,sort_keys=True,indent=2)+'\n').encode())
  j.update(campaign_root=str(root),controlled_target_root=str(root),control_target_path=str(target),controlled_dependency=str(target),controlled_spec_path=str(sp),controlled_spec_sha256=sha(sp),timeout_seconds=3600,
   recovery_v13={'prior_native_attempts':q['prior_native_attempts_lower_bound'],'prior_attempt_proofs':q['prior_attempt_proofs'],'max_cumulative_attempts':3,'new_max_iterations':500,'old_max_iterations':spec['max_rounds'],'target_source':str(p),'target_source_sha256':sha(p),'target_bytes_unchanged':sha(p)==sha(target),'calibration_reference':t['calibration'],'science':'same prefix/native and first actual target; 500-round new continuation budget; original calibration excluded from accuracy'})
  jobs.append(j)
 plan={'version':'controlled-dependency-recovery-v13','source_plan':str(SOURCE/'plan.json'),'source_plan_sha256':sha(SOURCE/'plan.json'),'audit_sha256':sha(auditpath),'jobs':jobs,'blocked':blocked,'concurrency':16,'implementation_sha256':{n:sha(ROOT/'scripts'/n) for n in ['run_controlled_dependency_recovery_v13.py','network_entry_v13.py']}}
 immutable(root/'plan.json',(json.dumps(plan,sort_keys=True,indent=2)+'\n').encode());return plan

def worker(specpath,out):
 job=read(specpath);root=Path(job['campaign_root']);plan=read(root/'plan.json')
 if job not in plan['jobs']:raise ValueError('Job is not frozen')
 for n,h in plan['implementation_sha256'].items():
  if sha(ROOT/'scripts'/n)!=h:raise ValueError('Operational source changed')
 if (out/'attempt-started.json').exists():raise ValueError('No duplicate native launch')
 original=frozen.validate
 def validate(j,d):
  spec,cfg=original(j,d)
  save(d/'v13-operational-budget.json',{'previous_max_iterations':spec['max_rounds'],'actual_max_iterations':500,'timeout_seconds':3600,'original_source_prefix_unchanged':True,'original_native_and_target_validated':True})
  return {**spec,'max_rounds':500},cfg
 sys.argv=[frozen.__file__,'--spec',str(specpath),'--out',str(out),'--live']
 with patch.object(frozen,'validate',validate):frozen.main()

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,default=DEFAULT);ap.add_argument('--audit',type=Path,default=ROOT/'outputs/recovery-controlled-info-v13/audit.json');ap.add_argument('--prepare',action='store_true');ap.add_argument('--live',action='store_true');ap.add_argument('--worker-spec',type=Path);ap.add_argument('--out',type=Path);a=ap.parse_args()
 if a.worker_spec:
  if not a.live:raise ValueError('Explicit live worker required')
  a.out.mkdir(parents=True,exist_ok=True);worker(a.worker_spec,a.out);return
 root=a.root.resolve();root.mkdir(parents=True,exist_ok=True)
 plan=prepared(root,a.audit) if a.prepare else read(root/'plan.json')
 if not a.live:print(json.dumps({'live':False,'eligible_text_jobs':len(plan['jobs']),'blocked':len(plan['blocked']),'restored_targets':len(list((root/'control-targets').glob('*.json')))}));return
 lease=(root/'run.lock').open('a');fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB);active={};stopping=False
 def stop(*args):
  nonlocal stopping
  stopping=True
 signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
 env,_=environment(ROOT,'hermes');jobs=plan['jobs']
 while True:
  if (root/'STOP').exists():stopping=True
  for jid,(p,d,started,handle) in list(active.items()):
   if p.poll() is None and time.monotonic()-started>3600:
    os.killpg(p.pid,signal.SIGTERM);time.sleep(2)
    if p.poll() is None:os.killpg(p.pid,signal.SIGKILL)
   if p.poll() is not None:
    status=read(d/'native-result.json').get('status') if(d/'native-result.json').exists() else 'timeout' if time.monotonic()-started>=3600 else 'failed'
    save(d/'controller-terminal.json',{'status':status,'exit_code':p.returncode,'elapsed':time.monotonic()-started,'pid':p.pid});handle.close();del active[jid]
  eligible=[]
  for j in jobs:
   parent=root/'jobs'/j['job_id'];attempts=sorted(parent.glob('attempt_*'));done=[read(d/'controller-terminal.json') for d in attempts if(d/'controller-terminal.json').exists()]
   if any(x['status']=='completed' for x in done) or j['job_id'] in active:continue
   if any(not(d/'controller-terminal.json').exists() for d in attempts):continue # Unknown prior start stays blocked.
   if len(attempts)+j['recovery_v13']['prior_native_attempts']>=3:continue
   if done and done[-1]['status']!='timeout':continue # Scientific failures never automatically repeated.
   eligible.append((j,parent,len(attempts)+1))
  if not stopping:
   for j,parent,n in eligible[:max(0,16-len(active))]:
    d=parent/f'attempt_{n:03d}';d.mkdir(parents=True,exist_ok=False);sp=d/'job.json';save(sp,j);log=(d/'worker.log').open('a')
    cmd=[python_for(ROOT),str(ROOT/'scripts/network_entry_v13.py'),'--target',str(Path(__file__).resolve()),'--worker-spec',str(sp),'--out',str(d),'--live']
    p=subprocess.Popen(cmd,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True);save(d/'dispatch.json',{'pid':p.pid,'started_at':time.time(),'cumulative_attempt':j['recovery_v13']['prior_native_attempts']+n});active[j['job_id']]=(p,d,time.monotonic(),log)
  save(root/'status.json',{'at':time.time(),'active':list(active),'remaining_dispatch_candidates':len(eligible),'stop_dispatch':stopping,'concurrency':16})
  if not active and (stopping or not eligible):break
  time.sleep(3)
if __name__=='__main__':main()
