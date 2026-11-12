"""Verify the final DSH evaluation observer maxSteps before the native launch."""
import argparse,hashlib,json
from pathlib import Path
from unittest.mock import patch
import run_dsh_eval_v3 as native
import dsh_retry3_worker_v11 as previous
from turns500_contract_v12 import VERSION

def verify_observer(env):
    workspace=Path(env['ACL_WORKSPACE']);path=workspace.parent/'evaluation.patch.json'
    rows=json.loads(path.read_text());values=[p['config']['maxSteps']for row in rows for p in row.get('insert',[])if p.get('id')=='acl-evaluation']
    if values!=[500] or type(values[0]) is not int:raise ValueError('Actual DSH maxSteps must equal 500')
    out=workspace/'metrics/turn-limit-binding-v12.json';out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps({'version':VERSION,'harness':'dsh','actual_evaluation_maxSteps':500,
      'observer_path':str(path),'observer_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'model_calls_by_observer':0}))

def main():
    p=argparse.ArgumentParser(add_help=False);p.add_argument('--config',type=Path,required=True);a,_=p.parse_known_args();cfg=json.loads(a.config.read_text())
    if cfg.get('turn_limit_version')!=VERSION or cfg.get('bc100',{}).get('max_rounds')!=500:raise ValueError('Explicit native DSH turn policy required')
    original=native.command
    def command(root,harness,prompt,env):
        argv=original(root,harness,prompt,env);verify_observer(env);return argv
    with patch.object(native,'command',command):previous.main()

if __name__=='__main__':main()
