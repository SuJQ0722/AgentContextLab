"""Frozen-options-safe middleware and final CLI separator, isolated from V8 code."""
import argparse
import hashlib
import json
from pathlib import Path
from unittest.mock import patch
from lab import ROOT
import run_dsh_eval_v3 as native
import dsh_inline_bc_worker_v7 as visual
import dsh_baseline_inline_worker_v8 as baseline
from dsh_inline_bc_worker_v4 import separate_prompt


def main():
    p=argparse.ArgumentParser(add_help=False);p.add_argument('--strategies',nargs='+',required=True);args,_=p.parse_known_args()
    original_command,original_popen=native.command,native.subprocess.Popen
    def command(root,harness,prompt,env):
        overlay=Path(env['ACL_WORKSPACE']).parent/'evaluation.patch.json'
        patches=json.loads(overlay.read_text());count=0
        for item in patches:
            for plugin in item.get('insert',[]):
                if plugin.get('id')=='acl-wire-expectations':
                    if Path(plugin['name'])!=ROOT/'scripts/dsh_wire_expectations.mjs':raise ValueError('Unexpected original wire observer')
                    plugin['name']=str(ROOT/'scripts/dsh_wire_expectations_v9.mjs');count+=1
        if count!=1:raise ValueError('Exactly one native wire observer required')
        overlay.write_text(json.dumps(patches))
        report=Path(env['ACL_WORKSPACE'])/'metrics/readonly-options-repair-v9.json'
        report.parent.mkdir(parents=True,exist_ok=True)
        report.write_text(json.dumps({'version':'dsh-readonly-options-recovery-v9','middleware_sha256':hashlib.sha256((ROOT/'scripts/dsh_wire_expectations_v9.mjs').read_bytes()).hexdigest(),
            'upstream_modified':False,'native_messages_mutated':False,'image_count_limit':10,'final_cli_separator':True}))
        return original_command(root,harness,prompt,env)
    def popen(cmd,*pos,**kw):return original_popen(separate_prompt(cmd),*pos,**kw)
    with patch.object(native,'command',command),patch.object(native.subprocess,'Popen',popen),patch.object(baseline,'separate_prompt',lambda cmd:cmd):
        (visual if args.strategies==['visual_native'] else baseline).main()


if __name__=='__main__':main()
