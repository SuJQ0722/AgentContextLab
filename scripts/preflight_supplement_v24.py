"""Actual native initialization with SDK/HTTP/process boundaries denied. No paid calls."""
import argparse, contextlib, copy, json, subprocess, sys, time, traceback
from pathlib import Path
from unittest.mock import patch
import httpx
from openai.resources.chat.completions import Completions
from lab import ROOT
import supplement_worker_v24 as worker

class Boundary(BaseException): pass
class UnexpectedHTTP(BaseException): pass

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);ap.add_argument('--job',required=True)
    a=ap.parse_args();plan=json.loads((a.root/'plan.json').read_text())
    job=copy.deepcopy(next(j for j in plan['jobs'] if j['job_id']==a.job))
    out=ROOT/'outputs/preflight'/('supplement-init-'+a.job+'-'+str(time.time_ns()));out.mkdir(parents=True)
    native=out/'jobs'/a.job/'attempts/attempt_001/native';native.mkdir(parents=True)
    if job['scope']=='controlled':job['controlled_job']['output_path']=str(native)
    sp=out/'spec.json';sp.write_text(json.dumps(job));calls=[];http=[];frames=[];error=None
    def intercepted(*args,**kwargs):
        calls.append({'boundary':'sdk','max_tokens':kwargs.get('max_tokens')});raise Boundary()
    def denied(*args,**kwargs):http.append(True);raise UnexpectedHTTP()
    original_popen=subprocess.Popen
    def popen(command,*args,**kwargs):
        if job['harness']=='dsh' and any(str(x).endswith('deepseekHarness/apps/cli/lib/bin.js') for x in command):
            calls.append({'boundary':'native_process'});raise Boundary()
        return original_popen(command,*args,**kwargs)
    with (out/'initialization.log').open('w') as log, contextlib.redirect_stdout(log),contextlib.redirect_stderr(log):
        try:
            with patch.object(sys,'argv',['supplement_worker_v24','--spec',str(sp),'--out',str(native),'--live']),patch.object(Completions,'create',intercepted),patch.object(httpx.Client,'send',denied),patch.object(subprocess,'Popen',popen):worker.main()
        except BaseException as exc:
            error=type(exc).__name__;frames=[{'file':f.filename,'line':f.lineno,'function':f.name} for f in traceback.extract_tb(exc.__traceback__)]
    bindings=[json.loads(p.read_text()) for p in native.rglob('turn-limit-v24.json')]
    passed=bool(calls) and not http and bool(bindings) and error in (None,'Boundary','SystemExit')
    result={'job_id':a.job,'passed':passed,'model_calls':0,'boundaries':calls,'http_denied':len(http),'error':error,'frames':frames,'bindings':bindings,'output':str(out)}
    (out/'readiness.json').write_text(json.dumps(result,indent=2));print(json.dumps(result));return 0 if passed else 1

if __name__=='__main__':sys.exit(main())
