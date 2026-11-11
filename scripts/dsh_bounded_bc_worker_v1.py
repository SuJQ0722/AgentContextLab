#!/usr/bin/env python3
"""Versioned DSH wrapper: bounded shared policy plus final serialized-body guard."""
import argparse
import hashlib
import json
from pathlib import Path
from unittest.mock import patch
import run_dsh_eval_v3 as native
from lab import ROOT

PROTOCOL='bc-bounded-pages-v1'
BOUNDED_SOURCE_FILES=[
    'scripts/'+n for n in (
        'shared_context_bounded_bc_v1.py','dsh_bounded_wire_guard_v1.mjs','dsh_bounded_registry_v1.py',
        'rq3_bounded_renderer_v2.py','bounded_lossless_transport_v1.py','hermes_bounded_rq3_worker_v1.py',
        'run_dsh_eval_v3.py','dsh_wire_image_guard.mjs','dsh_raw_usage_observer.mjs','dsh_wire_expectations.mjs','dsh_pre_sdk_images.mjs',
        'dsh_image_preservation.py','native_image_origins.py','shared_context_policy.py','rq3_pdf_renderer.py',
        'local_web.py','review_execution.py','lab.py','hermes_tool_bridge.py')
]+['plugins/'+n for n in (
    'dsh-context/hermes-policy-v3.mjs','dsh-context/shared-surface.mjs','dsh-context/content.mjs','dsh-context/image-data-url-cache.mjs',
    'dsh-evaluation/index.mjs','dsh-local-web/hermes-tools-v2.mjs')]

SOURCES=('dsh_bounded_bc_worker_v1.py','shared_context_bounded_bc_v1.py','dsh_bounded_wire_guard_v1.mjs')

def validate(config):
    if config.get('bounded_bc_protocol')!=PROTOCOL or config.get('bounded_transport_encoding')!='bounded-canvas-lossless-webp-v1':
        raise ValueError('Explicit bounded BC/transport configuration required')
    expected={'history_scale':.75,'font_size':16,'image_width':1024,'max_image_height':2048,
              'history_max_image_height':2048,'keep_rounds':1,'recent_rounds':5,'text_only':False}
    settings=config.get('shared_policy',{}).get('strategy_configs',{}).get('visual',{})
    if any(settings.get(k)!=v for k,v in expected.items()) or config.get('visual_renderer',{}).get('history_scale')!=.75:
        raise ValueError('Explicit bounded BC geometry mismatch')

def main():
    p=argparse.ArgumentParser(add_help=False);p.add_argument('--config',type=Path,required=True)
    p.add_argument('--dataset',required=True);p.add_argument('--strategies',nargs='+',required=True)
    p.add_argument('--output-root',type=Path,required=True);a,_=p.parse_known_args()
    config=json.loads(a.config.read_text());validate(config)
    if a.dataset!='bc100' or a.strategies!=['visual_native']:raise ValueError('Bounded DSH supports BC visual only')
    original_command=native.command;original_policy=native.policy_config
    def policy(strategy,cfg,save_dir):
        value=original_policy(strategy,cfg,save_dir);value['strategy_config']['bounded_bc_protocol']=PROTOCOL;return value
    def command(root,harness,prompt,env):
        if harness!='dsh':raise ValueError('Expected DSH runtime')
        workspace=Path(env['ACL_WORKSPACE']).resolve();overlay=workspace.parent/'research.patch.yml'
        value=json.loads(overlay.read_text());found=[]
        for operation in value:
            for plugin in operation.get('insert',[]):
                if plugin.get('id')=='acl-hermes-shared-compaction':found.append(plugin)
        if len(found)!=1 or found[0]['name']!=str(ROOT/'plugins/dsh-context/hermes-policy-v3.mjs'):
            raise ValueError('Expected original reviewed shared-policy plugin')
        pc=found[0]['config']
        if pc['sharedPolicy']!=str(ROOT/'scripts/shared_context_policy.py') or pc['policyConfig'].get('strategy_config',{}).get('bounded_bc_protocol')!=PROTOCOL:
            raise ValueError('Unexpected shared policy helper/configuration')
        pc['sharedPolicy']=str(ROOT/'scripts/shared_context_bounded_bc_v1.py')
        overlay.write_text(json.dumps(value))
        old=str(ROOT/'scripts/dsh_wire_image_guard.mjs');options=env.get('NODE_OPTIONS','')
        if old not in options:raise ValueError('Reviewed original image wire guard absent')
        preload=str(ROOT/'scripts/dsh_bounded_wire_guard_v1.mjs')
        if preload in options:raise ValueError('Bounded preload already present')
        # This inner fetch guard installs first; the existing outer guard applies
        # exact Hermes image detail, then sends its final serialized bytes here.
        env['NODE_OPTIONS']='--import '+preload+' '+options
        env['ACL_BOUNDED_PYTHON']=pc['python']
        env['ACL_BOUNDED_CANVAS_ROOT']=str(workspace/'metrics/raw-canvases')
        env['ACL_BOUNDED_WIRE_LEDGER']=str(workspace/'metrics/bounded-request-guard.jsonl')
        (workspace.parent/'bounded-dsh-protocol.json').write_text(json.dumps({'protocol':PROTOCOL,
            'helper':pc['sharedPolicy'],'preload_before_existing':True,'far_scale':.75,'recent_scale':1.,
            'native_images_unchanged':True,'source_sha256':{n:hashlib.sha256((ROOT/'scripts'/n).read_bytes()).hexdigest() for n in SOURCES}},indent=2))
        return original_command(root,harness,prompt,env)
    with patch.object(native,'policy_config',policy),patch.object(native,'command',command):native.main()

if __name__=='__main__':main()
