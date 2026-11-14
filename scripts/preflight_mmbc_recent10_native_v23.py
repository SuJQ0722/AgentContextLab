"""Exercise migrated native entry through all contracts, intercepting first SDK call."""
import argparse
import contextlib
import json
from pathlib import Path
import runpy
import sys
import time
from unittest.mock import patch
import httpx
from openai.resources.chat.completions import Completions
from lab import ROOT
from recovery_once_entry_v23 import install_contract
install_contract()
from run_recovery_once_trial_v23 import native_command
from recovery_once_contract_v23 import validate_authorization,validate_turns
from prepare_visual_hosted_retry_v1 import load_validate
from report_once24h_v15 import atomic
import hashlib
class Boundary(BaseException):pass
class DeniedHTTP(BaseException):pass

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def main():
    p=argparse.ArgumentParser();p.add_argument('--cell',required=True);a=p.parse_args()
    root=ROOT/'outputs/campaigns/mmbc-recent10-pending-v23/cells'/a.cell
    plan,_=load_validate(root);job=plan['jobs'][0]
    out=ROOT/'outputs/preflight'/('core-recent10-native-v23-'+a.cell+'-'+str(time.time_ns()));out.mkdir(parents=True)
    sp=out/'spec.json';spec={**job,'campaign_root':str(root),'plan_sha256':sha(root/'plan.json'),'cohort_sha256':plan['definition']['cohort_sha256'],'_spec_path':str(sp)};sp.write_text(json.dumps(spec))
    validate_authorization(spec);validate_turns(spec,json.loads(Path(spec['config_path']).read_text()))
    command,_,timeout=native_command(spec,out);assert Path(command[1]).name=='hermes_core_recent_ten_worker_v23.py'and'--live'in command
    sdk=[];http=[];code=None;err=None
    def intercepted(client,*args,**kwargs):
        sdk.append({'model':kwargs.get('model'),'max_tokens':kwargs.get('max_tokens'),'messages':len(kwargs.get('messages',[])),'messages_sha256':hashlib.sha256(json.dumps(kwargs.get('messages',[]),sort_keys=True).encode()).hexdigest()});raise Boundary()
    def denied(client,request,*args,**kwargs):http.append({'method':request.method});raise DeniedHTTP()
    with(out/'initialization.log').open('w')as log:
        with contextlib.redirect_stdout(log),contextlib.redirect_stderr(log):
            try:
                with patch.object(sys,'argv',command[1:]),patch.object(Completions,'create',intercepted),patch.object(httpx.Client,'send',denied):
                    runpy.run_path(command[1],run_name='__main__')
            except SystemExit as e:code=e.code
            except BaseException as e:err=type(e).__name__
    native=Path(command[command.index('--out')+1]);bp=native/'metrics/core-image-policy-binding-v23.json';binding=json.loads(bp.read_text())if bp.exists()else{}
    passed=1<=len(sdk)<=3 and len({(x['model'],x['max_tokens'],x['messages_sha256'])for x in sdk})==1 and not http and err is None and code in(None,0)and binding.get('native_image_policy')=='core_recent10'and binding.get('core_transport_version')=='core-page-caps-then-recent-ten-v22'
    result={'at':time.time(),'cell':a.cell,'slot_id':spec['slot_id'],'new_authorized_ordinal':spec['new_authorized_ordinal'],'plan_sha256':sha(root/'plan.json'),
        'external_model_calls':0,'native_api_retry_cap_unchanged':3,'sdk_boundaries':sdk,'http_sends_denied':http,'native_entry':command[1],'native_entry_sha256':sha(command[1]),
        'policy_binding_path':str(bp),'policy_binding_sha256':sha(bp)if bp.exists()else None,'policy_binding':binding,'error_type':err,'exit_code':code,
        'source_sha256':sha(__file__),'timeout_seconds':timeout,'passed':passed,'output_path':str(out)}
    atomic(out/'readiness.json',result);print(json.dumps(result));raise SystemExit(0 if passed else 1)
if __name__=='__main__':main()
