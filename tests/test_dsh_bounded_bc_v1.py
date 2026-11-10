"""Actual renderer and final request boundary, without provider/network calls."""
import base64
import copy
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
sys.path.insert(0,str(ROOT/'tests'))
import dsh_bounded_bc_worker_v1 as worker
from lab import environment,python_for
from test_bounded_multimodal_renderer_v1 import fixture,png,part

SETTINGS={'history_scale':.75,'font_size':16,'image_width':1024,'max_image_height':2048,'history_max_image_height':2048,'keep_rounds':1,'recent_rounds':5,'text_only':False}
def config():return {'bounded_bc_protocol':worker.PROTOCOL,'bounded_transport_encoding':'bounded-canvas-lossless-webp-v1','visual_renderer':{'history_scale':.75},'shared_policy':{'strategy_configs':{'visual':dict(SETTINGS)}}}

class DSHBoundedTests(unittest.TestCase):
    def node(self,code,args=(),env_extra=None):
        env,_=environment(ROOT,'dsh');env.pop('NODE_OPTIONS',None)
        for k in list(env):
            if k.startswith('ACL_BOUNDED_') or k.startswith('ACL_IMAGE_WIRE_'):env.pop(k)
        env.update(env_extra or {})
        result=subprocess.run(['node','--input-type=module','-e',code,*map(str,args)],env=env,cwd=ROOT,capture_output=True,text=True,timeout=150)
        self.assertEqual(result.returncode,0,result.stderr[-5000:]);return result.stdout

    def test_overlay_preserves_plugins_and_observer_with_correct_guard_order(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);cp=root/'cfg.json';cp.write_text(json.dumps(config()));workspace=root/'run/workspace';workspace.mkdir(parents=True)
            old=str(ROOT/'scripts/dsh_wire_image_guard.mjs');env={'ACL_WORKSPACE':str(workspace),'NODE_OPTIONS':'--import '+old}
            untouched={'id':'observer','name':str(ROOT/'plugins/dsh-evaluation/index.mjs'),'config':{'fixture':True}}
            called=[]
            def policy(strategy,cfg,save):return {'strategy_config':dict(SETTINGS)}
            def original(root,harness,prompt,env):called.append(env.copy());return ['original']
            def main():
                value=worker.native.policy_config('visual',{},'unused')
                overlay=[{'insert':[{'id':'acl-hermes-shared-compaction','name':str(ROOT/'plugins/dsh-context/hermes-policy-v3.mjs'),'config':{'sharedPolicy':str(ROOT/'scripts/shared_context_policy.py'),'policyConfig':value,'python':python_for(ROOT)}},untouched]}]
                (workspace.parent/'research.patch.yml').write_text(json.dumps(overlay))
                self.assertEqual(worker.native.command(ROOT,'dsh','prompt',env),['original'])
                actual=json.loads((workspace.parent/'research.patch.yml').read_text())
                self.assertEqual(actual[0]['insert'][1],untouched)
                self.assertEqual(actual[0]['insert'][0]['config']['sharedPolicy'],str(ROOT/'scripts/shared_context_bounded_bc_v1.py'))
            with patch.object(worker.native,'main',main),patch.object(worker.native,'command',original),patch.object(worker.native,'policy_config',policy),patch.object(sys,'argv',['entry','--config',str(cp),'--dataset','bc100','--strategies','visual_native','--output-root',str(root)]):worker.main()
            self.assertTrue(called[0]['NODE_OPTIONS'].startswith('--import '+str(ROOT/'scripts/dsh_bounded_wire_guard_v1.mjs')))
            self.assertEqual(called[0]['NODE_OPTIONS'].split()[-1],old)
            self.assertTrue(all((ROOT/p).is_file() for p in worker.BOUNDED_SOURCE_FILES))
            with self.assertRaises(ValueError):worker.validate({**config(),'bounded_bc_protocol':'wrong'})

    def test_real_ipc_and_direct_hermes_pixel_parity_and_registry_tamper(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);source=root/'source';source.mkdir();messages=fixture(source)
            request={'strategy':'visual','messages':messages,'provider_usage':{'prompt_tokens':40000,'completion_tokens':20},'config':{'model':'fixture','context_length':65536,'threshold_tokens':32768,'strategy_config':{**SETTINGS,'bounded_bc_protocol':worker.PROTOCOL,'save_dir':str(root/'dsh')}}}
            env,_=environment(ROOT,'hermes')
            r=subprocess.run([python_for(ROOT),str(ROOT/'scripts/shared_context_bounded_bc_v1.py')],input=json.dumps(request),env=env,capture_output=True,text=True,cwd=ROOT,timeout=150)
            self.assertEqual(r.returncode,0,r.stderr[-1000:]);actual=json.loads(r.stdout)
            self.assertEqual(actual['status'],'compressed',str(actual)[:1000]);self.assertEqual(actual['compression_count'],1)
            self.assertEqual(actual['messages'][:2],messages[:2]);self.assertEqual(actual['messages'][-2:],messages[-2:])
            self.assertGreater(actual['timings']['renderer_calls'],0);stats=actual['render_stats'];self.assertTrue(stats['transport_pixel_identity_verified']);self.assertTrue(stats['source_image_coverage_verified'])
            direct_request=copy.deepcopy(request);direct_request['config']['strategy_config']['save_dir']=str(root/'hermes')
            code="import sys,json;sys.path.insert(0,'scripts');import shared_context_policy as s;from rq3_bounded_renderer_v2 import install;from bounded_lossless_transport_v1 import install as encode;r=json.load(sys.stdin);e=s.make_engine('visual',r['config']);from plugins.context_engine.visual import render;install(render);encode(render);e.update_from_response(r['provider_usage']);print(json.dumps(e.compress(r['messages'],current_tokens=40000)))"
            r=subprocess.run([python_for(ROOT),'-c',code],input=json.dumps(direct_request),env=env,capture_output=True,text=True,cwd=ROOT,timeout=150)
            self.assertEqual(r.returncode,0,r.stderr[-2000:]);expected=json.loads(r.stdout)
            # Entire output bytes/message structure match identical shared Hermes rendering.
            self.assertEqual(actual['messages'],expected)
            code="import {registry} from './scripts/dsh_bounded_wire_guard_v1.mjs';const s=registry(process.argv[1]);if(s.size<4)throw Error('missing pages');console.log(s.size)"
            self.node(code,[root/'dsh'],{'ACL_BOUNDED_PYTHON':python_for(ROOT)})
            encoded=next((root/'dsh').glob('*.webp'));encoded.write_bytes(encoded.read_bytes()+b'changed')
            code="import {registry} from './scripts/dsh_bounded_wire_guard_v1.mjs';let rejected=false;try{registry(process.argv[1])}catch{rejected=true}if(!rejected)throw Error('tamper accepted')"
            self.node(code,[root/'dsh'],{'ACL_BOUNDED_PYTHON':python_for(ROOT)})

    def test_final_serialized_guard_order_preserves_pixels_and_raw_usage(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);raw=png();digest=hashlib.sha256(raw).hexdigest();payload={'model':'fixture/huoshan/huoshan','messages':[{'role':'user','content':[part(raw)]}]};(root/'body.json').write_text(json.dumps(payload))
            (root/'expected.json').write_text(json.dumps({'wire_sha256':[digest],'details':['high'],'session_id':'fixture','purpose':'agent'}))
            extra={'ACL_BOUNDED_CANVAS_ROOT':str(root/'canvas'),'ACL_BOUNDED_WIRE_LEDGER':str(root/'guard.jsonl'),'ACL_BOUNDED_PYTHON':python_for(ROOT),'ACL_IMAGE_WIRE_AUDIT_DIR':str(root/'wire'),'ACL_IMAGE_WIRE_EXPECTED':str(root/'expected.json'),'ACL_IMAGE_WIRE_APPLY_DETAILS':'1'}
            code=r"""
import fs from 'node:fs';import crypto from 'node:crypto';
const root=process.argv[1];let count=0,last;
globalThis.fetch=async(input,init)=>{count++;last=init.body;const b=JSON.parse(last);if(b.messages[0].content[0].image_url.detail!=='high')throw Error('wrong outer order');return new Response(JSON.stringify({usage:{prompt_tokens:100,prompt_cache_hit_tokens:60,prompt_cache_miss_tokens:40,completion_tokens:7,total_tokens:107}}),{headers:{'content-type':'application/json'}})};
await import('./scripts/dsh_bounded_wire_guard_v1.mjs');await import('./scripts/dsh_wire_image_guard.mjs');
const body=fs.readFileSync(root+'/body.json','utf8');await fetch('https://fixture.invalid/v1/chat/completions',{method:'POST',body});
const {flushUsageObservers}=await import('./scripts/dsh_raw_usage_observer.mjs');await flushUsageObservers();
const rows=fs.readFileSync(root+'/guard.jsonl','utf8').trim().split('\n').map(JSON.parse);if(rows[0].body_bytes!==Buffer.byteLength(last)||rows[0].body_sha256!==crypto.createHash('sha256').update(last).digest('hex'))throw Error('not final body');
const usage=fs.readFileSync(root+'/wire/raw-usage.jsonl','utf8').trim().split('\n').map(JSON.parse).find(x=>x.observation_status==='complete');if(usage.cached_input_tokens!==60||usage.noncache_input_tokens!==40||usage.output_tokens!==7||!usage.conservation.valid)throw Error('usage lost');
const huge=JSON.parse(body);huge.padding='x'.repeat(8*1024*1024);let blocked=false;try{await fetch('https://fixture.invalid/v1/chat/completions',{body:JSON.stringify(huge)})}catch{blocked=true}if(!blocked||count!==1)throw Error('oversize network attempt');await flushUsageObservers();
"""
            self.node(code,[root],extra)

    def test_image_count_and_native_evidence_geometry(self):
        raw=png(width=2200,height=10);body={'messages':[{'role':'user','content':[part(raw)]}]}
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'body';path.write_text(json.dumps(body));digest=hashlib.sha256(raw).hexdigest()
            code=r"""
import fs from 'node:fs';import {inspectBody} from './scripts/dsh_bounded_wire_guard_v1.mjs';const b=fs.readFileSync(process.argv[1]);if(inspectBody(b,new Set()).violations.length)throw Error('native evidence resized/rejected');if(!inspectBody(b,new Set([process.argv[2]])).violations.includes('canvas_exceeds_geometry'))throw Error('canvas unbounded');const p=JSON.parse(b);p.messages[0].content=Array(33).fill(p.messages[0].content[0]);if(!inspectBody(JSON.stringify(p),new Set()).violations.includes('image_count_exceeds_32'))throw Error('image count unbounded');
"""
            self.node(code,[path,digest])

if __name__=='__main__':unittest.main()
