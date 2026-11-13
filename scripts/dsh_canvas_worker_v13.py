"""V12 visual worker with independent handle-aware bridge and unchanged budgets."""
import argparse,json,hashlib
from pathlib import Path
from unittest.mock import patch
from lab import ROOT
import run_dsh_eval_v3 as native
import dsh_turns500_worker_v12 as previous
VERSION='dsh-canvas-handle-segments-v13'

def main():
    p=argparse.ArgumentParser(add_help=False);p.add_argument('--config',type=Path,required=True);p.add_argument('--timeout',type=int,required=True);a,_=p.parse_known_args()
    cfg=json.loads(a.config.read_text())
    if a.timeout!=3600 or cfg.get('timeout_seconds')!=3600 or cfg.get('max_output_tokens')!=8192:raise ValueError('Preserve one-hour/8192 budgets')
    original=native.command
    def command(root,harness,prompt,env):
        argv=original(root,harness,prompt,env)
        old=str(ROOT/'scripts/dsh_inline_wire_v5.mjs');new=str(ROOT/'scripts/dsh_inline_wire_v13.mjs')
        if env.get('NODE_OPTIONS','').count(old)!=1:raise ValueError('Expected exactly one one-hour wire preload')
        env['NODE_OPTIONS']=env['NODE_OPTIONS'].replace(old,new)
        metrics=Path(env['ACL_WORKSPACE'])/'metrics'
        (metrics/'canvas-handle-repair-v13.json').write_text(json.dumps({'version':VERSION,'timeout_seconds':3600,'max_rounds':500,'max_output_tokens':8192,'page_budget':{'history':5,'recent':2},'max_images':10,'frozen_harness_modified':False,'wire_sha256':hashlib.sha256(Path(new).read_bytes()).hexdigest()}))
        return argv
    with patch.object(native,'command',command):previous.main()
if __name__=='__main__':main()
