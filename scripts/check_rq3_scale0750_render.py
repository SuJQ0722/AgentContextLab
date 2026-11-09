#!/usr/bin/env python3
"""No-API PDF-renderer intervention check, with enough rounds for far history."""
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from lab import ROOT,environment,python_for


def main():
    if '--worker' not in sys.argv:
        env,_=environment(ROOT,'hermes')
        raise SystemExit(subprocess.call([python_for(ROOT),__file__,'--worker'],env=env))
    sys.path.insert(0,str(ROOT/'hermes-agent'))
    from plugins.context_engine.visual import render
    from rq3_pdf_renderer import install
    renderer_implementation=install()
    from render_dsh_history import RenderFailures,reject_fallback
    from unittest.mock import patch
    from run_rq3_parity_v3 import label
    SCALES=(.75,1.)
    from PIL import Image
    import io
    out=ROOT/'outputs/preflight'/f'rq3-scale0750-render-{time.time_ns()}';out.mkdir(parents=True)
    messages=[]
    for i in range(14):
        messages.extend([{'role':'assistant','content':'Inspect source evidence.','tool_calls':[{'id':str(i),'type':'function',
            'function':{'name':'web_fetch','arguments':json.dumps({'url':f'https://example.org/{i}'})}}]},
            {'role':'tool','tool_call_id':str(i),'content':f'Round {i}, record XR-{i:03d}.\n'+ '\n'.join(f'Source row {j}: retain entity Cedar and measured quantity {1000+i*30+j}.' for j in range(20))}])
    records=[];failures=RenderFailures();render.logger.addHandler(failures)
    try:
        with patch.object(render,'_text_to_images_fallback',reject_fallback):
            for scale in SCALES:
                dest=out/label(scale);dest.mkdir();stats={}
                result=render.render_visual_compression(messages,head_end=0,keep_rounds=0,recent_rounds=5,font_size=16,
                    history_scale=scale,save_dir=str(dest),stats=stats)
                if failures.errors:raise RuntimeError('PDF renderer failed: '+'; '.join(failures.errors))
                images=[p for m in result for p in m.get('content',[]) if isinstance(p,dict) and p.get('type')=='image_url']
                if not images:raise RuntimeError('No rendered image')
                blobs=[base64.b64decode(p['image_url']['url'].split(',',1)[1]) for p in images]
                records.append({'scale':scale,'image_count':len(images),'sha256':[hashlib.sha256(x).hexdigest() for x in blobs],
                    'dimensions':[list(Image.open(io.BytesIO(x)).size) for x in blobs],
                    'details':[p['image_url'].get('detail') for p in images],
                    'recent_sha256':[hashlib.sha256(x.read_bytes()).hexdigest() for x in sorted(dest.glob('recent_*.png'))], 'old_images':len(list(dest.glob('old_*.png'))),'recent_images':len(list(dest.glob('recent_*.png'))),'stats':stats})
        if len({tuple(r['sha256']) for r in records})!=len(records):raise RuntimeError('Scale intervention produced identical canvases')
        if any(r['old_images']==0 for r in records):raise RuntimeError('Far-history intervention not exercised')
        if records[0]['recent_sha256']!=records[1]['recent_sha256']:raise RuntimeError('Recent history changed with far-history scale')
        (out/'result.json').write_text(json.dumps({'passed':True,'api_calls':0,'synthetic_fixture_not_accuracy':True,'renderer_implementation':renderer_implementation,'records':records},indent=2))
        print(json.dumps({'passed':True,'api_calls':0,'scales':len(records),'artifact':str(out/'result.json')}))
    finally:render.logger.removeHandler(failures)


if __name__=='__main__':main()
