"""Explicit operational proxy replacement; retain frozen inference code and budgets.

Every spawned Python script inherits this entrypoint. Secrets are read from a
private file, never argv or telemetry. The deployment binding records actual
network endpoint separately from historical frozen config values.
"""
import sys,os,json,runpy,subprocess,hashlib,time
from pathlib import Path
ROOT=Path('/mnt/afs_agents/sujiaqi/workspace/projects/AgentContextLab')
PRIVATE=ROOT/'outputs/private-network/proxy-recovery-v13.json'
OLD='http://10.120.0.246:7890'
ENTRY=Path(__file__).resolve()

def apply(proxy):
 import httpx
 original_init=httpx.Client.__init__
 def init(self,*a,**kw):
  if kw.get('proxy')==OLD:kw['proxy']=proxy
  return original_init(self,*a,**kw)
 httpx.Client.__init__=init
 def envfix(env):
  result=dict(env)
  for k in ('http_proxy','https_proxy','HTTP_PROXY','HTTPS_PROXY'):result[k]=proxy
  for k in ('all_proxy','ALL_PROXY'):result.pop(k,None)
  return result
 os.environ.update(envfix(os.environ))
 import lab
 original_environment=lab.environment
 def environment(*a,**kw):
  env,cfg=original_environment(*a,**kw);return envfix(env),cfg
 lab.environment=environment
 import bootstrap_mmbc100_cci as boot
 research=boot.research_environment
 boot.research_environment=lambda *a,**kw:envfix(research(*a,**kw))
 import visual_transport_runtime_v4 as transport
 old_install=transport.install
 def install(*a,**kw):
  if kw.get('gateway_proxy')==OLD:kw['gateway_proxy']=proxy
  return old_install(*a,**kw)
 transport.install=install
 original_popen=subprocess.Popen
 class WrappedPopen(original_popen):
  def __init__(self,args,*a,**kw):
   command=list(args)if isinstance(args,(list,tuple))else args
   if isinstance(command,list) and len(command)>1 and 'python' in Path(str(command[0])).name:
    target=Path(str(command[1]))
    if target.suffix=='.py' and target.resolve()!=ENTRY:
     command=[command[0],str(ENTRY),'--target',str(target),*command[2:]]
   if kw.get('env') is not None:kw['env']=envfix(kw['env'])
   super().__init__(command,*a,**kw)
 subprocess.Popen=WrappedPopen
 return envfix

def main():
 if len(sys.argv)<3 or sys.argv[1]!='--target':raise SystemExit('Expected --target script.py')
 target=Path(sys.argv[2]).resolve();argv=sys.argv[3:]
 if not target.is_file():raise ValueError('Target missing')
 if PRIVATE.stat().st_mode&0o077:raise ValueError('Proxy credential file must be private')
 deployment=json.loads(PRIVATE.read_text());proxy=deployment['proxy']
 sys.path.insert(0,str(ROOT/'scripts'));sys.path.insert(0,str(target.parent))
 apply(proxy)
 # Attach actual operational transport identity to each worker artifact.
 if '--out' in argv:
  out=Path(argv[argv.index('--out')+1]);out.mkdir(parents=True,exist_ok=True)
  from urllib.parse import urlsplit
  p=urlsplit(proxy)
  (out/'network-deployment-v13.json').write_text(json.dumps({'at_unix':time.time(),'version':'proxy-recovery-v13','target':target.name,'actual_proxy_host':p.hostname,'actual_proxy_port':p.port,'proxy_has_auth':bool(p.username),'entry_sha256':hashlib.sha256(ENTRY.read_bytes()).hexdigest(),'science_and_attempt_budgets_unchanged':True}))
 sys.argv=[str(target),*argv]
 runpy.run_path(str(target),run_name='__main__')
if __name__=='__main__':main()
